from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from market_intel.pipeline.process.cluster import adjudicate_synthetic_event_clusters

from clustering import test_batch42_synthetic_cluster as fixtures


class TitleAdjudicationTests(unittest.TestCase):
    bundle = fixtures.SyntheticEventClusterTests.bundle

    def setUp(self):
        self.reference = json.loads((fixtures._TESTS / "fixtures" / "demo.json").read_text(encoding="utf-8"))

    @staticmethod
    def decision(left, right, outcome):
        return {"event_version_ids": [f"ev_{left}", f"ev_{right}"], "decision": outcome}

    def scenario(self):
        return [
            self.bundle("a"),
            self.bundle("b", body="合成反向证据：🧪", relation="contradicts"),
            self.bundle("c", relation="reports"),
            self.bundle("d", body="qa-different-title-body-marker", title="qa-different-title-marker"),
        ], [
            self.decision("c", "b", "needs_more_evidence"),
            self.decision("b", "a", "same_event"),
        ]

    def adjudicate(self, bundles, decisions, cutoff=fixtures._CUTOFF):
        return adjudicate_synthetic_event_clusters(bundles, decisions, cutoff=cutoff)

    @staticmethod
    def member(bundle):
        raw, event, evidence = (bundle[key] for key in ("raw", "event", "evidence"))
        serialized = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return {
            "event_id": event["event_id"],
            "event_version_id": event["event_version_id"],
            "version": event["version"],
            "raw_item_id": raw["raw_item_id"],
            "evidence_id": evidence["evidence_id"],
            "relation": evidence["relation"],
            "bundle_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
        }

    def test_decisions_are_sorted_and_retain_exact_members_and_conflicts(self):
        bundles, decisions = self.scenario()
        fourth = bundles[3]
        fourth["event"]["title"] = bundles[0]["event"]["title"]
        decisions.insert(0, self.decision("d", "a", "different_event"))
        cutoff = "2026-11-06T00:06:00.000000Z"
        original = deepcopy((bundles, decisions))
        a, b, c, d = map(self.member, bundles)
        expected = {
            "schema_version": "synthetic-event-cluster-adjudication/0.1",
            "is_synthetic": True,
            "cutoff": cutoff,
            "counts": {"decisions": 3, "same_event": 1, "different_event": 1, "needs_more_evidence": 1},
            "adjudications": [
                {"decision": "same_event", "members": [a, b]},
                {"decision": "different_event", "members": [a, d]},
                {"decision": "needs_more_evidence", "members": [b, c]},
            ],
        }
        self.assertEqual(self.adjudicate(bundles, decisions, cutoff), expected)
        reversed_decisions = [{**decision, "event_version_ids": decision["event_version_ids"][::-1]}
                              for decision in reversed(decisions)]
        self.assertEqual(self.adjudicate(bundles[::-1], reversed_decisions, cutoff), expected)
        self.assertEqual((bundles, decisions), original)
        self.assertEqual(b["relation"], "contradicts")
        self.assertEqual(c["relation"], "reports")

    def test_bad_pairs_and_outcomes_fail_closed(self):
        bundles, decisions = self.scenario()
        bundles.append(self.bundle("revision", event_id="event_a", version=2, body="qa-revision-body-marker"))
        valid = decisions[1]
        tests = {
            "duplicate": [valid, self.decision("a", "b", "different_event")],
            "exact_overlap": [self.decision("c", "a", "same_event")],
            "outside_group": [self.decision("d", "a", "same_event")],
            "missing": [self.decision("absent", "a", "same_event")],
            "same_version": [self.decision("a", "a", "same_event")],
            "same_logical_event": [self.decision("a", "revision", "needs_more_evidence")],
            "type": [{**valid, "decision": True}],
            "unknown_outcome": [{**valid, "decision": "qa-private-outcome-marker"}],
            "extra_key": [{**valid, "notes": "qa-private-notes-marker"}],
            "too_many": [valid] * 1001,
        }
        for case, invalid in tests.items():
            with self.subTest(case=case), self.assertRaisesRegex(ValueError,
                                                                 "^synthetic_event_cluster_adjudication_invalid$"):
                self.adjudicate(bundles, invalid)

    def test_cutoff_tracks_latest_member_evidence_and_empty_input(self):
        bundles, decisions = self.scenario()
        bundles[1]["evidence"]["available_at"] = fixtures._AFTER_CUTOFF
        with self.assertRaisesRegex(ValueError, "^synthetic_event_cluster_adjudication_invalid$"):
            self.adjudicate(bundles, decisions)
        later = self.adjudicate(bundles, decisions, fixtures._AFTER_CUTOFF)
        self.assertEqual(later["counts"]["decisions"], 2)
        self.assertEqual(later["counts"]["needs_more_evidence"], 1)
        empty = self.adjudicate([], [])
        self.assertEqual(empty["adjudications"], [])
        self.assertEqual(empty["counts"], dict.fromkeys(
            ("decisions", "same_event", "different_event", "needs_more_evidence"), 0))
        self.assertEqual(self.adjudicate(bundles, []), empty)

    def test_actual_cli_is_read_only_and_retains_fixed_errors(self):
        bundles, decisions = self.scenario()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / "qa-title-adjudication.json"
            command = [
                sys.executable, "-X", "utf8", "-m", "market_intel", "adjudicate-synthetic-event-clusters",
                "--input", str(path), "--cutoff", fixtures._CUTOFF,
            ]

            def run(raw):
                path.write_bytes(raw)
                result = subprocess.run(
                    command, cwd=workspace,
                    env={**os.environ, "PYTHONPATH": str(fixtures._ROOT / "src")},
                    capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
                )
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(list(workspace.iterdir()), [path])
                return result

            valid = json.dumps({"bundles": bundles, "decisions": decisions}, ensure_ascii=False).encode("utf-8")
            result = run(valid)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(json.loads(result.stdout), self.adjudicate(bundles, decisions))
            for marker in ("synthetic-full-body-marker", "合成反向证据", "synthetic-title-marker", "example.com"):
                self.assertNotIn(marker, result.stdout)

            invalid = (
                (b'{"bundles":[],"decisions":[],"qa-private-marker":0}', "synthetic_event_cluster_adjudication_invalid"),
                (b'{"qa-private-marker":1,"qa-private-marker":2}', "synthetic_event_cluster_input_invalid"),
            )
            for raw, error in invalid:
                with self.subTest(error=error):
                    result = run(raw)
                    self.assertEqual((result.returncode, result.stdout), (1, ""))
                    self.assertIn(error, result.stderr)
                    self.assertNotIn("qa-private-marker", result.stderr)
                    self.assertNotIn(str(path), result.stderr)
