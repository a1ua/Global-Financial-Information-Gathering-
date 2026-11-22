from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.contracts.scheduled_sessions import compile_scheduled_sessions
from market_intel.pipeline.market_sample_audit import compare_index_samples
from test_batch30_market_scope import MARKETS, WINDOW, _calendar


FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close"]


def _sample(symbol, *rows):
    return json.dumps({
        "code": 0,
        "msg": "synthetic private provider marker",
        "data": {"fields": FIELDS, "items": [[symbol, *row] for row in rows]},
    }).encode("utf-8")


class IndexSampleComparisonTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.calendar_path = directory / "calendar.json"
        self.before_path = directory / "before.json"
        self.after_path = directory / "after.json"
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("database access")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("network access")))

    def _args(self, exchange, symbol):
        return [
            "compare-index-samples", "--exchange", exchange, "--symbol", symbol,
            "--calendar", str(self.calendar_path), "--before", str(self.before_path),
            "--after", str(self.after_path), "--start-date", WINDOW["start_date"],
            "--end-date", WINDOW["end_date"],
        ]

    def _write(self, exchange, before, after):
        self.calendar_path.write_text(json.dumps(_calendar(exchange)), encoding="utf-8")
        self.before_path.write_bytes(before)
        self.after_path.write_bytes(after)

    def _invoke(self, exchange, symbol):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(self._args(exchange, symbol))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_equal_values_ignore_number_spelling_and_response_order(self):
        for _, exchange, symbol, _ in MARKETS:
            with self.subTest(exchange=exchange):
                before = _sample(symbol, ("20261008", 2, 5, 1, 4), ("20261009", 3, 6, 2, 5))
                after = _sample(symbol, ("20261009", 3.0, 6.0, 2.0, 5.0), ("20261008", 2.0, 5.0, 1.0, 4.0))
                self._write(exchange, before, after)
                code, out, err = self._invoke(exchange, symbol)
                self.assertEqual((code, err), (0, ""))
                report = json.loads(out)
                calendar = _calendar(exchange)
                self.assertEqual(report, compare_index_samples(before, after, calendar,
                                                                exchange=exchange, symbol=symbol, **WINDOW))
                self.assertEqual(report["schema_version"], "index-sample-comparison/0.1")
                self.assertEqual(report["status"], "unchanged")
                self.assertEqual(report["changed_sessions"], [])
                self.assertEqual(report["before_response_sha256"], sha256(before).hexdigest())
                self.assertEqual(report["after_response_sha256"], sha256(after).hexdigest())
                self.assertEqual(report["calendar_snapshot_sha256"],
                                 compile_scheduled_sessions(calendar)["snapshot_sha256"])
                self.assertEqual(self.before_path.read_bytes(), before)
                self.assertEqual(self.after_path.read_bytes(), after)

    def test_module_entrypoint_reports_sorted_changes_with_decimal_precision(self):
        symbol = "000300.SH"
        before = _sample(symbol, ("20261009", 2, 8, 1, 4), ("20261008", 2, 8, 1, 4))
        after = _sample(symbol, ("20261009", 3, 9, 2, 5), ("20261008", 2, 8, 1, 12345))
        before = before.replace(b", 4]", b", 123456789.12345671]").replace(b", 8,", b", 223456789,")
        after = (after.replace(b", 12345]", b", 123456789.12345672]")
                 .replace(b", 8,", b", 223456789,"))
        self._write("SSE", before, after)
        source = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "market_intel", *self._args("SSE", symbol)],
            capture_output=True, check=False, timeout=15, env={**os.environ, "PYTHONPATH": source},
        )
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        report = json.loads(proc.stdout)
        self.assertEqual(report["status"], "changed")
        self.assertEqual(report["changed_sessions"], [
            {"session_date": "2026-10-08", "fields": ["close"]},
            {"session_date": "2026-10-09", "fields": ["open", "high", "low", "close"]},
        ])

    def test_missing_and_duplicate_dates_preclude_comparison(self):
        symbol = "399300.SZ"
        before = _sample(symbol, ("20261008", 2, 5, 1, 4))
        after = _sample(symbol, ("20261008", 3, 5, 1, 4), ("20261008", 2, 5, 1, 4),
                        ("20261009", 3, 5, 1, 4))
        self._write("SZSE", before, after)
        code, out, err = self._invoke("SZSE", symbol)
        self.assertEqual((code, err), (2, ""))
        report = json.loads(out)
        self.assertEqual(report["status"], "coverage_incomplete")
        self.assertIsNone(report["changed_sessions"])
        self.assertEqual(report["before_audit"]["missing_sessions"], ["2026-10-09"])
        self.assertEqual(report["after_audit"]["duplicate_sessions"], ["2026-10-08"])

    def test_invalid_response_and_wrong_exchange_have_empty_stdout(self):
        symbol = "000300.SH"
        before = _sample(symbol, ("20261008", 2, 5, 1, 4), ("20261009", 3, 5, 1, 4))
        self._write("SSE", before, b'{"code":42,"msg":"synthetic-private-marker","data":null}')
        code, out, err = self._invoke("SSE", symbol)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["reason"], "tushare_sample_provider_error")
        self.assertNotIn("synthetic-private-marker", err)

        self._write("SZSE", before, before)
        code, out, err = self._invoke("SSE", symbol)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["reason"], "sse_index_sample_scope_invalid")
