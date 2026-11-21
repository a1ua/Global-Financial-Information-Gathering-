"""Compile scheduled trading dates from fixed SSE or SZSE source data."""

from datetime import date, timedelta

from . import choice, http_url, identifier, record
from .candidate_snapshot import payload_sha256


_SOURCE_FIELDS = {"schema_version", "calendar_id", "exchange", "year",
                  "closure_ranges", "source_urls"}
_OFFICIAL_PREFIXES = {
    "SSE": ("https://www.sse.com.cn/",),
    "SZSE": ("https://www.szse.cn/", "https://docs.static.szse.cn/"),
}


def _invalid():
    raise ValueError("scheduled_sessions_invalid") from None


def _day(value, year):
    if type(value) is not str or len(value) != 10:
        _invalid()
    day = date.fromisoformat(value)
    if day.year != year or day.isoformat() != value:
        _invalid()
    return day


def _closures(ranges, year):
    if type(ranges) is not list or len(ranges) > 32:
        _invalid()
    closed = set()
    previous_end = None
    for item in ranges:
        record(item, {"start", "end"}, "closure_range")
        start, end = _day(item["start"], year), _day(item["end"], year)
        if end < start or (previous_end is not None and start <= previous_end):
            _invalid()
        closed.update(start + timedelta(days=i) for i in range((end - start).days + 1))
        previous_end = end
    return closed


def _validate_sources(urls, exchange):
    if type(urls) is not list or not 1 <= len(urls) <= 8:
        _invalid()
    for url in urls:
        if type(url) is not str or len(url) > 512 or not url.startswith(_OFFICIAL_PREFIXES[exchange]):
            _invalid()
        http_url(url, "source_url")
    if urls != sorted(set(urls)):
        _invalid()


def compile_scheduled_sessions(value):
    """Return the versioned scheduled dates and hashes for supplied exchange evidence."""
    try:
        record(value, _SOURCE_FIELDS, "calendar")
        choice(value["schema_version"], {"scheduled-session-source/0.1"}, "schema_version")
        exchange = value["exchange"]
        choice(exchange, _OFFICIAL_PREFIXES, "exchange")
        identifier(value["calendar_id"], "calendar_id")
        year = value["year"]
        if type(year) is not int or not 1900 <= year <= 9998:
            _invalid()
        closed = _closures(value["closure_ranges"], year)
        _validate_sources(value["source_urls"], exchange)
    except ValueError:
        _invalid()

    first = date(year, 1, 1)
    days = (date(year + 1, 1, 1) - first).days
    dates = (first + timedelta(days=i) for i in range(days))
    sessions = [day.isoformat() for day in dates if day.weekday() < 5 and day not in closed]
    if not sessions:
        _invalid()
    snapshot = {
        "schema_version": "scheduled-session-snapshot/0.1",
        "calendar_id": value["calendar_id"],
        "exchange": exchange,
        "timezone": "Asia/Shanghai",
        "year": year,
        "source_sha256": payload_sha256(value),
        "scheduled_sessions": sessions,
    }
    return {**snapshot, "snapshot_sha256": payload_sha256(snapshot)}
