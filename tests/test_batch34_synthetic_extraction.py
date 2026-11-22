from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from market_intel.contracts import validate_bundle
from market_intel.contracts.synthetic_extraction import validate_synthetic_extraction


class SyntheticExtractionTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "demo.json"
        self.bundle = json.loads(fixture.read_text(encoding="utf-8"))
        self.raw = self.bundle["raw"]
        self.cutoff = self.raw["available_at"]

    def replace_text(self, value):
        digest = sha256(value.encode("utf-8")).hexdigest()
        self.raw.update(normalized_text=value, content_sha256=digest, content_ref=f"raw/{digest}.txt")
        self.bundle["evidence"]["quote"] = value
        self.bundle["evidence"]["locator"].update(start=0, end=len(value))

    def proposal(self, *, start=0, end=2):
        return {
            "schema_version": "synthetic-extraction-proposal/0.1",
            "is_synthetic": True,
            "raw_item_id": self.raw["raw_item_id"],
            "content_sha256": self.raw["content_sha256"],
            "normalization_version": self.raw["normalization_version"],
            "category": "company",
            "start": start,
            "end": end,
            "quote": self.raw["normalized_text"][start:end],
        }

    def assert_invalid(self, proposal, *, cutoff=None):
        with self.assertRaisesRegex(ValueError, "^synthetic_extraction_invalid$"):
            validate_synthetic_extraction(self.bundle, proposal, cutoff=self.cutoff if cutoff is None else cutoff)

    def test_unicode_code_point_span_and_non_mutation(self):
        self.replace_text("\U0001f4c8\u7532e\u0301\u4e59")
        proposal = self.proposal(start=1, end=4)
        original = deepcopy((self.bundle, proposal))
        self.assertEqual(proposal["quote"], "\u7532e\u0301")

        result = validate_synthetic_extraction(self.bundle, proposal, cutoff=self.cutoff)
        self.assertEqual(result, {
            "schema_version": "synthetic-extraction-validation/0.1",
            "is_synthetic": True,
            "status": "structurally_valid",
            "raw_item_id": self.raw["raw_item_id"],
            "content_sha256": self.raw["content_sha256"],
            "category": "company",
            "start": 1,
            "end": 4,
        })
        self.assertEqual((self.bundle, proposal), original)
        self.assert_invalid(dict(proposal, start=2, end=5))  # UTF-16 offsets for the same quote
        self.assert_invalid(dict(proposal, quote="\u7532\u00e9"))

    def test_cutoff_uses_source_availability_with_inclusive_boundary(self):
        proposal = self.proposal()
        result = validate_synthetic_extraction(self.bundle, proposal, cutoff=self.cutoff)
        self.assertEqual(result["status"], "structurally_valid")
        for cutoff in ("2026-11-06T00:05:02.999999Z", "2026-11-06T00:05:03", "2026-11-06T00:05:03+00:00"):
            with self.subTest(cutoff=cutoff):
                self.assert_invalid(proposal, cutoff=cutoff)

    def test_rejects_wrong_source_identity_or_unverified_reference_bytes(self):
        proposal = self.proposal()
        for key, value in (("raw_item_id", "raw_other"), ("content_sha256", "a" * 64),
                           ("normalization_version", "text-normalize/0.2")):
            with self.subTest(key=key):
                self.assert_invalid(dict(proposal, **{key: value}))
        self.raw["normalized_text"] += " synthetic-tamper-marker"
        self.assert_invalid(proposal)

    def test_rejects_malformed_proposals_without_echoing_payload(self):
        proposal = self.proposal()
        for change in ({"is_synthetic": 1}, {"start": False}, {"end": 2.0}, {"start": -1},
                       {"end": len(self.raw["normalized_text"]) + 1}, {"end": 0, "quote": ""},
                       {"category": "private-synthetic-marker"}, {"quote": "private-synthetic-marker"},
                       {"schema_version": "synthetic-extraction-proposal/0.2"},
                       {"instruction": "private-synthetic-marker"}):
            with self.subTest(change=change):
                self.assert_invalid(dict(proposal, **change))
        self.assert_invalid({key: value for key, value in proposal.items() if key != "quote"})
        self.assert_invalid([])

    def test_excludes_valid_metadata_only_and_non_synthetic_references(self):
        self.raw["storage_policy"] = "metadata_only"
        self.replace_text(self.raw["title"])
        self.bundle["event"].update(title=self.raw["title"], fact_summary=self.raw["title"],
                                    extraction_quality="metadata_only")
        self.bundle["evidence"]["relation"] = "reports"
        validate_bundle(self.bundle)
        self.assert_invalid(self.proposal())

        self.raw["storage_policy"] = "full_text"
        for item in self.bundle.values():
            item["is_synthetic"] = False
        self.bundle["event"].update(extraction_method="rule", extraction_quality="structurally_valid")
        validate_bundle(self.bundle)
        self.assert_invalid(self.proposal())
