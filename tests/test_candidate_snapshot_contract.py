import copy
import unittest

from market_intel.contracts.candidate_snapshot import (
    describe_candidate_bundle, payload_sha256, validate_candidate_snapshot,
)
from market_intel.pipeline.evidence_candidates import _descriptor, _stamp
from test_evidence_candidates import fixture


class CandidateSnapshotContractTests(unittest.TestCase):
    def snapshot(self, *bundles, include=True):
        manifest = {"schema_version": "evidence-candidate-input/0.1", "selection_version": "latest-available/0.1",
                    "cutoff": "2026-11-09T12:00:00Z", "max_candidates": 100, "include_synthetic": include,
                    "candidates": [describe_candidate_bundle(b, None) for b in bundles]}
        return {"schema_version": "evidence-candidate-snapshot/0.1", "input_manifest": manifest,
                "input_manifest_sha256": payload_sha256(manifest)}

    def reject(self, snapshot):
        snapshot["input_manifest_sha256"] = payload_sha256(snapshot["input_manifest"])
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_invalid$"):
            validate_candidate_snapshot(snapshot)

    def test_descriptor_matches_09b_for_synthetic_and_real(self):
        for synthetic, receipt in ((True, None), (False, "2026-11-09T01:00:00Z")):
            bundle = fixture(synthetic=synthetic)
            effective = _stamp(receipt or bundle["event"]["available_at"])
            self.assertEqual(describe_candidate_bundle(bundle, receipt), _descriptor(bundle, effective, receipt))

    def test_empty_and_explicit_synthetic_valid(self):
        validate_candidate_snapshot(self.snapshot(include=False))
        validate_candidate_snapshot(self.snapshot(fixture()))

    def test_strict_fields_types_time_and_hash(self):
        original = self.snapshot(fixture())
        mutations = [lambda s: s.update(extra=1),
                     lambda s: s["input_manifest"].update(max_candidates=True),
                     lambda s: s["input_manifest"].update(include_synthetic=1),
                     lambda s: s["input_manifest"].update(cutoff="2026-11-09T12:00:00+00:00"),
                     lambda s: s["input_manifest"]["candidates"][0].update(version=True),
                     lambda s: s["input_manifest"]["candidates"][0].update(effective_available_at="2026-11-09T00:00:00Z"),
                     lambda s: s["input_manifest"]["candidates"][0].update(content_ref="../secret"),
                     lambda s: s["input_manifest"]["candidates"][0].update(receipt_committed_at="2026-11-09T00:00:00Z"),
                     lambda s: s["input_manifest"].update(include_synthetic=False)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(original)
                mutate(value)
                self.reject(value)
        original["input_manifest_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_candidate_snapshot(original)

    def test_duplicate_order_and_shared_raw_conflict_reject(self):
        value = self.snapshot(fixture("b"), fixture("a"))
        self.reject(value)
        value = self.snapshot(fixture(), fixture())
        self.reject(value)
        value = self.snapshot(fixture("a"), fixture("b"))
        candidates = value["input_manifest"]["candidates"]
        candidates[1]["raw_item_id"] = candidates[0]["raw_item_id"]
        self.reject(value)

    def test_bundle_extra_fields_and_invalid_receipts_reject(self):
        for bundle, receipt in (({**fixture(), "extra": 1}, None), (fixture(), "2026-11-09T00:00:00Z"),
                                (fixture(synthetic=False), None),
                                (fixture(synthetic=False), "2026-11-08T00:00:00Z")):
            with self.assertRaises(ValueError):
                describe_candidate_bundle(bundle, receipt)


if __name__ == "__main__":
    unittest.main()
