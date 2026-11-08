import copy
import json
from pathlib import Path
import tempfile
import unittest

from market_intel.offline import canonical, connect, digest, ingest_fixture, render
from market_intel.report.verify import verify_report


class ReportVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "market.db")
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        ingest_fixture(self.db, self.bundle, self.root)
        self.folder = render(self.db, self.root, "2026-11-06T00:30:00Z", "test_report")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def manifest(self):
        return json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest):
        (self.folder / "manifest.json").write_text(canonical(manifest), encoding="utf-8")

    def test_verification_does_not_mutate_published_files_or_database(self):
        before_db = (self.root / "market.db").read_bytes()
        before_html = (self.folder / "brief.html").read_bytes()
        before_manifest = (self.folder / "manifest.json").read_bytes()
        result = verify_report(self.db, self.root, "test_report")
        self.assertEqual(result["events"], 1)
        self.assertEqual(before_db, (self.root / "market.db").read_bytes())
        self.assertEqual(before_html, (self.folder / "brief.html").read_bytes())
        self.assertEqual(before_manifest, (self.folder / "manifest.json").read_bytes())
        self.assertFalse(self.db.in_transaction)

    def test_missing_field_is_structured_validation_error(self):
        value = self.manifest()
        del value["renderer_version"]
        self.write_manifest(value)
        with self.assertRaisesRegex(ValueError, "missing_or_unknown_fields"):
            verify_report(self.db, self.root, "test_report")

    def test_nonexistent_input_even_with_matching_manifest_hash_is_rejected(self):
        value = self.manifest()
        value["input_manifest"]["event_version_ids"] = ["missing_event"]
        value["input_manifest_sha256"] = digest(canonical(value["input_manifest"]))
        self.write_manifest(value)
        with self.assertRaisesRegex(ValueError, "report_input_missing"):
            verify_report(self.db, self.root, "test_report")

    def test_existing_but_unrelated_evidence_is_rejected(self):
        extra = copy.deepcopy(self.bundle)
        extra["raw"]["raw_item_id"] += "_other"
        extra["raw"]["source_item_key"] += "_other"
        extra["event"]["event_id"] += "_other"
        extra["event"]["event_version_id"] += "_other"
        extra["event"]["input_raw_item_ids"] = [extra["raw"]["raw_item_id"]]
        extra["evidence"]["evidence_id"] += "_other"
        extra["evidence"]["raw_item_id"] = extra["raw"]["raw_item_id"]
        extra["evidence"]["event_version_id"] = extra["event"]["event_version_id"]
        extra["event"]["evidence_ids"] = [extra["evidence"]["evidence_id"]]
        ingest_fixture(self.db, extra, self.root)
        value = self.manifest()
        value["input_manifest"]["evidence_ids"] = [extra["evidence"]["evidence_id"]]
        value["input_manifest_sha256"] = digest(canonical(value["input_manifest"]))
        self.write_manifest(value)
        with self.assertRaisesRegex(ValueError, "report_input_closure_mismatch"):
            verify_report(self.db, self.root, "test_report")

    def test_tampered_cutoff_cannot_include_later_evidence(self):
        value = self.manifest()
        value["information_cutoff"] = "2026-11-06T00:00:00Z"
        self.write_manifest(value)
        with self.assertRaisesRegex(ValueError, "report_input_after_cutoff"):
            verify_report(self.db, self.root, "test_report")

    def test_deleted_or_changed_raw_file_fails_verification(self):
        path = self.root / self.bundle["raw"]["content_ref"]
        path.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "report_evidence_corrupt"):
            verify_report(self.db, self.root, "test_report")
        path.unlink()
        with self.assertRaisesRegex(ValueError, "report_file_missing"):
            verify_report(self.db, self.root, "test_report")

    def test_tampered_html_fails_verification(self):
        (self.folder / "brief.html").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "published_artifact_corrupt"):
            verify_report(self.db, self.root, "test_report")

    def test_declared_source_configuration_must_match_actual_inputs(self):
        value = self.manifest()
        value["source_config_version"] = "unrelated-source-1"
        self.write_manifest(value)
        with self.assertRaisesRegex(ValueError, "report_source_config_mismatch"):
            verify_report(self.db, self.root, "test_report")

    def test_corrupt_naive_receipt_is_validation_error_not_type_error(self):
        from market_intel.capture import now
        from market_intel.offline import ingest_bundle
        real_root = self.root / "receipt-case"
        real_db = connect(real_root / "market.db")
        try:
            bundle = copy.deepcopy(self.bundle)
            for record in bundle.values():
                record["is_synthetic"] = False
            bundle["raw"]["storage_policy"] = "excerpt_metadata"
            bundle["event"]["extraction_method"] = "rule"
            bundle["event"]["extraction_quality"] = "structurally_valid"
            ingest_bundle(real_db, bundle, real_root)
            render(real_db, real_root, now(), "receipt_report")
            # Simulate an independently damaged test snapshot, not an app update.
            real_db.execute("DROP TRIGGER receipts_no_update")
            real_db.execute("UPDATE availability_receipts SET committed_at='2026-11-06T00:00:00'")
            real_db.commit()
            with self.assertRaisesRegex(ValueError, "utc_z_timestamp_required"):
                verify_report(real_db, real_root, "receipt_report")
        finally:
            real_db.close()


if __name__ == "__main__":
    unittest.main()
