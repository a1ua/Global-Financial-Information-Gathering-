"""Consistent model-ledger snapshots; restoration creates isolated copies only."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from uuid import uuid4

from ..contracts import ContractError, instant
from ..llm.client import ModelError, _matches, _safe_json, _schema, _strict_loads
from .backup import _copy, _destination, _file, _hash_file, _linked, _root


_MANIFEST = "ledger-backup-manifest.json"
_DATABASE = "ledger.db"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COLUMNS = {
    "days": {"day", "token_cap", "cost_cap"},
    "calls": set("""call_id cache_key day started_at finished_at attempt provider model status
        reserved_tokens reserved_cost charged_tokens charged_cost input_tokens output_tokens
        output_text output_sha256 error_code request_metadata""".split()),
    "cache": {"cache_key", "call_id"},
}


def _fail(reason):
    raise ValueError(reason)


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 10**15


def _sha(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_links(path):
    for item in (path, *path.parents):
        if _linked(item):
            _fail("ledger_backup_symlink_forbidden")


def _source(path):
    path = Path(path).absolute()
    _reject_links(path)
    if not path.is_file():
        _fail("ledger_backup_source_missing")
    return path.resolve(strict=True)


def _folder(path):
    path = Path(path).absolute()
    _reject_links(path)
    return _root(path)


@contextmanager
def _readonly(path):
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        yield db
    except sqlite3.Error:
        raise ValueError("ledger_backup_database_error") from None
    finally:
        if db is not None:
            db.close()


def _parse(value):
    try:
        result = _strict_loads(value)
        _safe_json(result)
        return result
    except (ModelError, TypeError, RecursionError, UnicodeError):
        raise ValueError("ledger_backup_json_invalid") from None


def _stamp(value):
    try:
        return instant(value, "ledger_backup.timestamp")
    except (ContractError, TypeError):
        raise ValueError("ledger_backup_time_invalid") from None


def _day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            _fail("ledger_backup_day_invalid")
        return parsed
    except (TypeError, ValueError):
        raise ValueError("ledger_backup_day_invalid") from None


def _cost(metadata, incoming, outgoing):
    """All amounts are configured-rate estimates in the day bucket currency."""
    generic = {"budget_currency", "input_micro_units_per_million_tokens", "output_micro_units_per_million_tokens"}
    if generic & metadata.keys():
        if not generic <= metadata.keys() or metadata["budget_currency"] not in ("USD", "CNY"):
            _fail("ledger_backup_rate_invalid")
        input_rate = metadata["input_micro_units_per_million_tokens"]
        output_rate = metadata["output_micro_units_per_million_tokens"]
        if not _integer(input_rate) or not _integer(output_rate):
            _fail("ledger_backup_rate_invalid")
        return (incoming * input_rate + 999_999) // 1_000_000 + (outgoing * output_rate + 999_999) // 1_000_000
    input_rate = metadata.get("input_micro_usd_per_token")
    output_rate = metadata.get("output_micro_usd_per_token")
    if not _integer(input_rate) or not _integer(output_rate):
        _fail("ledger_backup_rate_invalid")
    return incoming * input_rate + outgoing * output_rate


def _metadata(value):
    metadata = _parse(value)
    required = {"prompt_version", "rules_version", "schema_version", "parameters", "input_sha256",
                "prompt_sha256", "output_schema", "max_output_tokens", "max_output_bytes", "input_bound",
                "input_micro_usd_per_token", "output_micro_usd_per_token", "accounting_basis"}
    if type(metadata) is not dict or not required <= metadata.keys():
        _fail("ledger_backup_metadata_invalid")
    if any(type(metadata[key]) is not str or not metadata[key].strip()
           for key in ("prompt_version", "rules_version", "schema_version")):
        _fail("ledger_backup_metadata_invalid")
    if type(metadata["parameters"]) is not dict or not all(_sha(metadata[key]) for key in ("input_sha256", "prompt_sha256")):
        _fail("ledger_backup_metadata_invalid")
    if metadata["accounting_basis"] != "configured_rate_estimate":
        _fail("ledger_backup_metadata_invalid")
    if not all(_integer(metadata[key], 1) for key in ("max_output_tokens", "max_output_bytes", "input_bound")):
        _fail("ledger_backup_metadata_invalid")
    try:
        _schema(metadata["output_schema"])
    except (ModelError, TypeError, RecursionError):
        raise ValueError("ledger_backup_metadata_invalid") from None
    if metadata["output_schema"].get("type") != "object":
        _fail("ledger_backup_metadata_invalid")
    _cost(metadata, 0, 0)
    return metadata


def _ledger(db):
    if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"] or list(db.execute("PRAGMA foreign_key_check")):
        _fail("ledger_backup_integrity_failed")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (1, 2):
        _fail("ledger_backup_schema_unsupported")
    objects = list(db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    if {row["name"] for row in objects if row["type"] == "table"} != set(_COLUMNS):
        _fail("ledger_backup_schema_invalid")
    if any(row["type"] in ("view", "trigger") for row in objects):
        _fail("ledger_backup_schema_invalid")
    for table, columns in _COLUMNS.items():
        expected = columns | ({"currency"} if table == "days" and version == 2 else set())
        rows = list(db.execute(f"PRAGMA table_info({table})"))
        if {row["name"] for row in rows} != expected:
            _fail("ledger_backup_schema_invalid")
        primary = {row["name"] for row in rows if row["pk"]}
        if primary != {{"days": "day", "calls": "call_id", "cache": "cache_key"}[table]}:
            _fail("ledger_backup_schema_invalid")
    days = {}
    for row in db.execute("SELECT * FROM days"):
        _day(row["day"])
        if not _integer(row["token_cap"], 1) or not _integer(row["cost_cap"], 1):
            _fail("ledger_backup_day_cap_invalid")
        currency = row["currency"] if version == 2 else "USD"
        if currency not in ("USD", "CNY"):
            _fail("ledger_backup_currency_invalid")
        days[row["day"]] = {"token_cap": row["token_cap"], "cost_cap": row["cost_cap"],
                            "currency": currency, "tokens": 0, "cost": 0}
    calls = {}
    pending = 0
    for row in db.execute("SELECT * FROM calls"):
        call = dict(row)
        if type(call["call_id"]) is not str or not re.fullmatch(r"call_[0-9a-f]{32}", call["call_id"]) or not _sha(call["cache_key"]):
            _fail("ledger_backup_call_identity_invalid")
        if call["day"] not in days or _stamp(call["started_at"]).date() != _day(call["day"]):
            _fail("ledger_backup_call_day_invalid")
        if call["status"] not in ("pending", "failed", "succeeded") or not _integer(call["attempt"], 1):
            _fail("ledger_backup_call_state_invalid")
        if any(type(call[key]) is not str or not call[key] or len(call[key]) > 128
               or not all(char.isalnum() or char in "_.-/" for char in call[key]) for key in ("provider", "model")):
            _fail("ledger_backup_call_identity_invalid")
        if not all(_integer(call[key]) for key in ("reserved_tokens", "reserved_cost", "charged_tokens", "charged_cost")):
            _fail("ledger_backup_amount_invalid")
        if call["charged_tokens"] > call["reserved_tokens"] or call["charged_cost"] > call["reserved_cost"]:
            _fail("ledger_backup_amount_invalid")
        metadata = _metadata(call["request_metadata"])
        if metadata.get("budget_currency", "USD") != days[call["day"]]["currency"]:
            _fail("ledger_backup_currency_invalid")
        if call["reserved_tokens"] != metadata["input_bound"] + metadata["max_output_tokens"]:
            _fail("ledger_backup_reservation_invalid")
        if call["reserved_cost"] != _cost(metadata, metadata["input_bound"], metadata["max_output_tokens"]):
            _fail("ledger_backup_reservation_invalid")
        if call["status"] == "pending":
            pending += 1
            if any(call[key] is not None for key in ("finished_at", "input_tokens", "output_tokens", "output_text", "output_sha256", "error_code")):
                _fail("ledger_backup_call_state_invalid")
        else:
            if _stamp(call["finished_at"]) < _stamp(call["started_at"]):
                _fail("ledger_backup_time_invalid")
        if call["status"] == "failed":
            if type(call["error_code"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_]*", call["error_code"]):
                _fail("ledger_backup_call_state_invalid")
            if any(call[key] is not None for key in ("input_tokens", "output_tokens", "output_text", "output_sha256")):
                _fail("ledger_backup_call_state_invalid")
        if call["status"] == "succeeded":
            if call["error_code"] is not None or type(call["output_text"]) is not str or not _sha(call["output_sha256"]):
                _fail("ledger_backup_output_invalid")
            text = call["output_text"]
            try:
                encoded = text.encode("utf-8")
            except UnicodeError:
                raise ValueError("ledger_backup_output_invalid") from None
            if len(encoded) > metadata["max_output_bytes"] or hashlib.sha256(encoded).hexdigest() != call["output_sha256"]:
                _fail("ledger_backup_output_invalid")
            output = _parse(text)
            if not _matches(output, metadata["output_schema"]):
                _fail("ledger_backup_output_invalid")
            if (call["input_tokens"] is None) != (call["output_tokens"] is None):
                _fail("ledger_backup_usage_invalid")
            if call["input_tokens"] is None and "budget_currency" in metadata and len(encoded) > metadata["max_output_tokens"]:
                _fail("ledger_backup_output_invalid")
            if call["input_tokens"] is not None:
                if not _integer(call["input_tokens"], 1) or call["input_tokens"] > metadata["input_bound"] or not _integer(call["output_tokens"], 1) or call["output_tokens"] > metadata["max_output_tokens"]:
                    _fail("ledger_backup_usage_invalid")
                if call["charged_tokens"] != call["input_tokens"] + call["output_tokens"] or call["charged_cost"] != _cost(metadata, call["input_tokens"], call["output_tokens"]):
                    _fail("ledger_backup_usage_invalid")
        if call["input_tokens"] is None and (call["charged_tokens"], call["charged_cost"]) != (call["reserved_tokens"], call["reserved_cost"]):
            _fail("ledger_backup_unknown_spend_released")
        days[call["day"]]["tokens"] += call["charged_tokens"]
        days[call["day"]]["cost"] += call["charged_cost"]
        calls[call["call_id"]] = call
    for totals in days.values():
        if totals["tokens"] > totals["token_cap"] or totals["cost"] > totals["cost_cap"]:
            _fail("ledger_backup_day_cap_exceeded")
    cached_calls = set()
    for row in db.execute("SELECT * FROM cache"):
        call = calls.get(row["call_id"])
        if not call or call["status"] != "succeeded" or row["cache_key"] != call["cache_key"]:
            _fail("ledger_backup_cache_closure_invalid")
        cached_calls.add(call["cache_key"])
    if {call["cache_key"] for call in calls.values() if call["status"] == "succeeded"} != cached_calls:
        _fail("ledger_backup_cache_closure_invalid")
    return {"database_schema_version": version, "days": len(days), "calls": len(calls), "pending_calls": pending}


def _result(status, location, counts):
    return {"status": status, "backup": str(location), "files": 1,
            **counts, "restore_mode": "isolated_copy"}


def create_ledger_backup(state_path, destination):
    """Snapshot an existing ledger, without creating/changing its schema or calls."""
    database = _source(state_path)
    destination = _destination(database, destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    with _readonly(database) as source:
        snapshot = sqlite3.connect(staging / _DATABASE)
        deadline = time.monotonic() + 20
        def progress(*_):
            if time.monotonic() > deadline:
                _fail("ledger_backup_timeout")
        try:
            source.backup(snapshot, pages=128, progress=progress, sleep=0.01)
            snapshot.execute("PRAGMA journal_mode=DELETE")
        finally:
            snapshot.close()
    with _readonly(staging / _DATABASE) as snapshot:
        counts = _ledger(snapshot)
    manifest = {"schema_version": "llm-ledger-backup/0.1", "backup_id": "ledger_backup_" + uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "restore_mode": "isolated_copy", **counts,
                "files": {_DATABASE: _hash_file(staging / _DATABASE)}}
    (staging / _MANIFEST).write_text(_json(manifest), encoding="utf-8", newline="")
    verify_ledger_backup(staging)
    os.rename(staging, destination)
    return _result("backed_up", destination, counts)


def verify_ledger_backup(backup):
    """Read-only file inventory and ledger business invariants, not a signature."""
    backup = _folder(backup)
    names = {path.name for path in backup.iterdir()}
    if names != {_MANIFEST, _DATABASE}:
        _fail("ledger_backup_inventory_invalid")
    manifest = _parse(_file(backup, _MANIFEST).read_text(encoding="utf-8"))
    required = {"schema_version", "backup_id", "created_at", "restore_mode", "database_schema_version",
                "days", "calls", "pending_calls", "files"}
    if type(manifest) is not dict or manifest.keys() != required or manifest["schema_version"] != "llm-ledger-backup/0.1" or manifest["restore_mode"] != "isolated_copy":
        _fail("ledger_backup_manifest_invalid")
    if type(manifest["backup_id"]) is not str or not re.fullmatch(r"ledger_backup_[0-9a-f]{32}", manifest["backup_id"]):
        _fail("ledger_backup_manifest_invalid")
    _stamp(manifest["created_at"])
    if any(not _integer(manifest[key]) for key in ("database_schema_version", "days", "calls", "pending_calls")):
        _fail("ledger_backup_manifest_invalid")
    files = manifest["files"]
    if type(files) is not dict or files.keys() != {_DATABASE}:
        _fail("ledger_backup_inventory_invalid")
    recorded = files[_DATABASE]
    if type(recorded) is not dict or recorded.keys() != {"sha256", "size"} or not _sha(recorded["sha256"]) or not _integer(recorded["size"], 1):
        _fail("ledger_backup_manifest_invalid")
    database = _file(backup, _DATABASE)
    if _hash_file(database) != recorded:
        _fail("ledger_backup_file_hash_mismatch")
    with _readonly(database) as db:
        counts = _ledger(db)
    if any(manifest[key] != value for key, value in counts.items()):
        _fail("ledger_backup_snapshot_metadata_mismatch")
    return _result("verified", backup, counts)


def restore_ledger_backup(backup, destination):
    """Copy into a new directory; never replace an active/current budget pool."""
    backup = _folder(backup)
    checked = verify_ledger_backup(backup)
    destination = _destination(backup, destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    for name in (_DATABASE, _MANIFEST):
        _copy(backup, staging, name)
    verify_ledger_backup(staging)
    os.rename(staging, destination)
    counts = {key: checked[key] for key in ("database_schema_version", "days", "calls", "pending_calls")}
    result = _result("restored", destination, counts)
    result.pop("backup")
    return {**result, "workspace": str(destination), "ledger": str(destination / _DATABASE)}
