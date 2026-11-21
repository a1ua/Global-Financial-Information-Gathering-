"""Audit normalized daily OHLC against an explicit session cohort."""

from collections import Counter
from datetime import date
from decimal import Decimal
import re


_LIMIT = 366
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PRICE = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,8})?")
_PRICES = ("open", "high", "low", "close")
_BAR_FIELDS = {"session_date", *_PRICES}


def _invalid():
    raise ValueError("market_sample_invalid") from None


def _session_date(value):
    if type(value) is not str or not _DATE.fullmatch(value):
        _invalid()
    try:
        date.fromisoformat(value)
    except ValueError:
        _invalid()
    return value


def _price(value):
    if type(value) is not str or not _PRICE.fullmatch(value):
        _invalid()
    price = Decimal(value)
    if price <= 0:
        _invalid()
    return price


def validate_ohlc_bar(bar):
    """Validate one normalized bar and return its session date."""
    if type(bar) is not dict or bar.keys() != _BAR_FIELDS:
        _invalid()
    session = _session_date(bar["session_date"])
    open_price, high, low, close = (_price(bar[field]) for field in _PRICES)
    if not (low <= open_price <= high and low <= close <= high):
        _invalid()
    return session


def audit_daily_ohlc(expected_sessions, bars):
    """Check fixed-point prices and coverage on supplied exchange-local dates."""
    if (type(expected_sessions) is not list or not 1 <= len(expected_sessions) <= _LIMIT
            or type(bars) is not list or len(bars) > _LIMIT):
        _invalid()
    sessions = [_session_date(value) for value in expected_sessions]
    if any(left >= right for left, right in zip(sessions, sessions[1:])):
        _invalid()

    observed = Counter()
    for bar in bars:
        observed[validate_ohlc_bar(bar)] += 1

    expected = set(sessions)
    missing = sorted(expected.difference(observed))
    unexpected = sorted(observed.keys() - expected)
    duplicates = sorted(session for session, count in observed.items() if count > 1)
    return {
        "status": "incomplete" if missing or unexpected or duplicates else "complete",
        "expected_count": len(sessions),
        "bar_count": len(bars),
        "missing_sessions": missing,
        "unexpected_sessions": unexpected,
        "duplicate_sessions": duplicates,
    }
