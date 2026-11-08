from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.llm import ModelClient, ModelResponse
from market_intel.llm.deepseek import DeepSeekTransport
from test_deepseek import FakeOpener, FakeResponse, completion
from test_llm_cny import cny_policy, REQUEST


class Batch06CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment_get = os.environ.get

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(map(str, args)))
        text = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(text), text

    def without_key_read(self, name, default=None):
        if name == "DEEPSEEK_API_KEY":
            raise AssertionError("must not read key")
        return self.environment_get(name, default)

    def test_check_is_read_only_and_does_not_read_key(self):
        with patch("market_intel.cli.os.environ.get", side_effect=self.without_key_read):
            code, result, _ = self.invoke("deepseek-check", "--workspace", self.root / "new")
        self.assertEqual(code, 0)
        self.assertEqual(result["currency"], "CNY")
        self.assertEqual(result["daily_limit_micro_cny"], 10_000_000)
        self.assertFalse(result["live_enabled"])
        self.assertFalse(result["key_checked"])
        self.assertFalse((self.root / "new").exists())

    def test_missing_live_flag_never_reads_credentials_or_creates_ledger(self):
        with patch("market_intel.cli.os.environ.get", side_effect=self.without_key_read):
            code, result, _ = self.invoke("deepseek-smoke", "--workspace", self.root)
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "explicit_live_flag_required")
        self.assertFalse((self.root / "llm-state.db").exists())

    def test_live_missing_key_fails_before_reservation_or_network(self):
        with patch.dict(os.environ, {}, clear=True), patch("market_intel.cli.DeepSeekTransport") as transport:
            code, result, _ = self.invoke("deepseek-smoke", "--live", "--workspace", self.root)
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "deepseek_key_not_configured")
        transport.assert_not_called()
        self.assertFalse((self.root / "llm-state.db").exists())

    def test_explicit_live_with_synthetic_http_uses_cny_and_redacts_key(self):
        opener = FakeOpener(FakeResponse(completion()))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "synthetic-cli-key"}), patch(
                "market_intel.cli.DeepSeekTransport", side_effect=lambda key: DeepSeekTransport(key, opener=opener)):
            code, result, text = self.invoke("deepseek-smoke", "--live", "--workspace", self.root)
            second_code, cached, _ = self.invoke("deepseek-smoke", "--live", "--workspace", self.root)
        self.assertEqual((code, second_code), (0, 0))
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["output"], {"category": "other"})
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(len(opener.requests), 1)
        self.assertNotIn("synthetic-cli-key", text)
        self.assertNotIn(b"synthetic-cli-key", (self.root / "llm-state.db").read_bytes())
        usage = list(result["budget_by_utc_day"].values())[-1]
        self.assertEqual(usage["currency"], "CNY")
        self.assertEqual(usage["charged_micro_cny"], 104)

    def test_backup_verify_restore_cli_preserve_cny_budget(self):
        path = self.root / "source" / "llm-state.db"
        client = ModelClient(path, cny_policy(), lambda *_: ModelResponse('{"category":"other"}', 20, 8))
        client.generate({"title": "synthetic"}, **REQUEST)
        before = path.read_bytes()
        backup, restored = self.root / "backup", self.root / "restored"
        code, result, _ = self.invoke("ledger-backup", "--ledger", path, "--destination", backup)
        self.assertEqual(code, 0)
        self.assertEqual(result["database_schema_version"], 2)
        self.assertEqual(self.invoke("verify-ledger-backup", "--backup", backup)[0], 0)
        self.assertEqual(self.invoke("restore-ledger", "--backup", backup, "--destination", restored)[0], 0)
        restored_client = ModelClient(restored / "ledger.db", cny_policy())
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(restored_client.usage(day)["charged_micro_cny"], client.usage(day)["charged_micro_cny"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.invoke("restore-ledger", "--backup", backup, "--destination", restored)[0], 1)

    def test_restored_isolated_copy_cannot_be_used_by_smoke(self):
        (self.root / "ledger-backup-manifest.json").write_text("{}", encoding="utf-8")
        with patch("market_intel.cli.os.environ.get", side_effect=self.without_key_read):
            code, result, _ = self.invoke("deepseek-smoke", "--live", "--workspace", self.root)
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "isolated_ledger_not_live")


if __name__ == "__main__":
    unittest.main()
