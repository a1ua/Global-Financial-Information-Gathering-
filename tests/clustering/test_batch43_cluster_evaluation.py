from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from market_intel.pipeline.process.cluster import evaluate_synthetic_event_clusters

from clustering import test_batch42_synthetic_cluster as fixtures


class SyntheticEventClusterEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads((fixtures._TESTS / "fixtures" / "demo.json").read_text(encoding="utf-8"))

    bundle = fixtures.SyntheticEventClusterTests.bundle

    def scenario(self):
        bundles = [
            self.bundle("a"), self.bundle("b"), self.bundle("c"),
            self.bundle("d", body="synthetic-alternative-marker", relation="contradicts"),
            self.bundle("e", body="synthetic-separate-marker", title="qa-separate-title-marker"),
            self.bundle("unlabeled"),
        ]
        labels = [
            self.label("b", "c", False),
            self.label("e", "a", True),
            self.label("b", "a", True),
            self.label("e", "d", False),
            self.label("c", "a", False),
            self.label("d", "a", True),
        ]
        return bundles, labels

    @staticmethod
    def label(left, right, same_event):
        return {"event_version_ids": [f"ev_{left}", f"ev_{right}"], "same_event": same_event}

    def evaluate(self, bundles, labels, cutoff=fixtures._CUTOFF):
        return evaluate_synthetic_event_clusters(bundles, labels, cutoff=cutoff)

    def test_exact_candidates_are_scored_on_labeled_pairs_only(self):
        bundles, labels = self.scenario()
        original = deepcopy((bundles, labels))
        expected = {
            "schema_version": "synthetic-event-cluster-evaluation/0.1",
            "is_synthetic": True,
            "counts": {"labeled_pairs": 6, "true_positive": 1, "false_positive": 2,
                       "false_negative": 2, "true_negative": 1},
            "false_positive_pairs": [["ev_a", "ev_c"], ["ev_b", "ev_c"]],
            "false_negative_pairs": [["ev_a", "ev_d"], ["ev_a", "ev_e"]],
        }
        self.assertEqual(self.evaluate(bundles, labels), expected)
        reversed_labels = [{**item, "event_version_ids": list(reversed(item["event_version_ids"]))}
                           for item in reversed(labels)]
        self.assertEqual(self.evaluate(list(reversed(bundles)), reversed_labels), expected)
        self.assertEqual((bundles, labels), original)

    def test_no_labels_does_not_infer_negative_or_positive_pairs(self):
        bundles, _ = self.scenario()
        result = self.evaluate(bundles, [])
        self.assertEqual(result["counts"], dict.fromkeys(
            ("labeled_pairs", "true_positive", "false_positive", "false_negative", "true_negative"), 0))
        self.assertEqual(result["false_positive_pairs"], [])
        self.assertEqual(result["false_negative_pairs"], [])
        self.assertEqual(self.evaluate([], []), result)

    def test_bad_pair_shape_repeated_identity_and_hidden_member_rejected(self):
        a, b = self.bundle("a"), self.bundle("b")
        same_event = self.bundle("revision", event_id="event_a", version=2)
        hidden = self.bundle("later")
        hidden["evidence"]["available_at"] = fixtures._AFTER_CUTOFF
        bundles = [a, b, same_event, hidden]
        valid = self.label("a", "b", True)
        bad_label_sets = (
            (valid,),
            [valid] * 1001,
            [valid, self.label("b", "a", False)],
            [self.label("a", "a", True)],
            [self.label("a", "revision", True)],
            [self.label("a", "later", True)],
            [self.label("a", "absent", False)],
            [self.label("a", "b", 1)],
            [{**valid, "unexpected": None}],
            [{**valid, "event_version_ids": ("ev_a", "ev_b")}],
            [{**valid, "event_version_ids": ["ev_a", "ev_b", "ev_later"]}],
            [{**valid, "event_version_ids": ["ev_a", {"private": "marker"}]}],
        )
        for bad in bad_label_sets:
            with self.subTest(labels_type=type(bad).__name__, count=len(bad)):
                with self.assertRaisesRegex(ValueError, "^synthetic_event_cluster_evaluation_invalid$"):
                    self.evaluate(bundles, bad)
        visible = self.evaluate(bundles, [self.label("a", "later", True)], fixtures._AFTER_CUTOFF)
        self.assertEqual(visible["counts"]["true_positive"], 1)

    def test_actual_cli_has_exact_parity_and_fixed_errors(self):
        bundles, labels = self.scenario()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa-cluster-evaluation.json"
            command = [sys.executable, "-X", "utf8", "-m", "market_intel", "evaluate-synthetic-event-clusters",
                       "--input", str(path), "--cutoff", fixtures._CUTOFF]

            def run(raw):
                path.write_bytes(raw)
                result = subprocess.run(
                    command, cwd=fixtures._ROOT, env={**os.environ, "PYTHONPATH": str(fixtures._ROOT / "src")},
                    capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
                )
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(list(path.parent.iterdir()), [path])
                return result

            valid = json.dumps({"bundles": bundles, "labels": labels}).encode("utf-8")
            result = run(valid)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(json.loads(result.stdout), self.evaluate(bundles, labels))
            for marker in ("synthetic-full-body-marker", "qa-separate-title-marker", "evidence_a", "example.com"):
                self.assertNotIn(marker, result.stdout)

            invalid = (
                (b'{"bundles":[],"labels":[],"qa-private-marker":0}', "synthetic_event_cluster_evaluation_invalid"),
                (b'{"qa-private-marker":1,"qa-private-marker":2}', "synthetic_event_cluster_input_invalid"),
                (b'{"bundles":[],"labels":[NaN]}', "synthetic_event_cluster_input_invalid"),
            )
            for raw, error in invalid:
                with self.subTest(error=error):
                    result = run(raw)
                    self.assertEqual((result.returncode, result.stdout), (1, ""))
                    self.assertIn(error, result.stderr)
                    self.assertNotIn("qa-private-marker", result.stderr)
                    self.assertNotIn(str(path), result.stderr)
