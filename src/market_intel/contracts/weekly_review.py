"""Summarize a Shanghai receipt-week of synthetic abnormal return results."""

from collections import Counter, defaultdict
from datetime import date
from fractions import Fraction
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import SHA256, identifier, instant, record
from .abnormal_return import _decimal_text


_RESULT_FIELDS = {
    "schema_version", "is_synthetic", "prediction_id", "content_sha256", "committed_at",
    "calendar_snapshot_sha256", "evaluation_protocol_sha256", "as_of", "status", "reason",
    "target_snapshot_sha256", "benchmark_snapshot_sha256", "missing_target_sessions",
    "missing_benchmark_sessions", "segments", "car",
}
_SEGMENT_RETURNS = ("target_return", "benchmark_return", "abnormal_return")
_SEGMENT_FIELDS = {"session_date", *_SEGMENT_RETURNS}
_STATUS_REASONS = {
    "calculated": (None,),
    "pending": ("window_incomplete", "window_not_closed"),
    "unavailable": ("missing_prices",),
}
_RATIO = re.compile(r"-?(?:0|[1-9][0-9]{0,23})\.[0-9]{8}")


def _invalid():
    raise ValueError("synthetic_weekly_review_invalid") from None


def _date(value):
    if type(value) is not str or len(value) != 10:
        _invalid()
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        _invalid()
    return day


def _hash(value):
    if type(value) is not str or not SHA256.fullmatch(value):
        _invalid()


def _ratio(value):
    if type(value) is not str or not _RATIO.fullmatch(value) or value == "-0.00000000":
        _invalid()


def _dates(values):
    if type(values) is not list or len(values) > 5:
        _invalid()
    previous = None
    for value in values:
        day = _date(value)
        if previous is not None and day <= previous:
            _invalid()
        previous = day


def _result(result, monday, zone):
    record(result, _RESULT_FIELDS, "evaluation")
    if result["schema_version"] != "synthetic-abnormal-return/0.1" or result["is_synthetic"] is not True:
        _invalid()
    identifier(result["prediction_id"], "prediction_id")
    for field in ("content_sha256", "calendar_snapshot_sha256", "evaluation_protocol_sha256"):
        _hash(result[field])
    committed = instant(result["committed_at"], "committed_at")
    if (instant(result["as_of"], "as_of") < committed
            or not 0 <= (committed.astimezone(zone).date() - monday).days < 7):
        _invalid()

    status, reason = result["status"], result["reason"]
    if type(status) is not str or status not in _STATUS_REASONS or reason not in _STATUS_REASONS[status]:
        _invalid()
    target, benchmark = result["target_snapshot_sha256"], result["benchmark_snapshot_sha256"]
    missing_target, missing_benchmark = result["missing_target_sessions"], result["missing_benchmark_sessions"]
    for dates in (missing_target, missing_benchmark):
        _dates(dates)

    segments, car = result["segments"], result["car"]
    if type(segments) is not list or len(segments) > 5:
        _invalid()
    if status == "pending":
        if target is not None or benchmark is not None or missing_target or missing_benchmark:
            _invalid()
    else:
        _hash(target)
        _hash(benchmark)
    if status != "calculated":
        if segments or car is not None or (status == "unavailable" and not (missing_target or missing_benchmark)):
            _invalid()
        return status, None

    if missing_target or missing_benchmark or not segments:
        _invalid()
    days = []
    for segment in segments:
        record(segment, _SEGMENT_FIELDS, "segment")
        days.append(segment["session_date"])
        for field in _SEGMENT_RETURNS:
            _ratio(segment[field])
    _dates(days)
    _ratio(car)
    return status, Fraction(car)


def _counts(counter):
    counts = {status: counter[status] for status in _STATUS_REASONS}
    return {"total": sum(counts.values()), **counts}


def summarize_synthetic_week(results, *, week_monday):
    """Count one result per prediction and average published CAR within each protocol."""
    try:
        monday = _date(week_monday)
        if monday.weekday() != 0 or type(results) is not list or len(results) > 1000:
            _invalid()
        zone = ZoneInfo("Asia/Shanghai")
        seen = set()
        totals = Counter()
        by_protocol = defaultdict(Counter)
        car_totals = defaultdict(Fraction)
        for result in results:
            status, car = _result(result, monday, zone)
            identity, protocol = result["prediction_id"], result["evaluation_protocol_sha256"]
            if identity in seen:
                _invalid()
            seen.add(identity)
            totals[status] += 1
            by_protocol[protocol][status] += 1
            if car is not None:
                car_totals[protocol] += car

        return {
            "schema_version": "synthetic-weekly-review/0.1",
            "is_synthetic": True,
            "week_monday": week_monday,
            "counts": _counts(totals),
            "protocols": [
                {"evaluation_protocol_sha256": protocol, "counts": _counts(counts),
                 "mean_car": _decimal_text(car_totals[protocol] / counts["calculated"])
                 if counts["calculated"] else None}
                for protocol, counts in sorted(by_protocol.items())
            ],
        }
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        _invalid()
