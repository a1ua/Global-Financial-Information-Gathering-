from copy import deepcopy
import json
from pathlib import Path
import unittest

from market_intel.contracts.synthetic_extraction import evaluate_synthetic_extraction


class SyntheticExtractionEvaluationTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "demo.json"
        self.reference = json.loads(fixture.read_text(encoding="utf-8"))
        self.cutoff = self.reference["raw"]["available_at"]

    def case(self, index, expected="company", proposed="company"):
        reference = deepcopy(self.reference)
        raw = reference["raw"]
        raw_id = f"raw_evaluation_{index}"
        raw["raw_item_id"] = raw_id
        reference["event"]["input_raw_item_ids"] = [raw_id]
        reference["evidence"]["raw_item_id"] = raw_id
        proposal = {
            "schema_version": "synthetic-extraction-proposal/0.1",
            "is_synthetic": True,
            "raw_item_id": raw_id,
            "content_sha256": raw["content_sha256"],
            "normalization_version": raw["normalization_version"],
            "category": proposed,
            "start": 0,
            "end": 2,
            "quote": raw["normalized_text"][:2],
        }
        return {"reference_bundle": reference, "expected_category": expected, "proposal": proposal}

    def assert_invalid_batch(self, cases, *, cutoff=None):
        with self.assertRaisesRegex(ValueError, "^synthetic_extraction_evaluation_invalid$"):
            evaluate_synthetic_extraction(cases, cutoff=self.cutoff if cutoff is None else cutoff)

    def test_counts_all_cases_and_reports_sorted_pairs_only_for_valid_proposals(self):
        missing = dict(self.case(1), proposal=None)
        invalid = self.case(2)
        invalid["proposal"]["quote"] = "synthetic-private-marker"
        cases = [self.case(3, "policy", "policy"), missing, self.case(4, "company", "policy"),
                 invalid, self.case(5), self.case(6, "company", "policy")]
        original = deepcopy(cases)
        result = evaluate_synthetic_extraction(cases, cutoff=self.cutoff)
        self.assertEqual(result, {
            "schema_version": "synthetic-extraction-evaluation/0.1",
            "is_synthetic": True,
            "counts": {"total": 6, "correct": 2, "incorrect": 2, "invalid": 1, "missing": 1},
            "category_pairs": [
                {"expected_category": "company", "proposed_category": "company", "count": 1},
                {"expected_category": "company", "proposed_category": "policy", "count": 2},
                {"expected_category": "policy", "proposed_category": "policy", "count": 1},
            ],
        })
        self.assertEqual(evaluate_synthetic_extraction(cases[::-1], cutoff=self.cutoff), result)
        self.assertEqual(cases, original)

    def test_bad_proposals_count_as_invalid_without_rejecting_good_references(self):
        cases = [dict(self.case(index), proposal=proposal)
                 for index, proposal in enumerate((False, {}, [], "synthetic-invalid-value", 0))]
        wrong_source = self.case(5)
        wrong_source["proposal"]["content_sha256"] = "a" * 64
        cases.append(wrong_source)
        result = evaluate_synthetic_extraction(cases, cutoff=self.cutoff)
        self.assertEqual(result["counts"], {"total": 6, "correct": 0, "incorrect": 0, "invalid": 6, "missing": 0})
        self.assertEqual(result["category_pairs"], [])

    def test_bad_labeled_references_fail_even_for_missing_proposals(self):
        missing = dict(self.case(1), proposal=None)
        tampered = deepcopy(missing)
        tampered["reference_bundle"]["raw"]["normalized_text"] += " private-tamper-marker"
        duplicate = dict(self.case(1), proposal=None)
        for cases in ([missing, duplicate], [tampered], [dict(missing, expected_category="unsupported")],
                      [dict(missing, expected_category=[])], [dict(missing, extra=True)], [None], (missing,)):
            with self.subTest(cases_type=type(cases)):
                self.assert_invalid_batch(cases)
        self.assert_invalid_batch([missing], cutoff="2026-11-06T00:05:02.999999Z")

    def test_empty_evaluation_still_requires_a_valid_cutoff(self):
        result = evaluate_synthetic_extraction([], cutoff=self.cutoff)
        self.assertEqual(result["counts"], {"total": 0, "correct": 0, "incorrect": 0, "invalid": 0, "missing": 0})
        self.assertEqual(result["category_pairs"], [])
        for cutoff in ("2026-11-06T00:05:03", "2026-11-06T00:05:03+00:00"):
            with self.subTest(cutoff=cutoff):
                self.assert_invalid_batch([], cutoff=cutoff)

    def test_batch_requires_at_most_one_thousand_cases(self):
        cases = [dict(self.case(index), proposal=None) for index in range(1000)]
        result = evaluate_synthetic_extraction(cases, cutoff=self.cutoff)
        self.assertEqual(result["counts"], {"total": 1000, "correct": 0, "incorrect": 0, "invalid": 0, "missing": 1000})
        self.assert_invalid_batch([*cases, self.case(1000)])
