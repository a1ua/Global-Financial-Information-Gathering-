from hashlib import sha256
import unittest

from market_intel.contracts.scheduled_sessions import compile_scheduled_sessions
from market_intel.pipeline.market_sample_audit import (
    audit_sse_index_sample,
    audit_szse_index_sample,
)
from test_market_sample_audit import calendar, response


def szse_calendar():
    return {
        **calendar(),
        "calendar_id": "szse.batch22.fixture",
        "exchange": "SZSE",
        "source_urls": ["https://docs.static.szse.cn/example/rules.pdf",
                        "https://www.szse.cn/example/calendar"],
    }


class SzseIndexAuditTests(unittest.TestCase):
    scope = {"start_date": "2026-10-07", "end_date": "2026-10-09"}

    def test_szse_snapshot_and_report_bind_exchange_and_hashes(self):
        source = szse_calendar()
        raw = response("20261009", "20261007", "20261009", symbol="399300.SZ")
        snapshot = compile_scheduled_sessions(source)
        self.assertEqual(snapshot["exchange"], "SZSE")
        result = audit_szse_index_sample(raw, source, symbol="399300.SZ", **self.scope)
        self.assertEqual(result, {
            "schema_version": "szse-index-sample-audit/0.1",
            "symbol": "399300.SZ",
            **self.scope,
            "calendar_id": source["calendar_id"],
            "calendar_snapshot_sha256": snapshot["snapshot_sha256"],
            "response_sha256": sha256(raw).hexdigest(),
            "audit": {
                "status": "incomplete", "expected_count": 2, "bar_count": 3,
                "missing_sessions": ["2026-10-08"],
                "unexpected_sessions": ["2026-10-07"],
                "duplicate_sessions": ["2026-10-09"],
            },
        })

    def test_equivalent_dates_do_not_allow_cross_market_calendars(self):
        sh_source, sz_source = calendar(), szse_calendar()
        sh_snapshot = compile_scheduled_sessions(sh_source)
        sz_snapshot = compile_scheduled_sessions(sz_source)
        self.assertEqual(sh_snapshot["scheduled_sessions"], sz_snapshot["scheduled_sessions"])
        self.assertNotEqual(sh_snapshot["snapshot_sha256"], sz_snapshot["snapshot_sha256"])
        with self.assertRaisesRegex(ValueError, "^sse_index_sample_scope_invalid$"):
            audit_sse_index_sample(response(), sz_source, symbol="000300.SH", **self.scope)
        with self.assertRaisesRegex(ValueError, "^szse_index_sample_scope_invalid$"):
            audit_szse_index_sample(response(), sh_source, symbol="399300.SZ", **self.scope)

    def test_szse_rejects_wrong_market_symbols_and_unofficial_sources(self):
        for symbol in ("000300.SH", "399300.sz", "399300.CSI"):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(
                    ValueError, "^szse_index_sample_scope_invalid$"):
                audit_szse_index_sample(response(), szse_calendar(), symbol=symbol, **self.scope)
        for url in ("https://www.sse.com.cn/example/calendar",
                    "https://www.szse.cn.example.com/calendar",
                    "https://docs.static.szse.cn.example.com/rules.pdf"):
            with self.subTest(url=url), self.assertRaisesRegex(
                    ValueError, "^scheduled_sessions_invalid$"):
                compile_scheduled_sessions({**szse_calendar(), "source_urls": [url]})
