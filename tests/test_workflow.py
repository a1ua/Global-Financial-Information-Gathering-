import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.capture import collect_fed, make_bundle, now
from market_intel.offline import connect, ingest_fixture, ingest_bundle, render, replay_report


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = connect(self.root / "market.db")
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        self.feed = (Path(__file__).parent / "fixtures/sources/rss-synthetic.xml").read_bytes()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def item(self, title="A synthetic title"):
        return {"source_item_key": "guid:demo", "original_url": "https://example.com/demo", "title": title,
                "normalized_text": "A synthetic description", "source_time_text": None,
                "source_published_at": None, "source_time_precision": "unknown", "source_timezone": None,
                "time_parse_status": "missing"}

    def test_new_schema_and_immutable_database_identity(self):
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO raw_items VALUES ('mismatch', '{\"raw_item_id\":\"different\"}')")
        self.db.rollback()

    def test_legacy_schema_migrates_without_rewriting_content(self):
        legacy_path = self.root / "legacy.db"
        old = sqlite3.connect(legacy_path)
        old.execute("CREATE TABLE raw_items(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        raw = self.bundle["raw"]
        payload = json.dumps(raw)
        old.execute("INSERT INTO raw_items VALUES (?,?)", (raw["raw_item_id"], payload))
        old.commit()
        old.close()
        migrated = connect(legacy_path)
        try:
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(migrated.execute("SELECT payload FROM raw_items").fetchone()[0], payload)
        finally:
            migrated.close()

    def test_future_database_schema_is_rejected(self):
        self.db.execute("PRAGMA user_version=999")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "unsupported_database_version"):
            connect(self.root / "market.db")

    def test_exact_manifest_replay_ignores_later_imports(self):
        ingest_fixture(self.db, self.bundle, self.root)
        original = render(self.db, self.root, "2026-11-06T00:30:00Z", "frozen")
        extra = copy.deepcopy(self.bundle)
        extra["raw"]["raw_item_id"] += "_extra"
        extra["raw"]["source_item_key"] += "_extra"
        extra["event"]["event_id"] += "_extra"
        extra["event"]["event_version_id"] += "_extra"
        extra["event"]["input_raw_item_ids"] = [extra["raw"]["raw_item_id"]]
        extra["event"]["evidence_ids"] = [extra["evidence"]["evidence_id"] + "_extra"]
        extra["evidence"]["evidence_id"] += "_extra"
        extra["evidence"]["raw_item_id"] = extra["raw"]["raw_item_id"]
        extra["evidence"]["event_version_id"] = extra["event"]["event_version_id"]
        ingest_fixture(self.db, extra, self.root)
        replayed = replay_report(self.db, self.root, "frozen", self.root / "replay")
        self.assertEqual((original / "brief.html").read_bytes(), (replayed / "brief.html").read_bytes())
        with self.assertRaisesRegex(ValueError, "published_report_conflict"):
            render(self.db, self.root, "2026-11-06T00:30:00Z", "frozen")

    def test_replay_rejects_corrupt_manifest(self):
        ingest_fixture(self.db, self.bundle, self.root)
        folder = render(self.db, self.root, "2026-11-06T00:30:00Z", "frozen")
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["input_manifest"]["raw_item_ids"] = []
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid_report_manifest"):
            replay_report(self.db, self.root, "frozen", self.root / "replay")

    def test_real_metadata_bundle_has_postcommit_visibility_fence(self):
        from unittest.mock import patch
        # Do not assume Windows wall-clock reads advance between two commits.
        prepared_at = "2026-11-06T00:00:00Z"
        with patch("market_intel.capture.now", return_value=prepared_at):
            bundle = make_bundle(self.db, self.item(), fetched_at=prepared_at)
        ingest_bundle(self.db, bundle, self.root)
        # Its prepared timestamp must not bypass the later persisted receipt.
        path = render(self.db, self.root, bundle["event"]["available_at"], "before", report_kind="rss_snapshot")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["input_manifest"]["event_version_ids"], [])
        path = render(self.db, self.root, now(), "after", report_kind="rss_snapshot")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["input_manifest"]["event_version_ids"]), 1)
        self.assertFalse(manifest["is_synthetic"])

    def test_capture_revisions_and_reversions_preserve_versions(self):
        first = make_bundle(self.db, self.item(), fetched_at=now())
        ingest_bundle(self.db, first, self.root)
        self.assertIsNone(make_bundle(self.db, self.item(), fetched_at=now()))
        second = make_bundle(self.db, self.item("Changed title"), fetched_at=now())
        ingest_bundle(self.db, second, self.root)
        reverted = make_bundle(self.db, self.item(), fetched_at=now())
        ingest_bundle(self.db, reverted, self.root)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM event_versions").fetchone()[0], 3)

    def test_network_failure_logs_without_fake_success(self):
        def unavailable():
            raise OSError("network_unavailable")
        with self.assertRaisesRegex(OSError, "network_unavailable"):
            collect_fed(self.db, self.root, fetcher=unavailable)
        log = json.loads(next((self.root / "runs").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(log["status"], "failed")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 0)

    def test_excerpt_title_revision_with_unchanged_description(self):
        first = make_bundle(self.db, self.item(), fetched_at=now(), excerpt=True)
        ingest_bundle(self.db, first, self.root)
        changed = make_bundle(self.db, self.item("Revised title"), fetched_at=now(), excerpt=True)
        ingest_bundle(self.db, changed, self.root)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 2)

    def test_replay_rejects_changed_renderer_with_same_version(self):
        from unittest.mock import patch
        ingest_fixture(self.db, self.bundle, self.root)
        render(self.db, self.root, "2026-11-06T00:30:00Z", "frozen")
        with patch("market_intel.offline.html.escape", side_effect=lambda value, **kw: str(value) + "CHANGED"):
            with self.assertRaisesRegex(ValueError, "replay_artifact_mismatch"):
                replay_report(self.db, self.root, "frozen", self.root / "replay")
        self.assertFalse((self.root / "replay/frozen").exists())

    def test_replace_cannot_bypass_immutable_records_even_with_recursive_triggers_off(self):
        bundle = make_bundle(self.db, self.item(), fetched_at=now())
        ingest_bundle(self.db, bundle, self.root)
        self.db.execute("PRAGMA recursive_triggers=OFF")
        for table in ("raw_items", "event_versions", "evidence", "availability_receipts"):
            rows = self.db.execute(f"SELECT * FROM {table}").fetchall()
            placeholders = ",".join("?" for _ in rows[0])
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append_only_replace"):
                self.db.execute(f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})", rows[0])
            self.db.rollback()
            self.assertEqual(rows, self.db.execute(f"SELECT * FROM {table}").fetchall())

    def test_unknown_rss_timezone_is_preserved_without_guessing(self):
        item = self.item()
        item.update(source_time_text="Fri, 06 Nov 2026 09:30:00 MYSTERY", source_timezone="MYSTERY", time_parse_status="timezone_missing")
        bundle = make_bundle(self.db, item, fetched_at=now())
        ingest_bundle(self.db, bundle, self.root)
        self.assertIsNone(bundle["raw"]["source_published_at"])


if __name__ == "__main__":
    unittest.main()
