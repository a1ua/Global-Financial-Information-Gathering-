from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.llm import ModelClient, ModelResponse
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.ops.llm_backup import create_ledger_backup
from test_llm_cny import cny_policy, REQUEST


class Batch08CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "live"
        self.ledger = self.workspace / "llm-state.db"
        self.client = ModelClient(self.ledger, cny_policy(), lambda *_: ModelResponse(
            '{"category":"other"}', 20, 8), clock=lambda: datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
        self.client.generate({"title": "synthetic CLI check"}, **REQUEST)
        ensure_workspace_ledger(self.workspace, adopt_existing=True)
        with closing(sqlite3.connect(self.ledger)) as db:
            self.call_id, self.cost = db.execute("SELECT call_id,charged_cost FROM calls").fetchone()
        self.statement = self.root / "statement.json"
        self.write_statement(self.cost)

    def tearDown(self):
        self.temp.cleanup()

    def write_statement(self, amount):
        value = {"schema_version": "ledger-reconciliation-statement/0.1",
                 "ledger_id": self.client.ledger_id, "utc_day": "2026-11-09", "currency": "CNY",
                 "provider": "mock", "evidence_kind": "synthetic", "evidence_sha256": "0" * 64,
                 "records": [{"call_id": self.call_id, "charged_micro_units": amount}]}
        self.statement.write_text(json.dumps(value), encoding="utf-8")

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        original_get = os.environ.get
        def guarded_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                raise AssertionError("must not read key")
            return original_get(name, default)
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                "market_intel.cli.os.environ.get", side_effect=guarded_get):
            code = main(list(map(str, args)))
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_matched_statement_is_never_settlement_permission(self):
        before = {p.name: p.read_bytes() for p in self.workspace.iterdir()}
        for _ in range(2):
            code, result = self.invoke("ledger-reconcile-preview", "--workspace", self.workspace,
                                       "--statement", self.statement)
            self.assertEqual((code, result["status"]), (0, "matched_estimates"))
            self.assertFalse(result["settlement_allowed"])
            self.assertFalse(result["evidence_authenticated"])
        self.assertEqual({p.name: p.read_bytes() for p in self.workspace.iterdir()}, before)

    def test_difference_is_valid_result_without_budget_changes(self):
        self.write_statement(self.cost + 1)
        before = self.ledger.read_bytes()
        code, result = self.invoke("ledger-reconcile-preview", "--workspace", self.workspace,
                                   "--statement", self.statement)
        self.assertEqual((code, result["status"], result["delta_micro_units"]), (0, "differences", 1))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_identical_backup_never_grants_switch(self):
        backup = self.root / "backup"
        create_ledger_backup(self.ledger, backup)
        code, result = self.invoke("ledger-recovery-preflight", "--workspace", self.workspace,
                                   "--backup", backup)
        self.assertEqual((code, result["status"]), (0, "equivalent_observation"))
        self.assertFalse(result["switch_allowed"])
        self.assertFalse(result["trusted_high_water"])
        self.assertIn("production_switch_not_implemented", result["blockers"])

    def test_old_backup_is_not_equivalent_and_is_not_applied(self):
        backup = self.root / "backup"
        create_ledger_backup(self.ledger, backup)
        self.client.generate({"title": "second synthetic call"}, **REQUEST)
        before = self.ledger.read_bytes()
        code, result = self.invoke("ledger-recovery-preflight", "--workspace", self.workspace,
                                   "--backup", backup)
        self.assertEqual((code, result["status"], result["candidate_missing_calls"]), (0, "not_equivalent", 1))
        self.assertFalse(result["switch_allowed"])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_missing_workspace_is_not_initialized(self):
        missing = self.root / "missing"
        for command, option, path in (("ledger-reconcile-preview", "--statement", self.statement),
                                      ("ledger-recovery-preflight", "--backup", self.root / "absent")):
            code, result = self.invoke(command, "--workspace", missing, option, path)
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(missing.exists())

    def test_invalid_json_returns_safe_failure(self):
        self.statement.write_text('{"private":"synthetic-sensitive-text"', encoding="utf-8")
        code, result = self.invoke("ledger-reconcile-preview", "--workspace", self.workspace,
                                   "--statement", self.statement)
        self.assertEqual(code, 1)
        self.assertNotIn("synthetic-sensitive-text", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_no_apply_or_force_options_exist(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["ledger-reconcile-preview", "--statement", str(self.statement), "--apply"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
