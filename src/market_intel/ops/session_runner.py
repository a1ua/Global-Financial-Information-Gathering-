"""Guarded offline runner combining OPS-01 single-instance locking & run journaling
with RPT-02 dual-template session brief rendering and read-only verification.

No network access, no live model calls, no live market data, and no OS task installation.
"""

from datetime import datetime, timezone
import re
import sqlite3
from uuid import uuid4

from ..contracts import ContractError, instant
from ..contracts.ops_schedule import (
    SESSION_JOBS,
    validate_calendar_date,
    validate_ops_run_record,
    validate_timezone_strict,
)
from ..llm.client import ModelError, _strict_loads
from ..report.session_brief import render_session_brief, verify_session_brief
from ..store import connect
from .scheduler import (
    _format_utc,
    _load_run_journal,
    _parse_now,
    _safe_child_no_symlink,
    _safe_workspace,
    acquire_run_lock,
    record_ops_run,
    release_run_lock,
)

__all__ = ["SCHEMA_GUARDED_RESULT", "run_guarded_session_brief"]

SCHEMA_GUARDED_RESULT = "ops-guarded-run-result/0.1"
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _finish_iso(started_dt, explicit_now):
    if explicit_now is not None:
        return _format_utc(started_dt)
    now_dt = datetime.now(timezone.utc)
    return _format_utc(now_dt if now_dt >= started_dt else started_dt)


def run_guarded_session_brief(
    workspace,
    *,
    report_type,
    market_session_date,
    cutoff,
    run_id=None,
    report_id=None,
    scheduled_for=None,
    display_timezone="Asia/Shanghai",
    supersedes_report_id=None,
    default_synthetic=False,
    retrospective_catchup=False,
    ttl_seconds=900,
    now_utc=None,
    pid=None,
    lock_id=None,
    recover_expired=True,
):
    """Execute one lock-guarded offline session brief render + read-only verify + journal append.

    Behavior:
    - Validates all inputs, workspace path safety, database presence, and existing run journal
      BEFORE acquiring any lock or mutating any files.
    - Active lock held (or expired lock with recover_expired=False): never renders or overwrites;
      appends a validated `skipped_locked` record to ops/runs.jsonl and returns status='skipped_locked'.
    - Corrupt lock file: fails closed without modifying lock or journal (status='blocked_corrupt_lock').
    - Acquired lock (including forensic stale-lock archival): renders dual-template session brief,
      immediately runs read-only verify_session_brief, records `degraded` (or `failed_runtime` on
      render/verify error), and ALWAYS releases the acquired lock in `finally`.
    """
    if report_type not in SESSION_JOBS:
        raise ValueError("invalid_report_type")
    validate_calendar_date(market_session_date, "ops_guarded.market_session_date")
    instant(cutoff, "ops_guarded.cutoff")
    validate_timezone_strict(display_timezone, "ops_guarded.display_timezone")
    if scheduled_for is not None:
        instant(scheduled_for, "ops_guarded.scheduled_for")
    if type(default_synthetic) is not bool:
        raise ValueError("invalid_default_synthetic")
    if type(retrospective_catchup) is not bool:
        raise ValueError("invalid_retrospective_catchup")
    if type(recover_expired) is not bool:
        raise ValueError("invalid_recover_expired")
    if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 86400:
        raise ValueError("invalid_ttl_seconds")
    if pid is not None and (type(pid) is not int or not 1 <= pid <= 2_147_483_647):
        raise ValueError("invalid_pid")
    if lock_id is not None and (type(lock_id) is not str or not _ID_RE.fullmatch(lock_id)):
        raise ValueError("invalid_lock_id")

    effective_run_id = f"run_{uuid4().hex[:16]}" if run_id is None else run_id
    if type(effective_run_id) is not str or not _ID_RE.fullmatch(effective_run_id):
        raise ValueError("invalid_run_id")

    if report_id is None:
        compact_date = market_session_date.replace("-", "")
        prefix = "pre" if report_type == "pre_market" else "post"
        effective_report_id = f"{prefix}_{compact_date}_{effective_run_id}"
    else:
        effective_report_id = report_id
    if type(effective_report_id) is not str or not _ID_RE.fullmatch(effective_report_id):
        raise ValueError("invalid_report_id")

    if supersedes_report_id is not None:
        if type(supersedes_report_id) is not str or not _ID_RE.fullmatch(supersedes_report_id):
            raise ValueError("invalid_supersedes_report_id")
        if supersedes_report_id == effective_report_id:
            raise ValueError("supplement_self_reference")

    ws = _safe_workspace(workspace)
    started_dt = _parse_now(now_utc)
    started_iso = _format_utc(started_dt)

    db_path = _safe_child_no_symlink(ws, "market.db")
    if not db_path.is_file():
        raise ValueError("workspace_database_missing")

    # Pre-flight journal integrity and run_id uniqueness before touching any lock or report.
    _, existing_runs = _load_run_journal(ws)
    if effective_run_id in existing_runs:
        raise ValueError("ops_run_id_conflict")

    lock_res = acquire_run_lock(
        ws,
        job_name=report_type,
        run_id=effective_run_id,
        ttl_seconds=ttl_seconds,
        now_utc=started_iso,
        pid=pid,
        lock_id=lock_id,
        recover_expired=recover_expired,
    )

    if lock_res["status"] == "blocked_corrupt_lock":
        return {
            "schema_version": SCHEMA_GUARDED_RESULT,
            "status": "blocked_corrupt_lock",
            "reason_code": lock_res["reason_code"],
            "run_id": effective_run_id,
            "report_id": None,
            "report_type": report_type,
            "market_session_date": market_session_date,
            "verified": False,
            "recorded_run": False,
            "stale_lock_recovered": False,
            "recovered_stale_lock_id": None,
            "archived_stale_lock": None,
            "lock_released": False,
            "run_record": None,
        }

    if not lock_res["acquired"]:
        skip_record = {
            "schema_version": "ops-run-record/0.1",
            "run_id": effective_run_id,
            "job_name": report_type,
            "market_session_date": market_session_date,
            "scheduled_for": scheduled_for,
            "started_at": started_iso,
            "finished_at": _finish_iso(started_dt, now_utc),
            "outcome": "skipped_locked",
            "reason_codes": ["lock_held_active"],
            "report_id": None,
            "lock_id": None,
            "stale_lock_recovered": False,
            "is_synthetic": False,
        }
        validate_ops_run_record(skip_record)
        record_ops_run(ws, skip_record)
        return {
            "schema_version": SCHEMA_GUARDED_RESULT,
            "status": "skipped_locked",
            "lock_status": lock_res["status"],
            "reason_code": lock_res["reason_code"],
            "run_id": effective_run_id,
            "report_id": None,
            "report_type": report_type,
            "market_session_date": market_session_date,
            "verified": False,
            "recorded_run": True,
            "stale_lock_recovered": False,
            "recovered_stale_lock_id": None,
            "archived_stale_lock": None,
            "lock_released": False,
            "blocking_lock": lock_res.get("active_lock") or lock_res.get("expired_lock"),
            "run_record": skip_record,
        }

    held_lock_id = lock_res["lock"]["lock_id"]
    stale_recovered = lock_res["stale_lock_recovered"]
    recovered_stale_id = lock_res["recovered_stale_lock_id"]
    archived_stale = lock_res["archived_stale_lock"]

    result = None
    try:
        try:
            db = connect(db_path)
            try:
                published_dir = render_session_brief(
                    db,
                    ws,
                    cutoff=cutoff,
                    report_id=effective_report_id,
                    report_type=report_type,
                    market_session_date=market_session_date,
                    run_id=effective_run_id,
                    display_timezone=display_timezone,
                    supersedes_report_id=supersedes_report_id,
                    default_synthetic=default_synthetic,
                )
            finally:
                db.close()

            ro_db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                verify_res = verify_session_brief(ro_db, ws, effective_report_id)
            finally:
                ro_db.close()

            manifest_path = _safe_child_no_symlink(ws, "reports", effective_report_id, "manifest.json")
            manifest = _strict_loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError, sqlite3.Error, ContractError, ModelError) as exc:
            fail_reasons = ["runtime_error"]
            if stale_recovered:
                fail_reasons.append("stale_lock_recovered")
            fail_record = {
                "schema_version": "ops-run-record/0.1",
                "run_id": effective_run_id,
                "job_name": report_type,
                "market_session_date": market_session_date,
                "scheduled_for": scheduled_for,
                "started_at": started_iso,
                "finished_at": _finish_iso(started_dt, now_utc),
                "outcome": "failed_runtime",
                "reason_codes": fail_reasons,
                "report_id": None,
                "lock_id": held_lock_id,
                "stale_lock_recovered": stale_recovered,
                "is_synthetic": False,
            }
            validate_ops_run_record(fail_record)
            record_ops_run(ws, fail_record)
            result = {
                "schema_version": SCHEMA_GUARDED_RESULT,
                "status": "failed_runtime",
                "error_type": type(exc).__name__,
                "reason": str(exc),
                "run_id": effective_run_id,
                "report_id": None,
                "report_type": report_type,
                "market_session_date": market_session_date,
                "verified": False,
                "recorded_run": True,
                "lock_id": held_lock_id,
                "stale_lock_recovered": stale_recovered,
                "recovered_stale_lock_id": recovered_stale_id,
                "archived_stale_lock": archived_stale,
                "lock_released": False,
                "run_record": fail_record,
            }
        else:
            is_synthetic = bool(manifest["is_synthetic"])
            degraded_reasons = ["degraded_no_model", "degraded_no_market_data"]
            if is_synthetic:
                degraded_reasons.append("synthetic_fixture")
            if stale_recovered:
                degraded_reasons.append("stale_lock_recovered")
            if retrospective_catchup:
                degraded_reasons.append("retrospective_catchup")
            run_record = {
                "schema_version": "ops-run-record/0.1",
                "run_id": effective_run_id,
                "job_name": report_type,
                "market_session_date": market_session_date,
                "scheduled_for": scheduled_for,
                "started_at": started_iso,
                "finished_at": _finish_iso(started_dt, now_utc),
                "outcome": "degraded",
                "reason_codes": degraded_reasons,
                "report_id": effective_report_id,
                "lock_id": held_lock_id,
                "stale_lock_recovered": stale_recovered,
                "is_synthetic": is_synthetic,
            }
            validate_ops_run_record(run_record)
            record_ops_run(ws, run_record)
            result = {
                "schema_version": SCHEMA_GUARDED_RESULT,
                "status": "degraded",
                "run_id": effective_run_id,
                "report_id": effective_report_id,
                "report_type": report_type,
                "market_session_date": market_session_date,
                "is_synthetic": is_synthetic,
                "verified": True,
                "recorded_run": True,
                "lock_id": held_lock_id,
                "stale_lock_recovered": stale_recovered,
                "recovered_stale_lock_id": recovered_stale_id,
                "archived_stale_lock": archived_stale,
                "lock_released": False,
                "artifact_sha256": verify_res["artifact_sha256"],
                "html": str((published_dir / "brief.html").resolve()),
                "markdown": str((published_dir / "brief.md").resolve()),
                "manifest": str((published_dir / "manifest.json").resolve()),
                "run_record": run_record,
            }
    finally:
        release_run_lock(ws, lock_id=held_lock_id)

    result["lock_released"] = True
    return result
