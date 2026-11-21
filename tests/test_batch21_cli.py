from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from test_market_sample_audit import calendar, response


class MarketSampleAuditCLITests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.calendar = Path(folder, "calendar.json")
        self.calendar.write_text(json.dumps(calendar()), encoding="utf-8")
        self.response = Path(folder, "response.json")
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("unexpected database")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("unexpected network")))

    def invoke(self):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["sse-index-sample-audit", "--calendar", str(self.calendar),
                         "--response", str(self.response), "--symbol", "000300.SH",
                         "--start-date", "2026-10-07", "--end-date", "2026-10-09"])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_complete_and_incomplete_return_report(self):
        for days, expected_code in ((("20261008", "20261009"), 0), (("20261009",), 2), ((), 2), (("20251231",), 2)):
            with self.subTest(days=days):
                raw = response(*days)
                self.response.write_bytes(raw)
                code, stdout, stderr = self.invoke()
                self.assertEqual(code, expected_code)
                self.assertFalse(stderr)
                report = json.loads(stdout)
                self.assertEqual(report["response_sha256"], sha256(raw).hexdigest())
                if not days or days == ("20251231",):
                    self.assertEqual(report["audit"]["missing_sessions"], ["2026-10-08", "2026-10-09"])
                    self.assertEqual(report["audit"]["unexpected_sessions"], ["2025-12-31"] if days else [])
                self.assertNotIn("private-provider-message", stdout)
                self.assertEqual(self.response.read_bytes(), raw)

    def test_invalid_input_returns_fixed_error(self):
        self.response.write_bytes(b" " * 262_145)
        code, stdout, stderr = self.invoke()
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(json.loads(stderr)["reason"], "market_sample_file_too_large")
        self.calendar.write_bytes(b'{"year":2026,"year":2027}')
        code, stdout, stderr = self.invoke()
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(json.loads(stderr)["reason"], "market_sample_calendar_invalid")
