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
from market_intel.ops import provider_receipt as module
from test_model_call_info import REQUEST


class ProviderReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "source"
        self.path = self.root / "llm-state.db"
        ensure_workspace_ledger(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, error=None):
        def transport(*_):
            if error is not None:
                raise error
            return ModelResponse('{"label":"private-output"}', 20, 8, "a" * 64)
        client = ModelClient(self.path, Policy(enabled=True, max_retries=0,
                             budget_currency="CNY", daily_micro_units=10_000_000,
                             input_micro_units_per_million_tokens=2_000_000,
                             output_micro_units_per_million_tokens=8_000_000), transport,
                             clock=lambda: datetime(2026, 11, 10, 23, 59, tzinfo=timezone.utc))
        if error is None:
            return client.generate({"text": "private-input"}, **REQUEST).call_id
        with self.assertRaises((ModelError, KeyboardInterrupt)):
            client.generate({"text": "private-input"}, **REQUEST)
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT call_id FROM calls ORDER BY rowid DESC").fetchone()[0]

    def claim(self, call_id):
        local = module.inspect_model_call(self.root, call_id)
        return {"schema_version": "provider-receipt-claim/0.1", "call_id": call_id,
                "response_id_sha256": local["response_id_sha256"] or "a" * 64,
                "provider": local["provider"], "model": local["model"],
                "utc_day": local["started_at"][:10], "currency": local["currency"],
                "input_tokens": local["input_tokens"] or 0,
                "output_tokens": local["output_tokens"] or 0,
                "billed_micro_units": local["charged_cost_micro_units"]}

    def state(self):
        return self.path.read_bytes(), (self.root / "llm-binding.json").read_bytes()

    def test_matching_claim_is_unverified_single_read_and_unchanged(self):
        call_id = self.call()
        claim = self.claim(call_id)
        before, original = self.state(), dict(claim)
        with patch.object(module, "inspect_model_call", wraps=module.inspect_model_call) as inspect, patch(
                "socket.create_connection", side_effect=AssertionError("network forbidden")), patch(
                "market_intel.llm.client.ModelClient.__init__", side_effect=AssertionError("model forbidden")):
            result = module.compare_provider_receipt(self.root, call_id, claim)
        inspect.assert_called_once_with(self.root, call_id)
        self.assertEqual(set(result), set("schema_version status read_only evidence_authenticated invoice_verified settlement_allowed switch_allowed model_called call_summary budget_day_utc missing_local_fields mismatched_fields amount_comparison".split()))
        self.assertEqual(result["schema_version"], "provider-receipt-comparison/0.1")
        self.assertEqual(result["status"], "unverified_comparison")
        self.assertEqual(result["missing_local_fields"], [])
        self.assertEqual(result["mismatched_fields"], [])
        self.assertEqual(result["budget_day_utc"], "2026-11-10")
        self.assertEqual(result["amount_comparison"], "configured_estimate_only")
        self.assertTrue(result["read_only"])
        for key in ("evidence_authenticated", "invoice_verified", "settlement_allowed", "switch_allowed", "model_called"):
            self.assertIs(result[key], False)
        self.assertEqual(before, self.state())
        self.assertEqual(original, claim)
        for private in ("private-output", "private-input", str(self.root), "request_metadata"):
            self.assertNotIn(private, json.dumps(result))

    def test_mismatches_are_ordered_and_claim_strings_not_echoed(self):
        call_id = self.call()
        claim = self.claim(call_id)
        claim.update(provider="deepseek", model="supplier-private-marker", utc_day="2026-11-11",
                     response_id_sha256="b" * 64, input_tokens=21, output_tokens=9, billed_micro_units=999)
        result = module.compare_provider_receipt(self.root, call_id, claim)
        self.assertEqual(result["mismatched_fields"], ["provider", "model", "utc_day", "response_id_sha256", "input_tokens", "output_tokens", "billed_micro_units"])
        self.assertNotIn("supplier-private-marker", json.dumps(result))

    def test_currency_mismatch_suppresses_amount_comparison(self):
        call_id = self.call()
        claim = self.claim(call_id)
        claim.update(currency="USD", billed_micro_units=10**15)
        result = module.compare_provider_receipt(self.root, call_id, claim)
        self.assertEqual(result["mismatched_fields"], ["currency"])
        self.assertEqual(result["amount_comparison"], "not_comparable_currency_mismatch")

    def test_failed_and_pending_keep_full_reservations(self):
        for error in (ObservedTransportError("synthetic_error", "b" * 64), KeyboardInterrupt()):
            call_id = self.call(error)
            claim = self.claim(call_id)
            before = self.state()
            result = module.compare_provider_receipt(self.root, call_id, claim)
            expected = ["input_tokens", "output_tokens"]
            if isinstance(error, KeyboardInterrupt):
                expected.insert(0, "response_id_sha256")
            self.assertEqual(result["missing_local_fields"], expected)
            self.assertEqual(result["mismatched_fields"], [])
            local = result["call_summary"]
            self.assertEqual(local["charged_cost_micro_units"], local["reserved_cost_micro_units"])
            self.assertEqual(local["charged_tokens"], local["reserved_tokens"])
            self.assertEqual(before, self.state())

    def test_zero_and_upper_bounds_are_valid_claims(self):
        call_id = self.call()
        claim = self.claim(call_id)
        for tokens, amount in ((0, 0), (10**9, 10**15)):
            claim.update(input_tokens=tokens, output_tokens=tokens, billed_micro_units=amount)
            result = module.compare_provider_receipt(self.root, call_id, claim)
            self.assertEqual(result["mismatched_fields"], ["input_tokens", "output_tokens", "billed_micro_units"])

    def test_invalid_claims_reject_before_read_with_fixed_error(self):
        call_id = "call_" + "a" * 32
        good = {"schema_version": "provider-receipt-claim/0.1", "call_id": call_id,
                "response_id_sha256": "a" * 64, "provider": "mock", "model": "safe/1",
                "utc_day": "2026-11-10", "currency": "CNY", "input_tokens": 0,
                "output_tokens": 0, "billed_micro_units": 0}
        bad = [None, [], {}, {**good, "extra": "secret"}]
        for field in good:
            bad.append({key: value for key, value in good.items() if key != field})
            for value in (None, [], {}, True, "private-secret-\ud800"):
                bad.append({**good, field: value})
        for field, values in {"call_id": ["call_"+"b"*32], "response_id_sha256": ["A"*64, "a"*63],
                              "utc_day": ["2026-02-30", "20261110"], "model": ["x"*129, "with space"],
                              "input_tokens": [-1, 10**9+1, 0.0], "output_tokens": [-1, 10**9+1],
                              "billed_micro_units": [-1, 10**15+1]}.items():
            bad.extend({**good, field: value} for value in values)
        with patch.object(module, "inspect_model_call", side_effect=AssertionError("read forbidden")):
            for claim in bad:
                with self.subTest(claim_type=type(claim).__name__), self.assertRaisesRegex(ValueError, "^provider_receipt_claim_invalid$"):
                    module.compare_provider_receipt(self.root, call_id, claim)

    def test_valid_claim_missing_workspace_does_not_create(self):
        call_id = self.call()
        claim = self.claim(call_id)
        missing = self.root.parent / "missing"
        with self.assertRaisesRegex(ValueError, "^model_call_binding_required$"):
            module.compare_provider_receipt(missing, call_id, claim)
        self.assertFalse(missing.exists())

    def test_corrupt_local_ledger_no_partial_comparison(self):
        call_id = self.call()
        claim = self.claim(call_id)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE calls SET request_metadata=? WHERE call_id=?", ('{"private":"secret"}', call_id))
        before = self.state()
        with self.assertRaisesRegex(ValueError, "^model_call_invalid$"):
            module.compare_provider_receipt(self.root, call_id, claim)
        self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
