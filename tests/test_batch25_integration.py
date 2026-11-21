from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from market_intel.contracts.evaluation_window import plan_synthetic_evaluation_window
from market_intel.offline import ingest_fixture
from market_intel.store import connect
from market_intel.store.predictions import read_prediction, submit_prediction
from test_evidence_candidates import fixture
from test_prediction_input import prediction_fixture, refresh_hashes


class EvaluationReceiptIntegrationTests(unittest.TestCase):
    def test_receipt_at_open_starts_from_next_session(self):
        evidence = fixture()
        value = prediction_fixture(evidence)
        sessions = [
            {"opens_at": "2026-11-10T08:00:00Z", "closes_at": "2026-11-10T09:00:00Z"},
            {"opens_at": "2026-11-11T08:00:00Z", "closes_at": "2026-11-11T09:00:00Z"},
        ]
        value["inputs"]["calendar"]["sessions"] = sessions
        refresh_hashes(value)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with closing(connect(root / "market.db")) as db:
                ingest_fixture(db, evidence, root)
                submit_prediction(db, root, value,
                                  clock=lambda: datetime(2026, 11, 10, 8, tzinfo=timezone.utc))
                record = read_prediction(db, value["content"]["prediction_id"])
                plan = plan_synthetic_evaluation_window(
                    {"content": record["content"], "inputs": record["inputs"]},
                    record["receipt"],
                )
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["sessions"], [sessions[1]])
        self.assertEqual(plan["committed_at"], "2026-11-10T08:00:00.000000Z")
