from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.binding import check_workspace_ledger, ensure_workspace_ledger


REQUEST = {"system_prompt": "Classify synthetic metadata", "prompt_version": "test/1",
           "rules_version": "test/1", "schema_version": "test/1", "parameters": {},
           "output_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                             "required": ["ok"], "additionalProperties": False}}


class LedgerBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "live"
        self.ledger = self.root / "llm-state.db"
        self.binding = self.root / "llm-binding.json"

    def tearDown(self):
        self.temp.cleanup()

    def error(self, code, action, *args, **kwargs):
        with self.assertRaises(ModelError) as caught:
            action(*args, **kwargs)
        self.assertEqual(str(caught.exception), code)

    def snapshot(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            return {name: db.execute("SELECT * FROM " + name + " ORDER BY rowid").fetchall()
                    for name in ("days", "calls", "cache")}

    def populated_v2(self):
        client = ModelClient(self.ledger, Policy(enabled=True, max_retries=0),
                             lambda *_: ModelResponse('{"ok":true}', 10, 5),
                             clock=lambda: datetime(2026, 11, 8, tzinfo=timezone.utc))
        client.generate({"synthetic": "success"}, **REQUEST)
        client.transport = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            client.generate({"synthetic": "pending"}, **REQUEST)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DROP TABLE ledger_identity")
            db.execute("PRAGMA user_version=2")
        return self.snapshot()

    def test_check_nonexistent_is_read_only(self):
        result = check_workspace_ledger(self.root)
        self.assertEqual(result, {"status": "uninitialized", "ledger_id": None,
                                  "ledger": os.path.normcase(str(self.ledger.resolve()))})
        self.assertFalse(self.root.exists())

    def test_initialize_and_check_strict_binding(self):
        result = ensure_workspace_ledger(self.root)
        self.assertEqual(result["status"], "initialized")
        self.assertRegex(result["ledger_id"], r"^ledger_[0-9a-f]{32}$")
        value = json.loads(self.binding.read_text(encoding="utf-8"))
        self.assertEqual(set(value), {"schema_version", "ledger_id", "ledger_path", "created_at"})
        self.assertEqual(value["schema_version"], "ledger-binding/0.1")
        self.assertTrue(value["created_at"].endswith("Z"))
        before = (self.ledger.read_bytes(), self.binding.read_bytes())
        self.assertEqual(ensure_workspace_ledger(self.root)["status"], "bound")
        self.assertEqual(check_workspace_ledger(self.root)["ledger_id"], result["ledger_id"])
        self.assertEqual(before, (self.ledger.read_bytes(), self.binding.read_bytes()))

    def test_unbound_check_and_default_rejection_do_not_migrate(self):
        self.populated_v2()
        before = self.ledger.read_bytes()
        self.assertEqual(check_workspace_ledger(self.root)["status"], "unbound")
        self.error("ledger_binding_required", ensure_workspace_ledger, self.root)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(self.binding.exists())

    def test_explicit_adopt_preserves_success_cache_pending_and_amounts(self):
        rows = self.populated_v2()
        self.assertEqual([row[8] for row in rows["calls"]], ["succeeded", "pending"])
        result = ensure_workspace_ledger(self.root, adopt_existing=True)
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(self.snapshot(), rows)
        with closing(sqlite3.connect(self.ledger)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(ModelClient(self.ledger).ledger_id, result["ledger_id"])

    def test_explicit_adopt_rejects_invalid_business_without_migration(self):
        self.populated_v2()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE calls SET charged_cost=-1")
        before = self.ledger.read_bytes()
        self.error("ledger_adoption_invalid", ensure_workspace_ledger, self.root, adopt_existing=True)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(self.binding.exists())

    def test_binding_without_database_does_not_recreate(self):
        ensure_workspace_ledger(self.root)
        self.ledger.unlink()
        for action in (check_workspace_ledger, ensure_workspace_ledger):
            self.error("bound_ledger_missing", action, self.root)
            self.assertFalse(self.ledger.exists())

    def test_replaced_database_rejected_even_with_adopt(self):
        ensure_workspace_ledger(self.root)
        other = Path(self.temp.name) / "other"
        ensure_workspace_ledger(other)
        shutil.copyfile(other / "llm-state.db", self.ledger)
        before = self.binding.read_bytes()
        self.error("ledger_binding_identity_mismatch", check_workspace_ledger, self.root)
        self.error("ledger_binding_identity_mismatch", ensure_workspace_ledger, self.root, adopt_existing=True)
        self.assertEqual(self.binding.read_bytes(), before)

    def test_moved_workspace_rejected(self):
        ensure_workspace_ledger(self.root)
        moved = Path(self.temp.name) / "moved"
        self.root.rename(moved)
        self.error("ledger_binding_path_mismatch", ensure_workspace_ledger, moved, adopt_existing=True)

    def test_deleted_binding_needs_adopt_and_keeps_identity(self):
        original = ensure_workspace_ledger(self.root)
        self.binding.unlink()
        self.error("ledger_binding_required", ensure_workspace_ledger, self.root)
        adopted = ensure_workspace_ledger(self.root, adopt_existing=True)
        self.assertEqual(adopted["ledger_id"], original["ledger_id"])

    def test_invalid_binding_json_duplicate_extra_fields_and_timestamp_fail_closed(self):
        ensure_workspace_ledger(self.root)
        value = json.loads(self.binding.read_text(encoding="utf-8"))
        variants = ['{"schema_version":', '{"schema_version":1,"schema_version":2}',
                    json.dumps(dict(value, extra=True)), json.dumps(dict(value, created_at="2026-11-08")),
                    json.dumps(dict(value, schema_version="unknown"))]
        for raw in variants:
            with self.subTest(raw=raw):
                self.binding.write_text(raw, encoding="utf-8")
                self.error("ledger_binding_invalid", ensure_workspace_ledger, self.root, adopt_existing=True)
                self.assertEqual(self.binding.read_text(encoding="utf-8"), raw)

    def test_identity_missing_or_invalid_is_not_regenerated(self):
        ensure_workspace_ledger(self.root)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DELETE FROM ledger_identity")
        before = self.ledger.read_bytes()
        self.error("ledger_identity_invalid", ensure_workspace_ledger, self.root, adopt_existing=True)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_isolated_restore_marker_blocks_initialization_and_adoption(self):
        self.root.mkdir()
        marker = self.root / "ledger-backup-manifest.json"
        marker.write_text("{}", encoding="utf-8")
        self.error("isolated_ledger_not_live", ensure_workspace_ledger, self.root)
        self.assertFalse(self.ledger.exists())
        ModelClient(self.ledger)
        self.error("isolated_ledger_not_live", ensure_workspace_ledger, self.root, adopt_existing=True)

    def test_database_open_errors_are_fixed_and_do_not_leak(self):
        ensure_workspace_ledger(self.root)
        with patch("market_intel.llm.binding.sqlite3.connect", side_effect=sqlite3.OperationalError("secret payload")):
            self.error("ledger_binding_database_error", check_workspace_ledger, self.root)

    def test_ancestor_link_rejected_before_io(self):
        parent = self.root.parent
        with patch("market_intel.llm.binding._linked", side_effect=lambda path: path == parent):
            self.error("ledger_binding_link_forbidden", ensure_workspace_ledger, self.root)
        self.assertFalse(self.root.exists())

    def test_real_directory_link_rejected_when_supported(self):
        self.root.mkdir()
        linked = self.root.parent / "linked"
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Windows symlink creation requires local privilege")
        self.error("ledger_binding_link_forbidden", ensure_workspace_ledger, linked)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_real_junction_ancestor_rejected(self):
        self.root.mkdir()
        linked = self.root.parent / "junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(self.root)],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, "junction creation failed")
        try:
            self.error("ledger_binding_link_forbidden", ensure_workspace_ledger, linked / "nested")
            self.assertFalse((self.root / "nested").exists())
        finally:
            os.rmdir(linked)

    def test_empty_database_from_interrupted_creation_fails_closed(self):
        self.root.mkdir()
        self.ledger.touch()
        self.error("ledger_binding_schema_unsupported", ensure_workspace_ledger, self.root, adopt_existing=True)
        self.assertEqual(self.ledger.read_bytes(), b"")
        self.assertFalse(self.binding.exists())

    def test_concurrent_initialization_has_single_identity_without_overwrite(self):
        def run(_):
            try:
                return ensure_workspace_ledger(self.root)
            except ModelError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        final = check_workspace_ledger(self.root)
        self.assertEqual(final["status"], "bound")
        self.assertEqual(sum(result is not None and result["status"] == "initialized" for result in results), 1)
        self.assertTrue(all(result is None or result["ledger_id"] == final["ledger_id"] for result in results))

    def test_adoption_flag_must_be_boolean(self):
        self.error("ledger_adoption_flag_invalid", ensure_workspace_ledger, self.root, adopt_existing="yes")


if __name__ == "__main__":
    unittest.main()
