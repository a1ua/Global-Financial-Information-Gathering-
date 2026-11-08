import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from market_intel.contracts import ContractError
from market_intel.contracts.report import validate_report_manifest
from market_intel.offline import connect, ingest_fixture, render


def input_hash(inputs):
    canonical = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def valid_manifest(version="0.3", synthetic=True):
    inputs = {"raw_item_ids": ["raw_1"], "event_version_ids": ["event_1"], "evidence_ids": ["evidence_1"], "prediction_ids": [], "market_snapshot_id": None}
    return {
        "schema_version": "report-manifest/0.1", "report_id": "test_v1", "run_id": "test_v1",
        "report_type": "offline_fixture" if synthetic else "source_snapshot",
        "market_session_date": None, "display_timezone": "Asia/Shanghai",
        "information_cutoff": "2026-11-06T00:30:00Z", "generated_at": "2026-11-08T04:00:00Z",
        "status": "degraded", "reason_codes": ["synthetic_fixture", "retrospective", "market_data_unavailable"] if synthetic else ["rss_excerpt_only" if version == "0.2" else "source_metadata_only", "content_support_not_reviewed", "market_data_unavailable"],
        "input_manifest": inputs, "input_manifest_sha256": input_hash(inputs),
        "canonical_json_version": "python-json-sorted-utf8/0.1", "source_config_version": "sources-test-1",
        "rules_version": "strict-cutoff/" + version, "template_version": "evidence-brief/" + version,
        "renderer_version": "evidence-brief/" + version, "market_data_as_of": None,
        "citation_check": "passed", "content_support_check": "not_performed",
        "artifact_refs": ["brief.html"], "artifact_sha256": "a" * 64,
        "supersedes_report_id": None, "is_synthetic": synthetic,
    }


class ReportManifestTests(unittest.TestCase):
    def test_current_and_legacy_versions_without_input_mutation(self):
        for version in ("0.2", "0.3"):
            for synthetic in (True, False):
                value = valid_manifest(version, synthetic)
                before = copy.deepcopy(value)
                validate_report_manifest(value, expected_report_id="test_v1")
                self.assertEqual(value, before)

    def test_missing_unknown_or_nonobject_rejected(self):
        for value in (None, [], "report"):
            with self.assertRaises(ContractError):
                validate_report_manifest(value)
        for key, action in (("generated_at", "remove"), ("published_at", "add")):
            value = valid_manifest()
            if action == "remove":
                del value[key]
            else:
                value[key] = "2026-11-08T04:01:00Z"
            with self.assertRaisesRegex(ContractError, "missing_or_unknown_fields"):
                validate_report_manifest(value)

    def test_report_directory_identity_and_no_self_supersedes(self):
        for key in ("report_id", "run_id", "supersedes_report_id"):
            value = valid_manifest()
            value[key] = "../outside"
            with self.assertRaisesRegex(ContractError, "invalid_report_id"):
                validate_report_manifest(value)
        with self.assertRaisesRegex(ContractError, "report_id_mismatch"):
            validate_report_manifest(valid_manifest(), expected_report_id="another")
        value = valid_manifest()
        value["supersedes_report_id"] = value["report_id"]
        with self.assertRaisesRegex(ContractError, "self_reference"):
            validate_report_manifest(value)

    def test_utc_order_dates_and_display_timezone(self):
        cases = {"generated_at": "2026-11-06T00:29:59Z", "information_cutoff": "2026-11-06T00:30:00+00:00", "market_session_date": "2026-02-30", "display_timezone": "Not/AZone"}
        for key, invalid in cases.items():
            value = valid_manifest()
            value[key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_report_manifest(value)
        value = valid_manifest()
        value["market_session_date"] = "2026-11-06"
        validate_report_manifest(value)

    def test_versions_canonicalization_and_hash_shapes(self):
        cases = {"schema_version": "report-manifest/99", "renderer_version": "offline/0.1", "template_version": "evidence-brief/0.2", "rules_version": "strict-cutoff/0.2", "canonical_json_version": "unspecified", "artifact_sha256": "A" * 64, "input_manifest_sha256": "a" * 64}
        for key, invalid in cases.items():
            value = valid_manifest()
            value[key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_report_manifest(value)

    def test_input_lists_types_uniqueness_and_reference_shape(self):
        for key in ("raw_item_ids", "event_version_ids", "evidence_ids", "prediction_ids"):
            for invalid in ("not-a-list", ["same", "same"], [True], ["../path"]):
                value = valid_manifest()
                value["input_manifest"][key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ContractError):
                    validate_report_manifest(value)
        value = valid_manifest()
        value["input_manifest"]["unexpected"] = []
        with self.assertRaisesRegex(ContractError, "missing_or_unknown_fields"):
            validate_report_manifest(value)
        value = valid_manifest()
        value["input_manifest"]["raw_item_ids"] = []
        with self.assertRaisesRegex(ContractError, "incomplete_evidence_input_set"):
            validate_report_manifest(value)

    def test_hash_recomputed_using_exact_declared_algorithm(self):
        value = valid_manifest()
        value["input_manifest"]["raw_item_ids"] = ["raw_changed"]
        with self.assertRaisesRegex(ContractError, "input_manifest_hash_mismatch"):
            validate_report_manifest(value)
        value["input_manifest_sha256"] = input_hash(value["input_manifest"])
        validate_report_manifest(value)

    def test_model_and_market_claims_not_supported(self):
        for key, invalid in (("prediction_ids", ["prediction_1"]), ("market_snapshot_id", "market_1")):
            value = valid_manifest()
            value["input_manifest"][key] = invalid
            with self.assertRaisesRegex(ContractError, "prediction_or_market_not_supported"):
                validate_report_manifest(value)
        value = valid_manifest()
        value["market_data_as_of"] = "2026-11-06T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "market_data_not_supported"):
            validate_report_manifest(value)

    def test_fixed_artifact_path_blocks_escape_or_extra_files(self):
        for invalid in (["../brief.html"], ["C:/brief.html"], ["brief.html", "extra"], "brief.html", []):
            value = valid_manifest()
            value["artifact_refs"] = invalid
            with self.assertRaisesRegex(ContractError, "fixed_artifact_path_required"):
                validate_report_manifest(value)

    def test_source_configs_and_empty_report(self):
        value = valid_manifest(synthetic=False)
        value["source_config_version"] = "fed-rss-0.1,nbs-list-0.1"
        validate_report_manifest(value)
        for invalid in ("", "b,a", "a,a", "../outside"):
            value["source_config_version"] = invalid
            with self.assertRaises(ContractError):
                validate_report_manifest(value)
        value = valid_manifest(synthetic=False)
        for key in ("raw_item_ids", "event_version_ids", "evidence_ids"):
            value["input_manifest"][key] = []
        value["source_config_version"] = ""
        value["input_manifest_sha256"] = input_hash(value["input_manifest"])
        validate_report_manifest(value)

    def test_status_support_and_synthetic_consistency(self):
        for key, invalid in (("status", "succeeded"), ("content_support_check", "verified"), ("citation_check", "unchecked"), ("is_synthetic", 1), ("report_type", "A_pre")):
            value = valid_manifest()
            value[key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_report_manifest(value)
        value = valid_manifest()
        value["is_synthetic"] = False
        with self.assertRaises(ContractError):
            validate_report_manifest(value)

    def test_reason_codes_are_unique_known_and_consistent(self):
        for reasons in ([], ["market_data_unavailable"], ["synthetic_fixture"] * 2, ["arbitrary"], "synthetic_fixture"):
            value = valid_manifest()
            value["reason_codes"] = reasons
            with self.assertRaises(ContractError):
                validate_report_manifest(value)
        value = valid_manifest(synthetic=False)
        value["reason_codes"].append("mixed_test_data")
        validate_report_manifest(value)

    def test_rendered_fixture_manifest_is_accepted(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = connect(root / "market.db")
            try:
                ingest_fixture(db, fixture, root)
                path = render(db, root, "2026-11-06T00:30:00Z", "fixture_report")
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                validate_report_manifest(manifest, expected_report_id="fixture_report")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
