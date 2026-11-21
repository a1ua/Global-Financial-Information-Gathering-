from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.llm.client import ObservedTransportError
from market_intel.ops import provider_preflight as module
from market_intel.ops.provider_preflight import preflight_provider_evidence
from test_model_call_info import REQUEST, FIELDS


class ProviderPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "source"
        self.path = self.root / "llm-state.db"
        ensure_workspace_ledger(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, response=None, error=None):
        def transport(*_):
            if error is not None:
                raise error
            return response or ModelResponse('{"label":"private-output"}', 20, 8, "a" * 64)
        policy = Policy(enabled=True, max_retries=0, budget_currency="CNY", daily_micro_units=10_000_000,
                        input_micro_units_per_million_tokens=2_000_000, output_micro_units_per_million_tokens=8_000_000)
        client = ModelClient(self.path, policy, transport,
                             clock=lambda: datetime(2026, 11, 10, 23, 59, tzinfo=timezone.utc))
        if error is None:
            return client.generate({"text": "private-input"}, **REQUEST).call_id
        with self.assertRaises((ModelError, KeyboardInterrupt)):
            client.generate({"text": "private-input"}, **REQUEST)
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT call_id FROM calls ORDER BY rowid DESC").fetchone()[0]

    def state(self):
        return self.path.read_bytes(), (self.root / "llm-binding.json").read_bytes()

    def test_success_local_observations_still_require_receipt(self):
        call_id = self.call()
        before = self.state()
        actual = module.inspect_model_call
        with patch.object(module, "inspect_model_call", wraps=actual) as inspect, patch(
                "socket.create_connection", side_effect=AssertionError("network forbidden")), patch(
                "market_intel.llm.client.ModelClient.__init__", side_effect=AssertionError("model forbidden")):
            result = preflight_provider_evidence(self.root, call_id)
        inspect.assert_called_once_with(self.root, call_id)
        self.assertEqual(set(result), set("schema_version status read_only model_called invoice_verified settlement_allowed switch_allowed call_summary budget_day_utc evidence_gaps supplier_receipt_requirements".split()))
        self.assertEqual(result["schema_version"], "provider-evidence-preflight/0.1")
        self.assertEqual(set(result["call_summary"]), FIELDS)
        self.assertEqual(result["budget_day_utc"], "2026-11-10")
        self.assertEqual(result["evidence_gaps"], ["supplier_receipt_missing"])
        self.assertEqual(result["supplier_receipt_requirements"], ["response_id_hash", "provider", "model", "utc_day", "currency", "input_tokens", "output_tokens", "billed_amount", "provenance"])
        self.assertEqual(result["status"], "evidence_incomplete")
        self.assertEqual(result["call_summary"]["charged_cost_micro_units"], 104)
        self.assertTrue(result["read_only"])
        for key in ("model_called", "invoice_verified", "settlement_allowed", "switch_allowed"):
            self.assertIs(result[key], False)
        self.assertEqual(before, self.state())
        for secret in ("private-input", "private-output", "private-prompt-marker", str(self.root), "request_metadata"):
            self.assertNotIn(secret, json.dumps(result))

    def test_failure_observation_keeps_full_reservation(self):
        call_id = self.call(error=ObservedTransportError("synthetic_error", "b" * 64))
        before = self.state()
        result = preflight_provider_evidence(self.root, call_id)
        self.assertEqual(result["evidence_gaps"], ["usage_missing", "supplier_receipt_missing"])
        summary = result["call_summary"]
        self.assertEqual(summary["correlation_status"], "failure_recorded")
        self.assertEqual(summary["charged_cost_micro_units"], summary["reserved_cost_micro_units"])
        self.assertEqual(summary["charged_tokens"], summary["reserved_tokens"])
        self.assertEqual(before, self.state())

    def test_timeout_and_pending_have_ordered_gaps(self):
        for error in (TimeoutError("private-error"), KeyboardInterrupt()):
            call_id = self.call(error=error)
            before = self.state()
            result = preflight_provider_evidence(self.root, call_id)
            self.assertEqual(result["evidence_gaps"], ["response_hash_missing", "usage_missing", "supplier_receipt_missing"])
            self.assertEqual(before, self.state())

    def test_unaccepted_zero_response_usage_is_missing(self):
        call_id = self.call(response=ModelResponse('{"label":"zero"}', 0, 0))
        result = preflight_provider_evidence(self.root, call_id)
        self.assertEqual(result["evidence_gaps"], ["response_hash_missing", "usage_missing", "supplier_receipt_missing"])
        self.assertFalse(result["invoice_verified"])

    def test_present_zero_summary_values_are_not_null(self):
        call_id = self.call()
        summary = module.inspect_model_call(self.root, call_id)
        summary.update(input_tokens=0, output_tokens=0)
        with patch.object(module, "inspect_model_call", return_value=summary):
            result = preflight_provider_evidence(self.root, call_id)
        self.assertEqual(result["evidence_gaps"], ["supplier_receipt_missing"])
        self.assertFalse(result["invoice_verified"])

    def test_missing_workspace_no_creation_and_sanitized_error(self):
        missing = self.root.parent / "missing"
        with self.assertRaisesRegex(ValueError, "^model_call_binding_required$"):
            preflight_provider_evidence(missing, "call_" + "a" * 32)
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ValueError, "^model_call_id_invalid$"):
            preflight_provider_evidence(missing, "private-error")

    def test_corrupt_ledger_rejects_without_partial_report(self):
        call_id = self.call()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", ('{"private":"secret"}', call_id))
        before = self.state()
        with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
            preflight_provider_evidence(self.root, call_id)
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
