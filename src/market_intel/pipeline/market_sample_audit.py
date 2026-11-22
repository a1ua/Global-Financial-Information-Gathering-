"""Audit one offline index sample against a bounded exchange schedule."""

from datetime import date
from decimal import Decimal
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


def _scheduled_scope(calendar_source, *, exchange, symbol, start_date, end_date):
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
    return calendar, expected


def _audit_index_sample(raw, calendar_source, *, exchange, symbol, start_date, end_date, explain_scope):
    calendar, expected = _scheduled_scope(calendar_source, exchange=exchange, symbol=symbol,
                                          start_date=start_date, end_date=end_date)
    bars = parse_index_daily_sample(raw, expected_symbol=symbol)
    audit = audit_daily_ohlc(expected, bars)
    result = {
        "schema_version": f"{exchange.lower()}-index-sample-audit/0.1",
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "calendar_id": calendar["calendar_id"],
        "calendar_snapshot_sha256": calendar["snapshot_sha256"],
        "response_sha256": sha256(raw).hexdigest(),
        "audit": audit,
    }
    if explain_scope:
        diagnostics = {"outside_requested_range": [], "inside_range_not_scheduled": []}
        for day in audit["unexpected_sessions"]:
            category = "inside_range_not_scheduled" if start_date <= day <= end_date else "outside_requested_range"
            diagnostics[category].append(day)
        result["scope_diagnostics"] = diagnostics
    return result


def audit_sse_index_sample(raw, calendar_source, *, symbol, start_date, end_date, explain_scope=False):
    """Bind a Shanghai sample audit to its response and SSE snapshot."""
    return _audit_index_sample(raw, calendar_source, exchange="SSE",
                               symbol=symbol, start_date=start_date, end_date=end_date, explain_scope=explain_scope)


def audit_szse_index_sample(raw, calendar_source, *, symbol, start_date, end_date, explain_scope=False):
    """Bind a Shenzhen sample audit to its response and SZSE snapshot."""
    return _audit_index_sample(raw, calendar_source, exchange="SZSE",
                               symbol=symbol, start_date=start_date, end_date=end_date, explain_scope=explain_scope)


def compare_index_samples(before, after, calendar_source, *, exchange, symbol, start_date, end_date):
    """Compare numeric OHLC fields only when both samples cover the same schedule."""
    if type(exchange) is not str or exchange not in _SYMBOLS:
        raise ValueError("index_sample_comparison_exchange_invalid")
    calendar, expected = _scheduled_scope(calendar_source, exchange=exchange, symbol=symbol,
                                          start_date=start_date, end_date=end_date)
    before_bars = parse_index_daily_sample(before, expected_symbol=symbol)
    after_bars = parse_index_daily_sample(after, expected_symbol=symbol)
    before_audit = audit_daily_ohlc(expected, before_bars)
    after_audit = audit_daily_ohlc(expected, after_bars)
    changes = None
    status = "coverage_incomplete"
    if before_audit["status"] == after_audit["status"] == "complete":
        changes = []
        before_by_day = {bar["session_date"]: bar for bar in before_bars}
        after_by_day = {bar["session_date"]: bar for bar in after_bars}
        for day in expected:
            old, new = before_by_day[day], after_by_day[day]
            fields = [field for field in ("open", "high", "low", "close")
                      if Decimal(old[field]) != Decimal(new[field])]
            if fields:
                changes.append({"session_date": day, "fields": fields})
        status = "changed" if changes else "unchanged"

    return {
        "schema_version": "index-sample-comparison/0.1",
        "status": status,
        "exchange": exchange,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "calendar_id": calendar["calendar_id"],
        "calendar_snapshot_sha256": calendar["snapshot_sha256"],
        "before_response_sha256": sha256(before).hexdigest(),
        "after_response_sha256": sha256(after).hexdigest(),
        "before_audit": before_audit,
        "after_audit": after_audit,
        "changed_sessions": changes,
    }
