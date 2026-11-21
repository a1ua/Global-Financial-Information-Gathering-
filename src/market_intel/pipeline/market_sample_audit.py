"""Audit one offline index sample against a bounded exchange schedule."""

from datetime import date
from hashlib import sha256
import re

from ..adapters.market.tushare_sample import parse_index_daily_sample
from ..contracts.market_sample import audit_daily_ohlc
from ..contracts.scheduled_sessions import compile_scheduled_sessions


_SYMBOLS = {
    "SSE": re.compile(r"[0-9]{6}\.SH"),
    "SZSE": re.compile(r"[0-9]{6}\.SZ"),
}


def _scope_invalid(exchange):
    raise ValueError(f"{exchange.lower()}_index_sample_scope_invalid") from None


def _scope_day(value, exchange):
    if type(value) is not str or len(value) != 10:
        _scope_invalid(exchange)
    try:
        day = date.fromisoformat(value)
    except ValueError:
        _scope_invalid(exchange)
    if day.isoformat() != value:
        _scope_invalid(exchange)
    return day


def _audit_index_sample(raw, calendar_source, *, exchange, symbol, start_date, end_date):
    if type(symbol) is not str or not _SYMBOLS[exchange].fullmatch(symbol):
        _scope_invalid(exchange)
    start = _scope_day(start_date, exchange)
    end = _scope_day(end_date, exchange)
    if start > end or start.year != end.year:
        _scope_invalid(exchange)

    calendar = compile_scheduled_sessions(calendar_source)
    if calendar["exchange"] != exchange or start.year != calendar["year"]:
        _scope_invalid(exchange)
    expected = [session for session in calendar["scheduled_sessions"]
                if start_date <= session <= end_date]
    if not expected:
        _scope_invalid(exchange)

    bars = parse_index_daily_sample(raw, expected_symbol=symbol)
    audit = audit_daily_ohlc(expected, bars)
    return {
        "schema_version": f"{exchange.lower()}-index-sample-audit/0.1",
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "calendar_id": calendar["calendar_id"],
        "calendar_snapshot_sha256": calendar["snapshot_sha256"],
        "response_sha256": sha256(raw).hexdigest(),
        "audit": audit,
    }


def audit_sse_index_sample(raw, calendar_source, *, symbol, start_date, end_date):
    """Bind a Shanghai sample audit to its response and SSE snapshot."""
    return _audit_index_sample(raw, calendar_source, exchange="SSE",
                               symbol=symbol, start_date=start_date, end_date=end_date)


def audit_szse_index_sample(raw, calendar_source, *, symbol, start_date, end_date):
    """Bind a Shenzhen sample audit to its response and SZSE snapshot."""
    return _audit_index_sample(raw, calendar_source, exchange="SZSE",
                               symbol=symbol, start_date=start_date, end_date=end_date)
