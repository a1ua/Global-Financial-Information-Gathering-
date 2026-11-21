"""Calculate synthetic abnormal returns over pinned evaluation sessions."""

from fractions import Fraction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import instant, record
from .evaluation_window import plan_synthetic_evaluation_window
from .market_snapshot import load_market_snapshot


def _invalid():
    raise ValueError("synthetic_abnormal_return_invalid") from None


def _session_closes(sessions):
    zone = ZoneInfo("Asia/Shanghai")
    closes = {}
    for session in sessions:
        opens = instant(session["opens_at"], "opens_at")
        close = instant(session["closes_at"], "closes_at")
        day = opens.astimezone(zone).date().isoformat()
        if close.astimezone(zone).date().isoformat() != day or day in closes:
            _invalid()
        closes[day] = close
    return closes


def _load_leg(calendar_source, leg, instrument_id, closes, cutoff):
    record(leg, {"snapshot", "bars"}, "price_leg")
    snapshot = leg["snapshot"]
    versions = load_market_snapshot(calendar_source, leg["bars"], snapshot)
    days = list(closes)
    if (snapshot["instrument_id"] != instrument_id
            or instant(snapshot["cutoff"], "cutoff") != cutoff
            or snapshot["start_date"] != days[0] or snapshot["end_date"] != days[-1]):
        _invalid()
    prices = {version["bar"]["session_date"]: version for version in versions}
    missing = snapshot["missing_sessions"]
    if prices.keys() | set(missing) != closes.keys():
        _invalid()
    for day, version in prices.items():
        if instant(version["available_at"], "available_at") < closes[day]:
            _invalid()
    return prices, list(missing), snapshot["snapshot_sha256"]


def _returns(prices):
    previous_close = None
    for version in prices.values():
        bar = version["bar"]
        close = Fraction(bar["close"])
        base = Fraction(bar["open"]) if previous_close is None else previous_close
        yield close / base - 1
        previous_close = close


def _decimal_text(value):
    scale = 10**8
    scaled = round(value * scale)
    whole, fractional = divmod(abs(scaled), scale)
    sign = "-" if scaled < 0 else ""
    return f"{sign}{whole}.{fractional:08d}"


def calculate_synthetic_abnormal_return(value, receipt, calendar_source, target, benchmark, *, as_of):
    """Measure the complete, closed synthetic window without selecting new quotes."""
    try:
        window = plan_synthetic_evaluation_window(value, receipt)
        cutoff = instant(as_of, "as_of")
        content = value["content"]
        target_id, benchmark_id = content["target_instrument_id"], content["benchmark_instrument_id"]
        if (content["direction_basis"] != "benchmark_relative" or target_id == benchmark_id
                or cutoff < instant(window["committed_at"], "committed_at")):
            _invalid()

        result = {
            "schema_version": "synthetic-abnormal-return/0.1",
            "is_synthetic": True,
            "prediction_id": window["prediction_id"],
            "content_sha256": window["content_sha256"],
            "committed_at": window["committed_at"],
            "calendar_snapshot_sha256": window["calendar_snapshot_sha256"],
            "evaluation_protocol_sha256": window["evaluation_protocol_sha256"],
            "as_of": as_of,
            "status": "pending",
            "reason": "window_incomplete",
            "target_snapshot_sha256": None,
            "benchmark_snapshot_sha256": None,
            "missing_target_sessions": [],
            "missing_benchmark_sessions": [],
            "segments": [],
            "car": None,
        }
        if window["status"] == "pending":
            return result
        sessions = window["sessions"]
        if instant(sessions[-1]["closes_at"], "closes_at") > cutoff:
            result["reason"] = "window_not_closed"
            return result

        closes = _session_closes(sessions)
        targets, missing_target, target_hash = _load_leg(calendar_source, target, target_id, closes, cutoff)
        benchmarks, missing_benchmark, benchmark_hash = _load_leg(
            calendar_source, benchmark, benchmark_id, closes, cutoff)
        result.update(target_snapshot_sha256=target_hash, benchmark_snapshot_sha256=benchmark_hash,
                      missing_target_sessions=missing_target, missing_benchmark_sessions=missing_benchmark)
        if missing_target or missing_benchmark:
            result.update(status="unavailable", reason="missing_prices")
            return result

        car = Fraction(0)
        for day, target_return, benchmark_return in zip(closes, _returns(targets), _returns(benchmarks)):
            abnormal = target_return - benchmark_return
            car += abnormal
            result["segments"].append({
                "session_date": day,
                "target_return": _decimal_text(target_return),
                "benchmark_return": _decimal_text(benchmark_return),
                "abnormal_return": _decimal_text(abnormal),
            })
        result.update(status="calculated", reason=None, car=_decimal_text(car))
        return result
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        _invalid()
