from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelResponse, Policy
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.ops.llm_backup import create_ledger_backup, verify_ledger_backup
from market_intel.ops.recovery_preflight import preflight_ledger_recovery


REQUEST = {"system_prompt": "Synthetic data only.", "prompt_version": "test/1",
           "rules_version": "test/1", "schema_version": "test/1", "parameters": {},
           "output_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                             "required": ["ok"], "additionalProperties": False}}
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


class RecoveryPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "live"
        ensure_workspace_ledger(self.workspace)
        self.ledger = self.workspace / "llm-state.db"
        self.backup = self.root / "backup"
        self.client = ModelClient(self.ledger, Policy(enabled=True, max_retries=0),
                                  lambda *_: ModelResponse('{"ok":true}', 10, 5), clock=lambda: NOW)

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, title="synthetic"):
        return self.client.generate({"synthetic": title}, **REQUEST)

    def make_backup(self):
        return create_ledger_backup(self.ledger, self.backup)

    def mutate(self, path, sql, values=()):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(sql, values)

    def rehash(self):
        path = self.backup / "ledger.db"
        manifest_path = self.backup / "ledger-backup-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["ledger.db"] = {"size": path.stat().st_size,
                                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_identical_snapshot_remains_blocked_and_repeated_read_is_unchanged(self):
        self.generate()
        self.make_backup()
        before = self.snapshot()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual(result, preflight_ledger_recovery(self.workspace, self.backup))
        self.assertEqual(result["status"], "equivalent_observation")
        self.assertEqual(result["current_calls"], 1)
        self.assertFalse(result["switch_allowed"])
        self.assertFalse(result["trusted_high_water"])
        self.assertEqual(result["blockers"], ["trusted_high_water_unavailable", "reconciliation_not_verified",
                                               "production_switch_not_implemented"])
        self.assertEqual(before, self.snapshot())

    def test_empty_same_identity_is_not_a_production_recovery_permit(self):
        self.make_backup()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual((result["status"], result["current_calls"]), ("equivalent_observation", 0))
        self.assertFalse(result["switch_allowed"])

    def test_old_snapshot_missing_new_call_and_cache_is_not_equivalent(self):
        self.generate("first")
        self.make_backup()
        self.generate("second")
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual(result["status"], "not_equivalent")
        self.assertEqual((result["candidate_missing_calls"], result["missing_cache"]), (1, 1))
        self.assertIn("snapshot_not_equivalent", result["blockers"])

    def test_candidate_extra_call_does_not_imply_newer_or_safe(self):
        self.generate()
        self.make_backup()
        candidate = ModelClient(self.backup / "ledger.db", self.client.policy,
                                self.client.transport, clock=lambda: NOW)
        candidate.generate({"synthetic": "only-candidate"}, **REQUEST)
        manifest_path = self.backup / "ledger-backup-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["calls"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.rehash()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual((result["candidate_extra_calls"], result["extra_cache"]), (1, 1))
        self.assertFalse(result["switch_allowed"])

    def test_same_count_same_cost_but_changed_call_row_is_detected(self):
        self.generate()
        self.make_backup()
        output = ' {"ok":true} '
        self.mutate(self.backup / "ledger.db", "UPDATE calls SET output_text=?, output_sha256=?",
                    (output, hashlib.sha256(output.encode()).hexdigest()))
        self.rehash()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual((result["changed_calls"], result["candidate_missing_calls"], result["candidate_extra_calls"]),
                         (1, 0, 0))
        self.assertEqual(result["status"], "not_equivalent")

    def test_day_cap_change_is_detected_without_reinterpreting_amounts(self):
        self.generate()
        self.make_backup()
        self.mutate(self.backup / "ledger.db", "UPDATE days SET cost_cap=cost_cap+1")
        self.rehash()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual((result["changed_days"], result["changed_calls"]), (1, 0))

    def test_additional_empty_day_is_detected(self):
        self.make_backup()
        self.mutate(self.ledger, "INSERT INTO days VALUES('2026-11-09',1000,1000,'USD')")
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual(result["missing_days"], 1)

    def test_changed_valid_cache_pointer_is_detected(self):
        self.generate()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            row = list(db.execute("SELECT * FROM calls").fetchone())
            columns = [item[1] for item in db.execute("PRAGMA table_info(calls)")]
            row[columns.index("call_id")] = "call_" + "a" * 32
            db.execute("INSERT INTO calls VALUES(" + ",".join("?" for _ in row) + ")", row)
        self.make_backup()
        self.mutate(self.backup / "ledger.db", "UPDATE cache SET call_id=?", ("call_" + "a" * 32,))
        self.rehash()
        self.assertEqual(verify_ledger_backup(self.backup)["calls"], 2)
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual((result["changed_cache"], result["changed_calls"]), (1, 0))

    def test_pending_is_preserved_even_for_equivalent_snapshot(self):
        def interrupt(*_):
            raise KeyboardInterrupt()
        self.client.transport = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.generate()
        self.make_backup()
        before = self.snapshot()
        result = preflight_ledger_recovery(self.workspace, self.backup)
        self.assertEqual(result["status"], "equivalent_observation")
        self.assertFalse(result["switch_allowed"])
        self.assertEqual(before, self.snapshot())

    def test_unbound_and_missing_workspace_do_not_initialize(self):
        self.make_backup()
        for workspace in (self.root / "missing", self.root / "unbound"):
            if workspace.name == "unbound":
                ModelClient(workspace / "llm-state.db")
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, "ledger_recovery_binding_required"):
                preflight_ledger_recovery(workspace, self.backup)
            self.assertEqual(before, self.snapshot())

    def test_isolated_workspace_marker_is_rejected(self):
        self.make_backup()
        (self.workspace / "ledger-backup-manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "isolated_ledger_not_live"):
            preflight_ledger_recovery(self.workspace, self.backup)

    def test_wrong_candidate_identity_is_rejected(self):
        other = self.root / "other.db"
        ModelClient(other)
        create_ledger_backup(other, self.backup)
        with self.assertRaisesRegex(ValueError, "ledger_recovery_identity_mismatch"):
            preflight_ledger_recovery(self.workspace, self.backup)

    def test_legacy_backup_rejected_without_migration(self):
        for version in (1, 2):
            with self.subTest(version=version):
                source = self.root / (str(version) + ".db")
                ModelClient(source)
                with closing(sqlite3.connect(source)) as db, db:
                    db.execute("DROP TABLE ledger_identity")
                    if version == 1:
                        db.execute("ALTER TABLE days DROP COLUMN currency")
                    db.execute("PRAGMA user_version=" + str(version))
                target = self.root / ("backup" + str(version))
                create_ledger_backup(source, target)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "ledger_recovery_schema3_required"):
                    preflight_ledger_recovery(self.workspace, target)
                self.assertEqual(before, self.snapshot())

    def test_hash_mismatch_and_current_business_corruption_are_rejected(self):
        self.generate()
        self.make_backup()
        path = self.backup / "ledger.db"
        with path.open("ab") as stream:
            stream.write(b"synthetic tamper")
        with self.assertRaisesRegex(ValueError, "ledger_backup_file_hash_mismatch"):
            preflight_ledger_recovery(self.workspace, self.backup)
        self.mutate(self.ledger, "UPDATE calls SET charged_cost=0")
        # First restore only the original candidate bytes from its own valid new
        # fixture: no recovery operation is invoked by the product under test.
        fresh = self.root / "fresh.db"
        ModelClient(fresh)
        self.mutate(fresh, "UPDATE ledger_identity SET ledger_id=?", (self.client.ledger_id,))
        target = self.root / "valid-backup"
        create_ledger_backup(fresh, target)
        with self.assertRaisesRegex(ValueError, "ledger_backup_usage_invalid"):
            preflight_ledger_recovery(self.workspace, target)

    def test_candidate_revalidated_inside_actual_read_transaction(self):
        self.generate()
        self.make_backup()
        original_verify = verify_ledger_backup
        def replace_after_verify(backup):
            checked = original_verify(backup)
            self.mutate(self.backup / "ledger.db", "UPDATE ledger_identity SET ledger_id=?",
                        ("ledger_" + "b" * 32,))
            return checked
        with patch("market_intel.ops.recovery_preflight.verify_ledger_backup", side_effect=replace_after_verify):
            with self.assertRaisesRegex(ValueError, "ledger_recovery_identity_mismatch"):
                preflight_ledger_recovery(self.workspace, self.backup)

    def test_io_errors_are_fixed_and_do_not_leak_exception_text(self):
        with patch("market_intel.ops.recovery_preflight.check_workspace_ledger",
                   side_effect=OSError("synthetic-sensitive-detail")):
            with self.assertRaisesRegex(ValueError, "^ledger_recovery_io_error$"):
                preflight_ledger_recovery(self.workspace, self.backup)

    def test_candidate_business_closure_revalidated_after_initial_verification(self):
        self.generate()
        self.make_backup()
        original_verify = verify_ledger_backup
        def corrupt_after_verify(backup):
            checked = original_verify(backup)
            self.mutate(self.backup / "ledger.db", "UPDATE calls SET charged_cost=0")
            return checked
        with patch("market_intel.ops.recovery_preflight.verify_ledger_backup", side_effect=corrupt_after_verify):
            with self.assertRaisesRegex(ValueError, "ledger_backup_usage_invalid"):
                preflight_ledger_recovery(self.workspace, self.backup)

    def test_linked_candidate_ancestor_is_rejected(self):
        self.make_backup()
        with patch("market_intel.ops.llm_backup._linked", side_effect=lambda p: p == self.root):
            with self.assertRaisesRegex(ValueError, "symlink_forbidden"):
                preflight_ledger_recovery(self.workspace, self.backup)


if __name__ == "__main__":
    unittest.main()
