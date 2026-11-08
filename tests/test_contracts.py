import copy
import hashlib
import json
from pathlib import Path
import unittest

from market_intel.contracts import ContractError, validate_bundle


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))

    def refresh_text(self, value):
        raw, ev = self.bundle["raw"], self.bundle["evidence"]
        raw["normalized_text"] = value
        raw["content_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()
        raw["content_ref"] = f"raw/{raw['content_sha256']}.txt"
        ev["quote"] = value
        ev["locator"]["start"] = 0
        ev["locator"]["end"] = len(value)

    def real_bundle(self, policy="excerpt_metadata"):
        for key in ("raw", "event", "evidence"):
            self.bundle[key]["is_synthetic"] = False
        self.bundle["raw"]["storage_policy"] = policy
        self.bundle["event"]["extraction_method"] = "rule"
        self.bundle["event"]["extraction_quality"] = "structurally_valid"

    def test_fixture_compatible_and_unchanged(self):
        original = copy.deepcopy(self.bundle)
        self.assertIsNone(validate_bundle(self.bundle))
        self.assertEqual(self.bundle, original)

    def test_allow_synthetic_false_rejects_fixture(self):
        with self.assertRaisesRegex(ContractError, "synthetic_not_allowed"):
            validate_bundle(self.bundle, allow_synthetic=False)

    def test_real_excerpt_and_full_text(self):
        for policy in ("excerpt_metadata", "full_text"):
            self.real_bundle(policy)
            self.assertIsNone(validate_bundle(self.bundle, allow_synthetic=False))

    def test_fixture_policy_cannot_be_real(self):
        self.real_bundle("full_text_fixture")
        with self.assertRaisesRegex(ContractError, "fixture_policy"):
            validate_bundle(self.bundle)

    def test_mixed_synthetic_flags_rejected(self):
        self.bundle["event"]["is_synthetic"] = False
        with self.assertRaisesRegex(ContractError, "mixed_synthetic"):
            validate_bundle(self.bundle)

    def test_nonobjects_and_missing_unknown_fields(self):
        for value in (None, [], {"raw": {}}, {**self.bundle, "instruction": "ignore rules"}):
            with self.subTest(value=type(value)), self.assertRaises(ContractError):
                validate_bundle(value)
        del self.bundle["raw"]["source_id"]
        with self.assertRaisesRegex(ContractError, "missing_or_unknown"):
            validate_bundle(self.bundle)

    def test_invalid_schema_and_enum(self):
        for obj, field, value in (("raw", "schema_version", "raw-item/9"), ("event", "category", "buy"), ("evidence", "validation_status", "semantically_verified"), ("event", "markets", ["HK"]), ("raw", "source_tier", [])):
            sample = copy.deepcopy(self.bundle)
            sample[obj][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_bundle(sample)

    def test_bool_is_not_version_or_offset(self):
        for version in (True, False, 0, -1, 1.0, "1"):
            sample = copy.deepcopy(self.bundle)
            sample["event"]["version"] = version
            with self.subTest(version=version), self.assertRaises(ContractError):
                validate_bundle(sample)
        self.bundle["evidence"]["locator"]["start"] = False
        with self.assertRaisesRegex(ContractError, "invalid_locator"):
            validate_bundle(self.bundle)

    def test_ids_and_self_supersedes(self):
        for bad in ("../escape", "", "two words", "新闻", "x" * 129):
            sample = copy.deepcopy(self.bundle)
            sample["raw"]["raw_item_id"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                validate_bundle(sample)
        self.bundle["event"]["supersedes_event_version_id"] = self.bundle["event"]["event_version_id"]
        with self.assertRaisesRegex(ContractError, "self_reference"):
            validate_bundle(self.bundle)

    def test_utc_timestamp_shape_and_calendar_validity(self):
        for bad in ("2026-11-06T00:05:03", "2026-11-06T08:05:03+08:00", "2026-02-30T00:05:03Z", "20261106T000503Z", "2026-11-06T00:05:03z", None):
            sample = copy.deepcopy(self.bundle)
            sample["raw"]["available_at"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                validate_bundle(sample)

    def test_time_order_and_commit_equality(self):
        changes = (("raw", "first_seen_at", "2026-11-06T01:00:00Z"), ("raw", "available_at", "2026-11-06T00:05:04Z"), ("event", "processed_at", "2026-11-06T00:07:00Z"), ("evidence", "available_at", "2026-11-06T00:00:00Z"))
        for obj, field, value in changes:
            sample = copy.deepcopy(self.bundle)
            sample[obj][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, "timestamp_order_invalid"):
                validate_bundle(sample)

    def test_date_only_does_not_gain_midnight(self):
        raw = self.bundle["raw"]
        raw.update(time_parse_status="date_only", source_time_precision="date", source_published_at=None)
        validate_bundle(self.bundle)
        raw["source_published_at"] = "2026-11-06T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "date_only"):
            validate_bundle(self.bundle)

    def test_unknown_times_do_not_gain_utc(self):
        raw = self.bundle["raw"]
        for status in ("missing", "invalid", "timezone_missing", "failed", "ambiguous"):
            raw.update(time_parse_status=status, source_time_precision="unknown", source_published_at=None, source_timezone=None)
            validate_bundle(self.bundle)
        raw["source_published_at"] = "2026-11-06T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "unparsed_time"):
            validate_bundle(self.bundle)

    def test_timezone_offsets_gmt_and_iana(self):
        raw = self.bundle["raw"]
        for zone in ("Asia/Shanghai", "GMT", "UTC", "+08:00", "+0800", "-0500"):
            raw["source_timezone"] = zone
            raw["source_published_date"] = "2026-11-05" if zone == "-0500" else "2026-11-06"
            validate_bundle(self.bundle)
        raw["source_timezone"] = "+24:00"
        with self.assertRaisesRegex(ContractError, "invalid_offset"):
            validate_bundle(self.bundle)

    def test_local_date_consistency(self):
        self.bundle["raw"]["source_published_date"] = "2026-11-05"
        with self.assertRaisesRegex(ContractError, "local_date_mismatch"):
            validate_bundle(self.bundle)

    def test_unsafe_http_urls(self):
        for url in ("javascript:alert(1)", "file:///secret", "https://user:secret@example.com/", "http://localhost/x", "http://127.0.0.1/x", "http://[::1]/x", "http://10.0.0.1/x", "http://2130706433/", "http://127.1/", "https://example.com:99999/", "https://example.com/\nheader", "https://example.com/\"bad", "https://example.com\\@evil.com/", "https://bad%.example.com/", "https://service.local/x"):
            sample = copy.deepcopy(self.bundle)
            sample["raw"]["original_url"] = url
            with self.subTest(url=url), self.assertRaises(ContractError):
                validate_bundle(sample)

    def test_canonical_url_is_checked_too(self):
        self.bundle["raw"]["canonical_url"] = "javascript:alert(1)"
        with self.assertRaises(ContractError):
            validate_bundle(self.bundle)

    def test_hash_and_content_address(self):
        self.bundle["raw"]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "content_hash_mismatch"):
            validate_bundle(self.bundle)
        self.refresh_text("新的合成文本")
        self.bundle["raw"]["content_ref"] = "../" + self.bundle["raw"]["content_ref"]
        with self.assertRaisesRegex(ContractError, "content_address"):
            validate_bundle(self.bundle)

    def test_broken_single_bundle_reference(self):
        self.bundle["event"]["input_raw_item_ids"].append("raw_other")
        with self.assertRaisesRegex(ContractError, "single_bundle_reference"):
            validate_bundle(self.bundle)
        self.bundle["event"]["input_raw_item_ids"] = [self.bundle["raw"]["raw_item_id"]]
        self.bundle["evidence"]["event_version_id"] = "event_other_v1"
        with self.assertRaisesRegex(ContractError, "broken_reference"):
            validate_bundle(self.bundle)

    def test_unicode_code_points_and_crlf(self):
        self.refresh_text("甲😀乙\r\n第二行")
        self.bundle["evidence"]["quote"] = "😀"
        self.bundle["evidence"]["locator"].update(start=1, end=2)
        validate_bundle(self.bundle)
        self.bundle["evidence"]["locator"]["end"] = 3
        with self.assertRaisesRegex(ContractError, "quote_mismatch"):
            validate_bundle(self.bundle)

    def test_lone_surrogate_rejected_as_contract_error(self):
        self.bundle["raw"]["title"] = "\ud800"
        with self.assertRaisesRegex(ContractError, "invalid_unicode"):
            validate_bundle(self.bundle)

    def test_metadata_only_title_preservation(self):
        self.real_bundle("metadata_only")
        title = self.bundle["raw"]["title"]
        self.refresh_text(title)
        self.bundle["event"].update(title=title, fact_summary=title, extraction_quality="metadata_only")
        self.bundle["evidence"]["relation"] = "reports"
        validate_bundle(self.bundle, allow_synthetic=False)
        self.bundle["event"]["fact_summary"] = "未保存正文的新结论"
        with self.assertRaisesRegex(ContractError, "metadata_only"):
            validate_bundle(self.bundle)

    def test_structural_validation_does_not_upgrade_semantics(self):
        self.real_bundle()
        self.bundle["event"]["fact_summary"] = "语义上未经核查的外部陈述"
        original = copy.deepcopy(self.bundle)
        validate_bundle(self.bundle)
        self.assertEqual(self.bundle, original)
        self.assertEqual(self.bundle["event"]["extraction_quality"], "structurally_valid")


if __name__ == "__main__":
    unittest.main()
