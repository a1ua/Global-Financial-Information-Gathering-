from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from market_intel.cli import main
from test_market_sample_audit import response


class ShenzhenSampleAuditCLITests(unittest.TestCase):
    def test_shenzhen_schedule_matches_only_shenzhen_command(self):
        root = Path(__file__).resolve().parents[1]
        config = root / "config" / "szse-2026-scheduled-days.example.json"
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "synthetic.json"
            payload.write_bytes(response("20261008", "20261009", symbol="399300.SZ"))
            for command, symbol, expected_code in (
                ("szse-index-sample-audit", "399300.SZ", 0),
                ("sse-index-sample-audit", "000300.SH", 1),
            ):
                with self.subTest(command=command):
                    stdout, stderr = StringIO(), StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main([command, "--calendar", str(config), "--response", str(payload),
                                     "--symbol", symbol, "--start-date", "2026-10-07",
                                     "--end-date", "2026-10-09"])
                    self.assertEqual(code, expected_code)
                    if code == 0:
                        report = json.loads(stdout.getvalue())
                        self.assertEqual(report["schema_version"], "szse-index-sample-audit/0.1")
                        self.assertEqual(report["calendar_id"], "szse-2026-scheduled-1")
                        self.assertEqual(report["audit"]["status"], "complete")
                        self.assertFalse(stderr.getvalue())
                    else:
                        self.assertFalse(stdout.getvalue())
                        self.assertEqual(json.loads(stderr.getvalue())["reason"],
                                         "sse_index_sample_scope_invalid")
