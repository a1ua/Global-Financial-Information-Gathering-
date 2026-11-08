from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.llm import ModelClient, ModelResponse, Policy
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.ops.llm_backup import _ledger
from market_intel.ops.reconciliation import preview_reconciliation
from test_llm_cny import cny_policy, REQUEST


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "live"
        self.bound = ensure_workspace_ledger(self.workspace)
        self.ledger = self.workspace / "llm-state.db"
        self.statement = self.root / "statement.json"
        self.client = ModelClient(self.ledger, cny_policy(), lambda *_: ModelResponse(
            '{"category":"other"}', 20, 8), clock=lambda: NOW)
        self.client.generate({"title": "synthetic first"}, **REQUEST)

    def tearDown(self):
        self.temp.cleanup()

    def calls(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM calls ORDER BY rowid")]

    def value(self, **changes):
        value = {"schema_version": "ledger-reconciliation-statement/0.1",
                 "ledger_id": self.bound["ledger_id"], "utc_day": "2026-11-09", "currency": "CNY",
                 "provider": "mock", "evidence_kind": "synthetic", "evidence_sha256": "a" * 64,
                 "records": [{"call_id": row["call_id"], "charged_micro_units": row["charged_cost"]}
                             for row in self.calls()]}
        value.update(changes)
        return value

    def write(self, value=None):
        self.statement.write_text(json.dumps(self.value() if value is None else value), encoding="utf-8")
        return self.statement

    def snapshot(self):
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def preview(self, value=None):
        self.write(value)
        return preview_reconciliation(self.workspace, self.statement)

    def test_matching_estimates_never_authenticate_or_settle_and_repeat_without_writes(self):
        self.write(self.value(evidence_kind="manual_statement"))
        before = self.snapshot()
        result = preview_reconciliation(self.workspace, self.statement)
        self.assertEqual(result, preview_reconciliation(self.workspace, self.statement))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(result["status"], "matched_estimates")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["evidence_authenticated"])
        self.assertFalse(result["settlement_allowed"])
        self.assertEqual((result["local_estimated_micro_units"], result["statement_micro_units"],
                          result["delta_micro_units"]), (104, 104, 0))
        self.assertEqual(set(result), {"schema_version", "status", "ledger_id", "utc_day", "currency",
                                      "provider", "evidence_kind", "read_only", "evidence_authenticated",
                                      "settlement_allowed", "local_calls", "statement_records", "missing_records",
                                      "pending_calls", "difference_records", "local_estimated_micro_units",
                                      "statement_micro_units", "delta_micro_units"})

    def test_missing_statement_records_are_incomplete_and_delta_uses_all_local_calls(self):
        result = self.preview(self.value(records=[]))
        self.assertEqual((result["status"], result["missing_records"], result["delta_micro_units"]),
                         ("incomplete", 1, -104))

    def test_per_call_differences_do_not_cancel_out_with_equal_total(self):
        self.client.generate({"title": "synthetic second"}, **REQUEST)
        value = self.value()
        value["records"][0]["charged_micro_units"] += 1
        value["records"][1]["charged_micro_units"] -= 1
        result = self.preview(value)
        self.assertEqual((result["status"], result["difference_records"], result["delta_micro_units"]),
                         ("differences", 2, 0))

    def test_pending_with_matching_amount_is_incomplete_and_not_released(self):
        def interrupt(*_):
            raise KeyboardInterrupt()
        client = ModelClient(self.ledger, cny_policy(), interrupt, clock=lambda: NOW)
        with self.assertRaises(KeyboardInterrupt):
            client.generate({"title": "synthetic interrupted"}, **REQUEST)
        self.write()
        before, calls = self.snapshot(), self.calls()
        result = preview_reconciliation(self.workspace, self.statement)
        self.assertEqual((result["status"], result["pending_calls"], result["difference_records"]),
                         ("incomplete", 1, 0))
        self.assertEqual(self.calls(), calls)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(result["settlement_allowed"])

    def test_zero_calls_in_provider_scope_is_not_authenticated(self):
        result = self.preview(self.value(provider="deepseek", records=[]))
        self.assertEqual((result["status"], result["local_calls"]), ("matched_estimates", 0))
        self.assertFalse(result["evidence_authenticated"])
        self.assertFalse(result["settlement_allowed"])

    def test_usd_scope_keeps_usd_units_and_integer_boundary_amounts(self):
        workspace = self.root / "usd"
        bound = ensure_workspace_ledger(workspace)
        client = ModelClient(workspace / "llm-state.db", Policy(enabled=True), lambda *_: ModelResponse(
            '{"category":"other"}', 20, 8), clock=lambda: NOW)
        call = client.generate({"title": "synthetic USD"}, **REQUEST)
        for amount in (0, 10**15):
            self.write(self.value(ledger_id=bound["ledger_id"], currency="USD", records=[
                {"call_id": call.call_id, "charged_micro_units": amount}]))
            result = preview_reconciliation(workspace, self.statement)
            self.assertEqual(result["currency"], "USD")
            self.assertEqual(result["statement_micro_units"], amount)
            self.assertEqual(result["status"], "differences")
            self.assertFalse(result["settlement_allowed"])

    def test_unknown_or_wrong_provider_call_rejected(self):
        for changes in ({"provider": "deepseek"}, {"records": [
                {"call_id": "call_" + "0" * 32, "charged_micro_units": 0}]}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "ledger_reconciliation_unknown_call"):
                self.preview(self.value(**changes))

    def test_wrong_day_currency_and_identity_rejected(self):
        for changes, code in (({"utc_day": "2026-11-10"}, "day_missing"),
                              ({"currency": "USD"}, "currency_mismatch"),
                              ({"ledger_id": "ledger_" + "0" * 32}, "identity_mismatch")):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "ledger_reconciliation_" + code):
                self.preview(self.value(**changes))

    def test_duplicate_call_ids_rejected(self):
        value = self.value()
        value["records"] *= 2
        with self.assertRaisesRegex(ValueError, "ledger_reconciliation_statement_invalid"):
            self.preview(value)

    def test_invalid_json_duplicate_keys_nonfinite_and_utf8_rejected_without_echo(self):
        for raw in (b'{"secret marker":', b'{"records":[],"records":[]}', b'NaN', b'Infinity', b'\xff'):
            with self.subTest(raw=raw):
                self.statement.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "^ledger_reconciliation_statement_invalid$"):
                    preview_reconciliation(self.workspace, self.statement)

    def test_invalid_field_types_formats_and_extra_fields_rejected(self):
        for changes in ({"schema_version": None}, {"ledger_id": "bad"}, {"provider": []},
                        {"evidence_sha256": "A" * 64}, {"evidence_kind": "verified"},
                        {"utc_day": "2026-11-09T00:00:00Z"}, {"utc_day": "2026-02-30"},
                        {"currency": True}, {"records": {}}, {"extra": "secret marker"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "^ledger_reconciliation_statement_invalid$"):
                self.preview(self.value(**changes))

    def test_invalid_record_amounts_types_and_extra_fields_rejected(self):
        for amount in (True, -1, 1.0, None, 10**15 + 1):
            value = self.value()
            value["records"][0]["charged_micro_units"] = amount
            with self.subTest(amount=amount), self.assertRaisesRegex(ValueError, "statement_invalid"):
                self.preview(value)
        for record in ({}, {"call_id": "call_bad", "charged_micro_units": 0},
                       {"call_id": self.calls()[0]["call_id"], "charged_micro_units": 0, "extra": 1}):
            with self.subTest(record=record), self.assertRaisesRegex(ValueError, "statement_invalid"):
                self.preview(self.value(records=[record]))

    def test_statement_size_boundary_and_record_limit(self):
        raw = json.dumps(self.value()).encode("utf-8")
        self.statement.write_bytes(raw + b" " * (1_048_576 - len(raw)))
        self.assertEqual(preview_reconciliation(self.workspace, self.statement)["status"], "matched_estimates")
        self.statement.write_bytes(raw + b" " * (1_048_577 - len(raw)))
        with self.assertRaisesRegex(ValueError, "statement_too_large"):
            preview_reconciliation(self.workspace, self.statement)
        value = self.value(records=[{"call_id": f"call_{n:032x}", "charged_micro_units": 0} for n in range(10001)])
        self.assertLess(len(json.dumps(value).encode()), 1_048_576)
        with self.assertRaisesRegex(ValueError, "statement_invalid"):
            self.preview(value)

    def test_missing_file_directory_and_os_error_have_safe_codes(self):
        with self.assertRaisesRegex(ValueError, "statement_missing"):
            preview_reconciliation(self.workspace, self.statement)
        with self.assertRaisesRegex(ValueError, "statement_missing"):
            preview_reconciliation(self.workspace, self.root)
        self.write()
        with patch("market_intel.ops.reconciliation.Path.open", side_effect=OSError("secret marker")):
            with self.assertRaisesRegex(ValueError, "^ledger_reconciliation_io_error$"):
                preview_reconciliation(self.workspace, self.statement)

    def test_statement_ancestor_link_rejected(self):
        self.write()
        with patch("market_intel.ops.reconciliation._linked", side_effect=lambda p: p == self.statement.parent):
            with self.assertRaisesRegex(ValueError, "link_forbidden"):
                preview_reconciliation(self.workspace, self.statement)

    def test_missing_or_unbound_workspace_never_created_or_adopted(self):
        self.write()
        missing = self.root / "missing"
        with self.assertRaisesRegex(ValueError, "binding_required"):
            preview_reconciliation(missing, self.statement)
        self.assertFalse(missing.exists())
        (self.workspace / "llm-binding.json").unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "binding_required"):
            preview_reconciliation(self.workspace, self.statement)
        self.assertEqual(self.snapshot(), before)

    def test_isolated_restore_marker_rejected(self):
        self.write()
        (self.workspace / "ledger-backup-manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "^isolated_ledger_not_live$"):
            preview_reconciliation(self.workspace, self.statement)

    def test_business_closure_corruption_rejected_without_repair(self):
        self.write()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE calls SET charged_cost=0")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "ledger_reconciliation_ledger_invalid"):
            preview_reconciliation(self.workspace, self.statement)
        self.assertEqual(self.snapshot(), before)

    def test_database_read_is_single_query_only_transaction_and_rechecks_identity(self):
        self.write()
        def validate(db):
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM calls")
            return _ledger(db)
        with patch("market_intel.ops.reconciliation._ledger", side_effect=validate):
            self.assertEqual(preview_reconciliation(self.workspace, self.statement)["status"], "matched_estimates")
        with patch("market_intel.ops.reconciliation._ledger", return_value={
                "database_schema_version": 3, "ledger_id": "ledger_" + "f" * 32}):
            with self.assertRaisesRegex(ValueError, "identity_mismatch"):
                preview_reconciliation(self.workspace, self.statement)


if __name__ == "__main__":
    unittest.main()
