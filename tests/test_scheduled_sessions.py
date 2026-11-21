import unittest
from copy import deepcopy

from market_intel.contracts.candidate_snapshot import payload_sha256
from market_intel.contracts.market_sample import audit_daily_ohlc
from market_intel.contracts.scheduled_sessions import compile_scheduled_sessions


def fixture(**changes):
    return {
        "schema_version": "scheduled-session-source/0.1",
        "exchange": "SSE",
        "calendar_id": "sse.example.2024",
        "year": 2024,
        "closure_ranges": [],
        "source_urls": ["https://www.sse.com.cn/example/calendar"],
        **changes,
    }


class ScheduledSessionsTests(unittest.TestCase):
    def test_leap_year_and_chronological_limits(self):
        sessions = compile_scheduled_sessions(fixture())["scheduled_sessions"]
        self.assertEqual(len(sessions), 262)
        self.assertEqual(sessions[0], "2024-01-01")
        self.assertEqual(sessions[-1], "2024-12-31")
        self.assertIn("2024-02-29", sessions)

    def test_inclusive_ranges_and_weekend_filtering(self):
        source = fixture(closure_ranges=[
            {"start": "2024-01-01", "end": "2024-01-01"},
            {"start": "2024-02-29", "end": "2024-03-03"},
        ])
        sessions = compile_scheduled_sessions(source)["scheduled_sessions"]
        self.assertEqual(len(sessions), 259)
        self.assertEqual(sessions[0], "2024-01-02")
        self.assertIn("2024-02-28", sessions)
        self.assertNotIn("2024-03-01", sessions)
        self.assertNotIn("2024-03-02", sessions)
        self.assertIn("2024-03-04", sessions)

    def test_snapshot_binds_provenance_and_keeps_prior_snapshot(self):
        source = fixture()
        original = deepcopy(source)
        snapshot = compile_scheduled_sessions(source)
        self.assertEqual(source, original)
        self.assertEqual(compile_scheduled_sessions(dict(reversed(list(source.items())))), snapshot)
        self.assertEqual(snapshot["source_sha256"], payload_sha256(source))
        self.assertEqual(snapshot["snapshot_sha256"],
                         payload_sha256({k: v for k, v in snapshot.items() if k != "snapshot_sha256"}))
        source["source_urls"].append("https://www.sse.com.cn/example/confirmation")
        revised = compile_scheduled_sessions(source)
        self.assertEqual(revised["scheduled_sessions"], snapshot["scheduled_sessions"])
        self.assertNotEqual(revised["snapshot_sha256"], snapshot["snapshot_sha256"])
        self.assertEqual(snapshot["source_sha256"], payload_sha256(original))

    def test_invalid_source_schema_and_range_bounds(self):
        for changes in (
            {"calendar_id": "invalid/slash"},
            {"exchange": "SZSE"},
            {"schema_version": ["scheduled-session-source/0.1"]},
            {"year": True},
            {"year": 9999},
            {"closure_ranges": [{"start": "2023-12-31", "end": "2024-01-01"}]},
            {"closure_ranges": [{"start": "2024-02-30", "end": "2024-03-01"}]},
            {"closure_ranges": [{"start": "2024-03-02", "end": "2024-03-01"}]},
            {"closure_ranges": [{"start": "2024-01-01", "end": "2024-12-31"}]},
            {"closure_ranges": [
                {"start": "2024-03-01", "end": "2024-03-04"},
                {"start": "2024-03-04", "end": "2024-03-05"},
            ]},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    ValueError, "^scheduled_sessions_invalid$"):
                compile_scheduled_sessions(fixture(**changes))

    def test_invalid_source_urls(self):
        for urls in (
            [],
            ["http://www.sse.com.cn/example"],
            ["https://www.sse.com.cn.evil.example/page"],
            ["https://www.sse.com.cn/example has space"],
            ["https://www.sse.com.cn/b", "https://www.sse.com.cn/a"],
            ["https://www.sse.com.cn/a"] * 2,
            [{}],
        ):
            with self.subTest(urls=urls), self.assertRaisesRegex(
                    ValueError, "^scheduled_sessions_invalid$"):
                compile_scheduled_sessions(fixture(source_urls=urls))

    def test_scheduled_dates_feed_ohlc_audit(self):
        source = fixture(closure_ranges=[{"start": "2024-01-01", "end": "2024-01-01"}])
        expected = compile_scheduled_sessions(source)["scheduled_sessions"][:2]
        bars = [{"session_date": "2024-01-01", "open": "1", "high": "2",
                 "low": "1", "close": "2"}]
        self.assertEqual(audit_daily_ohlc(expected, bars), {
            "status": "incomplete",
            "expected_count": 2,
            "bar_count": 1,
            "missing_sessions": ["2024-01-02", "2024-01-03"],
            "unexpected_sessions": ["2024-01-01"],
            "duplicate_sessions": [],
        })
