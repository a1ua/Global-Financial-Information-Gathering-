from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
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
from market_intel.ops import reconciliation
from test_llm_cny import cny_policy, REQUEST


class Batch08CIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "live"
        self.ledger = self.workspace / "llm-state.db"
        self.client = ModelClient(self.ledger, cny_policy(), lambda *_: ModelResponse(
            '{"category":"other"}', 20, 8), clock=lambda: datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
        self.client.generate({"title": "synthetic audit"}, **REQUEST)
        ensure_workspace_ledger(self.workspace, adopt_existing=True)
        with closing(sqlite3.connect(self.ledger)) as db:
            call_id, cost = db.execute("SELECT call_id,charged_cost FROM calls").fetchone()
        self.value = {"schema_version": "ledger-reconciliation-statement/0.1",
                      "ledger_id": self.client.ledger_id, "utc_day": "2026-11-09", "currency": "CNY",
                      "provider": "mock", "evidence_kind": "synthetic", "evidence_sha256": "0" * 64,
                      "records": [{"call_id": call_id, "charged_micro_units": cost}]}
        self.statement = self.root / "statement.json"
        self.statement.write_text(json.dumps(self.value), encoding="utf-8")
        self.journal = self.root / "audit" / "journal.db"

    def tearDown(self):
        self.temp.cleanup()

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

    def record(self, journal=None):
        return self.invoke("ledger-audit-record", "--workspace", self.workspace,
                           "--statement", self.statement, "--journal", journal or self.journal)

    def test_explicit_record_idempotence_and_readonly_verify_leave_ledger_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.workspace.iterdir()}
        code, first = self.record()
        code2, second = self.record()
        self.assertEqual((code, code2, first["status"], second["status"]), (0, 0, "recorded", "already_recorded"))
        self.assertEqual(first["event_id"], second["event_id"])
        code, verified = self.invoke("verify-ledger-audit", "--journal", self.journal)
        self.assertEqual((code, verified["events"]), (0, 1))
        for result in (first, second, verified):
            self.assertFalse(result["trusted_high_water"])
            self.assertFalse(result["settlement_allowed"])
            self.assertFalse(result["switch_allowed"])
        self.assertEqual({p.name: p.read_bytes() for p in self.workspace.iterdir()}, before)

    def test_statement_is_read_once_and_canonical_hash_uses_the_same_value(self):
        original = reconciliation._statement
        def read_then_change(path):
            value = original(path)
            self.statement.write_text('{"changed":"after parse"}', encoding="utf-8")
            return value
        with patch.object(reconciliation, "_statement", side_effect=read_then_change) as read:
            code, _ = self.record()
        self.assertEqual(code, 0)
        self.assertEqual(read.call_count, 1)
        with closing(sqlite3.connect(self.journal)) as db:
            observation = json.loads(db.execute("SELECT payload FROM audit_events").fetchone()[0])
        canonical = json.dumps(self.value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(observation["statement_sha256"], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(observation["evidence_sha256"], self.value["evidence_sha256"])
        self.assertEqual(observation["preview"]["status"], "matched_estimates")

    def test_readonly_preview_does_not_create_journal(self):
        code, _ = self.invoke("ledger-reconcile-preview", "--workspace", self.workspace, "--statement", self.statement)
        self.assertEqual(code, 0)
        self.assertFalse(self.journal.parent.exists())

    def test_invalid_statement_or_missing_workspace_never_creates_journal(self):
        self.statement.write_text("{}", encoding="utf-8")
        self.assertEqual(self.record()[0], 1)
        self.assertFalse(self.journal.parent.exists())
        code, _ = self.invoke("verify-ledger-audit", "--journal", self.journal)
        self.assertEqual(code, 1)
        self.assertFalse(self.journal.parent.exists())

    def test_conflicting_roles_are_rejected_without_touching_inputs(self):
        before = self.statement.read_bytes()
        for path in (self.statement, self.ledger, self.workspace / "audit.db"):
            code, result = self.record(path)
            self.assertEqual((code, result["reason"]), (1, "ledger_audit_path_conflict"))
        self.assertEqual(self.statement.read_bytes(), before)
        self.assertFalse((self.workspace / "audit.db").exists())

    def test_changed_observation_appends_even_with_same_statement(self):
        self.assertEqual(self.record()[0], 0)
        self.client.generate({"title": "another synthetic call"}, **REQUEST)
        code, result = self.record()
        self.assertEqual((code, result["status"], result["events"]), (0, "recorded", 2))
        with closing(sqlite3.connect(self.journal)) as db:
            payload = json.loads(db.execute("SELECT payload FROM audit_events WHERE seq=2").fetchone()[0])
        self.assertEqual(payload["preview"]["status"], "incomplete")
        self.assertFalse(payload["preview"]["settlement_allowed"])


if __name__ == "__main__":
    unittest.main()
