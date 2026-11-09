from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.binding import check_workspace_ledger, ensure_workspace_ledger
from market_intel.ops import model_calls as module
from market_intel.ops.model_calls import inspect_model_call


NOW = datetime(2026, 11, 10, 1, tzinfo=timezone.utc)
REQUEST = {"system_prompt": "private-prompt-marker", "prompt_version": "test/1", "rules_version": "test/1",
           "schema_version": "test/1", "parameters": {},
           "output_schema": {"type": "object", "properties": {"label": {"type": "string"}},
                             "required": ["label"], "additionalProperties": False}}
FIELDS = set("""schema_version status read_only model_called invoice_verified settlement_allowed ledger_id call_id
call_status attempt provider model started_at finished_at currency accounting_basis reserved_tokens charged_tokens
reserved_cost_micro_units charged_cost_micro_units input_tokens output_tokens input_rate_micro_units_per_million
output_rate_micro_units_per_million correlation_status response_id_sha256""".split())


class ModelCallInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.ledger = self.root / "llm-state.db"
        ensure_workspace_ledger(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def client(self, policy=None, transport=None):
        return ModelClient(self.ledger, policy or Policy(enabled=True, max_retries=0),
                           transport or (lambda *_: ModelResponse('{"label":"private-output-marker"}', 20, 8)),
                           clock=lambda: NOW)

    def successful(self):
        return self.client().generate({"text": "private-input-marker"}, **REQUEST)

    def metadata(self, call_id, correlation):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            value = json.loads(db.execute("SELECT request_metadata FROM calls WHERE call_id=?", (call_id,)).fetchone()[0])
            if correlation is ...:
                value.pop("provider_response", None)
            else:
                value["provider_response"] = correlation
            db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", (json.dumps(value), call_id))

    def state(self):
        return self.ledger.read_bytes(), (self.root / "llm-binding.json").read_bytes()

    def test_recorded_summary_exact_fields_no_payload_and_no_write(self):
        result = self.successful()
        value = {"schema_version": "provider-response-correlation/0.1", "response_id_sha256": "a" * 64,
                 "input_tokens": 20, "output_tokens": 8}
        self.metadata(result.call_id, value)
        before = self.state()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), patch(
                "market_intel.llm.client.ModelClient.__init__", side_effect=AssertionError("mutating client forbidden")):
            summary = inspect_model_call(self.root, result.call_id)
        self.assertEqual(set(summary), FIELDS)
        self.assertEqual((summary["correlation_status"], summary["response_id_sha256"]), ("recorded", "a" * 64))
        self.assertEqual((summary["charged_tokens"], summary["charged_cost_micro_units"]), (28, 28))
        self.assertEqual(summary["currency"], "USD")
        self.assertEqual(summary["input_rate_micro_units_per_million"], 1_000_000)
        self.assertTrue(summary["read_only"])
        for flag in ("model_called", "invoice_verified", "settlement_allowed"):
            self.assertFalse(summary[flag])
        serialized = json.dumps(summary)
        for secret in ("private-input-marker", "private-prompt-marker", "private-output-marker", "output_text", "request_metadata", str(self.root)):
            self.assertNotIn(secret, serialized)
        self.assertEqual(before, self.state())

    def test_legacy_success_and_cache_preserve_absent_correlation(self):
        client = self.client()
        first = client.generate({"text": "private-input-marker"}, **REQUEST)
        self.metadata(first.call_id, ...)
        before = self.state()
        self.assertEqual(inspect_model_call(self.root, first.call_id)["correlation_status"], "absent")
        client.transport = lambda *_: (_ for _ in ()).throw(AssertionError("cache must not call transport"))
        cached = client.generate({"text": "private-input-marker"}, **REQUEST)
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.call_id, first.call_id)
        self.assertEqual(before, self.state())

    def test_new_client_metadata_and_cache_keep_original_recorded_call(self):
        client = self.client(transport=lambda *_: ModelResponse('{"label":"synthetic"}', 20, 8, "b" * 64))
        result = client.generate({"synthetic": True}, **REQUEST)
        summary = inspect_model_call(self.root, result.call_id)
        self.assertEqual((summary["correlation_status"], summary["response_id_sha256"]), ("recorded", "b" * 64))
        before = self.state()
        client.transport = lambda *_: (_ for _ in ()).throw(AssertionError("cache must not transmit"))
        cached = client.generate({"synthetic": True}, **REQUEST)
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.call_id, result.call_id)
        self.assertEqual(summary, inspect_model_call(self.root, cached.call_id))
        self.assertEqual(before, self.state())

    def test_invalid_correlation_fields_reject_in_full_ledger_validation(self):
        result = self.successful()
        base = {"schema_version": "provider-response-correlation/0.1", "response_id_sha256": "a" * 64,
                "input_tokens": 20, "output_tokens": 8}
        for change in ({"extra": "sensitive-value"}, {"input_tokens": True}, {"output_tokens": 9},
                       {"response_id_sha256": "private-raw-id"}):
            with self.subTest(change=change):
                self.metadata(result.call_id, {**base, **change})
                with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
                    inspect_model_call(self.root, result.call_id)

    def test_id_unavailable_and_cny_rates(self):
        policy = Policy(enabled=True, max_retries=0, budget_currency="CNY", daily_micro_units=10_000_000,
                        input_micro_units_per_million_tokens=2_000_000, output_micro_units_per_million_tokens=8_000_000)
        result = self.client(policy).generate({"synthetic": True}, **REQUEST)
        self.metadata(result.call_id, {"schema_version": "provider-response-correlation/0.1", "response_id_sha256": None,
                                       "input_tokens": 20, "output_tokens": 8})
        summary = inspect_model_call(self.root, result.call_id)
        self.assertEqual((summary["correlation_status"], summary["response_id_sha256"]), ("id_unavailable", None))
        self.assertEqual((summary["currency"], summary["charged_cost_micro_units"]), ("CNY", 104))
        self.assertEqual((summary["input_rate_micro_units_per_million"], summary["output_rate_micro_units_per_million"]),
                         (2_000_000, 8_000_000))

    def test_pending_and_failed_remain_unassociated_and_reserved(self):
        for error, state in ((TimeoutError(), "failed"), (KeyboardInterrupt(), "pending")):
            with self.subTest(state=state):
                client = self.client(transport=lambda *_: (_ for _ in ()).throw(error))
                with self.assertRaises((ModelError, KeyboardInterrupt)):
                    client.generate({"case": state}, **REQUEST)
                with closing(sqlite3.connect(self.ledger)) as db:
                    call_id = db.execute("SELECT call_id FROM calls WHERE status=?", (state,)).fetchone()[0]
                summary = inspect_model_call(self.root, call_id)
                self.assertEqual((summary["call_status"], summary["correlation_status"]), (state, "absent"))
                self.assertIsNone(summary["input_tokens"])
                self.assertEqual(summary["charged_tokens"], summary["reserved_tokens"])
                self.assertEqual(summary["charged_cost_micro_units"], summary["reserved_cost_micro_units"])

    def test_invalid_id_missing_call_and_missing_workspace_do_not_initialize(self):
        missing = self.root.parent / "missing"
        for call_id in (None, True, "call_" + "A" * 32, "private-marker", "call_" + "a" * 33):
            with self.assertRaisesRegex(ValueError, "^model_call_id_invalid$"):
                inspect_model_call(missing, call_id)
        with self.assertRaisesRegex(ValueError, "^model_call_binding_required$"):
            inspect_model_call(missing, "call_" + "a" * 32)
        self.assertFalse(missing.exists())
        before = self.state()
        with self.assertRaisesRegex(ValueError, "^model_call_missing$"):
            inspect_model_call(self.root, "call_" + "a" * 32)
        self.assertEqual(before, self.state())

    def test_unbound_and_old_schema_reject_without_migration(self):
        result = self.successful()
        (self.root / "llm-binding.json").unlink()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DROP TABLE ledger_identity")
            db.execute("PRAGMA user_version=2")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "^model_call_binding_required$"):
            inspect_model_call(self.root, result.call_id)
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertFalse((self.root / "llm-binding.json").exists())

    def test_identity_changed_between_binding_and_transaction_rejects(self):
        result = self.successful()
        actual_check = module.check_workspace_ledger
        def changed(workspace):
            bound = actual_check(workspace)
            with closing(sqlite3.connect(self.ledger)) as db, db:
                db.execute("UPDATE ledger_identity SET ledger_id=?", ("ledger_" + "b" * 32,))
            return bound
        with patch.object(module, "check_workspace_ledger", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "^model_call_identity_mismatch$"):
                inspect_model_call(self.root, result.call_id)

    def test_one_query_only_transaction_and_wal_snapshot(self):
        result = self.successful()
        with closing(sqlite3.connect(self.ledger)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            observed = []
            actual = module._ledger
            def changed(db):
                observed.append((db.in_transaction, db.execute("PRAGMA query_only").fetchone()[0]))
                counts = actual(db)
                value = json.loads(writer.execute("SELECT request_metadata FROM calls WHERE call_id=?", (result.call_id,)).fetchone()[0])
                value["provider_response"] = {"schema_version": "provider-response-correlation/0.1", "response_id_sha256": "a" * 64,
                                              "input_tokens": 20, "output_tokens": 8}
                with writer:
                    writer.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", (json.dumps(value), result.call_id))
                return counts
            self.metadata(result.call_id, ...)
            with patch.object(module, "_ledger", side_effect=changed):
                summary = inspect_model_call(self.root, result.call_id)
            self.assertEqual(observed, [(True, 1)])
            self.assertEqual(summary["correlation_status"], "absent")
            self.assertEqual(inspect_model_call(self.root, result.call_id)["correlation_status"], "recorded")

    def test_corrupt_unrelated_row_and_private_errors_fail_without_echo(self):
        result = self.successful()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", ('{"private":"sensitive-body"}', result.call_id))
        with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
            inspect_model_call(self.root, result.call_id)
        with patch.object(module, "check_workspace_ledger", side_effect=OSError("private-path-or-body")):
            with self.assertRaisesRegex(ValueError, "^model_call_io_error$"):
                inspect_model_call(self.root, result.call_id)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_actual_junction_ancestor_rejects(self):
        result = self.successful()
        linked = self.root.parent / "linked"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(self.root)], capture_output=True, check=False)
        self.assertEqual(created.returncode, 0)
        try:
            with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
                inspect_model_call(linked, result.call_id)
        finally:
            os.rmdir(linked)


if __name__ == "__main__":
    unittest.main()
