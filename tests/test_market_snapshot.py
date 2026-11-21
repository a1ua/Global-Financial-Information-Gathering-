import copy
import unittest

from market_intel.contracts.candidate_snapshot import payload_sha256
from market_intel.contracts.market_snapshot import freeze_market_snapshot, load_market_snapshot


INSTRUMENT = "index.synthetic"
START = "2026-10-07"
END = "2026-10-09"
CUTOFF = "2026-10-09T08:00:00Z"
ERROR = "^synthetic_market_snapshot_invalid$"


def calendar():
    return {
        "schema_version": "scheduled-session-source/0.1",
        "calendar_id": "sse.test.v1",
        "exchange": "SSE",
        "year": 2026,
        "closure_ranges": [{"start": "2026-10-01", "end": "2026-10-07"}],
        "source_urls": ["https://www.sse.com.cn/example"],
    }


def version(day="2026-10-08", available="2026-10-08T07:30:00Z", close="2"):
    return {
        "instrument_id": INSTRUMENT,
        "is_synthetic": True,
        "available_at": available,
        "bar": {"session_date": day, "open": "1", "high": "3", "low": "1", "close": close},
    }


def freeze(bars, **kwargs):
    return freeze_market_snapshot(
        calendar(), INSTRUMENT, bars,
        **{"cutoff": CUTOFF, "start_date": START, "end_date": END, **kwargs},
    )


def rehash(snapshot):
    snapshot["snapshot_sha256"] = payload_sha256({
        key: value for key, value in snapshot.items() if key != "snapshot_sha256"
    })


class MarketSnapshotTests(unittest.TestCase):
    def test_freeze_selects_inclusive_cutoff_in_date_order(self):
        first = version()
        latest = version(available=CUTOFF, close="2.50")
        future = version(available="2026-10-09T08:00:00.000001Z", close="2.60")
        second = version("2026-10-09", "2026-10-09T07:30:00Z")
        bar_list = [second, future, latest, first]
        original = copy.deepcopy(bar_list)
        snapshot = freeze(bar_list)
        self.assertEqual(snapshot, freeze(list(reversed(bar_list))))
        self.assertEqual(bar_list, original)
        self.assertEqual(snapshot["selected"], [
            {"session_date": "2026-10-08", "bar_version_sha256": payload_sha256(latest)},
            {"session_date": "2026-10-09", "bar_version_sha256": payload_sha256(second)},
        ])
        self.assertEqual(snapshot["missing_sessions"], [])
        self.assertTrue(snapshot["is_synthetic"])

    def test_replay_preserves_selected_revision_and_missing_days_after_backfill(self):
        initial = version()
        snapshot = freeze([initial])
        backfilled = version(available="2026-10-09T08:00:00Z", close="2.50")
        filled = version("2026-10-09", "2026-10-09T07:45:00Z")
        revisions = [filled, backfilled, initial, copy.deepcopy(initial)]
        replay = load_market_snapshot(calendar(), revisions, snapshot)
        self.assertEqual(replay, [initial])
        self.assertEqual(snapshot["missing_sessions"], ["2026-10-09"])
        self.assertNotEqual(freeze(revisions[:-1]), snapshot)
        replay[0]["bar"]["close"] = "3"
        self.assertEqual(initial["bar"]["close"], "2")
        with self.assertRaisesRegex(ValueError, ERROR):
            load_market_snapshot(calendar(), revisions[:2], snapshot)

    def test_tied_instants_rejected_even_with_different_timestamp_spelling(self):
        with self.assertRaisesRegex(ValueError, ERROR):
            freeze([version(), version(available="2026-10-08T07:30:00.0Z", close="2.50")])

    def test_calendar_and_manifest_integrity_are_enforced(self):
        initial = version()
        snapshot = freeze([initial])
        changed_calendar = calendar()
        changed_calendar["calendar_id"] = "sse.test.v2"
        with self.assertRaisesRegex(ValueError, ERROR):
            load_market_snapshot(changed_calendar, [initial], snapshot)
        wrong_hash = {**snapshot, "snapshot_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, ERROR):
            load_market_snapshot(calendar(), [initial], wrong_hash)
        wrong_partition = {**snapshot, "missing_sessions": []}
        rehash(wrong_partition)
        with self.assertRaisesRegex(ValueError, ERROR):
            load_market_snapshot(calendar(), [initial], wrong_partition)

    def test_replay_rejects_rehashed_future_selection(self):
        future = version(available="2026-10-09T08:00:01Z")
        forged = freeze([])
        forged["selected"] = [{"session_date": "2026-10-08",
                               "bar_version_sha256": payload_sha256(future)}]
        forged["missing_sessions"] = ["2026-10-09"]
        rehash(forged)
        with self.assertRaisesRegex(ValueError, ERROR):
            load_market_snapshot(calendar(), [future], forged)

    def test_market_local_date_and_synthetic_scope(self):
        midnight = version(available="2026-10-07T16:00:00Z")
        self.assertEqual(load_market_snapshot(calendar(), [midnight], freeze([midnight])), [midnight])
        invalid = (
            version(available="2026-10-07T15:59:59Z"),
            version("2026-10-07"),
            {**version(), "is_synthetic": False},
            {**version(), "instrument_id": "other"},
        )
        for wrong in invalid:
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError, ERROR):
                freeze([wrong])
        with self.assertRaisesRegex(ValueError, ERROR):
            freeze([], start_date="2025-12-31")
        with self.assertRaisesRegex(ValueError, ERROR):
            freeze([], start_date=START, end_date=START)
