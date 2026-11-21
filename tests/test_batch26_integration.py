from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from market_intel.contracts.abnormal_return import calculate_synthetic_abnormal_return
from market_intel.contracts.market_snapshot import freeze_market_snapshot
from market_intel.offline import ingest_fixture
from market_intel.store import connect
from market_intel.store.predictions import read_prediction, submit_prediction
from test_evidence_candidates import fixture
from test_prediction_input import prediction_fixture, refresh_hashes


class AbnormalReturnIntegrationTests(unittest.TestCase):
    def test_stored_receipt_to_exact_two_session_car(self):
        evidence = fixture()
        value = prediction_fixture(evidence)
        dates = ["2026-11-10", "2026-11-11"]
        value["inputs"]["calendar"]["sessions"] = [
            {"opens_at": day + "T01:30:00Z", "closes_at": day + "T07:00:00Z"}
            for day in dates
        ]
        value["inputs"]["protocol"]["horizon_sessions"] = 2
        refresh_hashes(value)
        calendar = {"schema_version": "scheduled-session-source/0.1",
                    "calendar_id": "sse.synthetic.batch26", "exchange": "SSE",
                    "year": 2026, "closure_ranges": [],
                    "source_urls": ["https://www.sse.com.cn/example/calendar"]}
        as_of = "2026-11-11T07:00:00Z"

        def prices(key, closes):
            instrument = value["content"][key]
            bars = [
                {"instrument_id": instrument, "is_synthetic": True,
                 "available_at": day + "T07:00:00Z",
                 "bar": {"session_date": day, "open": "100", "high": "130",
                         "low": "99", "close": close}}
                for day, close in zip(dates, closes)
            ]
            snapshot = freeze_market_snapshot(calendar, instrument, bars, cutoff=as_of,
                                              start_date=dates[0], end_date=dates[-1])
            return {"snapshot": snapshot, "bars": bars}

        target = prices("target_instrument_id", ("110", "121"))
        benchmark = prices("benchmark_instrument_id", ("105", "105"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with closing(connect(root / "market.db")) as db:
                ingest_fixture(db, evidence, root)
                submit_prediction(db, root, value,
                                  clock=lambda: datetime(2026, 11, 9, 13, tzinfo=timezone.utc))
                record = read_prediction(db, value["content"]["prediction_id"])
                result = calculate_synthetic_abnormal_return(
                    {"content": record["content"], "inputs": record["inputs"]},
                    record["receipt"], calendar, target, benchmark, as_of=as_of,
                )
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["car"], "0.15000000")
        self.assertEqual([row["abnormal_return"] for row in result["segments"]],
                         ["0.05000000", "0.10000000"])
        self.assertEqual(result["target_snapshot_sha256"], target["snapshot"]["snapshot_sha256"])
