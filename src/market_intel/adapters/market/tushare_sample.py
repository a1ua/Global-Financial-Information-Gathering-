"""Normalize bounded, offline Tushare index_daily response samples."""

import json
import re

from ...contracts.market_sample import validate_ohlc_bar


_MAX_BYTES = 256 * 1024
_MAX_ROWS = 366
_SYMBOL = re.compile(r"[0-9]{6}\.(?:SH|SZ|CSI)")
_DATE = re.compile(r"[0-9]{8}")
_PRICES = ("open", "high", "low", "close")
_FIELDS = {"ts_code", "trade_date", *_PRICES}


class _NumberToken(str):
    """Retain a JSON number's spelling and distinguish it from a JSON string."""


class _IntegerToken(_NumberToken):
    """Distinguish integral tokens for the provider's status code."""


def _invalid():
    raise ValueError("tushare_sample_invalid") from None


def _reject_nonfinite(_token):
    _invalid()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _invalid()
        value[key] = item
    return value


def _normalize_rows(data, expected_symbol):
    if type(data) is not dict or data.keys() != {"fields", "items"}:
        _invalid()
    fields, items = data["fields"], data["items"]
    if (type(fields) is not list or len(fields) != len(_FIELDS)
            or any(type(field) is not str for field in fields)
            or set(fields) != _FIELDS
            or type(items) is not list or len(items) > _MAX_ROWS):
        _invalid()
    bars = []
    for row in items:
        if type(row) is not list or len(row) != len(fields):
            _invalid()
        values = dict(zip(fields, row))
        symbol, day = values["ts_code"], values["trade_date"]
        if (type(symbol) is not str or symbol != expected_symbol
                or type(day) is not str or not _DATE.fullmatch(day)):
            _invalid()
        bar = {"session_date": f"{day[:4]}-{day[4:6]}-{day[6:]}"}
        for field in _PRICES:
            number = values[field]
            if not isinstance(number, _NumberToken):
                _invalid()
            bar[field] = str(number)
        validate_ohlc_bar(bar)
        bars.append(bar)
    return bars


def parse_index_daily_sample(raw, *, expected_symbol):
    """Return normalized OHLC rows for one symbol, preserving response order."""
    if (type(raw) is not bytes or not 1 <= len(raw) <= _MAX_BYTES
            or type(expected_symbol) is not str or not _SYMBOL.fullmatch(expected_symbol)):
        _invalid()
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_float=_NumberToken,
            parse_int=_IntegerToken,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, RecursionError):
        _invalid()
    if (type(payload) is not dict or payload.keys() != {"code", "msg", "data"}
            or type(payload["code"]) is not _IntegerToken
            or (payload["msg"] is not None and type(payload["msg"]) is not str)):
        _invalid()
    if payload["code"] not in {"0", "-0"}:
        raise ValueError("tushare_sample_provider_error") from None
    try:
        return _normalize_rows(payload["data"], expected_symbol)
    except ValueError:
        _invalid()
