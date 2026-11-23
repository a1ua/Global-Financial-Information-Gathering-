from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from market_intel.pipeline.process.cluster import evaluate_synthetic_event_clusters


_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE = _ROOT / "config" / "synthetic-event-cluster-evaluation.example.json"
_CUTOFF = "2026-11-06T00:06:00Z"
_REVIEW = {
    "labeled_candidates": 2,
    "same_event_candidates": 1,
    "different_event_candidates": 1,
    "uncovered_false_negatives": 1,
    "covered_false_negative_pairs": [["ev_cluster_demo_original", "ev_cluster_demo_restatement"]],
}


class TitleReviewCoverageTests(unittest.TestCase):
    def load_example(self):
        example = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
        return example["bundles"], example["labels"]

    def test_example_fixed_counts_default_and_reordered_inputs(self):
        bundles, labels = self.load_example()
        original = deepcopy((bundles, labels))
        baseline = evaluate_synthetic_event_clusters(bundles, labels, cutoff=_CUTOFF)
        self.assertNotIn("title_review", baseline)
        self.assertEqual(baseline["counts"], {
            "labeled_pairs": 4, "true_positive": 1, "false_positive": 0,
            "false_negative": 2, "true_negative": 1,
        })
        expected = {**baseline, "title_review": _REVIEW}
        self.assertEqual(evaluate_synthetic_event_clusters(
            bundles, labels, cutoff=_CUTOFF, include_title_review=True), expected)
        reversed_labels = [{**label, "event_version_ids": list(reversed(label["event_version_ids"]))}
                           for label in reversed(labels)]
        self.assertEqual(evaluate_synthetic_event_clusters(
            list(reversed(bundles)), reversed_labels, cutoff=_CUTOFF, include_title_review=True), expected)
        self.assertEqual((bundles, labels), original)

    def test_exact_overlap_is_excluded_even_when_exact_rule_is_wrong(self):
        bundles, labels = self.load_example()
        labels[0]["same_event"] = False
        result = evaluate_synthetic_event_clusters(bundles, labels, cutoff=_CUTOFF, include_title_review=True)
        self.assertEqual(result["counts"]["false_positive"], 1)
        self.assertEqual(result["title_review"], _REVIEW)

    def test_unlabeled_pairs_do_not_count_and_option_requires_bool(self):
        bundles, _ = self.load_example()
        report = evaluate_synthetic_event_clusters(bundles, [], cutoff=_CUTOFF, include_title_review=True)
        self.assertEqual(report["title_review"], {
            "labeled_candidates": 0,
            "same_event_candidates": 0,
            "different_event_candidates": 0,
            "uncovered_false_negatives": 0,
            "covered_false_negative_pairs": [],
        })
        with self.assertRaisesRegex(ValueError, "^synthetic_event_cluster_evaluation_invalid$"):
            evaluate_synthetic_event_clusters(bundles, [], cutoff=_CUTOFF, include_title_review=1)

    def test_actual_cli_and_unavailable_cutoff(self):
        baseline_bytes = _EXAMPLE.read_bytes()
        command = [
            sys.executable, "-X", "utf8", "-m", "market_intel", "evaluate-synthetic-event-clusters",
            "--input", str(_EXAMPLE), "--include-title-review", "--cutoff",
        ]

        def run(cutoff):
            return subprocess.run(
                [*command, cutoff], cwd=_ROOT, env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
                capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
            )

        bundles, labels = self.load_example()
        result = run(_CUTOFF)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(json.loads(result.stdout), evaluate_synthetic_event_clusters(
            bundles, labels, cutoff=_CUTOFF, include_title_review=True))
        for marker in ("Synthetic industry support notice", "Synthetic agency A", "example.com"):
            self.assertNotIn(marker, result.stdout)
        failed = run("2026-11-06T00:05:59.999999Z")
        self.assertEqual((failed.returncode, failed.stdout), (1, ""))
        self.assertIn("synthetic_event_cluster_evaluation_invalid", failed.stderr)
        self.assertNotIn(str(_EXAMPLE), failed.stderr)
        self.assertEqual(_EXAMPLE.read_bytes(), baseline_bytes)
