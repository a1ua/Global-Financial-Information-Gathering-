from contextlib import closing, redirect_stderr, redirect_stdout
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
from test_candidate_batch import candidates
from test_llm_cny import cny_policy, REQUEST


class Batch09CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "input.json"
        self.workspace = self.root / "mock"
        self.path.write_text(json.dumps(candidates()), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, command, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        original_get = os.environ.get
        def guarded_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                raise AssertionError("must not read key")
            return original_get(name, default)
        args = [command, "--input", str(self.path), "--cutoff", "2099-01-01T00:00:00Z", *map(str, extra)]
        if command == "candidate-mock-run":
            args += ["--workspace", str(self.workspace)]
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                "market_intel.cli.os.environ.get", side_effect=guarded_get):
            code = main(args)
        text = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(text), text

    def test_plan_is_readonly_and_does_not_print_titles(self):
        code, result, text = self.invoke("candidate-plan", "--max-candidates", 2)
        self.assertEqual((code, result["selected_ids"]), (0, ["candidate_0", "candidate_1"]))
        self.assertEqual(result["limited_count"], 1)
        self.assertNotIn("synthetic title", text)
        self.assertFalse(self.workspace.exists())

    def test_explicit_mock_run_uses_cny_bound_ledger_and_cache_without_live_key(self):
        first = self.invoke("candidate-mock-run", "--max-candidates", 2)
        second = self.invoke("candidate-mock-run", "--max-candidates", 2)
        self.assertEqual((first[0], second[0]), (0, 0))
        self.assertFalse(first[1]["live_called"])
        self.assertTrue(all(r["cache_hit"] for r in second[1]["results"]))
        self.assertTrue((self.workspace / "llm-binding.json").is_file())
        with closing(sqlite3.connect(self.workspace / "llm-state.db")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*),SUM(charged_cost) FROM calls").fetchone(), (2, 120))
            self.assertEqual(db.execute("SELECT currency FROM days").fetchone()[0], "CNY")
        self.assertNotIn("synthetic title", first[2])

    def test_zero_limit_does_not_create_workspace(self):
        code, result, _ = self.invoke("candidate-mock-run", "--max-candidates", 0)
        self.assertEqual((code, result["selected_count"]), (0, 0))
        self.assertFalse(self.workspace.exists())

    def test_invalid_tail_after_limit_is_rejected_before_ensure(self):
        batch = candidates()
        batch["candidates"][-1]["is_synthetic"] = False
        self.path.write_text(json.dumps(batch), encoding="utf-8")
        self.assertEqual(self.invoke("candidate-mock-run", "--max-candidates", 1)[0], 1)
        self.assertFalse(self.workspace.exists())

    def test_existing_unbound_or_missing_bound_ledger_is_not_silently_reset(self):
        ledger = self.workspace / "llm-state.db"
        ModelClient(ledger)
        code, result, _ = self.invoke("candidate-mock-run")
        self.assertEqual((code, result["reason"]), (1, "ledger_binding_required"))
        ensure_workspace_ledger(self.workspace, adopt_existing=True)
        ledger.unlink()
        code, result, _ = self.invoke("candidate-mock-run")
        self.assertEqual((code, result["reason"]), (1, "bound_ledger_missing"))
        self.assertFalse(ledger.exists())

    def test_policy_conflict_stops_batch_without_more_model_calls(self):
        ledger = self.workspace / "llm-state.db"
        client = ModelClient(ledger, cny_policy(daily_micro_units=20_000_000),
                             lambda *_: ModelResponse('{"category":"other"}', 10, 5))
        client.generate({"title": "synthetic policy setup"}, **REQUEST)
        ensure_workspace_ledger(self.workspace, adopt_existing=True)
        code, result, _ = self.invoke("candidate-mock-run")
        self.assertEqual((code, result["status"], result["failed_count"], result["not_attempted_count"]),
                         (1, "stopped", 1, 2))
        self.assertEqual(result["results"][0]["reason"], "daily_budget_policy_changed")
        with closing(sqlite3.connect(ledger)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 1)

    def test_bad_json_size_and_limits_fail_without_echo_or_workspace(self):
        for text in ('{"secret":"synthetic-private"', '{"schema_version":1,"schema_version":2}',
                     '{"v":NaN}', 'x' * 1_048_577):
            self.path.write_text(text, encoding="utf-8")
            code, result, output = self.invoke("candidate-mock-run")
            self.assertEqual(code, 1)
            self.assertNotIn("synthetic-private", output)
            self.assertNotIn(str(self.root), output)
            self.assertFalse(self.workspace.exists())
        self.path.write_text(json.dumps(candidates()), encoding="utf-8")
        for cap in (-1, 101):
            self.assertEqual(self.invoke("candidate-mock-run", "--max-candidates", cap)[0], 1)
            self.assertFalse(self.workspace.exists())


if __name__ == "__main__":
    unittest.main()
