from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.offline import ingest_fixture
from market_intel.ops.backup import create_backup, restore_backup, verify_backup
from market_intel.pipeline.candidate_snapshot import load_candidate_snapshot_inputs
from market_intel.pipeline.evidence_candidates import plan_evidence_candidates
from market_intel.store import connect
from market_intel.store.predictions import read_prediction, submit_prediction
from test_evidence_candidates import CUTOFF, fixture
from test_prediction_input import prediction_fixture


def _time(hour):
    return datetime(2026, 11, 9, hour, tzinfo=timezone.utc)


class PredictionBackupTests(unittest.TestCase):
    def setUp(self):
        session = tempfile.TemporaryDirectory()
        self.addCleanup(session.cleanup)
        self.root = Path(session.name)
        self.source = self.root / "source"
        self.backup = self.root / "backup"
        self.restored = self.root / "restored"
        self.bundle = fixture()

    def _manifest(self):
        return json.loads((self.backup / "backup-manifest.json").read_text(encoding="utf-8"))

    def _save_manifest(self, manifest):
        (self.backup / "backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _rehash_database(self, manifest):
        data = (self.backup / "market.db").read_bytes()
        manifest["files"]["market.db"] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        self._save_manifest(manifest)

    def _create_with_prediction(self):
        value = prediction_fixture(self.bundle)
        with closing(connect(self.source / "market.db")) as db:
            ingest_fixture(db, self.bundle, self.source)
            submit_prediction(db, self.source, value, clock=lambda: _time(13))
        create_backup(self.source, self.backup)
        return value

    def test_schema4_backup_stays_legacy_and_compatible_with_exact_reader(self):
        with patch("market_intel.store.predictions.migrate_predictions", side_effect=RuntimeError("stop_before_5")):
            with self.assertRaisesRegex(RuntimeError, "^stop_before_5$"):
                connect(self.source / "market.db")
        value = prediction_fixture(self.bundle)
        with closing(sqlite3.connect(self.source / "market.db")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            ingest_fixture(db, self.bundle, self.source)
        created = create_backup(self.source, self.backup)
        self.assertEqual(set(created), {"status", "backup", "files", "raw_items", "reports"})
        manifest = self._manifest()
        self.assertEqual(manifest["schema_version"], "workspace-backup/0.1")
        self.assertNotIn("predictions", manifest)
        self.assertEqual(verify_backup(self.backup)["status"], "verified")
        restore_backup(self.backup, self.restored)
        with closing(sqlite3.connect(self.restored / "market.db")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual(load_candidate_snapshot_inputs(self.restored, value["inputs"]["evidence_snapshot"])["bundles"],
                         [{**self.bundle, "receipt_committed_at": None}])
        self.assertEqual(len(plan_evidence_candidates(self.restored, CUTOFF, include_synthetic=True)
                             ["input_manifest"]["candidates"]), 1)

    def test_schema5_backup_restores_receipt_and_unavailable_orphan(self):
        value = prediction_fixture(self.bundle)
        orphan = prediction_fixture(self.bundle)
        orphan["content"].update(prediction_id="prediction_orphan", prediction_family_id="family_orphan")
        with closing(connect(self.source / "market.db")) as db:
            ingest_fixture(db, self.bundle, self.source)
            submit_prediction(db, self.source, value, clock=lambda: _time(13))
            with self.assertRaisesRegex(ValueError, "^prediction_clock_regressed$"):
                submit_prediction(db, self.source, orphan, clock=lambda: _time(11))
            receipted = read_prediction(db, "prediction_1")
        create_backup(self.source, self.backup)
        manifest = self._manifest()
        self.assertEqual((manifest["schema_version"], manifest["predictions"], manifest["receipted_predictions"]),
                         ("workspace-backup/0.2", 2, 1))
        restore_backup(self.backup, self.restored)
        with closing(connect(self.restored / "market.db")) as db:
            self.assertEqual(read_prediction(db, "prediction_1"), receipted)
            self.assertIsNone(read_prediction(db, "prediction_orphan"))
            # A valid retry can issue the first receipt, so the pending row was kept.
            submit_prediction(db, self.restored, orphan, clock=lambda: _time(14))
            self.assertIsNotNone(read_prediction(db, "prediction_orphan"))
        self.assertEqual(len(plan_evidence_candidates(self.restored, CUTOFF, include_synthetic=True)
                             ["input_manifest"]["candidates"]), 1)

    def test_manifest_counts_and_versions_cannot_misclassify_schema5_snapshot(self):
        self._create_with_prediction()
        manifest = self._manifest()
        self._save_manifest({**manifest, "receipted_predictions": True})
        with self.assertRaisesRegex(ValueError, "^backup_prediction_counts_invalid$"):
            verify_backup(self.backup)
        self._save_manifest({**manifest, "predictions": 2})
        with self.assertRaisesRegex(ValueError, "^backup_prediction_counts_mismatch$"):
            verify_backup(self.backup)
        for field in ("predictions", "receipted_predictions"):
            del manifest[field]
        manifest["schema_version"] = "workspace-backup/0.1"
        self._save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "^backup_manifest_schema_invalid$"):
            verify_backup(self.backup)
        with closing(sqlite3.connect(self.backup / "market.db")) as db:
            db.execute("PRAGMA user_version=4")
        manifest["database_schema_version"] = 4
        self._rehash_database(manifest)
        with self.assertRaisesRegex(ValueError, "^backup_database_version_unsupported$"):
            verify_backup(self.backup)

    def test_corrupt_frozen_evidence_rejected_even_with_matching_backup_hash(self):
        self._create_with_prediction()
        database = self.backup / "market.db"
        with closing(sqlite3.connect(database)) as db, db:
            payload = dict(self.bundle["evidence"], quote="changed after the decision")
            db.execute("DROP TRIGGER evidence_no_update")
            db.execute("UPDATE evidence SET payload=? WHERE id=?", (json.dumps(payload), payload["evidence_id"]))
        self._rehash_database(self._manifest())
        with self.assertRaises(ValueError):
            verify_backup(self.backup)
        with self.assertRaises(ValueError):
            restore_backup(self.backup, self.restored)
        self.assertFalse(self.restored.exists())


if __name__ == "__main__":
    unittest.main()
