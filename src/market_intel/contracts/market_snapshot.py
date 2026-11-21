"""Freeze and replay exact synthetic OHLC versions against a pinned calendar."""

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import SHA256, identifier, instant, record
from .candidate_snapshot import payload_sha256
from .market_sample import validate_ohlc_bar
from .scheduled_sessions import compile_scheduled_sessions


_SCHEMA = "synthetic-market-snapshot/0.1"
_MANIFEST_FIELDS = {
    "schema_version", "instrument_id", "is_synthetic", "calendar_snapshot_sha256",
    "start_date", "end_date", "cutoff", "selected", "missing_sessions",
}
_VERSION_FIELDS = {"instrument_id", "is_synthetic", "available_at", "bar"}
_SELECTION_FIELDS = {"session_date", "bar_version_sha256"}


def _invalid():
    raise ValueError("synthetic_market_snapshot_invalid") from None


def _date(value):
    if type(value) is not str or len(value) != 10:
        _invalid()
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        _invalid()
    return day


def _scope(calendar_source, instrument_id, cutoff, start_date, end_date):
    identifier(instrument_id, "instrument_id")
    at = instant(cutoff, "cutoff")
    start, end = _date(start_date), _date(end_date)
    calendar = compile_scheduled_sessions(calendar_source)
    if start > end or start.year != calendar["year"] or end.year != calendar["year"]:
        _invalid()
    cohort = [day for day in calendar["scheduled_sessions"] if start_date <= day <= end_date]
    if not cohort:
        _invalid()
    return calendar, at, cohort


def _versions(bars, instrument_id, calendar):
    if type(bars) is not list or len(bars) > 1464:
        _invalid()
    days = set(calendar["scheduled_sessions"])
    zone = ZoneInfo(calendar["timezone"])
    for version in bars:
        record(version, _VERSION_FIELDS, "bar_version")
        if (type(version["instrument_id"]) is not str or version["instrument_id"] != instrument_id
                or version["is_synthetic"] is not True):
            _invalid()
        session = validate_ohlc_bar(version["bar"])
        available = instant(version["available_at"], "available_at")
        if session not in days or available.astimezone(zone).date() < _date(session):
            _invalid()
        yield session, available, version


def freeze_market_snapshot(calendar_source, instrument_id, bars, *, cutoff, start_date, end_date):
    """Select the latest revision visible on or before the supplied UTC cutoff."""
    try:
        calendar, at, cohort = _scope(calendar_source, instrument_id, cutoff, start_date, end_date)
        days = set(cohort)
        selected, seen = {}, set()
        for session, available, version in _versions(bars, instrument_id, calendar):
            key = session, available
            if key in seen:
                _invalid()
            seen.add(key)
            if session in days and available <= at:
                current = selected.get(session)
                if current is None or available > current[0]:
                    selected[session] = (available, version)
        manifest = {
            "schema_version": _SCHEMA,
            "instrument_id": instrument_id,
            "is_synthetic": True,
            "calendar_snapshot_sha256": calendar["snapshot_sha256"],
            "start_date": start_date,
            "end_date": end_date,
            "cutoff": cutoff,
            "selected": [
                {"session_date": day, "bar_version_sha256": payload_sha256(selected[day][1])}
                for day in cohort if day in selected
            ],
            "missing_sessions": [day for day in cohort if day not in selected],
        }
        return {**manifest, "snapshot_sha256": payload_sha256(manifest)}
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        _invalid()


def _selection(snapshot, cohort):
    selected = snapshot["selected"]
    if type(selected) is not list or len(selected) > len(cohort):
        _invalid()
    days, previous = set(cohort), ""
    by_day = {}
    for entry in selected:
        record(entry, _SELECTION_FIELDS, "selection")
        day, digest = entry["session_date"], entry["bar_version_sha256"]
        if (type(day) is not str or day not in days or day <= previous
                or type(digest) is not str or not SHA256.fullmatch(digest)):
            _invalid()
        by_day[day] = digest
        previous = day
    missing = snapshot["missing_sessions"]
    if type(missing) is not list or missing != [day for day in cohort if day not in by_day]:
        _invalid()
    return by_day


def load_market_snapshot(calendar_source, bars, snapshot):
    """Return detached copies of exactly the recorded revisions in date order."""
    try:
        record(snapshot, _MANIFEST_FIELDS | {"snapshot_sha256"}, "snapshot")
        if snapshot["schema_version"] != _SCHEMA or snapshot["is_synthetic"] is not True:
            _invalid()
        instrument_id = snapshot["instrument_id"]
        calendar, at, cohort = _scope(calendar_source, instrument_id, snapshot["cutoff"],
                                      snapshot["start_date"], snapshot["end_date"])
        if snapshot["calendar_snapshot_sha256"] != calendar["snapshot_sha256"]:
            _invalid()
        by_day = _selection(snapshot, cohort)
        digest = snapshot["snapshot_sha256"]
        if type(digest) is not str or digest != payload_sha256(
                {k: snapshot[k] for k in _MANIFEST_FIELDS}):
            _invalid()

        matched = {}
        for session, available, version in _versions(bars, instrument_id, calendar):
            expected = by_day.get(session)
            if expected is not None and available <= at and payload_sha256(version) == expected:
                matched[session] = {**version, "bar": dict(version["bar"])}
        if len(matched) != len(by_day):
            _invalid()
        return [matched[day] for day in by_day]
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        _invalid()
