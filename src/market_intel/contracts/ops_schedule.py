"""Pure, deterministic contracts for offline OPS-01 scheduling, locking, and recovery (v0.1)."""

from datetime import date, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from . import choice, fail, instant, record, text

__all__ = [
    "SCHEMA_LOCK",
    "SCHEMA_RUN_RECORD",
    "SCHEMA_RECOVERY_PLAN",
    "SCHEMA_TASK_TEMPLATE",
    "JOB_NAMES",
    "SESSION_JOBS",
    "OUTCOMES",
    "RUN_REASONS",
    "MISS_REASONS",
    "validate_timezone_strict",
    "validate_hhmm",
    "validate_calendar_date",
    "validate_ops_lock",
    "validate_ops_run_record",
    "validate_ops_recovery_plan",
]

SCHEMA_LOCK = "ops-lock/0.1"
SCHEMA_RUN_RECORD = "ops-run-record/0.1"
SCHEMA_RECOVERY_PLAN = "ops-missed-run-plan/0.1"
SCHEMA_TASK_TEMPLATE = "ops-windows-task-template/0.1"

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_HHMM_RE = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\Z")
_AVAILABLE_TIMEZONES = available_timezones()

JOB_NAMES = {"pre_market", "post_market", "collect_all", "manual_recovery"}
SESSION_JOBS = {"pre_market", "post_market"}
OUTCOMES = {"succeeded", "degraded", "skipped_locked", "failed_network", "failed_runtime"}

RUN_REASONS = {
    "normal_completion",
    "degraded_no_model",
    "degraded_no_market_data",
    "synthetic_fixture",
    "lock_held_active",
    "stale_lock_recovered",
    "network_unreachable",
    "source_partial_failure",
    "runtime_error",
    "retrospective_catchup",
}

DEGRADED_REASONS = {
    "degraded_no_model",
    "degraded_no_market_data",
    "source_partial_failure",
    "synthetic_fixture",
}

MISS_REASONS = {
    "offline_or_missed",
    "previous_network_failure",
    "previous_runtime_failure",
    "previous_lock_conflict",
}

PLAN_REASONS = {
    "read_only_plan",
    "no_auto_execution",
    "missed_runs_detected",
    "all_due_slots_completed",
    "no_due_slots_yet",
}

LOCK_FIELDS = {
    "schema_version",
    "lock_id",
    "job_name",
    "run_id",
    "workspace_sha256",
    "pid",
    "acquired_at",
    "expires_at",
    "ttl_seconds",
    "status",
    "recovered_stale_lock_id",
}

RUN_RECORD_FIELDS = {
    "schema_version",
    "run_id",
    "job_name",
    "market_session_date",
    "scheduled_for",
    "started_at",
    "finished_at",
    "outcome",
    "reason_codes",
    "report_id",
    "lock_id",
    "stale_lock_recovered",
    "is_synthetic",
}

RECOVERY_PLAN_FIELDS = {
    "schema_version",
    "evaluated_at",
    "display_timezone",
    "pre_market_local",
    "post_market_local",
    "window_start_date",
    "window_end_date",
    "scheduled_slots_checked",
    "completed_slots",
    "missed_slots",
    "pending_recovery_actions",
    "auto_execute",
    "reason_codes",
}

RECOVERY_ACTION_FIELDS = {
    "market_session_date",
    "job_name",
    "scheduled_for",
    "miss_reason",
    "last_failed_run_id",
    "recommended_command",
}


def _safe_id(value, path, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not _ID_RE.fullmatch(value):
        fail(path, "invalid_ops_id")


def _sha256(value, path):
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        fail(path, "sha256_required")


def validate_calendar_date(value, path, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        fail(path, "invalid_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        fail(path, "invalid_date")
    if parsed.isoformat() != value:
        fail(path, "invalid_date")
    return parsed


def validate_timezone_strict(value, path):
    text(value, path)
    if (
        value != value.strip()
        or any(ch.isspace() for ch in value)
        or "\\" in value
        or ".." in value
        or value.startswith("/")
        or value.endswith(("/", "."))
        or (_AVAILABLE_TIMEZONES and value not in _AVAILABLE_TIMEZONES)
    ):
        fail(path, "unknown_timezone")
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        fail(path, "unknown_timezone")


def validate_hhmm(value, path):
    if type(value) is not str:
        fail(path, "invalid_hhmm")
    match = _HHMM_RE.fullmatch(value)
    if not match:
        fail(path, "invalid_hhmm")
    return int(match.group(1)), int(match.group(2))


def validate_ops_lock(payload):
    """Validate an ops-lock/0.1 payload without I/O or mutation."""
    record(payload, LOCK_FIELDS, "ops_lock")
    if payload["schema_version"] != SCHEMA_LOCK:
        fail("ops_lock.schema_version", "unsupported_schema")
    _safe_id(payload["lock_id"], "ops_lock.lock_id")
    choice(payload["job_name"], JOB_NAMES, "ops_lock.job_name")
    _safe_id(payload["run_id"], "ops_lock.run_id")
    _sha256(payload["workspace_sha256"], "ops_lock.workspace_sha256")
    pid = payload["pid"]
    if type(pid) is not int or not 1 <= pid <= 2_147_483_647:
        fail("ops_lock.pid", "invalid_pid")
    acquired = instant(payload["acquired_at"], "ops_lock.acquired_at")
    expires = instant(payload["expires_at"], "ops_lock.expires_at")
    ttl = payload["ttl_seconds"]
    if type(ttl) is not int or not 30 <= ttl <= 86400:
        fail("ops_lock.ttl_seconds", "invalid_ttl_seconds")
    if expires <= acquired or acquired + timedelta(seconds=ttl) != expires:
        fail("ops_lock.expires_at", "ttl_expires_mismatch")
    choice(payload["status"], {"active"}, "ops_lock.status")
    recovered = payload["recovered_stale_lock_id"]
    _safe_id(recovered, "ops_lock.recovered_stale_lock_id", nullable=True)
    if recovered is not None and recovered == payload["lock_id"]:
        fail("ops_lock.recovered_stale_lock_id", "self_reference")


def validate_ops_run_record(payload):
    """Validate an immutable ops-run-record/0.1 entry without I/O or mutation."""
    record(payload, RUN_RECORD_FIELDS, "ops_run")
    if payload["schema_version"] != SCHEMA_RUN_RECORD:
        fail("ops_run.schema_version", "unsupported_schema")
    _safe_id(payload["run_id"], "ops_run.run_id")
    job = payload["job_name"]
    choice(job, JOB_NAMES, "ops_run.job_name")

    session_date = payload["market_session_date"]
    if job in SESSION_JOBS:
        validate_calendar_date(session_date, "ops_run.market_session_date", nullable=False)
    else:
        validate_calendar_date(session_date, "ops_run.market_session_date", nullable=True)

    instant(payload["scheduled_for"], "ops_run.scheduled_for", nullable=True)
    started = instant(payload["started_at"], "ops_run.started_at")
    finished = instant(payload["finished_at"], "ops_run.finished_at")
    if finished < started:
        fail("ops_run.finished_at", "finished_before_started")

    outcome = payload["outcome"]
    choice(outcome, OUTCOMES, "ops_run.outcome")

    reasons = payload["reason_codes"]
    if type(reasons) is not list or not reasons:
        fail("ops_run.reason_codes", "nonempty_list_required")
    for code in reasons:
        choice(code, RUN_REASONS, "ops_run.reason_codes")
    if len(reasons) != len(set(reasons)):
        fail("ops_run.reason_codes", "duplicate_reason")
    reason_set = set(reasons)

    _safe_id(payload["report_id"], "ops_run.report_id", nullable=True)
    _safe_id(payload["lock_id"], "ops_run.lock_id", nullable=True)
    if type(payload["stale_lock_recovered"]) is not bool:
        fail("ops_run.stale_lock_recovered", "boolean_required")
    if type(payload["is_synthetic"]) is not bool:
        fail("ops_run.is_synthetic", "boolean_required")

    if payload["stale_lock_recovered"] != ("stale_lock_recovered" in reason_set):
        fail("ops_run.stale_lock_recovered", "stale_lock_reason_mismatch")
    if payload["is_synthetic"] and "synthetic_fixture" not in reason_set and outcome in {"succeeded", "degraded"}:
        fail("ops_run.reason_codes", "synthetic_reason_required")
    if not payload["is_synthetic"] and "synthetic_fixture" in reason_set:
        fail("ops_run.reason_codes", "unexpected_synthetic_reason")

    if outcome != "succeeded" and "normal_completion" in reason_set:
        fail("ops_run.reason_codes", "normal_completion_only_for_succeeded")

    if outcome == "skipped_locked":
        if "lock_held_active" not in reason_set or payload["report_id"] is not None:
            fail("ops_run", "inconsistent_skipped_locked")
    elif outcome == "failed_network":
        if "network_unreachable" not in reason_set or payload["report_id"] is not None:
            fail("ops_run", "inconsistent_failed_network")
    elif outcome == "failed_runtime":
        if "runtime_error" not in reason_set or payload["report_id"] is not None:
            fail("ops_run", "inconsistent_failed_runtime")
    elif outcome == "succeeded":
        if reason_set & {"lock_held_active", "network_unreachable", "runtime_error", "degraded_no_model", "degraded_no_market_data", "source_partial_failure"}:
            fail("ops_run", "inconsistent_succeeded_reasons")
        if "normal_completion" not in reason_set:
            fail("ops_run.reason_codes", "normal_completion_required")
    elif outcome == "degraded":
        if not (reason_set & DEGRADED_REASONS):
            fail("ops_run.reason_codes", "degraded_reason_required")
        if reason_set & {"lock_held_active", "network_unreachable", "runtime_error"}:
            fail("ops_run", "inconsistent_degraded_reasons")


def validate_ops_recovery_plan(payload):
    """Validate an ops-missed-run-plan/0.1 payload without I/O or mutation."""
    record(payload, RECOVERY_PLAN_FIELDS, "ops_plan")
    if payload["schema_version"] != SCHEMA_RECOVERY_PLAN:
        fail("ops_plan.schema_version", "unsupported_schema")
    evaluated = instant(payload["evaluated_at"], "ops_plan.evaluated_at")
    validate_timezone_strict(payload["display_timezone"], "ops_plan.display_timezone")
    pre_hm = validate_hhmm(payload["pre_market_local"], "ops_plan.pre_market_local")
    post_hm = validate_hhmm(payload["post_market_local"], "ops_plan.post_market_local")
    if pre_hm >= post_hm:
        fail("ops_plan.post_market_local", "post_must_be_after_pre")

    start_d = validate_calendar_date(payload["window_start_date"], "ops_plan.window_start_date")
    end_d = validate_calendar_date(payload["window_end_date"], "ops_plan.window_end_date")
    if end_d < start_d:
        fail("ops_plan.window_end_date", "window_order_invalid")

    for field in ("scheduled_slots_checked", "completed_slots", "missed_slots"):
        val = payload[field]
        if type(val) is not int or val < 0:
            fail("ops_plan." + field, "nonnegative_integer_required")
    if payload["scheduled_slots_checked"] != payload["completed_slots"] + payload["missed_slots"]:
        fail("ops_plan", "slot_count_mismatch")
    if payload["auto_execute"] is not False:
        fail("ops_plan.auto_execute", "auto_execute_forbidden")

    actions = payload["pending_recovery_actions"]
    if type(actions) is not list or len(actions) != payload["missed_slots"]:
        fail("ops_plan.pending_recovery_actions", "action_count_mismatch")
    seen_slots = set()
    for action in actions:
        record(action, RECOVERY_ACTION_FIELDS, "ops_plan.action")
        ad = validate_calendar_date(action["market_session_date"], "ops_plan.action.market_session_date")
        if not (start_d <= ad <= end_d):
            fail("ops_plan.action.market_session_date", "action_outside_window")
        choice(action["job_name"], SESSION_JOBS, "ops_plan.action.job_name")
        slot_key = (action["market_session_date"], action["job_name"])
        if slot_key in seen_slots:
            fail("ops_plan.pending_recovery_actions", "duplicate_recovery_slot")
        seen_slots.add(slot_key)
        slot_ts = instant(action["scheduled_for"], "ops_plan.action.scheduled_for")
        if slot_ts > evaluated:
            fail("ops_plan.action.scheduled_for", "future_slot_in_missed_plan")
        choice(action["miss_reason"], MISS_REASONS, "ops_plan.action.miss_reason")
        _safe_id(action["last_failed_run_id"], "ops_plan.action.last_failed_run_id", nullable=True)
        if action["miss_reason"] == "offline_or_missed" and action["last_failed_run_id"] is not None:
            fail("ops_plan.action.last_failed_run_id", "unexpected_failed_run_id")
        if action["miss_reason"] != "offline_or_missed" and action["last_failed_run_id"] is None:
            fail("ops_plan.action.last_failed_run_id", "failed_run_id_required")
        text(action["recommended_command"], "ops_plan.action.recommended_command")

    reasons = payload["reason_codes"]
    if type(reasons) is not list:
        fail("ops_plan.reason_codes", "list_required")
    for code in reasons:
        choice(code, PLAN_REASONS, "ops_plan.reason_codes")
    if len(reasons) != len(set(reasons)):
        fail("ops_plan.reason_codes", "duplicate_reason")
    expected = {"read_only_plan", "no_auto_execution"}
    if payload["scheduled_slots_checked"] == 0:
        expected.add("no_due_slots_yet")
    elif payload["missed_slots"] > 0:
        expected.add("missed_runs_detected")
    else:
        expected.add("all_due_slots_completed")
    if set(reasons) != expected:
        fail("ops_plan.reason_codes", "inconsistent_plan_reasons")
