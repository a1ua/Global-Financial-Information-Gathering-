from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.pipeline.market_sample_audit import audit_sse_index_sample, audit_szse_index_sample


MARKETS = (
    ("sse", "SSE", "000300.SH", audit_sse_index_sample),
    ("szse", "SZSE", "399300.SZ", audit_szse_index_sample),
)
WINDOW = {"start_date": "2026-10-07", "end_date": "2026-10-11"}


def _calendar(exchange):
    host = {"SSE": "www.sse.com.cn", "SZSE": "www.szse.cn"}[exchange]
    return {
        "schema_version": "scheduled-session-source/0.1",
        "calendar_id": f"{exchange.lower()}.batch30.fixture",
        "exchange": exchange,
        "year": 2026,
        "closure_ranges": [{"start": "2026-10-01", "end": "2026-10-07"}],
        "source_urls": [f"https://{host}/example/calendar"],
    }


def _response(symbol, *dates):
    return json.dumps({
        "code": 0,
        "msg": "synthetic-provider-marker",
        "data": {
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close"],
            "items": [[symbol, day, 2, 3, 1, 3] for day in dates],
        },
    }).encode("utf-8")


class MarketScopeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.calendar_path = workspace / "calendar.json"
        self.response_path = workspace / "response.json"
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("database access")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("network access")))

    def _invoke(self, market, symbol, *, explain_scope=False):
        args = [
            f"{market}-index-sample-audit", "--calendar", str(self.calendar_path),
            "--response", str(self.response_path), "--symbol", symbol,
            "--start-date", WINDOW["start_date"], "--end-date", WINDOW["end_date"],
        ]
        if explain_scope:
            args.append("--explain-scope")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            exit_code = main(args)
        return exit_code, out.getvalue(), err.getvalue()

    def test_opt_in_partitions_unexpected_dates_and_preserves_legacy_report(self):
        for market, exchange, symbol, audit in MARKETS:
            with self.subTest(market=market):
                calendar = _calendar(exchange)
                raw = _response(symbol, "20270104", "20261011", "20261008", "20261010",
                                "20261007", "20261007", "20261006")
                calendar_text = json.dumps(calendar)
                self.calendar_path.write_text(calendar_text, encoding="utf-8")
                self.response_path.write_bytes(raw)

                default_code, default_out, default_err = self._invoke(market, symbol)
                code, out, err = self._invoke(market, symbol, explain_scope=True)
                self.assertEqual((default_code, default_err, code, err), (2, "", 2, ""))
                default = json.loads(default_out)
                detailed = json.loads(out)
                self.assertEqual(default, audit(raw, calendar, symbol=symbol, **WINDOW))
                self.assertEqual(detailed, audit(raw, calendar, symbol=symbol, **WINDOW, explain_scope=True))
                self.assertEqual(detailed.pop("scope_diagnostics"), {
                    "outside_requested_range": ["2026-10-06", "2027-01-04"],
                    "inside_range_not_scheduled": ["2026-10-07", "2026-10-10", "2026-10-11"],
                })
                self.assertEqual(default, detailed)
                self.assertEqual(default["audit"]["unexpected_sessions"], [
                    "2026-10-06", "2026-10-07", "2026-10-10", "2026-10-11", "2027-01-04",
                ])
                self.assertEqual(default["audit"]["duplicate_sessions"], ["2026-10-07"])
                self.assertEqual(default["audit"]["missing_sessions"], ["2026-10-09"])
                self.assertEqual(self.response_path.read_bytes(), raw)
                self.assertEqual(self.calendar_path.read_text(encoding="utf-8"), calendar_text)

    def test_complete_sample_exits_zero_with_empty_diagnostics(self):
        for market, exchange, symbol, _ in MARKETS:
            with self.subTest(market=market):
                self.calendar_path.write_text(json.dumps(_calendar(exchange)), encoding="utf-8")
                self.response_path.write_bytes(_response(symbol, "20261008", "20261009"))
                code, out, err = self._invoke(market, symbol, explain_scope=True)
                self.assertEqual((code, err), (0, ""))
                result = json.loads(out)
                self.assertEqual(result["audit"]["status"], "complete")
                self.assertEqual(result["scope_diagnostics"], {
                    "outside_requested_range": [], "inside_range_not_scheduled": [],
                })

    def test_invalid_provider_response_exits_one_without_diagnostics(self):
        for market, exchange, symbol, _ in MARKETS:
            with self.subTest(market=market):
                self.calendar_path.write_text(json.dumps(_calendar(exchange)), encoding="utf-8")
                self.response_path.write_bytes(b'{"code":2002,"msg":"synthetic-private-marker","data":null}')
                code, out, err = self._invoke(market, symbol, explain_scope=True)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(json.loads(err)["reason"], "tushare_sample_provider_error")
                self.assertNotIn("synthetic-private-marker", err)
