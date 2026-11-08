import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.offline import connect, ingest_fixture, render, replay_report
from market_intel.ops.backup import create_backup, restore_backup, verify_backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.workspace = self.base / "workspace"
        self.db = connect(self.workspace / "market.db")
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        ingest_fixture(self.db, self.bundle, self.workspace)
        self.report = render(self.db, self.workspace, "2026-11-06T00:30:00Z", "demo")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def backup(self):
        destination = self.base / "backup"
        result = create_backup(self.workspace, destination)
        return destination, result

    def test_snapshot_restores_database_evidence_and_report_replay(self):
        destination, result = self.backup()
        self.assertEqual(result["status"], "backed_up")
        self.assertEqual(result["raw_items"], 1)
        self.assertEqual(result["reports"], 1)
        restored = self.base / "restored"
        self.assertEqual(restore_backup(destination, restored)["status"], "restored")
        restored_db = connect(restored / "market.db")
        try:
            self.assertEqual(restored_db.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0], 1)
            output = replay_report(restored_db, restored, "demo", self.base / "replayed")
            self.assertEqual((self.report / "brief.html").read_bytes(), (output / "brief.html").read_bytes())
        finally:
            restored_db.close()

    def test_sqlite_backup_includes_committed_wal_not_uncommitted_write(self):
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("INSERT INTO capture_sources(source_id,last_successful_scan_at,scan_items) VALUES ('committed','2026-11-06T01:00:00Z',0)")
        self.db.commit()
        self.db.execute("INSERT INTO capture_sources(source_id,last_successful_scan_at,scan_items) VALUES ('pending','2026-11-06T02:00:00Z',0)")
        try:
            destination, _ = self.backup()
            snapshot = sqlite3.connect(destination / "market.db")
            try:
                self.assertEqual(snapshot.execute("SELECT source_id FROM capture_sources").fetchall(), [("committed",)])
            finally:
                snapshot.close()
        finally:
            self.db.rollback()

    def test_source_missing_evidence_never_publishes_backup(self):
        (self.workspace / self.bundle["raw"]["content_ref"]).unlink()
        with self.assertRaisesRegex(ValueError, "(?:backup|report)_file_missing"):
            self.backup()
        self.assertFalse((self.base / "backup").exists())

    def test_source_corrupt_evidence_never_publishes_backup(self):
        (self.workspace / self.bundle["raw"]["content_ref"]).write_text("corrupt", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.backup()
        self.assertFalse((self.base / "backup").exists())

    def test_backup_missing_evidence_fails_even_if_database_is_healthy(self):
        destination, _ = self.backup()
        (destination / self.bundle["raw"]["content_ref"]).unlink()
        with self.assertRaisesRegex(ValueError, "backup_file_missing"):
            verify_backup(destination)
        with self.assertRaises(ValueError):
            restore_backup(destination, self.base / "restored")
        self.assertFalse((self.base / "restored").exists())

    def test_corrupt_database_or_report_is_rejected(self):
        destination, _ = self.backup()
        html = destination / "reports/demo/brief.html"
        html.write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_file_hash_mismatch"):
            verify_backup(destination)
        html.write_bytes((self.report / "brief.html").read_bytes())
        (destination / "market.db").write_bytes(b"not a database")
        with self.assertRaisesRegex(ValueError, "backup_file_hash_mismatch"):
            verify_backup(destination)

    def test_existing_destination_is_never_overwritten(self):
        target = self.base / "existing"
        target.mkdir()
        marker = target / "do-not-touch.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_destination_exists"):
            create_backup(self.workspace, target)
        destination, _ = self.backup()
        with self.assertRaisesRegex(ValueError, "backup_destination_exists"):
            restore_backup(destination, target)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_nested_and_reverse_nested_targets_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "backup_directories_overlap"):
            create_backup(self.workspace, self.workspace / "nested")
        with self.assertRaisesRegex(ValueError, "backup_destination_exists"):
            create_backup(self.workspace, self.base)
        destination, _ = self.backup()
        with self.assertRaisesRegex(ValueError, "backup_directories_overlap"):
            restore_backup(destination, destination / "nested")

    def test_manifest_path_escape_and_unexpected_file_are_rejected(self):
        destination, _ = self.backup()
        path = destination / "backup-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"]["../outside.txt"] = {"sha256": "a" * 64, "size": 1}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe_backup_path"):
            verify_backup(destination)
        del manifest["files"]["../outside.txt"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        (destination / "unexpected.env").write_text("not backed up", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_unexpected_or_missing_files"):
            verify_backup(destination)

    def test_manifest_cannot_omit_referenced_evidence(self):
        destination, _ = self.backup()
        path = destination / "backup-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["files"][self.bundle["raw"]["content_ref"]]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_unexpected_or_missing_files"):
            verify_backup(destination)

    def test_staging_and_unreferenced_files_are_excluded(self):
        staging = self.workspace / "reports/.staging-unpublished"
        staging.mkdir()
        (staging / "brief.html").write_text("partial", encoding="utf-8")
        (self.workspace / "secrets.env").write_text("excluded", encoding="utf-8")
        (self.workspace / "raw/unreferenced.txt").write_text("orphan", encoding="utf-8")
        destination, _ = self.backup()
        self.assertFalse((destination / "secrets.env").exists())
        self.assertFalse((destination / "raw/unreferenced.txt").exists())
        self.assertFalse((destination / "reports/.staging-unpublished").exists())

    def test_linked_evidence_or_backup_objects_are_rejected(self):
        raw = self.workspace / self.bundle["raw"]["content_ref"]
        original = raw.read_bytes()
        external = self.base / "outside.txt"
        external.write_bytes(original)
        raw.unlink()
        try:
            raw.symlink_to(external)
        except OSError:
            raw.write_bytes(original)
            self.skipTest("This Windows account cannot create symbolic links")
        with self.assertRaisesRegex(ValueError, "backup_symlink_forbidden"):
            self.backup()

    def test_source_corrupt_report_is_not_silently_skipped(self):
        (self.report / "brief.html").write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_report_artifact_corrupt"):
            self.backup()

    def test_symlink_guard_is_exercised_without_windows_link_privilege(self):
        from unittest.mock import patch
        from market_intel.ops import backup as module
        raw = self.workspace / self.bundle["raw"]["content_ref"]
        original = module._linked
        with patch.object(module, "_linked", side_effect=lambda path: path == raw or original(path)):
            with self.assertRaisesRegex(ValueError, "backup_symlink_forbidden"):
                self.backup()

    def test_backup_does_not_modify_source_database_or_content(self):
        before_db = (self.workspace / "market.db").read_bytes()
        before_raw = (self.workspace / self.bundle["raw"]["content_ref"]).read_bytes()
        self.backup()
        self.assertEqual(before_db, (self.workspace / "market.db").read_bytes())
        self.assertEqual(before_raw, (self.workspace / self.bundle["raw"]["content_ref"]).read_bytes())

    def test_malformed_raw_payload_raises_structured_error(self):
        payload = {"raw_item_id": "bad", "content_sha256": "a" * 64, "content_ref": "raw/" + "a" * 64 + ".txt", "normalized_text": False}
        with self.db:
            self.db.execute("INSERT INTO raw_items VALUES (?,?)", ("bad", json.dumps(payload)))
        with self.assertRaisesRegex(ValueError, "backup_invalid_raw_record"):
            self.backup()

    def test_unsupported_source_database_schema_is_rejected(self):
        self.db.execute("PRAGMA user_version=999")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "backup_database_version_unsupported"):
            self.backup()

    def test_unsupported_backup_database_schema_is_rejected_even_with_new_hash(self):
        import hashlib
        destination, _ = self.backup()
        changed = sqlite3.connect(destination / "market.db")
        changed.execute("PRAGMA user_version=999")
        changed.close()
        path = destination / "backup-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        data = (destination / "market.db").read_bytes()
        manifest["files"]["market.db"] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        manifest["database_schema_version"] = 999
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "backup_database_version_unsupported"):
            verify_backup(destination)


if __name__ == "__main__":
    unittest.main()
