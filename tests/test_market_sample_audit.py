from hashlib import sha256
import json
import unittest

from market_intel.contracts.scheduled_sessions import compile_scheduled_sessions
from market_intel.pipeline.market_sample_audit import audit_sse_index_sample


def calendar():
    return {
        "schema_version": "scheduled-session-source/0.1",
        "calendar_id": "sse.batch21.fixture",
        "exchange": "SSE",
        "year": 2026,
        "closure_ranges": [{"start": "2026-10-01", "end": "2026-10-07"}],
        "source_urls": ["https://www.sse.com.cn/example/calendar"],
    }


def response(*days, symbol="000300.SH"):
    return json.dumps({
        "code": 0,
        "msg": "private-provider-message",
        "data": {
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close"],
            "items": [[symbol, day, 1, 3, 1, 2] for day in days],
        },
    }).encode("utf-8")


class MarketSampleAuditTests(unittest.TestCase):
    def audit(self, raw, source=None, **scope):
        selected = {
            "symbol": "000300.SH",
            "start_date": "2026-10-07",
            "end_date": "2026-10-09",
            **scope,
        }
        return audit_sse_index_sample(raw, calendar() if source is None else source, **selected)

    def test_report_binds_exact_bytes_and_calendar_without_rows_or_message(self):
        raw = response("20261008", "20261009")
        result = self.audit(raw)
        self.assertEqual(result, {
            "schema_version": "sse-index-sample-audit/0.1",
            "symbol": "000300.SH",
            "start_date": "2026-10-07",
            "end_date": "2026-10-09",
            "calendar_id": "sse.batch21.fixture",
            "calendar_snapshot_sha256": compile_scheduled_sessions(calendar())["snapshot_sha256"],
            "response_sha256": sha256(raw).hexdigest(),
            "audit": {
                "status": "complete", "expected_count": 2, "bar_count": 2,
                "missing_sessions": [], "unexpected_sessions": [], "duplicate_sessions": [],
            },
        })
        spaced = self.audit(raw + b" ")
        self.assertEqual(spaced["audit"], result["audit"])
        self.assertNotEqual(spaced["response_sha256"], result["response_sha256"])

    def test_outside_window_and_holiday_rows_are_not_discarded(self):
        result = self.audit(response("20261009", "20261009", "20261007", "20260105", "20270104"))
        self.assertEqual(result["audit"], {
            "status": "incomplete", "expected_count": 2, "bar_count": 5,
            "missing_sessions": ["2026-10-08"],
            "unexpected_sessions": ["2026-01-05", "2026-10-07", "2027-01-04"],
            "duplicate_sessions": ["2026-10-09"],
        })

    def test_invalid_scope_rejected(self):
        for scope in (
            {"symbol": "399300.SZ"},
            {"symbol": "000300.sh"},
            {"symbol": "０００３００.SH"},
            {"start_date": "20261008"},
            {"start_date": "2026-02-29"},
            {"start_date": "2026-10-10"},
            {"start_date": "2025-12-31"},
            {"start_date": "2025-12-30", "end_date": "2025-12-31"},
            {"end_date": "2026-10-07"},
        ):
            with self.subTest(scope=scope), self.assertRaisesRegex(
                    ValueError, "^sse_index_sample_scope_invalid$"):
                self.audit(response(), **scope)

    def test_delegated_validation_keeps_sanitized_errors(self):
        with self.assertRaisesRegex(ValueError, "^scheduled_sessions_invalid$"):
            self.audit(response(), source={})
        with self.assertRaisesRegex(ValueError, "^tushare_sample_invalid$"):
            self.audit(response("20261008", symbol="399300.SZ"))
        with self.assertRaisesRegex(ValueError, "^tushare_sample_provider_error$"):
            self.audit(b'{"code":2002,"msg":"private","data":null}')
