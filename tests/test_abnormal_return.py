from copy import deepcopy
import unittest

from market_intel.contracts.abnormal_return import calculate_synthetic_abnormal_return
from market_intel.contracts.market_snapshot import freeze_market_snapshot
from test_evaluation_window import _receipt, _with_sessions
from test_market_snapshot import calendar
from test_prediction_input import refresh_hashes


AS_OF = "2026-11-11T07:00:00Z"
INVALID = "^synthetic_abnormal_return_invalid$"


def _version(instrument, day, open_price, close, available=None):
    return {
        "instrument_id": instrument,
        "is_synthetic": True,
        "available_at": available or f"{day}T07:00:00Z",
        "bar": {"session_date": day, "open": open_price, "high": "200",
                "low": "1", "close": close},
    }


class SyntheticAbnormalReturnTests(unittest.TestCase):
    def setUp(self):
        self.value = _with_sessions()
        self.receipt = _receipt(self.value, "2026-11-09T12:00:00Z")
        self.calendar = calendar()
        self.target_id = self.value["content"]["target_instrument_id"]
        self.benchmark_id = self.value["content"]["benchmark_instrument_id"]

    def leg(self, instrument, rows, *, cutoff="2026-11-11T07:00:00.0Z",
            start="2026-11-10", end="2026-11-11"):
        snapshot = freeze_market_snapshot(self.calendar, instrument, rows, cutoff=cutoff,
                                          start_date=start, end_date=end)
        return {"snapshot": snapshot, "bars": rows}

    def fix_prices(self):
        target = self.leg(self.target_id, [
            _version(self.target_id, "2026-11-10", "100", "110"),
            _version(self.target_id, "2026-11-11", "130", "121"),
        ])
        benchmark = self.leg(self.benchmark_id, [
            _version(self.benchmark_id, "2026-11-10", "100", "105"),
            _version(self.benchmark_id, "2026-11-11", "120", "105"),
        ])
        return target, benchmark

    def calculate(self, target=None, benchmark=None, as_of=AS_OF):
        return calculate_synthetic_abnormal_return(
            self.value, self.receipt, self.calendar, target, benchmark, as_of=as_of)

    def test_exact_maturity_short_window_and_earlier_as_of(self):
        pending = self.calculate(as_of="2026-11-11T06:59:59.999999Z")
        self.assertEqual((pending["status"], pending["reason"]), ("pending", "window_not_closed"))
        self.assertEqual((pending["target_snapshot_sha256"], pending["segments"], pending["car"]),
                         (None, [], None))
        self.assertEqual(self.calculate(*self.fix_prices())["status"], "calculated")
        self.receipt = _receipt(self.value, "2026-11-11T01:30:00Z")
        self.assertEqual(self.calculate()["reason"], "window_incomplete")
        with self.assertRaisesRegex(ValueError, INVALID):
            self.calculate(as_of="2026-11-11T01:29:59.999999Z")

    def test_first_open_then_previous_close_and_pinned_replay(self):
        target, benchmark = self.fix_prices()
        result = self.calculate(target, benchmark)
        self.assertEqual(result["target_snapshot_sha256"], target["snapshot"]["snapshot_sha256"])
        self.assertEqual(result["benchmark_snapshot_sha256"], benchmark["snapshot"]["snapshot_sha256"])
        self.assertEqual(result["segments"], [
            {"session_date": "2026-11-10", "target_return": "0.10000000",
             "benchmark_return": "0.05000000", "abnormal_return": "0.05000000"},
            {"session_date": "2026-11-11", "target_return": "0.10000000",
             "benchmark_return": "0.00000000", "abnormal_return": "0.10000000"},
        ])
        self.assertEqual(result["car"], "0.15000000")
        revision = _version(self.target_id, "2026-11-10", "100", "130", "2026-11-10T08:00:00Z")
        target["bars"].insert(0, revision)
        self.assertEqual(self.calculate(target, benchmark), result)
        del target["bars"][1]
        with self.assertRaisesRegex(ValueError, INVALID):
            self.calculate(target, benchmark)

    def test_missing_is_unavailable_and_lists_each_leg(self):
        target = self.leg(self.target_id, [_version(self.target_id, "2026-11-10", "100", "110")])
        benchmark = self.leg(self.benchmark_id, [
            _version(self.benchmark_id, "2026-11-11", "120", "105"),
        ])
        result = self.calculate(target, benchmark)
        self.assertEqual((result["status"], result["reason"]), ("unavailable", "missing_prices"))
        self.assertEqual(result["missing_target_sessions"], ["2026-11-11"])
        self.assertEqual(result["missing_benchmark_sessions"], ["2026-11-10"])
        self.assertEqual((result["segments"], result["car"]), ([], None))
        self.assertEqual(result["target_snapshot_sha256"], target["snapshot"]["snapshot_sha256"])

    def test_round_half_even_and_sum_unrounded_segments(self):
        target = self.leg(self.target_id, [
            _version(self.target_id, "2026-11-10", "2", "2.00000001"),
            _version(self.target_id, "2026-11-11", "2", "2.00000002"),
        ])
        benchmark = self.leg(self.benchmark_id, [
            _version(self.benchmark_id, "2026-11-10", "2", "2"),
            _version(self.benchmark_id, "2026-11-11", "2", "2"),
        ])
        result = self.calculate(target, benchmark)
        self.assertEqual([row["abnormal_return"] for row in result["segments"]], ["0.00000000"] * 2)
        self.assertEqual(result["car"], "0.00000001")

    def test_reject_wrong_instrument_cutoff_cohort_and_preclose_observation(self):
        target, benchmark = self.fix_prices()
        preclose = deepcopy(target["bars"])
        preclose[1]["available_at"] = "2026-11-11T06:59:59.999999Z"
        for invalid in (
            benchmark,
            self.leg(self.target_id, target["bars"], cutoff="2026-11-11T07:00:00.000001Z"),
            self.leg(self.target_id, target["bars"], start="2026-11-09"),
            self.leg(self.target_id, preclose),
            {**target, "extra": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, INVALID):
                self.calculate(invalid, benchmark)

    def test_reject_window_skipping_a_planned_day_in_the_middle(self):
        self.value["inputs"]["calendar"]["sessions"].pop(1)
        refresh_hashes(self.value)
        self.receipt = _receipt(self.value, "2026-11-09T12:00:00Z")
        as_of = "2026-11-12T07:00:00Z"
        legs = [
            self.leg(instrument, [_version(instrument, "2026-11-10", "100", "110"),
                                  _version(instrument, "2026-11-12", "100", "110")],
                     cutoff=as_of, end="2026-11-12")
            for instrument in (self.target_id, self.benchmark_id)
        ]
        with self.assertRaisesRegex(ValueError, INVALID):
            self.calculate(*legs, as_of=as_of)
