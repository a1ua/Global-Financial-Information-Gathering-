from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.batch import run_mock_candidates
from market_intel.llm.deepseek import DeepSeekTransport
from test_llm_cny import cny_policy


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
CUTOFF = "2026-11-09T12:00:00Z"


def candidates(count=3):
    return {"schema_version": "synthetic-candidate-batch/0.1", "candidates": [
        {"candidate_id": f"candidate_{i}", "available_at": "2026-11-09T00:00:00Z",
         "title": "synthetic title", "is_synthetic": True} for i in range(count)]}


class CandidateBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "model" / "llm-state.db"

    def tearDown(self):
        self.temp.cleanup()

    def run_batch(self, batch=None, **kwargs):
        return run_mock_candidates(candidates() if batch is None else batch, self.path, CUTOFF,
                                   policy=kwargs.pop("policy", cny_policy()), clock=lambda: NOW, **kwargs)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM calls ORDER BY rowid")]

    def test_limit_applies_before_transport_and_cached_items_do_not_fill_extra_slots(self):
        seen = []
        def transport(request, timeout):
            seen.append(request["input"]["candidate_id"])
            return ModelResponse('{"category":"other"}', 10, 5)
        first = self.run_batch(max_candidates=2, transport=transport)
        second = self.run_batch(max_candidates=2, transport=transport)
        self.assertEqual(seen, ["candidate_0", "candidate_1"])
        self.assertEqual(first["succeeded_count"], 2)
        self.assertEqual(second["selected_count"], 2)
        self.assertTrue(all(r["cache_hit"] for r in second["results"]))
        self.assertEqual(len(self.rows()), 2)

    def test_budget_allows_prefix_then_stops_without_attempting_later_candidates(self):
        calibration = self.path.with_name("calibration.db")
        run_mock_candidates(candidates(), calibration, CUTOFF, 1, policy=cny_policy(), clock=lambda: NOW)
        with closing(sqlite3.connect(calibration)) as db:
            reserved = db.execute("SELECT reserved_cost FROM calls").fetchone()[0]
        seen = []
        def transport(request, timeout):
            seen.append(request["input"]["candidate_id"])
            return ModelResponse('{"category":"other"}', 10, 5)
        result = self.run_batch(policy=cny_policy(daily_micro_units=reserved), transport=transport)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual([r["status"] for r in result["results"]], ["succeeded", "failed", "not_attempted"])
        self.assertEqual(result["results"][1]["reason"], "budget_exceeded")
        self.assertEqual(seen, ["candidate_0"])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["charged_cost"], 60)

    def test_retries_each_reserve_even_when_candidate_cap_is_one(self):
        attempts = []
        def transport(request, timeout):
            attempts.append(request)
            if len(attempts) == 1:
                raise TimeoutError("synthetic private exception")
            return ModelResponse('{"category":"other"}', 10, 5)
        result = self.run_batch(max_candidates=1, policy=cny_policy(max_retries=1), transport=transport)
        self.assertEqual((result["selected_count"], result["succeeded_count"], len(attempts)), (1, 1, 2))
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["failed", "succeeded"])
        self.assertEqual(rows[0]["charged_cost"], rows[0]["reserved_cost"])
        self.assertGreater(rows[0]["charged_cost"], 0)

    def test_invalid_output_stops_batch_and_keeps_all_unknown_reservations(self):
        attempts = []
        def transport(*args):
            attempts.append(1)
            return ModelResponse("not JSON")
        result = self.run_batch(policy=cny_policy(max_retries=1), transport=transport)
        self.assertEqual((len(attempts), result["failed_count"], result["not_attempted_count"]), (2, 1, 2))
        self.assertTrue(all(r["charged_cost"] == r["reserved_cost"] > 0 for r in self.rows()))
        self.assertNotIn("not JSON", str(result))

    def test_invalid_policies_and_live_transport_never_create_ledger(self):
        live_policy = cny_policy(provider="deepseek", model="deepseek-flash")
        for policy, transport in ((Policy(), None), (live_policy, None),
                                   (cny_policy(), DeepSeekTransport("synthetic-key")), (cny_policy(), 1)):
            with self.subTest(policy=policy.provider, transport=type(transport).__name__), self.assertRaises(ModelError):
                self.run_batch(policy=policy, transport=transport)
            self.assertFalse(self.path.parent.exists())

    def test_zero_or_future_selection_does_not_create_ledger(self):
        self.assertEqual(self.run_batch(max_candidates=0)["selected_count"], 0)
        future = candidates(1)
        future["candidates"][0]["available_at"] = "2026-11-10T00:00:00Z"
        self.assertEqual(self.run_batch(future)["selected_count"], 0)
        self.assertFalse(self.path.parent.exists())

    def test_expected_identity_guard_precedes_generation(self):
        actual = ModelClient(self.path, cny_policy()).ledger_id
        self.assertNotEqual(actual, "ledger_" + "0" * 32)
        with self.assertRaisesRegex(ModelError, "^ledger_identity_mismatch$"):
            self.run_batch(expected_ledger_id="ledger_" + "0" * 32)
        self.assertEqual(self.rows(), [])

    def test_invalid_candidate_after_limit_is_rejected_before_ledger_creation(self):
        batch = candidates()
        batch["candidates"][-1]["is_synthetic"] = False
        with self.assertRaises(ValueError):
            self.run_batch(batch, max_candidates=1)
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
