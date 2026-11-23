from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from market_intel.pipeline.process.cluster import plan_synthetic_event_clusters


_TESTS = Path(__file__).resolve().parents[1]
_ROOT = _TESTS.parent
_CUTOFF = "2026-11-06T00:06:00Z"
_AFTER_CUTOFF = "2026-11-06T00:06:00.000001Z"


class SyntheticEventClusterTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads((_TESTS / "fixtures" / "demo.json").read_text(encoding="utf-8"))

    def bundle(self, suffix, *, event_id=None, version=1, title="synthetic-title-marker",
               body="synthetic-full-body-marker", markets=("A", "US"), category="policy",
               normalization_version="text-normalize/0.1", relation="supports"):
        bundle = deepcopy(self.reference)
        digest = sha256(body.encode("utf-8")).hexdigest()
        raw_id = f"raw_{suffix}"
        version_id = f"ev_{suffix}"
        evidence_id = f"evidence_{suffix}"
        bundle["raw"].update(raw_item_id=raw_id, normalized_text=body, content_sha256=digest,
                             content_ref=f"raw/{digest}.txt", normalization_version=normalization_version)
        bundle["event"].update(event_id=event_id or f"event_{suffix}", event_version_id=version_id,
                               version=version, title=title, markets=list(markets), category=category,
                               input_raw_item_ids=[raw_id], evidence_ids=[evidence_id])
        bundle["evidence"].update(evidence_id=evidence_id, event_version_id=version_id, raw_item_id=raw_id,
                                  relation=relation, normalization_version=normalization_version, quote=body)
        bundle["evidence"]["locator"]["end"] = len(body)
        return bundle

    def plan(self, bundles, cutoff=_CUTOFF):
        return plan_synthetic_event_clusters(bundles, cutoff=cutoff)

    def assert_invalid(self, bundles, cutoff=_CUTOFF):
        with self.assertRaisesRegex(ValueError, "^synthetic_event_cluster_invalid$"):
            self.plan(bundles, cutoff)

    def test_duplicate_candidates_and_ambiguous_titles_are_deterministic(self):
        one = self.bundle("c", version=10, event_id="event_0")
        old = self.bundle("a", version=2, event_id="event_0")
        two = self.bundle("b", markets=("US", "A"), relation="contradicts")
        three = self.bundle("d", body="synthetic-alternative-marker", relation="reports")
        different_market = self.bundle("e", markets=("GLOBAL",))
        different_category = self.bundle("f", category="company")
        other_normalizer = self.bundle("g", title="unrelated-title-marker",
                                       normalization_version="text-normalize/0.2")
        bundles = [two, one, other_normalizer, different_market, three, different_category, old]
        original = deepcopy(bundles)

        report = self.plan(bundles)
        self.assertEqual(report["schema_version"], "synthetic-event-cluster-plan/0.1")
        self.assertIs(report["is_synthetic"], True)
        self.assertEqual(report["excluded_after_cutoff"], 0)
        self.assertEqual(report["exact_duplicate_groups"], [["ev_a", "ev_b", "ev_c"]])
        self.assertEqual(report["ambiguous_title_groups"], [["ev_a", "ev_b", "ev_c", "ev_d"]])
        self.assertEqual(report["members"], [
            {"event_id": event_id, "event_version_id": f"ev_{suffix}", "version": version,
             "raw_item_id": f"raw_{suffix}", "evidence_id": f"evidence_{suffix}", "relation": relation}
            for event_id, suffix, version, relation in [
                ("event_0", "a", 2, "supports"), ("event_0", "c", 10, "supports"),
                ("event_b", "b", 1, "contradicts"), ("event_d", "d", 1, "reports"),
                ("event_e", "e", 1, "supports"), ("event_f", "f", 1, "supports"),
                ("event_g", "g", 1, "supports"),
            ]
        ])
        self.assertEqual(self.plan(list(reversed(bundles))), report)
        self.assertEqual(bundles, original)
        output = json.dumps(report)
        for marker in ("synthetic-title-marker", "synthetic-full-body-marker", "synthetic-alternative-marker",
                       "unrelated-title-marker", "example.com"):
            self.assertNotIn(marker, output)

    def test_latest_bundle_timestamp_controls_cutoff_with_no_future_leakage(self):
        old = self.bundle("old", event_id="event_same", version=1)
        future_event = self.bundle("event_future", event_id="event_same", version=2)
        future_event["event"].update(processed_at=_AFTER_CUTOFF, available_at=_AFTER_CUTOFF)
        future_evidence = self.bundle("evidence_future", relation="contradicts")
        future_evidence["evidence"]["available_at"] = _AFTER_CUTOFF
        future_raw = self.bundle("raw_future")
        future_raw["raw"].update(persisted_at=_AFTER_CUTOFF, available_at=_AFTER_CUTOFF)
        future_raw["event"].update(processed_at=_AFTER_CUTOFF, available_at=_AFTER_CUTOFF)
        future_raw["evidence"]["available_at"] = _AFTER_CUTOFF
        bundles = [future_raw, future_evidence, old, future_event]

        report = self.plan(bundles)
        self.assertEqual(report["members"], self.plan([old])["members"])
        self.assertEqual(report["excluded_after_cutoff"], 3)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertEqual(report["ambiguous_title_groups"], [])
        future = self.plan(bundles, _AFTER_CUTOFF)
        self.assertEqual(len(future["members"]), 4)
        self.assertEqual(future["excluded_after_cutoff"], 0)
        self.assertEqual(self.plan(bundles, "2026-11-06T00:05:59.999999Z")["members"], [])

    def test_scope_and_id_collisions_fail_closed(self):
        one = self.bundle("a")
        repeated_version = self.bundle("b")
        repeated_version["event"]["event_version_id"] = repeated_version["evidence"]["event_version_id"] = "ev_a"
        repeated_revision = self.bundle("b", event_id="event_a")
        repeated_evidence = self.bundle("b")
        repeated_evidence["event"]["evidence_ids"] = ["evidence_a"]
        repeated_evidence["evidence"]["evidence_id"] = "evidence_a"
        repeated_raw = self.bundle("b")
        repeated_raw["raw"]["raw_item_id"] = repeated_raw["evidence"]["raw_item_id"] = "raw_a"
        repeated_raw["event"]["input_raw_item_ids"] = ["raw_a"]
        self.assertEqual(len(self.plan([one, repeated_raw])["members"]), 2)
        raw_collision = deepcopy(repeated_raw)
        raw_collision["raw"]["title"] = "different identity payload"
        other_policy = self.bundle("b")
        other_policy["raw"]["storage_policy"] = "full_text"
        real = deepcopy(other_policy)
        for item in real.values():
            item["is_synthetic"] = False
        real["event"].update(extraction_method="manual", extraction_quality="structurally_valid")
        broken_future = self.bundle("b")
        broken_future["evidence"].update(quote="broken-future-quote", available_at=_AFTER_CUTOFF)
        for invalid in (repeated_version, repeated_revision, repeated_evidence, raw_collision, other_policy,
                        real, broken_future):
            with self.subTest(event=invalid["event"]["event_id"]):
                self.assert_invalid([one, invalid])
        self.assert_invalid([], "2026-11-06T00:06:00+00:00")
        self.assert_invalid([None] * 1001)

    def test_versions_of_the_same_event_do_not_form_groups_by_themselves(self):
        one = self.bundle("a", event_id="event_same", version=1)
        two = self.bundle("b", event_id="event_same", version=2)
        three = self.bundle("c", event_id="event_same", version=3, body="updated text")
        report = self.plan([three, one, two])
        self.assertEqual(len(report["members"]), 3)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertEqual(report["ambiguous_title_groups"], [])

    def test_actual_cli_reports_without_mutating_inputs_and_rejects_bad_json(self):
        def run(command_args):
            return subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "market_intel", "plan-synthetic-event-clusters",
                 *command_args], cwd=_ROOT, env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
                capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
            )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "qa-cluster-input.json"
            args = ["--input", str(source), "--cutoff", _CUTOFF]
            bundles = [self.bundle("a"), self.bundle("b", relation="contradicts")]
            raw = json.dumps(bundles).encode("utf-8")
            source.write_bytes(raw)
            result = run(args)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(json.loads(result.stdout), self.plan(bundles))
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(list(source.parent.iterdir()), [source])

            for invalid in (b'[{"qa-private-marker": 1, "qa-private-marker": 2}]', b"[NaN]",
                            b"[]" + b" " * (2**20 - 1)):
                with self.subTest(length=len(invalid)):
                    source.write_bytes(invalid)
                    result = run(args)
                    self.assertEqual((result.returncode, result.stdout), (1, ""))
                    self.assertNotIn("qa-private-marker", result.stderr)
                    self.assertNotIn(str(source), result.stderr)
                    self.assertEqual(source.read_bytes(), invalid)
