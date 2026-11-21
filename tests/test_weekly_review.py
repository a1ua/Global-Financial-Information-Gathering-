from copy import deepcopy
import unittest

from market_intel.contracts.abnormal_return import calculate_synthetic_abnormal_return
from market_intel.contracts.market_snapshot import freeze_market_snapshot
from market_intel.contracts.weekly_review import summarize_synthetic_week
from test_abnormal_return import AS_OF, _version
from test_evaluation_window import _receipt, _with_sessions
from test_market_snapshot import calendar
from test_prediction_input import refresh_hashes


_WEEK = "2026-11-09"
_INVALID = "^synthetic_weekly_review_invalid$"


def _evaluation(prediction_id, *, target_close="110", alternate=False, pending=False, missing=False):
    value = _with_sessions()
    content = value["content"]
    content["prediction_id"] = prediction_id
    if alternate:
        value["inputs"]["protocol"]["protocol_id"] = "second_protocol"
        content["evaluation_protocol_id"] = "second_protocol"
        refresh_hashes(value)
    receipt = _receipt(value, "2026-11-09T12:00:00Z")
    source = calendar()
    if pending:
        return calculate_synthetic_abnormal_return(
            value, receipt, source, None, None, as_of="2026-11-11T06:59:59Z")

    def leg(field, first_close):
        instrument = content[field]
        rows = [] if missing and field == "benchmark_instrument_id" else [
            _version(instrument, "2026-11-10", "100", first_close),
            _version(instrument, "2026-11-11", "100", first_close),
        ]
        snapshot = freeze_market_snapshot(source, instrument, rows, cutoff=AS_OF,
                                          start_date="2026-11-10", end_date="2026-11-11")
        return {"snapshot": snapshot, "bars": rows}

    return calculate_synthetic_abnormal_return(
        value, receipt, source, leg("target_instrument_id", target_close),
        leg("benchmark_instrument_id", "100"), as_of=AS_OF)


class SyntheticWeeklyReviewTests(unittest.TestCase):
    def test_status_counts_and_protocols_remain_separate(self):
        calculated = _evaluation("calculated")
        pending = _evaluation("pending", alternate=True, pending=True)
        unavailable = _evaluation("unavailable", missing=True)
        original = [pending, unavailable, calculated]
        report = summarize_synthetic_week(original, week_monday=_WEEK)
        self.assertEqual(report, summarize_synthetic_week(original[::-1], week_monday=_WEEK))
        self.assertEqual(report["counts"], {"total": 3, "calculated": 1, "pending": 1, "unavailable": 1})
        groups = {row["evaluation_protocol_sha256"]: row for row in report["protocols"]}
        self.assertEqual(groups[calculated["evaluation_protocol_sha256"]]["mean_car"], "0.10000000")
        self.assertEqual(groups[calculated["evaluation_protocol_sha256"]]["counts"]["total"], 2)
        self.assertIsNone(groups[pending["evaluation_protocol_sha256"]]["mean_car"])
        self.assertNotIn("mean_car", report)

    def test_published_car_mean_uses_exact_half_even(self):
        zero = _evaluation("zero", target_close="100")
        one = _evaluation("one", target_close="100.000001")
        two = _evaluation("two", target_close="100.000002")
        self.assertEqual((zero["car"], one["car"], two["car"]),
                         ("0.00000000", "0.00000001", "0.00000002"))
        for results, expected in (([zero, one], "0.00000000"), ([one, two], "0.00000002")):
            with self.subTest(expected=expected):
                report = summarize_synthetic_week(results, week_monday=_WEEK)
                self.assertEqual(report["protocols"][0]["mean_car"], expected)

    def test_shanghai_week_uses_receipt_even_when_as_of_is_later(self):
        result = _evaluation("boundary", pending=True)
        result["as_of"] = "2026-11-22T16:00:00Z"
        for received in ("2026-11-08T16:00:00Z", "2026-11-15T15:59:59.999999Z"):
            with self.subTest(received=received):
                result["committed_at"] = received
                self.assertEqual(summarize_synthetic_week([result], week_monday=_WEEK)["counts"]["pending"], 1)
        for received in ("2026-11-08T15:59:59.999999Z", "2026-11-15T16:00:00Z"):
            with self.subTest(received=received), self.assertRaisesRegex(ValueError, _INVALID):
                result["committed_at"] = received
                summarize_synthetic_week([result], week_monday=_WEEK)
        with self.assertRaisesRegex(ValueError, _INVALID):
            summarize_synthetic_week([], week_monday="2026-11-10")
        self.assertEqual(summarize_synthetic_week([], week_monday=_WEEK)["protocols"], [])

    def test_duplicate_prediction_rejected_even_across_protocols(self):
        results = [_evaluation("same"), _evaluation("same", alternate=True, pending=True)]
        with self.assertRaisesRegex(ValueError, _INVALID):
            summarize_synthetic_week(results, week_monday=_WEEK)

    def test_rejects_inconsistent_or_unbounded_input(self):
        calculated = _evaluation("calculated")
        pending = _evaluation("pending", pending=True)
        unavailable = _evaluation("unavailable", missing=True)
        for original, field, bad in (
                (calculated, "car", "-0.00000000"),
                (calculated, "car", "00.10000000"),
                (calculated, "segments", calculated["segments"][::-1]),
                (calculated, "as_of", "2026-11-08T00:00:00Z"),
                (pending, "target_snapshot_sha256", "a" * 64),
                (pending, "reason", "missing_prices"),
                (unavailable, "missing_benchmark_sessions", []),
                (unavailable, "missing_benchmark_sessions", ["2026-11-10"] * 2),
                (unavailable, "is_synthetic", 1)):
            with self.subTest(field=field, bad=bad), self.assertRaisesRegex(ValueError, _INVALID):
                result = deepcopy(original)
                result[field] = bad
                summarize_synthetic_week([result], week_monday=_WEEK)
        with self.assertRaisesRegex(ValueError, _INVALID):
            summarize_synthetic_week([pending] * 1001, week_monday=_WEEK)
