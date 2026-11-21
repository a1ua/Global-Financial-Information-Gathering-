import copy
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.contracts import prediction_input as contract
from market_intel.contracts.candidate_snapshot import describe_candidate_bundle, payload_sha256
from market_intel.contracts.prediction_input import validate_prediction_input
from market_intel.offline import ingest_fixture
from market_intel.pipeline import prediction_input as pipeline
from market_intel.store import connect
from test_evidence_candidates import CUTOFF, fixture


def refresh_hashes(value):
    """Rebuild the outer hashes without refreshing the separately bound model output."""
    content, inputs = value["content"], value["inputs"]
    content["input_manifest_sha256"] = payload_sha256(inputs)
    content["model_call_manifest_sha256"] = payload_sha256(inputs["model_call"])
    content["evaluation_protocol_sha256"] = payload_sha256(inputs["protocol"])
    content["calendar_snapshot_sha256"] = payload_sha256(inputs["calendar"])


def prediction_fixture(*bundles):
    bundles = bundles or (fixture(),)
    candidates = [describe_candidate_bundle(bundle, None) for bundle in bundles]
    candidates.sort(key=lambda item: (item["effective_available_at"], item["event_id"], item["event_version_id"]))
    snapshot_manifest = {"schema_version": "evidence-candidate-input/0.1",
                         "selection_version": "latest-available/0.1", "cutoff": CUTOFF,
                         "max_candidates": 5, "include_synthetic": True, "candidates": candidates}
    snapshot = {"schema_version": "evidence-candidate-snapshot/0.1", "input_manifest": snapshot_manifest,
                "input_manifest_sha256": payload_sha256(snapshot_manifest)}
    output = {"direction": "positive", "direction_basis": "benchmark_relative",
              "judgment_confidence": "low", "reasoning": "合成判断", "counter_evidence": [],
              "abstention_reason": None}
    content = {
        "schema_version": "prediction-content/0.1", "prediction_id": "prediction_1",
        "prediction_family_id": "family_1", "is_synthetic": True,
        "event_version_ids": sorted(row["event_version_id"] for row in candidates),
        "evidence_ids": sorted(row["evidence_id"] for row in candidates), "cluster_version_id": None,
        "model_call_id": "call_fixture", "model_ledger_id": "ledger_fixture", "created_at": CUTOFF,
        "target_instrument_id": "target_fixture", "benchmark_instrument_id": "benchmark_fixture",
        "evaluation_protocol_id": "protocol_fixture", "calendar_snapshot_id": "calendar_fixture",
        "rules_version": "rules.1", "supersedes_prediction_id": None, **output,
    }
    common = {"is_synthetic": True, "available_at": CUTOFF}
    inputs = {
        "schema_version": "prediction-input-manifest/0.1", "rules_version": "rules.1",
        "evidence_snapshot": snapshot,
        "model_call": {"schema_version": "prediction-fixture-call/0.1", **common,
                       "ledger_id": "ledger_fixture", "call_id": "call_fixture",
                       "evidence_manifest_sha256": snapshot["input_manifest_sha256"],
                       "output_sha256": payload_sha256(output)},
        "protocol": {"schema_version": "prediction-fixture-protocol/0.1", **common,
                     "protocol_id": "protocol_fixture", "target_instrument_id": "target_fixture",
                     "benchmark_instrument_id": "benchmark_fixture", "direction_basis": "benchmark_relative",
                     "calendar_snapshot_id": "calendar_fixture", "horizon_sessions": 1},
        "calendar": {"schema_version": "prediction-fixture-calendar/0.1", **common,
                     "calendar_snapshot_id": "calendar_fixture", "sessions": [
                         {"opens_at": "2026-11-10T01:30:00Z", "closes_at": "2026-11-10T07:00:00Z"}]},
    }
    value = {"content": content, "inputs": inputs}
    refresh_hashes(value)
    return value


class PredictionInputTests(unittest.TestCase):
    def test_valid_manifest_does_not_mutate_input(self):
        value = prediction_fixture(fixture("b"), fixture("a"))
        original = copy.deepcopy(value)
        self.assertIsNone(validate_prediction_input(value))
        self.assertEqual(original, value)

    def test_rehash_cannot_hide_reference_or_output_disagreement(self):
        cases = (
            ("content", "event_version_ids", ["event_unrelated"]),
            ("content", "counter_evidence", ["evidence_unrelated"]),
            ("content", "reasoning", "private changed output"),
            ("protocol", "target_instrument_id", "other"),
            ("model_call", "call_id", "other"),
            ("model_call", "evidence_manifest_sha256", "a" * 64),
        )
        for section, field, replacement in cases:
            with self.subTest(section=section, field=field):
                value = prediction_fixture()
                target = value["content"] if section == "content" else value["inputs"][section]
                target[field] = replacement
                refresh_hashes(value)
                with self.assertRaisesRegex(ValueError, "^prediction_input_invalid$"):
                    validate_prediction_input(value)

    def test_refuses_caller_receipt_and_real_fixture_flag(self):
        for section, field, replacement in (
            ("content", "committed_at", CUTOFF),
            ("content", "is_synthetic", 1),
            ("model_call", "is_synthetic", False),
            ("content", "cluster_version_id", "opaque_cluster"),
        ):
            with self.subTest(section=section, field=field):
                value = prediction_fixture()
                target = value["content"] if section == "content" else value["inputs"][section]
                target[field] = replacement
                refresh_hashes(value)
                with self.assertRaisesRegex(ValueError, "^prediction_input_invalid$"):
                    validate_prediction_input(value)

    def test_rejects_future_inputs_and_inconsistent_session_sequence(self):
        future = "2026-11-10T00:00:00Z"
        prior = "2026-11-09T11:59:59Z"
        cases = (
            ("content", "created_at", prior),
            ("calendar", "available_at", future),
            ("model_call", "available_at", prior),
            ("protocol", "horizon_sessions", True),
            ("protocol", "horizon_sessions", 2),
            ("calendar", "sessions", [
                {"opens_at": "2026-11-10T01:30:00Z", "closes_at": "2026-11-10T07:00:00Z"},
                {"opens_at": "2026-11-10T06:59:59Z", "closes_at": "2026-11-10T08:00:00Z"}]),
        )
        for section, field, replacement in cases:
            with self.subTest(section=section, field=field):
                value = prediction_fixture()
                target = value["content"] if section == "content" else value["inputs"][section]
                target[field] = replacement
                refresh_hashes(value)
                with self.assertRaisesRegex(ValueError, "^prediction_input_invalid$"):
                    validate_prediction_input(value)

    def test_rejects_bad_json_before_examining_business_fields(self):
        cyclic = []
        cyclic.append(cyclic)
        rejected = (cyclic, [None] * 32768, 2**63, 1.0, "\ud800", "汉" * 22000,
                    ["a" * 65536] * 17, ["\x00" * 60000] * 4, {17: None})
        for item in rejected:
            with self.subTest(kind=type(item).__name__), patch.object(contract, "_validate") as check:
                with self.assertRaisesRegex(ValueError, "^prediction_input_invalid$"):
                    validate_prediction_input({"unexpected": item})
                check.assert_not_called()

    def test_exact_snapshot_load_preserves_old_ids_and_database(self):
        original = fixture("a")
        value = prediction_fixture(original)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with closing(connect(root / "market.db")) as db:
                ingest_fixture(db, original, root)
                ingest_fixture(db, fixture("a", version=2, at="2026-11-09T01:00:00Z"), root)
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            result = pipeline.load_prediction_inputs(root, value)
            self.assertEqual(result["bundles"], [{**original, "receipt_committed_at": None}])
            self.assertTrue(result["verification"]["read_only"])
            self.assertEqual(before, {path: path.read_bytes() for path in root.rglob("*") if path.is_file()})
            (root / original["raw"]["content_ref"]).write_bytes(b"private corrupt evidence")
            with self.assertRaisesRegex(ValueError, "^prediction_inputs_unavailable$"):
                pipeline.load_prediction_inputs(root, value)

    def test_full_rehash_with_wrong_payload_hash_fails_real_snapshot_check(self):
        original = fixture()
        value = prediction_fixture(original)
        snapshot = value["inputs"]["evidence_snapshot"]
        snapshot["input_manifest"]["candidates"][0]["event_payload_sha256"] = "a" * 64
        snapshot["input_manifest_sha256"] = payload_sha256(snapshot["input_manifest"])
        value["inputs"]["model_call"]["evidence_manifest_sha256"] = snapshot["input_manifest_sha256"]
        refresh_hashes(value)
        validate_prediction_input(value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with closing(connect(root / "market.db")) as db:
                ingest_fixture(db, original, root)
            with self.assertRaisesRegex(ValueError, "^prediction_inputs_unavailable$"):
                pipeline.load_prediction_inputs(root, value)

    def test_validation_precedes_loading_and_missing_db_remains_absent(self):
        with patch.object(pipeline, "load_candidate_snapshot_inputs") as loader:
            with self.assertRaisesRegex(ValueError, "^prediction_input_invalid$"):
                pipeline.load_prediction_inputs("unopened", {})
            loader.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaisesRegex(ValueError, "^prediction_inputs_unavailable$"):
                pipeline.load_prediction_inputs(root, prediction_fixture())
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
