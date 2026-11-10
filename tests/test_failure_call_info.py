from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelError, Policy
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.llm.client import ObservedTransportError
from market_intel.ops import model_calls as module
from market_intel.ops.model_calls import inspect_model_call
from test_model_call_info import FIELDS, NOW, REQUEST


class FailureCallInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "bound"
        self.path = self.root / "llm-state.db"
        ensure_workspace_ledger(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def fail(self, observation=True):
        error = ObservedTransportError("synthetic_error", "a" * 64) if observation else TimeoutError("private-body-marker")
        def transport(*_):
            raise error
        client = ModelClient(self.path, Policy(enabled=True, max_retries=0), transport, clock=lambda: NOW)
        with self.assertRaises(ModelError):
            client.generate({"synthetic": True}, **REQUEST)
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT call_id FROM calls ORDER BY rowid DESC").fetchone()[0]

    def state(self):
        return self.path.read_bytes(), (self.root / "llm-binding.json").read_bytes()

    def test_failed_summary_preserves_reservation_and_hides_payload(self):
        call_id = self.fail()
        before = self.state()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), patch(
                "market_intel.llm.client.ModelClient.__init__", side_effect=AssertionError("client forbidden")):
            result = inspect_model_call(self.root, call_id)
        self.assertEqual(set(result), FIELDS)
        self.assertEqual((result["schema_version"], result["call_status"], result["correlation_status"]),
                         ("model-call-info/0.2", "failed", "failure_recorded"))
        self.assertEqual(result["response_id_sha256"], "a" * 64)
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["output_tokens"])
        self.assertEqual(result["charged_tokens"], result["reserved_tokens"])
        self.assertEqual(result["charged_cost_micro_units"], result["reserved_cost_micro_units"])
        for flag in ("model_called", "invoice_verified", "settlement_allowed"):
            self.assertFalse(result[flag])
        self.assertTrue(result["read_only"])
        self.assertEqual(before, self.state())
        for secret in ("private-body-marker", "request_metadata", "output_text", "private-prompt-marker", str(self.root)):
            self.assertNotIn(secret, json.dumps(result))

    def test_legacy_failed_no_response_is_not_backfilled(self):
        call_id = self.fail(observation=False)
        before = self.state()
        result = inspect_model_call(self.root, call_id)
        self.assertEqual((result["correlation_status"], result["response_id_sha256"]), ("absent", None))
        self.assertEqual(before, self.state())

    def test_invalid_failure_or_mutually_present_success_reject(self):
        call_id = self.fail()
        with closing(sqlite3.connect(self.path)) as db:
            original = json.loads(db.execute("SELECT request_metadata FROM calls WHERE call_id=?", (call_id,)).fetchone()[0])
        failure = original["provider_failure"]
        variants = [None, {**failure, "extra": "private-marker"}, {**failure, "response_id_sha256": "private-id-marker"}]
        for value in variants:
            metadata = {**original, "provider_failure": value}
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", (json.dumps(metadata), call_id))
            with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
                inspect_model_call(self.root, call_id)
        metadata = {**original, "provider_response": {"schema_version": "provider-response-correlation/0.1",
                     "response_id_sha256": "b" * 64, "input_tokens": 20, "output_tokens": 8}}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", (json.dumps(metadata), call_id))
        with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
            inspect_model_call(self.root, call_id)

    def test_wal_failed_observation_uses_validated_read_snapshot(self):
        call_id = self.fail(observation=False)
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            actual = module._ledger
            observations = []
            def changed(db):
                observations.append((db.in_transaction, db.execute("PRAGMA query_only").fetchone()[0]))
                counts = actual(db)
                value = json.loads(writer.execute("SELECT request_metadata FROM calls WHERE call_id=?", (call_id,)).fetchone()[0])
                value["provider_failure"] = {"schema_version": "provider-failure-correlation/0.1", "response_id_sha256": "c" * 64}
                with writer:
                    writer.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", (json.dumps(value), call_id))
                return counts
            with patch.object(module, "_ledger", side_effect=changed):
                result = inspect_model_call(self.root, call_id)
            self.assertEqual(observations, [(True, 1)])
            self.assertEqual(result["correlation_status"], "absent")
            result = inspect_model_call(self.root, call_id)
            self.assertEqual((result["correlation_status"], result["response_id_sha256"]), ("failure_recorded", "c" * 64))


if __name__ == "__main__":
    unittest.main()
