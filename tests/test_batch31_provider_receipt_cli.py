from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from unittest import TestCase
from unittest.mock import patch

from market_intel.cli import main
from market_intel.ops.provider_receipt import compare_provider_receipt
import test_provider_receipt as receipt_tests


class ProviderReceiptCLITests(TestCase):
    def setUp(self):
        self.fixture = receipt_tests.ProviderReceiptTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.call_id = self.fixture.call()
        self.claim = self.fixture.claim(self.call_id)
        self.claim_path = self.fixture.root.parent / "vendor-private-claim.json"
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("market_intel.llm.client.ModelClient.__init__",
                                side_effect=AssertionError("model forbidden")))

    def run_cli(self, workspace=None):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["compare-provider-receipt",
                         "--workspace", str(workspace or self.fixture.root),
                         "--call-id", self.call_id,
                         "--claim", str(self.claim_path)])
        return code, out.getvalue(), err.getvalue()

    def test_matching_and_mismatched_claims_use_read_only_api(self):
        before = self.fixture.state()
        for overrides, expected_mismatches in (
                ({}, []),
                ({"model": "supplier-private-marker", "currency": "USD"}, ["model", "currency"])):
            with self.subTest(expected_mismatches=expected_mismatches):
                claim = {**self.claim, **overrides}
                claim_bytes = json.dumps(claim).encode("utf-8")
                self.claim_path.write_bytes(claim_bytes)
                code, out, err = self.run_cli()
                self.assertEqual((code, err), (0, ""))
                result = json.loads(out)
                self.assertEqual(result, compare_provider_receipt(self.fixture.root, self.call_id, claim))
                self.assertEqual(result["mismatched_fields"], expected_mismatches)
                self.assertTrue(result["read_only"])
                for key in ("model_called", "evidence_authenticated", "invoice_verified",
                            "settlement_allowed", "switch_allowed"):
                    self.assertIs(result[key], False)
                self.assertEqual(self.claim_path.read_bytes(), claim_bytes)
                self.assertEqual(self.fixture.state(), before)
                self.assertNotIn("supplier-private-marker", out)

    def test_claim_size_boundary(self):
        encoded = json.dumps(self.claim).encode("utf-8")
        at_limit = encoded.ljust(16 * 1024, b" ")
        self.claim_path.write_bytes(at_limit)
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["mismatched_fields"], [])
        self.claim_path.write_bytes(at_limit + b" ")
        self.assert_claim_error("provider_receipt_claim_too_large")

    def test_invalid_claim_file_errors_are_sanitized(self):
        self.assert_claim_error("provider_receipt_claim_missing")
        for data in (b'{"model":"supplier-private-marker","model":"other"}',
                     b'{"model":"supplier-private-marker","input_tokens":NaN}',
                     b'{"model":"supplier-private-marker"\xff}',
                     b'{"unexpected":"supplier-private-marker"}'):
            with self.subTest(length=len(data)):
                self.claim_path.write_bytes(data)
                self.assert_claim_error("provider_receipt_claim_invalid")

    def test_missing_workspace_is_not_created(self):
        self.claim_path.write_text(json.dumps(self.claim), encoding="utf-8")
        missing = self.fixture.root.parent / "unused-workspace"
        code, out, err = self.run_cli(missing)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["reason"], "model_call_binding_required")
        self.assertFalse(missing.exists())

    def assert_claim_error(self, expected):
        before = self.fixture.state()
        code, out, err = self.run_cli()
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["reason"], expected)
        self.assertNotIn(self.claim_path.name, err)
        self.assertNotIn("supplier-private-marker", err)
        self.assertEqual(self.fixture.state(), before)
