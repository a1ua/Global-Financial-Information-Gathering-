from copy import deepcopy
import unittest

from market_intel.contracts.candidate_snapshot import payload_sha256
from market_intel.contracts.evaluation_window import plan_synthetic_evaluation_window
from test_prediction_input import prediction_fixture, refresh_hashes


def _with_sessions():
    value = prediction_fixture()
    value["inputs"]["calendar"]["sessions"] = [
        {"opens_at": f"2026-11-{day}T01:30:00Z", "closes_at": f"2026-11-{day}T07:00:00Z"}
        for day in (10, 11, 12)
    ]
    value["inputs"]["protocol"]["horizon_sessions"] = 2
    refresh_hashes(value)
    return value


def _receipt(value, committed):
    return {
        "schema_version": "prediction-receipt/0.1",
        "prediction_id": value["content"]["prediction_id"],
        "content_sha256": payload_sha256(value["content"]),
        "committed_at": committed,
    }


class SyntheticEvaluationWindowTests(unittest.TestCase):
    def test_committed_time_uses_strict_open_boundary(self):
        value = _with_sessions()
        at_open = "2026-11-10T01:30:00.000000Z"
        sessions = value["inputs"]["calendar"]["sessions"]
        result = plan_synthetic_evaluation_window(value, _receipt(value, at_open))
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["committed_at"], at_open)
        self.assertEqual(result["sessions"], sessions[1:])
        just_before = plan_synthetic_evaluation_window(
            value, _receipt(value, "2026-11-10T01:29:59.999999Z"))
        self.assertEqual(just_before["sessions"], sessions[:2])

    def test_insufficient_and_exhausted_calendar_return_pending_prefix(self):
        value = _with_sessions()
        sessions = value["inputs"]["calendar"]["sessions"]
        for committed, expected in (("2026-11-11T02:00:00Z", sessions[2:]),
                                    ("2026-11-12T07:00:00Z", [])):
            with self.subTest(committed=committed):
                result = plan_synthetic_evaluation_window(value, _receipt(value, committed))
                self.assertEqual(result["status"], "pending")
                self.assertEqual(result["sessions"], expected)
                self.assertEqual(result["horizon_sessions"], 2)

    def test_result_is_repeatable_and_detached_from_calendar(self):
        value = _with_sessions()
        original = deepcopy(value)
        receipt = _receipt(value, "2026-11-10T01:30:00Z")
        first = plan_synthetic_evaluation_window(value, receipt)
        second = plan_synthetic_evaluation_window(value, receipt)
        self.assertEqual(first, second)
        self.assertEqual(first["calendar_snapshot_sha256"],
                         value["content"]["calendar_snapshot_sha256"])
        self.assertEqual(first["evaluation_protocol_sha256"],
                         value["content"]["evaluation_protocol_sha256"])
        first["sessions"][0]["opens_at"] = "changed"
        self.assertEqual(value, original)
        self.assertEqual(plan_synthetic_evaluation_window(value, receipt), second)

    def test_receipt_from_parent_or_old_content_cannot_be_reused(self):
        parent = _with_sessions()
        receipt = _receipt(parent, "2026-11-10T01:30:00Z")
        child = deepcopy(parent)
        child["content"]["prediction_id"] = "prediction_child"
        child["content"]["supersedes_prediction_id"] = parent["content"]["prediction_id"]
        variants = (receipt, {**receipt, "prediction_id": "prediction_child"})
        for variant in variants:
            with self.subTest(receipt=variant), self.assertRaisesRegex(
                    ValueError, "^synthetic_evaluation_window_invalid$"):
                plan_synthetic_evaluation_window(child, variant)
        child_receipt = _receipt(child, "2026-11-10T01:30:00Z")
        self.assertEqual(plan_synthetic_evaluation_window(child, child_receipt)["status"], "planned")

    def test_invalid_receipt_and_malformed_prediction_have_fixed_error(self):
        value = _with_sessions()
        receipt = _receipt(value, "2026-11-10T01:30:00Z")
        for invalid in (None, {**receipt, "extra": "private"}, {**receipt, "schema_version": "unknown"},
                        {**receipt, "committed_at": "2026-11-10T01:30:00+00:00"},
                        {**receipt, "committed_at": "2026-01-01T00:00:00Z"}):
            with self.subTest(receipt=invalid), self.assertRaisesRegex(
                    ValueError, "^synthetic_evaluation_window_invalid$"):
                plan_synthetic_evaluation_window(value, invalid)
        with self.assertRaisesRegex(ValueError, "^synthetic_evaluation_window_invalid$"):
            plan_synthetic_evaluation_window({"content": {"is_synthetic": False}}, receipt)
