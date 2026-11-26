"""Offline OPS-01 scheduling core: atomic single-instance lock, append-only run
journal, read-only status inspection, deterministic missed-run recovery planner,
and dry-run Windows Task Scheduler XML template renderer.

No network access, no OS task installation, and no credential storage.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from ..contracts import ContractError, instant
from ..contracts.ops_schedule import (
    JOB_NAMES,
    OUTCOMES,
    SCHEMA_LOCK,
    SCHEMA_RECOVERY_PLAN,
    SCHEMA_RUN_RECORD,
    SCHEMA_TASK_TEMPLATE,
    SESSION_JOBS,
    validate_calendar_date,
    validate_hhmm,
    validate_ops_lock,
    validate_ops_recovery_plan,
    validate_ops_run_record,
    validate_timezone_strict,
)
from ..llm.client import ModelError, _strict_loads
from .backup import _linked

__all__ = [
    "acquire_run_lock",
    "release_run_lock",
    "inspect_run_lock",
    "record_ops_run",
    "read_ops_status",
    "plan_missed_runs",
    "render_windows_task_template",
]

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TASK_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SAFE_REL_SEG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}\Z")
_MAX_LOCK_BYTES = 65_536
_MAX_JOURNAL_BYTES = 16 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _format_utc(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_now(now_utc):
    if now_utc is None:
        return datetime.now(timezone.utc)
    return instant(now_utc, "ops.now_utc")


def _normalize_resolved(path):
    text_path = str(path.resolve())
    if text_path.startswith("\\\\?\\UNC\\"):
        raise ValueError("ops_path_unsupported")
    if text_path.startswith("\\\\?\\") and len(text_path) >= 6 and text_path[5] == ":":
        text_path = text_path[4:]
    return Path(text_path)


def _safe_workspace(path):
    raw_path = Path(path).absolute()
    if raw_path.drive.startswith("\\\\"):
        raise ValueError("ops_path_unsupported")
    if any(_linked(item) for item in (raw_path, *raw_path.parents)):
        raise ValueError("ops_symlink_not_allowed")
    return _normalize_resolved(raw_path)


def _unlink_with_retry(path, *, attempts=20, delay=0.005):
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _safe_child_no_symlink(base_dir, *parts):
    current = base_dir
    for part in parts:
        if (
            type(part) is not str
            or not part
            or part in {".", ".."}
            or "/" in part
            or "\\" in part
            or ":" in part
        ):
            raise ValueError("ops_path_outside_workspace")
        current = current / part
        if _linked(current):
            raise ValueError("ops_symlink_not_allowed")
    for _ in range(5):
        resolved = _normalize_resolved(current)
        if resolved.is_relative_to(base_dir):
            return current
        if "$Extend\\$Deleted\\" in str(resolved):
            time.sleep(0.005)
            continue
        raise ValueError("ops_path_outside_workspace")
    parent_resolved = _normalize_resolved(current.parent)
    if not parent_resolved.is_relative_to(base_dir):
        raise ValueError("ops_path_outside_workspace")
    return current


def _read_bounded_bytes(path, *, limit, role):
    if _linked(path):
        raise ValueError("ops_symlink_not_allowed")
    data = None
    for attempt in range(5):
        try:
            with path.open("rb") as stream:
                data = stream.read(limit + 1)
            break
        except PermissionError as exc:
            if path.is_dir() or attempt == 4:
                raise ValueError(f"{role}_io_error") from exc
            time.sleep(0.005)
        except OSError as exc:
            raise ValueError(f"{role}_io_error") from exc
    if len(data) > limit:
        raise ValueError(f"{role}_too_large")
    return data


def _read_lock_file(lock_path, *, expected_ws_hash=None):
    if _linked(lock_path):
        raise ValueError("ops_symlink_not_allowed")
    raw = None
    for _retry in range(5):
        try:
            with lock_path.open("rb") as stream:
                raw = stream.read(_MAX_LOCK_BYTES + 1)
            break
        except FileNotFoundError:
            return None, "missing"
        except IsADirectoryError:
            return None, "corrupt"
        except PermissionError:
            if lock_path.is_dir():
                return None, "corrupt"
            time.sleep(0.005)
        except OSError:
            return None, "corrupt"
    if raw is None:
        return None, "busy"
    if len(raw) > _MAX_LOCK_BYTES:
        return None, "corrupt"
    try:
        payload = _strict_loads(raw.decode("utf-8"))
        validate_ops_lock(payload)
    except (ValueError, UnicodeError, ModelError, ContractError):
        return None, "corrupt"
    if expected_ws_hash is not None and payload["workspace_sha256"] != expected_ws_hash:
        return None, "corrupt"
    return payload, "valid"


def _atomic_create_file(ops_dir, target_path, content_bytes):
    staging = ops_dir / f".lock-staging-{uuid4().hex}.tmp"
    if _linked(staging) or _linked(target_path):
        raise ValueError("ops_symlink_not_allowed")
    try:
        with staging.open("xb") as handle:
            handle.write(content_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(staging, target_path)
    finally:
        try:
            if staging.exists():
                staging.unlink()
        except OSError:
            pass


def inspect_run_lock(workspace, *, now_utc=None):
    """Read-only inspection of the workspace single-instance run lock."""
    ws = _safe_workspace(workspace)
    ws_hash = hashlib.sha256(str(ws).encode("utf-8")).hexdigest()
    now_dt = _parse_now(now_utc)
    ops_dir = _safe_child_no_symlink(ws, "ops")
    lock_path = _safe_child_no_symlink(ws, "ops", "run.lock")
    if not ops_dir.exists() or not lock_path.exists():
        return {
            "state": "unlocked",
            "evaluated_at": _format_utc(now_dt),
            "read_only": True,
            "lock": None,
        }
    if not lock_path.is_file():
        return {
            "state": "corrupt",
            "evaluated_at": _format_utc(now_dt),
            "read_only": True,
            "reason_code": "lock_corrupt_manual_check_required",
            "lock": None,
        }
    payload, status = _read_lock_file(lock_path, expected_ws_hash=ws_hash)
    if status == "missing":
        return {
            "state": "unlocked",
            "evaluated_at": _format_utc(now_dt),
            "read_only": True,
            "lock": None,
        }
    if status != "valid":
        return {
            "state": "corrupt",
            "evaluated_at": _format_utc(now_dt),
            "read_only": True,
            "reason_code": "lock_corrupt_manual_check_required",
            "lock": None,
        }
    expires_dt = instant(payload["expires_at"], "ops_lock.expires_at")
    state = "expired" if now_dt >= expires_dt else "active"
    return {
        "state": state,
        "evaluated_at": _format_utc(now_dt),
        "read_only": True,
        "lock": payload,
    }


def _build_lock_payload(*, lock_id, job_name, run_id, ws_hash, pid, now_dt, expires_dt, ttl_seconds, recovered_id):
    payload = {
        "schema_version": SCHEMA_LOCK,
        "lock_id": lock_id,
        "job_name": job_name,
        "run_id": run_id,
        "workspace_sha256": ws_hash,
        "pid": pid,
        "acquired_at": _format_utc(now_dt),
        "expires_at": _format_utc(expires_dt),
        "ttl_seconds": ttl_seconds,
        "status": "active",
        "recovered_stale_lock_id": recovered_id,
    }
    validate_ops_lock(payload)
    return payload, (_canonical(payload) + "\n").encode("utf-8")


def acquire_run_lock(
    workspace,
    *,
    job_name,
    run_id,
    ttl_seconds=900,
    now_utc=None,
    pid=None,
    lock_id=None,
    recover_expired=True,
):
    """Atomically acquire the workspace single-instance run lock.

    - Active unexpired locks are never overwritten (returns status='locked').
    - Corrupt lock files fail closed (returns status='blocked_corrupt_lock').
    - Expired locks are atomically archived under ops/stale-locks/ inside an
      exclusive recovery guard before acquiring a new lock when recover_expired=True.
    """
    if job_name not in JOB_NAMES:
        raise ValueError("invalid_job_name")
    if type(run_id) is not str or not _ID_RE.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 86400:
        raise ValueError("invalid_ttl_seconds")
    if type(recover_expired) is not bool:
        raise ValueError("invalid_recover_expired")
    effective_pid = os.getpid() if pid is None else pid
    if type(effective_pid) is not int or not 1 <= effective_pid <= 2_147_483_647:
        raise ValueError("invalid_pid")
    effective_lock_id = f"lock_{uuid4().hex[:16]}" if lock_id is None else lock_id
    if type(effective_lock_id) is not str or not _ID_RE.fullmatch(effective_lock_id):
        raise ValueError("invalid_lock_id")

    ws = _safe_workspace(workspace)
    now_dt = _parse_now(now_utc)
    expires_dt = now_dt + timedelta(seconds=ttl_seconds)
    ws_hash = hashlib.sha256(str(ws).encode("utf-8")).hexdigest()

    ops_dir = _safe_child_no_symlink(ws, "ops")
    lock_path = _safe_child_no_symlink(ws, "ops", "run.lock")
    recovery_guard = _safe_child_no_symlink(ws, "ops", ".stale-recovery.lock")
    stale_dir = _safe_child_no_symlink(ws, "ops", "stale-locks")
    ops_dir.mkdir(parents=True, exist_ok=True)

    fresh_payload, fresh_encoded = _build_lock_payload(
        lock_id=effective_lock_id,
        job_name=job_name,
        run_id=run_id,
        ws_hash=ws_hash,
        pid=effective_pid,
        now_dt=now_dt,
        expires_dt=expires_dt,
        ttl_seconds=ttl_seconds,
        recovered_id=None,
    )

    for _attempt in range(20):
        try:
            _atomic_create_file(ops_dir, lock_path, fresh_encoded)
            return {
                "status": "acquired",
                "acquired": True,
                "stale_lock_recovered": False,
                "recovered_stale_lock_id": None,
                "archived_stale_lock": None,
                "lock": fresh_payload,
            }
        except FileExistsError:
            pass

        existing, state = _read_lock_file(lock_path, expected_ws_hash=ws_hash)
        if state in {"missing", "busy"}:
            time.sleep(0.005)
            continue
        if state != "valid":
            return {
                "status": "blocked_corrupt_lock",
                "acquired": False,
                "reason_code": "lock_corrupt_manual_check_required",
                "stale_lock_recovered": False,
                "lock": None,
            }

        existing_expires = instant(existing["expires_at"], "ops_lock.expires_at")
        if now_dt < existing_expires:
            return {
                "status": "locked",
                "acquired": False,
                "reason_code": "lock_held_active",
                "stale_lock_recovered": False,
                "active_lock": existing,
            }

        if not recover_expired:
            return {
                "status": "expired_lock_present",
                "acquired": False,
                "reason_code": "stale_lock_recovery_disabled",
                "stale_lock_recovered": False,
                "expired_lock": existing,
            }

        # Serialize stale-lock archival + replacement under an exclusive recovery guard
        # so concurrent contenders can never steal a freshly created active lock.
        try:
            _atomic_create_file(ops_dir, recovery_guard, f"{effective_lock_id}\n".encode("utf-8"))
        except FileExistsError:
            time.sleep(0.005)
            continue

        try:
            current, cstate = _read_lock_file(lock_path, expected_ws_hash=ws_hash)
            if cstate in {"missing", "busy"}:
                # Lock vanished or was briefly busy before we acquired the recovery guard; retry cleanly.
                time.sleep(0.005)
                continue
            if cstate != "valid":
                return {
                    "status": "blocked_corrupt_lock",
                    "acquired": False,
                    "reason_code": "lock_corrupt_manual_check_required",
                    "stale_lock_recovered": False,
                    "lock": None,
                }
            current_expires = instant(current["expires_at"], "ops_lock.expires_at")
            if now_dt < current_expires:
                return {
                    "status": "locked",
                    "acquired": False,
                    "reason_code": "lock_held_active",
                    "stale_lock_recovered": False,
                    "active_lock": current,
                }
            if current["lock_id"] == effective_lock_id:
                raise ValueError("stale_lock_id_collision")

            stale_dir.mkdir(parents=True, exist_ok=True)
            compact_ts = now_dt.strftime("%Y%m%dT%H%M%SZ")
            archive_name = f"{current['lock_id']}-{compact_ts}-{uuid4().hex[:8]}.json"
            archive_path = _safe_child_no_symlink(ws, "ops", "stale-locks", archive_name)
            renamed = False
            for _rename_try in range(8):
                try:
                    os.rename(lock_path, archive_path)
                    renamed = True
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    # Windows sharing violation (WinError 32) while a concurrent reader inspects run.lock.
                    time.sleep(0.005)
            if not renamed:
                time.sleep(0.005)
                continue

            recovered_payload, recovered_encoded = _build_lock_payload(
                lock_id=effective_lock_id,
                job_name=job_name,
                run_id=run_id,
                ws_hash=ws_hash,
                pid=effective_pid,
                now_dt=now_dt,
                expires_dt=expires_dt,
                ttl_seconds=ttl_seconds,
                recovered_id=current["lock_id"],
            )
            try:
                _atomic_create_file(ops_dir, lock_path, recovered_encoded)
                return {
                    "status": "acquired",
                    "acquired": True,
                    "stale_lock_recovered": True,
                    "recovered_stale_lock_id": current["lock_id"],
                    "archived_stale_lock": f"ops/stale-locks/{archive_name}",
                    "lock": recovered_payload,
                }
            except FileExistsError:
                # A concurrent caller installed a fresh lock right after archival; observe it on next pass.
                continue
        finally:
            try:
                _unlink_with_retry(recovery_guard)
            except OSError:
                pass

    existing, state = _read_lock_file(lock_path, expected_ws_hash=ws_hash)
    if state == "valid":
        return {
            "status": "locked",
            "acquired": False,
            "reason_code": "lock_held_active",
            "stale_lock_recovered": False,
            "active_lock": existing,
        }
    if state in {"missing", "busy"}:
        return {
            "status": "locked",
            "acquired": False,
            "reason_code": "lock_held_active",
            "stale_lock_recovered": False,
            "active_lock": None,
        }
    return {
        "status": "blocked_corrupt_lock",
        "acquired": False,
        "reason_code": "lock_corrupt_manual_check_required",
        "stale_lock_recovered": False,
        "lock": None,
    }


def release_run_lock(workspace, *, lock_id):
    """Release the workspace run lock only if lock_id matches the current owner."""
    if type(lock_id) is not str or not _ID_RE.fullmatch(lock_id):
        raise ValueError("invalid_lock_id")
    ws = _safe_workspace(workspace)
    ws_hash = hashlib.sha256(str(ws).encode("utf-8")).hexdigest()
    lock_path = _safe_child_no_symlink(ws, "ops", "run.lock")
    existing, state = None, "busy"
    for _ in range(10):
        existing, state = _read_lock_file(lock_path, expected_ws_hash=ws_hash)
        if state != "busy":
            break
        time.sleep(0.005)
    if state == "missing":
        raise ValueError("lock_not_found")
    if state != "valid":
        raise ValueError("lock_corrupt_manual_check_required")
    if existing["lock_id"] != lock_id:
        raise ValueError("lock_owner_mismatch")
    _unlink_with_retry(lock_path)
    return {"status": "released", "lock_id": lock_id}


def _parse_run_journal_bytes(raw):
    try:
        decoded = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("ops_run_journal_corrupt") from exc
    if not decoded:
        return [], {}
    if not decoded.endswith("\n"):
        raise ValueError("ops_run_journal_corrupt")

    records = []
    by_id = {}
    for line in decoded.splitlines():
        if not line:
            raise ValueError("ops_run_journal_corrupt")
        try:
            entry = _strict_loads(line)
            validate_ops_run_record(entry)
        except (ValueError, ModelError, ContractError) as exc:
            raise ValueError("ops_run_journal_corrupt") from exc
        rid = entry["run_id"]
        if rid in by_id:
            raise ValueError("ops_duplicate_run_id")
        by_id[rid] = entry
        records.append(entry)
    return records, by_id


def _load_run_journal(ws, *, under_guard=False):
    ops_dir = _safe_child_no_symlink(ws, "ops")
    journal_path = _safe_child_no_symlink(ws, "ops", "runs.jsonl")
    journal_guard = _safe_child_no_symlink(ws, "ops", ".runs-journal.lock")
    if not ops_dir.exists() or not journal_path.exists():
        return [], {}
    if not journal_path.is_file():
        raise ValueError("ops_run_journal_corrupt")
    for attempt in range(1 if under_guard else 6):
        raw = _read_bounded_bytes(journal_path, limit=_MAX_JOURNAL_BYTES, role="ops_run_journal")
        try:
            return _parse_run_journal_bytes(raw)
        except ValueError as exc:
            if not under_guard and str(exc) == "ops_run_journal_corrupt" and journal_guard.exists() and attempt < 5:
                time.sleep(0.005)
                continue
            raise
    raise ValueError("ops_run_journal_corrupt")


def record_ops_run(workspace, run_record):
    """Append a validated ops-run-record/0.1 entry to <workspace>/ops/runs.jsonl.

    Serializes read-validate-append-fsync under an exclusive ops/.runs-journal.lock
    guard so concurrent callers never drop or interleave journal records on Windows.
    """
    validate_ops_run_record(run_record)
    ws = _safe_workspace(workspace)
    ops_dir = _safe_child_no_symlink(ws, "ops")
    journal_path = _safe_child_no_symlink(ws, "ops", "runs.jsonl")
    journal_guard = _safe_child_no_symlink(ws, "ops", ".runs-journal.lock")
    rid = run_record["run_id"]
    canonical_line = _canonical(run_record)

    ops_dir.mkdir(parents=True, exist_ok=True)
    acquired_guard = False
    for _ in range(200):
        try:
            _atomic_create_file(ops_dir, journal_guard, f"{rid}\n".encode("utf-8"))
            acquired_guard = True
            break
        except FileExistsError:
            time.sleep(0.005)
    if not acquired_guard:
        raise ValueError("ops_run_journal_busy")

    try:
        _, existing_by_id = _load_run_journal(ws, under_guard=True)
        if rid in existing_by_id:
            if _canonical(existing_by_id[rid]) == canonical_line:
                return {"status": "idempotent_duplicate", "recorded": False, "run_id": rid}
            raise ValueError("ops_run_id_conflict")

        if _linked(journal_path):
            raise ValueError("ops_symlink_not_allowed")
        with journal_path.open("ab") as handle:
            handle.write((canonical_line + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        _unlink_with_retry(journal_guard)

    return {"status": "recorded", "recorded": True, "run_id": rid, "outcome": run_record["outcome"]}


def read_ops_status(workspace, *, now_utc=None):
    """Strictly read-only summary of workspace lock state and append-only run journal."""
    ws = _safe_workspace(workspace)
    now_dt = _parse_now(now_utc)
    lock_info = inspect_run_lock(ws, now_utc=_format_utc(now_dt))
    records, _ = _load_run_journal(ws)

    stale_dir = _safe_child_no_symlink(ws, "ops", "stale-locks")
    stale_count = 0
    if stale_dir.exists():
        if not stale_dir.is_dir():
            raise ValueError("ops_stale_dir_corrupt")
        for item in stale_dir.iterdir():
            if _linked(item):
                raise ValueError("ops_symlink_not_allowed")
            if item.is_file() and item.suffix == ".json":
                stale_count += 1

    counts = {outcome: 0 for outcome in sorted(OUTCOMES)}
    last_by_job = {}
    for entry in records:
        counts[entry["outcome"]] += 1
        job = entry["job_name"]
        sort_key = (
            instant(entry["finished_at"], "ops_run.finished_at"),
            instant(entry["started_at"], "ops_run.started_at"),
            entry["run_id"],
        )
        prev = last_by_job.get(job)
        if prev is None or sort_key > prev[0]:
            last_by_job[job] = (sort_key, entry)

    return {
        "schema_version": "ops-status/0.1",
        "evaluated_at": _format_utc(now_dt),
        "read_only": True,
        "lock": lock_info,
        "total_runs": len(records),
        "counts_by_outcome": counts,
        "stale_locks_archived_count": stale_count,
        "last_run_by_job": {
            job: {
                "run_id": entry["run_id"],
                "market_session_date": entry["market_session_date"],
                "outcome": entry["outcome"],
                "finished_at": entry["finished_at"],
                "report_id": entry["report_id"],
            }
            for job, (_, entry) in sorted(last_by_job.items())
        },
    }


def _local_slot_to_utc(session_date, hour, minute, tz):
    naive = datetime(session_date.year, session_date.month, session_date.day, hour, minute, 0)
    aware = naive.replace(tzinfo=tz)
    utc_dt = aware.astimezone(timezone.utc)
    roundtrip = utc_dt.astimezone(tz)
    if (roundtrip.year, roundtrip.month, roundtrip.day, roundtrip.hour, roundtrip.minute) != (
        naive.year,
        naive.month,
        naive.day,
        naive.hour,
        naive.minute,
    ):
        raise ValueError("nonexistent_local_schedule_time")
    return utc_dt


def _extract_scheduled_dates(scheduled_dates):
    if type(scheduled_dates) is dict:
        if scheduled_dates.get("schema_version") != "scheduled-session-snapshot/0.1":
            raise ValueError("unsupported_calendar_snapshot")
        raw_dates = scheduled_dates.get("scheduled_sessions")
    else:
        raw_dates = scheduled_dates
    if type(raw_dates) is not list or not 1 <= len(raw_dates) <= 370:
        raise ValueError("invalid_scheduled_dates")
    parsed = []
    seen = set()
    for item in raw_dates:
        day = validate_calendar_date(item, "scheduled_dates")
        if item in seen:
            raise ValueError("duplicate_scheduled_date")
        seen.add(item)
        parsed.append((item, day))
    parsed.sort(key=lambda pair: pair[0])
    return parsed


def plan_missed_runs(
    workspace,
    *,
    scheduled_dates,
    now_utc=None,
    display_timezone="Asia/Shanghai",
    pre_market_local="08:30",
    post_market_local="16:30",
):
    """Strictly read-only deterministic planner for missed pre_market/post_market runs.

    - Never inspects or counts slots scheduled strictly after now_utc (anti-lookahead).
    - Only considers run journal records with finished_at <= now_utc (point-in-time pure).
    - Never executes network/model commands or mutates the workspace.
    """
    ws = _safe_workspace(workspace)
    now_dt = _parse_now(now_utc)
    tz = validate_timezone_strict(display_timezone, "ops_plan.display_timezone")
    pre_h, pre_m = validate_hhmm(pre_market_local, "ops_plan.pre_market_local")
    post_h, post_m = validate_hhmm(post_market_local, "ops_plan.post_market_local")
    if (pre_h, pre_m) >= (post_h, post_m):
        raise ValueError("post_must_be_after_pre")

    dates = _extract_scheduled_dates(scheduled_dates)
    records, _ = _load_run_journal(ws)

    # Point-in-time filter: ignore any runs completed strictly after evaluated_at.
    runs_by_slot = {}
    for entry in records:
        if entry["job_name"] not in SESSION_JOBS or entry["market_session_date"] is None:
            continue
        finished_dt = instant(entry["finished_at"], "ops_run.finished_at")
        if finished_dt > now_dt:
            continue
        slot_key = (entry["market_session_date"], entry["job_name"])
        runs_by_slot.setdefault(slot_key, []).append(entry)

    checked = 0
    completed = 0
    actions = []

    slot_specs = (("pre_market", pre_h, pre_m), ("post_market", post_h, post_m))
    for date_str, day_obj in dates:
        for job_name, hour, minute in slot_specs:
            slot_utc = _local_slot_to_utc(day_obj, hour, minute, tz)
            if slot_utc > now_dt:
                continue
            checked += 1
            slot_runs = runs_by_slot.get((date_str, job_name), [])
            if any(r["outcome"] in {"succeeded", "degraded"} for r in slot_runs):
                completed += 1
                continue

            if not slot_runs:
                miss_reason = "offline_or_missed"
                last_failed_id = None
            else:
                latest = max(
                    slot_runs,
                    key=lambda r: (
                        instant(r["finished_at"], "ops_run.finished_at"),
                        instant(r["started_at"], "ops_run.started_at"),
                        r["run_id"],
                    ),
                )
                last_failed_id = latest["run_id"]
                outcome_map = {
                    "failed_network": "previous_network_failure",
                    "failed_runtime": "previous_runtime_failure",
                    "skipped_locked": "previous_lock_conflict",
                }
                miss_reason = outcome_map[latest["outcome"]]

            slot_iso = _format_utc(slot_utc)
            compact_date = date_str.replace("-", "")
            prefix = "pre" if job_name == "pre_market" else "post"
            rec_cmd = (
                f"python -X utf8 -m market_intel session-brief "
                f"--report-type {job_name} --session-date {date_str} "
                f"--cutoff {slot_iso} --report-id {prefix}_{compact_date}_catchup"
            )
            actions.append(
                {
                    "market_session_date": date_str,
                    "job_name": job_name,
                    "scheduled_for": slot_iso,
                    "miss_reason": miss_reason,
                    "last_failed_run_id": last_failed_id,
                    "recommended_command": rec_cmd,
                }
            )

    missed = len(actions)
    reasons = ["read_only_plan", "no_auto_execution"]
    if checked == 0:
        reasons.append("no_due_slots_yet")
    elif missed > 0:
        reasons.append("missed_runs_detected")
    else:
        reasons.append("all_due_slots_completed")

    plan = {
        "schema_version": SCHEMA_RECOVERY_PLAN,
        "evaluated_at": _format_utc(now_dt),
        "display_timezone": display_timezone,
        "pre_market_local": pre_market_local,
        "post_market_local": post_market_local,
        "window_start_date": dates[0][0],
        "window_end_date": dates[-1][0],
        "scheduled_slots_checked": checked,
        "completed_slots": completed,
        "missed_slots": missed,
        "pending_recovery_actions": actions,
        "auto_execute": False,
        "reason_codes": reasons,
    }
    validate_ops_recovery_plan(plan)
    return plan


def _validate_safe_rel_workspace(value):
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError("invalid_workspace_rel")
    if "\\" in value or value.startswith("/") or value.endswith("/") or ":" in value:
        raise ValueError("invalid_workspace_rel")
    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."} or not _SAFE_REL_SEG_RE.fullmatch(part):
            raise ValueError("invalid_workspace_rel")
    return "/".join(parts)


def render_windows_task_template(
    *,
    job_name,
    task_name,
    trigger_local_time,
    display_timezone="Asia/Shanghai",
    workspace_rel="data/live",
    start_date="2026-11-24",
    output_path=None,
):
    """Render an inspectable Windows Task Scheduler 1.2 XML template (dry-run only).

    Never calls schtasks/PowerShell, never installs any OS scheduled task, and
    never embeds credentials or user secrets.
    """
    if job_name not in SESSION_JOBS:
        raise ValueError("invalid_job_name")
    if type(task_name) is not str or not _TASK_NAME_RE.fullmatch(task_name):
        raise ValueError("invalid_task_name")
    hour, minute = validate_hhmm(trigger_local_time, "ops_template.trigger_local_time")
    validate_timezone_strict(display_timezone, "ops_template.display_timezone")
    validate_calendar_date(start_date, "ops_template.start_date")
    safe_ws = _validate_safe_rel_workspace(workspace_rel)

    start_boundary = f"{start_date}T{hour:02d}:{minute:02d}:00"
    # Keep XML Exec Arguments strictly clean and shell-free:
    exec_args = f"-X utf8 -m market_intel ops-status --workspace {safe_ws}"
    description = (
        f"Dry-run Windows Task Scheduler template for market_intel {job_name} "
        f"({display_timezone} {trigger_local_time}). Not auto-installed; "
        f"configure MARKET_INTEL_PYTHON before explicit manual import."
    )

    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        f"    <Description>{xml_escape(description)}</Description>\n"
        f"    <URI>\\market_intel\\{xml_escape(task_name)}</URI>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <CalendarTrigger>\n"
        f"      <StartBoundary>{xml_escape(start_boundary)}</StartBoundary>\n"
        "      <Enabled>false</Enabled>\n"
        "      <ScheduleByWeek>\n"
        "        <DaysOfWeek>\n"
        "          <Monday />\n"
        "          <Tuesday />\n"
        "          <Wednesday />\n"
        "          <Thursday />\n"
        "          <Friday />\n"
        "        </DaysOfWeek>\n"
        "        <WeeksInterval>1</WeeksInterval>\n"
        "      </ScheduleByWeek>\n"
        "    </CalendarTrigger>\n"
        "  </Triggers>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>\n"
        "    <Enabled>false</Enabled>\n"
        "  </Settings>\n"
        "  <Actions Context=\"Author\">\n"
        "    <Exec>\n"
        "      <Command>%MARKET_INTEL_PYTHON%</Command>\n"
        f"      <Arguments>{xml_escape(exec_args)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )
    # Self-check XML well-formedness deterministically before returning.
    ET.fromstring(xml_text)
    xml_bytes = xml_text.encode("utf-8")
    digest = hashlib.sha256(xml_bytes).hexdigest()

    written_path = None
    if output_path is not None:
        raw_out = Path(output_path).absolute()
        if raw_out.drive.startswith("\\\\"):
            raise ValueError("ops_path_unsupported")
        if any(_linked(item) for item in (raw_out, *raw_out.parents)):
            raise ValueError("ops_symlink_not_allowed")
        if raw_out.exists():
            if not raw_out.is_file():
                raise ValueError("template_output_conflict")
            existing_bytes = _read_bounded_bytes(raw_out, limit=_MAX_LOCK_BYTES, role="ops_template")
            if existing_bytes != xml_bytes:
                raise ValueError("template_output_conflict")
        else:
            raw_out.parent.mkdir(parents=True, exist_ok=True)
            staging = raw_out.parent / f".template-staging-{uuid4().hex}.tmp"
            try:
                with staging.open("xb") as handle:
                    handle.write(xml_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.rename(staging, raw_out)
            finally:
                try:
                    if staging.exists():
                        staging.unlink()
                except OSError:
                    pass
        written_path = str(raw_out)

    return {
        "schema_version": SCHEMA_TASK_TEMPLATE,
        "auto_installed": False,
        "dry_run_template_only": True,
        "enabled_in_template": False,
        "task_name": task_name,
        "job_name": job_name,
        "display_timezone": display_timezone,
        "trigger_local_time": trigger_local_time,
        "workspace_rel": safe_ws,
        "xml_sha256": digest,
        "output_path": written_path,
        "xml": xml_text,
    }
