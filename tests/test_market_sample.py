import copy
from datetime import date, timedelta
import unittest

from market_intel.contracts.market_sample import audit_daily_ohlc


def bar(session_date, **changes):
    return {"session_date": session_date, "open": "100.10", "high": "101.50",
            "low": "99.90", "close": "100.90", **changes}


class MarketSampleTests(unittest.TestCase):
    def test_explicit_cohort_accepts_unsorted_bars_and_preserves_originals(self):
        sessions = ["2024-02-29", "2024-03-04"]
        bars = [bar("2024-03-04"), bar("2024-02-29")]
        original = copy.deepcopy((sessions, bars))
        self.assertEqual(audit_daily_ohlc(sessions, bars), {
            "status": "complete", "expected_count": 2, "bar_count": 2,
            "missing_sessions": [], "unexpected_sessions": [], "duplicate_sessions": [],
        })
        self.assertEqual((sessions, bars), original)

    def test_discrepancies_reported_independently_and_sorted(self):
        sessions = ["2026-10-08", "2026-10-09", "2026-10-12"]
        bars = [bar(day) for day in ("2026-10-10", "2026-10-08", "2026-10-07",
                                    "2026-10-10", "2026-10-08")]
        self.assertEqual(audit_daily_ohlc(sessions, bars), {
            "status": "incomplete", "expected_count": 3, "bar_count": 5,
            "missing_sessions": ["2026-10-09", "2026-10-12"],
            "unexpected_sessions": ["2026-10-07", "2026-10-10"],
            "duplicate_sessions": ["2026-10-08", "2026-10-10"],
        })

    def test_empty_sample_is_all_missing(self):
        result = audit_daily_ohlc(["2026-10-08"], [])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["bar_count"], 0)
        self.assertEqual(result["missing_sessions"], ["2026-10-08"])

    def test_rejects_invalid_cohort(self):
        for sessions in ([], ("2026-10-08",), ["2026-10-08", "2026-10-08"],
                         ["2026-10-09", "2026-10-08"], ["20261008"], ["2026-02-29"],
                         ["2026-10-8"], ["２０２６-10-08"], [True], ["0000-01-01"]):
            with self.subTest(sessions=sessions), self.assertRaisesRegex(
                    ValueError, "^market_sample_invalid$"):
                audit_daily_ohlc(sessions, [])

    def test_rejects_malformed_bars_even_outside_cohort(self):
        day = "2026-10-07"
        incomplete_bar = bar(day)
        del incomplete_bar["close"]
        bad_bars = [None, incomplete_bar, bar(day, extra="private"),
                    bar("2026-02-30"), bar(day, open="98"), bar(day, close="102"),
                    bar(day, open="102"), bar(day, close="98"), bar(day, low="102")]
        for row in bad_bars:
            with self.subTest(row=row), self.assertRaisesRegex(
                    ValueError, "^market_sample_invalid$"):
                audit_daily_ohlc(["2026-10-08"], [bar(day), row])

    def test_prices_are_bounded_positive_ascii_decimal_strings(self):
        day = "2026-10-08"
        for price in (True, 101, 101.0, "0", "0.00000000", "-1", "+1", ".1", "1.",
                      "1e2", "nan", "Infinity", " 1", "1 ", "１", "1234567890123",
                      "1.123456789"):
            with self.subTest(price=price), self.assertRaisesRegex(
                    ValueError, "^market_sample_invalid$"):
                audit_daily_ohlc([day], [bar(day, open=price)])
        result = audit_daily_ohlc([day], [
            bar(day, open="0.00000001", low="0.00000001",
                high="999999999999.99999999", close="999999999999.99999999"),
        ])
        self.assertEqual(result["status"], "complete")

    def test_counts_are_bounded(self):
        start = date(2024, 1, 1)
        sessions = [(start + timedelta(days=offset)).isoformat() for offset in range(367)]
        bars = [bar(day) for day in sessions]
        self.assertEqual(audit_daily_ohlc(sessions[:366], bars[:366])["status"], "complete")
        for expected, observed in ((sessions, []), (sessions[:366], bars),
                                   (sessions[:366], tuple(bars[:366]))):
            with self.subTest(session_count=len(expected), bar_count=len(observed)):
                with self.assertRaisesRegex(ValueError, "^market_sample_invalid$"):
                    audit_daily_ohlc(expected, observed)


if __name__ == "__main__":
    unittest.main()
