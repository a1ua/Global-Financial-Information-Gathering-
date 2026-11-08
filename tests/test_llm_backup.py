from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.ops.llm_backup import create_ledger_backup, restore_ledger_backup, verify_ledger_backup


SCHEMA = {"type": "object", "properties": {"category": {"type": "string", "enum": ["other"]}},
          "required": ["category"], "additionalProperties": False}
REQUEST = {"system_prompt": "Only classify synthetic data.", "prompt_version": "test/1",
           "rules_version": "test/1", "output_schema": SCHEMA, "schema_version": "test/1"}
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


class LedgerBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "llm-state.db"
        self.backup = self.root / "backup"
        self.restored = self.root / "restored"
        self.policy = Policy(enabled=True, max_retries=0)

    def tearDown(self):
        self.temp.cleanup()

    def client(self, path=None, policy=None, transport=None):
        return ModelClient(path or self.path, policy or self.policy,
                           transport or (lambda *_: ModelResponse(' {"category":"other"} ', 10, 8)),
                           clock=lambda: NOW)

    def generate(self, client=None, title="synthetic"):
        return (client or self.client()).generate({"title": title, "is_synthetic": True}, **REQUEST)

    def manifest(self):
        return json.loads((self.backup / "ledger-backup-manifest.json").read_text(encoding="utf-8"))

    def rehash(self):
        manifest = self.manifest()
        data = (self.backup / "ledger.db").read_bytes()
        manifest["files"]["ledger.db"] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (self.backup / "ledger-backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def mutate(self, sql, values=()):
        with closing(sqlite3.connect(self.backup / "ledger.db")) as db:
            db.execute(sql, values)
            db.commit()
        self.rehash()

    def pending(self):
        policy = replace(self.policy, daily_tokens=1500)
        def interrupt(*_):
            raise KeyboardInterrupt()
        client = self.client(policy=policy, transport=interrupt)
        with self.assertRaises(KeyboardInterrupt):
            self.generate(client)
        return client, policy

    def currency_fixture(self, currency, input_rate=2_000_000, output_rate=8_000_000):
        """Build the frozen schema2 fixture without relying on client migration."""
        self.generate()
        with closing(sqlite3.connect(self.path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(days)")}
            if "currency" not in columns:
                db.execute("ALTER TABLE days ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
            db.execute("UPDATE days SET currency=?,cost_cap=10000000", (currency,))
            row = db.execute("SELECT call_id,request_metadata,input_tokens,output_tokens FROM calls").fetchone()
            metadata = json.loads(row[1])
            metadata.update(budget_currency=currency, input_micro_units_per_million_tokens=input_rate,
                            output_micro_units_per_million_tokens=output_rate)
            cost = lambda incoming, outgoing: (incoming * input_rate + 999999) // 1000000 + (outgoing * output_rate + 999999) // 1000000
            reserved = cost(metadata["input_bound"], metadata["max_output_tokens"])
            db.execute("UPDATE calls SET request_metadata=?,reserved_cost=?,charged_cost=? WHERE call_id=?",
                       (json.dumps(metadata), reserved, cost(row[2], row[3]), row[0]))
            db.execute("DROP TABLE IF EXISTS ledger_identity")
            db.execute("PRAGMA user_version=2")
            db.commit()

    def test_success_snapshot_restore_and_cache_survive(self):
        client = self.client()
        original = self.generate(client)
        before = self.path.read_bytes()
        created = create_ledger_backup(self.path, self.backup)
        self.assertEqual(created["status"], "backed_up")
        self.assertEqual(created["database_schema_version"], 3)
        self.assertEqual(created["ledger_id"], client.ledger_id)
        self.assertEqual(self.manifest()["schema_version"], "llm-ledger-backup/0.2")
        self.assertEqual(self.manifest()["ledger_id"], client.ledger_id)
        self.assertEqual((created["days"], created["calls"], created["pending_calls"]), (1, 1, 0))
        self.assertEqual(self.path.read_bytes(), before)
        checked = verify_ledger_backup(self.backup)
        self.assertEqual(checked["ledger_id"], client.ledger_id)
        self.assertEqual(checked["restore_mode"], "isolated_copy")
        result = restore_ledger_backup(self.backup, self.restored)
        self.assertEqual(result["ledger_id"], client.ledger_id)
        self.assertEqual({p.name for p in self.restored.iterdir()}, {"ledger.db", "ledger-backup-manifest.json"})
        self.assertEqual(result["ledger"], str(self.restored / "ledger.db"))
        restored = self.client(self.restored / "ledger.db", transport=lambda *_: self.fail("cache must avoid transport"))
        self.assertEqual(restored.ledger_id, client.ledger_id)
        self.assertEqual(restored.usage("2026-11-08"), client.usage("2026-11-08"))
        cached = self.generate(restored)
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.call_id, original.call_id)
        self.assertEqual(self.path.read_bytes(), before)

    def test_empty_initialized_ledger(self):
        self.client()
        result = create_ledger_backup(self.path, self.backup)
        self.assertEqual((result["days"], result["calls"], result["pending_calls"]), (0, 0, 0))
        self.assertEqual(verify_ledger_backup(self.backup)["calls"], 0)

    def test_schema2_cny_and_rounded_rate_costs_preserved(self):
        self.currency_fixture("CNY", input_rate=1, output_rate=1)
        created = create_ledger_backup(self.path, self.backup)
        self.assertEqual(created["database_schema_version"], 2)
        self.assertNotIn("ledger_id", created)
        self.assertEqual(self.manifest()["schema_version"], "llm-ledger-backup/0.1")
        self.assertNotIn("ledger_id", self.manifest())
        self.assertNotIn("ledger_id", verify_ledger_backup(self.backup))
        self.assertNotIn("ledger_id", restore_ledger_backup(self.backup, self.restored))
        with closing(sqlite3.connect(self.restored / "ledger.db")) as db:
            self.assertEqual(db.execute("SELECT currency,cost_cap FROM days").fetchone(), ("CNY", 10000000))
            # ceil(10 / 1e6) + ceil(8 / 1e6) is two micro-units, never zero/one.
            self.assertEqual(db.execute("SELECT charged_cost FROM calls").fetchone()[0], 2)

    def test_schema2_metadata_currency_mismatch_rejected(self):
        self.currency_fixture("CNY")
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE days SET currency='USD'")
        with self.assertRaisesRegex(ValueError, "currency_invalid"):
            verify_ledger_backup(self.backup)

    def test_schema1_legacy_usd_snapshot_is_supported(self):
        self.generate()
        with closing(sqlite3.connect(self.path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(days)")}
            if "currency" in columns:
                db.execute("ALTER TABLE days DROP COLUMN currency")
            row = db.execute("SELECT call_id,request_metadata,input_tokens,output_tokens FROM calls").fetchone()
            metadata = json.loads(row[1])
            for key in ("budget_currency", "input_micro_units_per_million_tokens", "output_micro_units_per_million_tokens"):
                metadata.pop(key, None)
            cost = lambda incoming, outgoing: incoming * metadata["input_micro_usd_per_token"] + outgoing * metadata["output_micro_usd_per_token"]
            db.execute("UPDATE calls SET request_metadata=?,reserved_cost=?,charged_cost=? WHERE call_id=?",
                       (json.dumps(metadata), cost(metadata["input_bound"], metadata["max_output_tokens"]), cost(row[2], row[3]), row[0]))
            db.execute("DROP TABLE IF EXISTS ledger_identity")
            db.execute("PRAGMA user_version=1")
            db.commit()
        result = create_ledger_backup(self.path, self.backup)
        self.assertEqual(result["database_schema_version"], 1)
        self.assertNotIn("ledger_id", result)
        self.assertEqual(self.manifest()["schema_version"], "llm-ledger-backup/0.1")
        self.assertNotIn("ledger_id", self.manifest())
        self.assertNotIn("ledger_id", verify_ledger_backup(self.backup))
        restored = restore_ledger_backup(self.backup, self.restored)
        self.assertEqual(restored["database_schema_version"], 1)
        self.assertNotIn("ledger_id", restored)
        with closing(sqlite3.connect(self.restored / "ledger.db")) as db:
            self.assertEqual(db.execute("SELECT charged_tokens FROM calls").fetchone()[0], 18)
            self.assertNotIn("currency", {row[1] for row in db.execute("PRAGMA table_info(days)")})

    def test_pending_keeps_budget_and_next_call_is_denied_after_restore(self):
        client, policy = self.pending()
        before = client.usage("2026-11-08")
        self.assertEqual(before["pending_calls"], 1)
        create_ledger_backup(self.path, self.backup)
        restore_ledger_backup(self.backup, self.restored)
        restored = self.client(self.restored / "ledger.db", policy)
        self.assertEqual(restored.usage("2026-11-08"), before)
        with self.assertRaisesRegex(ModelError, "budget_exceeded"):
            self.generate(restored, "second synthetic input")
        self.assertEqual(client.usage("2026-11-08"), before)

    def test_failed_unknown_and_zero_usage_preserved(self):
        def timeout(*_):
            raise TimeoutError("not logged")
        with self.assertRaisesRegex(ModelError, "transport_timeout"):
            self.generate(self.client(transport=timeout))
        zero = self.client(transport=lambda *_: ModelResponse('{"category":"other"}', 0, 0))
        self.generate(zero, "zero usage")
        before = zero.usage("2026-11-08")
        create_ledger_backup(self.path, self.backup)
        restore_ledger_backup(self.backup, self.restored)
        self.assertEqual(self.client(self.restored / "ledger.db").usage("2026-11-08"), before)

    def test_wal_uncommitted_change_not_in_snapshot(self):
        self.generate()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE days SET token_cap=1")
            before = self.path.read_bytes()
            create_ledger_backup(self.path, self.backup)
            self.assertEqual(self.path.read_bytes(), before)
            with closing(sqlite3.connect(self.backup / "ledger.db")) as snapshot:
                self.assertEqual(snapshot.execute("SELECT token_cap FROM days").fetchone()[0], self.policy.daily_tokens)
                self.assertEqual(snapshot.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            writer.rollback()
        self.assertEqual({p.name for p in self.backup.iterdir()}, {"ledger.db", "ledger-backup-manifest.json"})

    def test_committed_wal_change_is_in_snapshot(self):
        self.generate()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("UPDATE days SET token_cap=99999")
            writer.commit()
            create_ledger_backup(self.path, self.backup)
            with closing(sqlite3.connect(self.backup / "ledger.db")) as snapshot:
                self.assertEqual(snapshot.execute("SELECT token_cap FROM days").fetchone()[0], 99999)

    def test_verify_is_readonly(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        before = {p.name: p.read_bytes() for p in self.backup.iterdir()}
        verify_ledger_backup(self.backup)
        self.assertEqual({p.name: p.read_bytes() for p in self.backup.iterdir()}, before)

    def test_missing_source_not_created(self):
        with self.assertRaisesRegex(ValueError, "source_missing"):
            create_ledger_backup(self.path, self.backup)
        self.assertFalse(self.path.exists())

    def test_database_corruption_detected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        with (self.backup / "ledger.db").open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "hash_mismatch"):
            verify_ledger_backup(self.backup)

    def test_pending_release_rejected_even_with_recomputed_manifest(self):
        self.pending()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE calls SET charged_tokens=0,charged_cost=0")
        with self.assertRaisesRegex(ValueError, "unknown_spend_released"):
            verify_ledger_backup(self.backup)

    def test_cache_to_other_valid_call_rejected(self):
        self.generate(title="one")
        self.generate(title="two")
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE cache SET call_id=(SELECT call_id FROM calls ORDER BY rowid DESC LIMIT 1)")
        with self.assertRaisesRegex(ValueError, "cache_closure_invalid"):
            verify_ledger_backup(self.backup)

    def test_output_corruption_rejected_after_rehash(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE calls SET output_text='{}'")
        with self.assertRaisesRegex(ValueError, "output_invalid"):
            verify_ledger_backup(self.backup)

    def test_output_schema_violation_with_matching_output_hash_rejected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        text = '{"category":"unsupported"}'
        self.mutate("UPDATE calls SET output_text=?,output_sha256=?", (text, hashlib.sha256(text.encode()).hexdigest()))
        with self.assertRaisesRegex(ValueError, "output_invalid"):
            verify_ledger_backup(self.backup)

    def test_unknown_usage_output_bound_rechecked_after_rehash(self):
        client = self.client(transport=lambda *_: ModelResponse('{"category":"other"}'))
        self.generate(client)
        create_ledger_backup(self.path, self.backup)
        # Schema and hash still match, but without trusted usage the current
        # client cannot accept this much output under its token-byte bound.
        text = " " * (self.policy.max_output_tokens + 1) + '{"category":"other"}'
        self.assertLess(len(text.encode()), self.policy.max_output_bytes)
        self.mutate("UPDATE calls SET output_text=?,output_sha256=?", (text, hashlib.sha256(text.encode()).hexdigest()))
        with self.assertRaisesRegex(ValueError, "output_invalid"):
            verify_ledger_backup(self.backup)

    def test_legacy_unknown_usage_byte_gap_preserved_without_rewrite(self):
        # Historical schema1 accepted a zero-usage response, then stored its
        # usage as NULL with the full reservation. Do not rewrite that history.
        self.generate()
        text = " " * (self.policy.max_output_tokens + 1) + '{"category":"other"}'
        with closing(sqlite3.connect(self.path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(days)")}
            if "currency" in columns:
                db.execute("ALTER TABLE days DROP COLUMN currency")
            row = db.execute("SELECT call_id,request_metadata FROM calls").fetchone()
            metadata = json.loads(row[1])
            for key in ("budget_currency", "input_micro_units_per_million_tokens", "output_micro_units_per_million_tokens"):
                metadata.pop(key, None)
            reserved_cost = metadata["input_bound"] * metadata["input_micro_usd_per_token"] + metadata["max_output_tokens"] * metadata["output_micro_usd_per_token"]
            db.execute("""UPDATE calls SET request_metadata=?,input_tokens=NULL,output_tokens=NULL,
                       reserved_cost=?,charged_cost=?,charged_tokens=reserved_tokens,output_text=?,output_sha256=? WHERE call_id=?""",
                       (json.dumps(metadata), reserved_cost, reserved_cost, text, hashlib.sha256(text.encode()).hexdigest(), row[0]))
            db.execute("DROP TABLE IF EXISTS ledger_identity")
            db.execute("PRAGMA user_version=1")
            db.commit()
        create_ledger_backup(self.path, self.backup)
        restore_ledger_backup(self.backup, self.restored)
        with closing(sqlite3.connect(self.restored / "ledger.db")) as db:
            stored = db.execute("SELECT output_text,charged_tokens,reserved_tokens FROM calls").fetchone()
            self.assertEqual(stored[0], text)
            self.assertEqual(stored[1], stored[2])

    def test_usage_cost_mismatch_rejected_after_rehash(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE calls SET charged_cost=0")
        with self.assertRaisesRegex(ValueError, "usage_invalid"):
            verify_ledger_backup(self.backup)

    def test_caps_below_consumption_rejected_after_rehash(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE days SET token_cap=1")
        with self.assertRaisesRegex(ValueError, "day_cap_exceeded"):
            verify_ledger_backup(self.backup)

    def test_call_day_mismatch_rejected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE calls SET day='2026-11-09'")
        with self.assertRaisesRegex(ValueError, "call_day_invalid"):
            verify_ledger_backup(self.backup)

    def test_future_schema_rejected_even_after_manifest_rehash(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "schema_unsupported"):
            verify_ledger_backup(self.backup)

    def test_schema3_identity_missing_table_or_row_rejected(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        self.mutate("DELETE FROM ledger_identity")
        with self.assertRaisesRegex(ValueError, "identity_invalid"):
            verify_ledger_backup(self.backup)
        self.mutate("DROP TABLE ledger_identity")
        with self.assertRaisesRegex(ValueError, "schema_invalid"):
            verify_ledger_backup(self.backup)

    def test_schema3_multiple_identity_rows_rejected(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        with closing(sqlite3.connect(self.backup / "ledger.db")) as db:
            db.execute("ALTER TABLE ledger_identity RENAME TO old_identity")
            db.execute("CREATE TABLE ledger_identity(singleton INTEGER PRIMARY KEY,ledger_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
            db.execute("INSERT INTO ledger_identity SELECT * FROM old_identity")
            db.execute("INSERT INTO ledger_identity VALUES(2,?,?)", ("ledger_" + "f" * 32, "2026-11-08T12:00:00Z"))
            db.execute("DROP TABLE old_identity")
            db.commit()
        self.rehash()
        with self.assertRaisesRegex(ValueError, "identity_invalid"):
            verify_ledger_backup(self.backup)

    def test_schema3_invalid_identity_id_and_time_rejected(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        ledger_id = self.manifest()["ledger_id"]
        for value in ("", "ledger_" + "A" * 32, "ledger_123", "call_" + "a" * 32):
            with self.subTest(ledger_id=value):
                self.mutate("UPDATE ledger_identity SET ledger_id=?", (value,))
                with self.assertRaisesRegex(ValueError, "identity_invalid"):
                    verify_ledger_backup(self.backup)
        self.mutate("UPDATE ledger_identity SET ledger_id=?", (ledger_id,))
        for value in ("2026-11-08T12:00:00", "2026-11-08T12:00:00+00:00", "not-a-time"):
            with self.subTest(created_at=value):
                self.mutate("UPDATE ledger_identity SET created_at=?", (value,))
                with self.assertRaisesRegex(ValueError, "time_invalid"):
                    verify_ledger_backup(self.backup)

    def test_schema3_manifest_identity_mismatch_rejected(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        manifest = self.manifest()
        manifest["ledger_id"] = "ledger_" + "e" * 32
        (self.backup / "ledger-backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata_mismatch"):
            verify_ledger_backup(self.backup)

    def test_schema3_changed_database_identity_rejected_after_rehash(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        self.mutate("UPDATE ledger_identity SET ledger_id=?", ("ledger_" + "e" * 32,))
        with self.assertRaisesRegex(ValueError, "metadata_mismatch"):
            restore_ledger_backup(self.backup, self.restored)
        self.assertFalse(self.restored.exists())

    def test_schema3_manifest_requires_exact_version_and_identity_field(self):
        self.client()
        create_ledger_backup(self.path, self.backup)
        original = self.manifest()
        cases = [dict(original, schema_version="llm-ledger-backup/0.1"),
                 {key: value for key, value in original.items() if key != "ledger_id"},
                 dict(original, ledger_id="invalid"), dict(original, unexpected=True),
                 dict(original, database_schema_version=2)]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                (self.backup / "ledger-backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "manifest_invalid"):
                    verify_ledger_backup(self.backup)

    def test_extra_tables_rejected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        self.mutate("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaisesRegex(ValueError, "schema_invalid"):
            verify_ledger_backup(self.backup)

    def test_manifest_counts_mismatch_rejected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        manifest = self.manifest()
        manifest["calls"] += 1
        (self.backup / "ledger-backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata_mismatch"):
            verify_ledger_backup(self.backup)

    def test_manifest_path_escape_and_extra_files_rejected(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        manifest = self.manifest()
        manifest["files"]["../outside.db"] = manifest["files"].pop("ledger.db")
        manifest_path = self.backup / "ledger-backup-manifest.json"
        original = manifest_path.read_bytes()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory_invalid"):
            verify_ledger_backup(self.backup)
        manifest_path.write_bytes(original)
        (self.backup / "unexpected.txt").write_text("not included", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory_invalid"):
            verify_ledger_backup(self.backup)

    def test_existing_destinations_never_overwritten(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            create_ledger_backup(self.path, self.backup)
        self.restored.mkdir()
        marker = self.restored / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            restore_ledger_backup(self.backup, self.restored)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_restore_nested_in_backup_refused(self):
        self.generate()
        create_ledger_backup(self.path, self.backup)
        with self.assertRaisesRegex(ValueError, "overlap"):
            restore_ledger_backup(self.backup, self.backup / "nested")

    def test_link_rejected_before_source_or_backup_read(self):
        self.generate()
        with patch("market_intel.ops.llm_backup._linked", return_value=True):
            with self.assertRaisesRegex(ValueError, "symlink_forbidden"):
                create_ledger_backup(self.path, self.backup)
        create_ledger_backup(self.path, self.backup)
        with patch("market_intel.ops.llm_backup._linked", return_value=True):
            with self.assertRaisesRegex(ValueError, "symlink_forbidden"):
                verify_ledger_backup(self.backup)


if __name__ == "__main__":
    unittest.main()
