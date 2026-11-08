import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.offline import connect, digest, ingest_fixture, render


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = connect(self.root / "market.db")
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def ingest(self, bundle=None):
        ingest_fixture(self.db, bundle or self.bundle, self.root)

    def manifest(self, cutoff="2026-11-06T00:30:00Z", report_id="test"):
        folder = render(self.db, self.root, cutoff, report_id)
        return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    def revision(self):
        new = copy.deepcopy(self.bundle)
        raw, event, evidence = (new[k] for k in ("raw", "event", "evidence"))
        raw["raw_item_id"] += "_v2"
        raw["normalized_text"] = "示例公告：机构发布修订支持文件。"
        raw["content_sha256"] = digest(raw["normalized_text"])
        raw["content_ref"] = f"raw/{raw['content_sha256']}.txt"
        for key in ("first_seen_at", "fetched_at", "persisted_at", "available_at"):
            raw[key] = "2026-11-06T02:00:00Z"
        event["event_version_id"] += "_v2"
        event["version"] = 2
        event["input_raw_item_ids"] = [raw["raw_item_id"]]
        event["evidence_ids"] = [evidence["evidence_id"] + "_v2"]
        event["fact_summary"] = raw["normalized_text"]
        event["available_at"] = event["processed_at"] = "2026-11-06T02:01:00Z"
        evidence["evidence_id"] += "_v2"
        evidence["event_version_id"] = event["event_version_id"]
        evidence["raw_item_id"] = raw["raw_item_id"]
        evidence["available_at"] = event["available_at"]
        evidence["quote"] = raw["normalized_text"]
        evidence["locator"]["end"] = len(evidence["quote"])
        return new

    def test_replay_is_idempotent(self):
        self.ingest()
        self.ingest()
        for table in ("raw_items", "event_versions", "evidence"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
        self.assertEqual(self.manifest(), self.manifest())

    def test_late_collection_not_in_old_report(self):
        self.ingest()
        result = self.manifest("2026-11-06T00:04:00Z")
        self.assertEqual(result["input_manifest"]["event_version_ids"], [])

    def test_processing_after_cutoff_is_excluded(self):
        self.ingest()
        self.assertEqual(self.manifest("2026-11-06T00:05:30Z")["input_manifest"]["event_version_ids"], [])

    def test_revision_and_historical_inputs_are_frozen(self):
        self.ingest()
        previous = self.manifest()
        self.ingest(self.revision())
        self.assertEqual(previous, self.manifest())
        current = self.manifest("2026-11-06T03:00:00Z", "new")
        self.assertEqual(len(current["input_manifest"]["event_version_ids"]), 1)
        self.assertTrue(current["input_manifest"]["event_version_ids"][0].endswith("_v2"))

    def test_append_only_update_and_delete(self):
        self.ingest()
        for table in ("raw_items", "event_versions", "evidence"):
            for operation in (f"UPDATE {table} SET payload='{{}}'", f"DELETE FROM {table}"):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(operation)
                self.db.rollback()

    def test_conflicting_id_rolls_back(self):
        self.ingest()
        bad = copy.deepcopy(self.bundle)
        bad["event"]["title"] = "changed"
        with self.assertRaisesRegex(ValueError, "immutable_id_conflict"):
            self.ingest(bad)

    def test_invalid_quote_rejected_before_writes(self):
        self.bundle["evidence"]["quote"] = "missing"
        with self.assertRaisesRegex(ValueError, "quote_mismatch"):
            self.ingest()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 0)

    def test_orphan_file_replay(self):
        path = self.root / self.bundle["raw"]["content_ref"]
        path.parent.mkdir(parents=True)
        path.write_text(self.bundle["raw"]["normalized_text"], encoding="utf-8")
        self.ingest()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 1)

    def test_missing_or_corrupt_evidence_blocks_report(self):
        self.ingest()
        path = self.root / self.bundle["raw"]["content_ref"]
        path.write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing_or_corrupt"):
            self.manifest()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing_or_corrupt"):
            self.manifest()

    def test_report_id_cannot_escape_output_directory(self):
        with self.assertRaisesRegex(ValueError, "invalid_report_id"):
            self.manifest(report_id="../escape")

    def test_report_conflict_does_not_overwrite(self):
        self.ingest()
        first = self.manifest()
        with self.assertRaisesRegex(ValueError, "published_report_conflict"):
            self.manifest("2026-11-06T00:31:00Z")
        self.assertEqual(first, self.manifest())

    def test_naive_time_rejected(self):
        self.bundle["raw"]["available_at"] = "2026-11-06T00:05:03"
        with self.assertRaisesRegex(ValueError, "utc_z_timestamp_required"):
            self.ingest()

    def test_crlf_evidence_is_byte_preserved(self):
        raw, evidence = self.bundle["raw"], self.bundle["evidence"]
        raw["normalized_text"] += "\r\n第二行"
        raw["content_sha256"] = digest(raw["normalized_text"])
        raw["content_ref"] = f"raw/{raw['content_sha256']}.txt"
        evidence["quote"] = raw["normalized_text"]
        evidence["locator"]["end"] = len(evidence["quote"])
        self.ingest()
        self.ingest()
        self.assertEqual(len(self.manifest()["input_manifest"]["raw_item_ids"]), 1)
        self.assertEqual(self.manifest(), self.manifest())

    def test_duplicate_logical_version_is_rejected_atomically(self):
        self.ingest()
        new = self.revision()
        new["event"]["version"] = 1
        with self.assertRaises(sqlite3.IntegrityError):
            self.ingest(new)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM event_versions").fetchone()[0], 1)

    def test_version_must_be_positive_integer(self):
        for value in (True, 0, -1, "1"):
            self.bundle["event"]["version"] = value
            with self.assertRaisesRegex(ValueError, "invalid_event_version"):
                self.ingest()


if __name__ == "__main__":
    unittest.main()
