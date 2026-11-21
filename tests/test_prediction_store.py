from contextlib import closing
import copy
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.contracts.candidate_snapshot import canonical_json, payload_sha256
from market_intel.offline import ingest_fixture
from market_intel.store import connect
from market_intel.store.predictions import (
    migrate_predictions, read_prediction, submit_prediction, verify_prediction_inventory,
)
from test_evidence_candidates import fixture
from test_prediction_input import prediction_fixture, refresh_hashes


SEAL = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)


class PredictionStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / "market.db"
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        evidence = fixture()
        ingest_fixture(self.db, evidence, self.root)
        self.value = prediction_fixture(evidence)

    def submit(self, value=None, clock=lambda: SEAL):
        return submit_prediction(self.db, self.root, self.value if value is None else value, clock=clock)

    def correction(self, identity="prediction_2"):
        value = copy.deepcopy(self.value)
        value["content"].update(prediction_id=identity, supersedes_prediction_id="prediction_1")
        return value

    def test_receipt_sample_follows_content_commit_and_retry_keeps_stamp(self):
        def after_content():
            with closing(sqlite3.connect(self.path)) as reader:
                self.assertEqual(reader.execute("SELECT count(*) FROM predictions").fetchone()[0], 1)
                self.assertEqual(reader.execute("SELECT count(*) FROM prediction_refs").fetchone()[0], 1)
                self.assertIsNone(read_prediction(reader, "prediction_1"))
            return SEAL

        sealed = self.submit(clock=after_content)
        self.assertEqual(sealed["receipt"]["committed_at"], "2026-11-10T08:00:00.000000Z")
        self.assertEqual(sealed["receipt"]["content_sha256"], payload_sha256(self.value["content"]))
        self.assertEqual(read_prediction(self.db, "prediction_1"), sealed)

        def should_not_resample():
            self.fail("sealed retry resampled its original receipt")

        self.assertEqual(self.submit(clock=should_not_resample), sealed)
        self.assertEqual(verify_prediction_inventory(self.db, self.root),
                         {"predictions": 1, "receipted_predictions": 1})

    def test_clock_regression_leaves_recoverable_unreceipted_content(self):
        early = datetime(2026, 11, 8, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "^prediction_clock_regressed$"):
            self.submit(clock=lambda: early)
        self.assertIsNone(read_prediction(self.db, "prediction_1"))
        self.assertEqual(verify_prediction_inventory(self.db, self.root),
                         {"predictions": 1, "receipted_predictions": 0})
        with self.assertRaisesRegex(ValueError, "^prediction_predecessor_invalid$"):
            self.submit(self.correction())
        raw = self.value["inputs"]["evidence_snapshot"]["input_manifest"]["candidates"][0]["content_ref"]
        (self.root / raw).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "^prediction_inputs_unavailable$"):
            self.submit()
        (self.root / raw).write_bytes(fixture()["raw"]["normalized_text"].encode("utf-8"))
        self.assertEqual(self.submit()["receipt"]["committed_at"], "2026-11-10T08:00:00.000000Z")

    def test_content_failure_rolls_back_rows_and_never_calls_clock(self):
        self.db.execute("""CREATE TEMP TRIGGER reject_prediction_refs BEFORE INSERT ON prediction_refs
                            BEGIN SELECT RAISE(ABORT,'injected fault'); END""")
        with self.assertRaisesRegex(ValueError, "^prediction_write_conflict$"):
            self.submit(clock=lambda: self.fail("clock sampled despite content rollback"))
        for table in ("predictions", "prediction_refs", "prediction_receipts"):
            self.assertEqual(self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
        self.assertFalse(self.db.in_transaction)

    def test_single_root_linear_correction_and_conflicting_id(self):
        original = self.submit()
        changed = copy.deepcopy(self.value)
        changed["content"]["created_at"] = "2026-11-10T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "^prediction_id_conflict$"):
            self.submit(changed)
        other_root = copy.deepcopy(self.value)
        other_root["content"]["prediction_id"] = "prediction_other"
        with self.assertRaisesRegex(ValueError, "^prediction_write_conflict$"):
            self.submit(other_root)
        changed_context = self.correction()
        changed_context["inputs"]["calendar"]["sessions"][0]["opens_at"] = "2026-11-10T01:31:00Z"
        refresh_hashes(changed_context)
        with self.assertRaisesRegex(ValueError, "^prediction_predecessor_invalid$"):
            self.submit(changed_context)
        second = self.submit(self.correction())
        with self.assertRaisesRegex(ValueError, "^prediction_write_conflict$"):
            self.submit(self.correction("prediction_fork"))
        self.assertEqual(read_prediction(self.db, "prediction_1"), original)
        self.assertEqual(read_prediction(self.db, "prediction_2"), second)

    def test_sql_guards_block_replacement_and_rowid_alias(self):
        self.submit()
        self.db.execute("PRAGMA recursive_triggers=OFF")
        for table, key in (("predictions", "id"), ("prediction_refs", "prediction_id"),
                           ("prediction_receipts", "prediction_id")):
            with self.subTest(table=table):
                for query in (f"UPDATE {table} SET {key}={key}", f"DELETE FROM {table}",
                              f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"):
                    with self.assertRaises(sqlite3.IntegrityError), self.db:
                        self.db.execute(query)
                with self.assertRaisesRegex(sqlite3.OperationalError, "no column named rowid"), self.db:
                    self.db.execute(f"INSERT OR REPLACE INTO {table}(rowid) VALUES (1)")
        # Different primary key colliding with the root's partial unique index.
        changed = copy.deepcopy(self.value)
        changed["content"]["prediction_id"] = "replacement"
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?)",
                            ("replacement", "family_1", None, canonical_json(changed),
                             payload_sha256(changed["content"])))

    def test_missing_storage_guard_invalidates_inventory(self):
        self.submit()
        self.db.execute("DROP TRIGGER predictions_no_update")
        with self.assertRaisesRegex(ValueError, "^prediction_inventory_invalid$"):
            verify_prediction_inventory(self.db, self.root)

    def test_autocommit_mode_and_active_caller_txn(self):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN")
            with self.assertRaisesRegex(ValueError, "^prediction_active_transaction$"):
                submit_prediction(db, self.root, self.value)
            self.assertTrue(db.in_transaction)
            db.execute("ROLLBACK")
            # Explicit SQL COMMIT also supports Python 3.12's autocommit=True.
            if hasattr(db, "autocommit"):
                db.autocommit = True
            self.assertEqual(submit_prediction(db, self.root, self.value, clock=lambda: SEAL),
                             read_prediction(db, "prediction_1"))
            self.assertFalse(db.in_transaction)

    def test_migration_objects_rollback_inside_caller_transaction(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("BEGIN IMMEDIATE")
            # A late DDL conflict proves the migration helper makes no early COMMIT.
            db.execute("CREATE TABLE prediction_receipts (unused INTEGER)")
            with self.assertRaises(sqlite3.OperationalError):
                migrate_predictions(db)
            db.execute("ROLLBACK")
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema").fetchall(), [])
