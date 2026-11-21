import unittest

from market_intel.adapters.market.tushare_sample import parse_index_daily_sample
from market_intel.contracts.market_sample import audit_daily_ohlc


_SYMBOL = "399300.SZ"
_FIELDS = b'["close","ts_code","open","trade_date","low","high"]'
_ROW = b'[100.35000000,"399300.SZ",100.20,"20261009",99,101.50]'


def sample(rows, *, fields=_FIELDS):
    return b'{"code":0,"msg":null,"data":{"fields":' + fields + b',"items":[' + b','.join(rows) + b']}}'


class TushareSampleTests(unittest.TestCase):
    def parse(self, raw, symbol=_SYMBOL):
        return parse_index_daily_sample(raw, expected_symbol=symbol)

    def test_preserves_decimal_lexemes_order_and_duplicates_for_audit(self):
        second = _ROW.replace(b"20261009", b"20261007")
        bars = self.parse(sample([_ROW, second, _ROW]))
        self.assertEqual([row["session_date"] for row in bars],
                         ["2026-10-09", "2026-10-07", "2026-10-09"])
        self.assertEqual(bars[0], {
            "session_date": "2026-10-09", "open": "100.20", "high": "101.50",
            "low": "99", "close": "100.35000000",
        })
        self.assertEqual(audit_daily_ohlc(["2026-10-08", "2026-10-09"], bars), {
            "status": "incomplete", "expected_count": 2, "bar_count": 3,
            "missing_sessions": ["2026-10-08"], "unexpected_sessions": ["2026-10-07"],
            "duplicate_sessions": ["2026-10-09"],
        })

    def test_empty_success_and_payload_boundary(self):
        raw = sample([])
        limit = 256 * 1024
        padded = raw.ljust(limit, b" ")
        self.assertEqual(self.parse(raw), [])
        self.assertEqual(self.parse(padded), [])
        with self.assertRaisesRegex(ValueError, "^tushare_sample_invalid$"):
            self.parse(padded + b" ")

    def test_provider_error_hides_message_and_response(self):
        with self.assertRaisesRegex(ValueError, "^tushare_sample_provider_error$") as caught:
            self.parse(b'{"code":2002,"msg":"private-provider-text","data":null}')
        self.assertIsNone(caught.exception.__cause__)

    def test_invalid_envelope_json_and_shape(self):
        for raw in (
            b"", "text", b"\xff", b'{"code":0,"code":0,"msg":null,"data":null}',
            b'{"code":false,"msg":null,"data":null}', b'{"code":0.0,"msg":null,"data":null}',
            b'{"code":0,"msg":3,"data":null}', b'{"code":0,"msg":null,"data":null}',
            b'{"code":0,"msg":null,"data":{"fields":[],"items":[],"items":[]}}',
            sample([]) + b"{}", sample([], fields=_FIELDS.replace(b"trade_date", b"ts_code")),
            sample([b"[]"]), sample([_ROW] * 367), b"[" * 1200 + b"]" * 1200,
        ):
            with self.subTest(raw=repr(raw)[:100]), self.assertRaisesRegex(
                    ValueError, "^tushare_sample_invalid$"):
                self.parse(raw)

    def test_invalid_symbol_and_trade_date(self):
        for raw, symbol in (
            (sample([_ROW]), "399300"),
            (sample([_ROW]), "399300.sz"),
            (sample([_ROW]), "３９９３００.SZ"),
            (sample([_ROW]), "399300.SH"),
            (sample([_ROW.replace(b"20261009", b"20260229")]), _SYMBOL),
            (sample([_ROW.replace(b'"20261009"', b"20261009")]), _SYMBOL),
            (sample([_ROW.replace(b"20261009", b"2026-10-09")]), _SYMBOL),
        ):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(
                    ValueError, "^tushare_sample_invalid$"):
                self.parse(raw, symbol)
        self.assertEqual(self.parse(sample([_ROW.replace(b"20261009", b"20240229")]))[0]
                         ["session_date"], "2024-02-29")

    def test_rejects_prices_that_cannot_be_safely_normalized(self):
        for price in (b"0", b"-1", b"1e2", b'"100.20"', b"false", b"null", b"NaN",
                      b"Infinity", b"100.123456789", b"1234567890123", b"102"):
            with self.subTest(price=price), self.assertRaisesRegex(
                    ValueError, "^tushare_sample_invalid$"):
                self.parse(sample([_ROW.replace(b"100.20", price)]))


if __name__ == "__main__":
    unittest.main()
