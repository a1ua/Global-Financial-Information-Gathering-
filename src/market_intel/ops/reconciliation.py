"""Read-only comparison of unverified statement amounts and ledger estimates."""

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ..llm.binding import check_workspace_ledger, _paths
from ..llm.client import ModelError, _safe_json, _strict_loads
from .backup import _linked
from .llm_backup import _ledger, _readonly


_LIMIT = 1_048_576
_FIELDS = {"schema_version", "ledger_id", "utc_day", "currency", "provider",
           "evidence_kind", "evidence_sha256", "records"}


def _fail(code):
    raise ValueError(code) from None


def _matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _statement(path):
    try:
        path = Path(path).absolute()
        if any(_linked(item) for item in (path, *path.parents)):
            _fail("ledger_reconciliation_link_forbidden")
        if not path.is_file():
            _fail("ledger_reconciliation_statement_missing")
        with path.open("rb") as stream:
            raw = stream.read(_LIMIT + 1)
        if len(raw) > _LIMIT:
            _fail("ledger_reconciliation_statement_too_large")
        try:
            value = _strict_loads(raw.decode("utf-8"))
            _safe_json(value)
        except (ModelError, UnicodeError, TypeError, RecursionError):
            _fail("ledger_reconciliation_statement_invalid")
        if type(value) is not dict or value.keys() != _FIELDS:
            _fail("ledger_reconciliation_statement_invalid")
        if (value["schema_version"] != "ledger-reconciliation-statement/0.1"
                or not _matches(value["ledger_id"], r"ledger_[0-9a-f]{32}")
                or value["currency"] not in ("CNY", "USD")
                or value["provider"] not in ("mock", "deepseek")
                or value["evidence_kind"] not in ("synthetic", "manual_statement")
                or not _matches(value["evidence_sha256"], r"[0-9a-f]{64}")):
            _fail("ledger_reconciliation_statement_invalid")
        try:
            day = date.fromisoformat(value["utc_day"])
            if day.isoformat() != value["utc_day"]:
                _fail("ledger_reconciliation_statement_invalid")
        except (TypeError, ValueError):
            _fail("ledger_reconciliation_statement_invalid")
        records = value["records"]
        if type(records) is not list or len(records) > 10000:
            _fail("ledger_reconciliation_statement_invalid")
        seen = set()
        for row in records:
            if (type(row) is not dict or row.keys() != {"call_id", "charged_micro_units"}
                    or not _matches(row["call_id"], r"call_[0-9a-f]{32}")
                    or type(row["charged_micro_units"]) is not int
                    or not 0 <= row["charged_micro_units"] <= 10**15
                    or row["call_id"] in seen):
                _fail("ledger_reconciliation_statement_invalid")
            seen.add(row["call_id"])
        return value
    except (TypeError, OverflowError):
        _fail("ledger_reconciliation_statement_invalid")


def _preview_statement(workspace, statement):
    """Compare one already validated statement within one ledger read snapshot."""
    try:
        root, _, _ = _paths(workspace)
        if (root / "ledger-backup-manifest.json").exists():
            _fail("isolated_ledger_not_live")
        bound = check_workspace_ledger(root)
        if bound["status"] != "bound":
            _fail("ledger_reconciliation_binding_required")
        if statement["ledger_id"] != bound["ledger_id"]:
            _fail("ledger_reconciliation_identity_mismatch")
        with _readonly(Path(bound["ledger"])) as db:
            db.execute("BEGIN")
            try:
                counts = _ledger(db)
            except ValueError:
                _fail("ledger_reconciliation_ledger_invalid")
            if counts["database_schema_version"] != 3 or counts.get("ledger_id") != bound["ledger_id"]:
                _fail("ledger_reconciliation_identity_mismatch")
            day = db.execute("SELECT currency FROM days WHERE day=?", (statement["utc_day"],)).fetchone()
            if day is None:
                _fail("ledger_reconciliation_day_missing")
            if day["currency"] != statement["currency"]:
                _fail("ledger_reconciliation_currency_mismatch")
            calls = {row["call_id"]: row for row in db.execute(
                "SELECT call_id,status,charged_cost FROM calls WHERE day=? AND provider=?",
                (statement["utc_day"], statement["provider"]))}
            records = {row["call_id"]: row["charged_micro_units"] for row in statement["records"]}
            if records.keys() - calls.keys():
                _fail("ledger_reconciliation_unknown_call")
            missing = len(calls.keys() - records.keys())
            pending = sum(row["status"] == "pending" for row in calls.values())
            differences = sum(amount != calls[call_id]["charged_cost"] for call_id, amount in records.items())
            local_total = sum(row["charged_cost"] for row in calls.values())
            stated_total = sum(records.values())
        status = "incomplete" if missing or pending else "differences" if differences else "matched_estimates"
        return {"schema_version": "ledger-reconciliation-preview/0.1", "status": status,
                "ledger_id": bound["ledger_id"], "utc_day": statement["utc_day"],
                "currency": statement["currency"], "provider": statement["provider"],
                "evidence_kind": statement["evidence_kind"], "read_only": True,
                "evidence_authenticated": False, "settlement_allowed": False,
                "local_calls": len(calls), "statement_records": len(records),
                "missing_records": missing, "pending_calls": pending, "difference_records": differences,
                "local_estimated_micro_units": local_total, "statement_micro_units": stated_total,
                "delta_micro_units": stated_total - local_total}
    except OSError:
        _fail("ledger_reconciliation_io_error")
    except sqlite3.Error:
        _fail("ledger_reconciliation_database_error")


def preview_reconciliation(workspace, statement_path):
    """Compare one UTC day/provider; never authenticate evidence or settle costs."""
    try:
        return _preview_statement(workspace, _statement(statement_path))
    except OSError:
        _fail("ledger_reconciliation_io_error")


def prepare_audit_observation(workspace, statement_path):
    """Parse once so the declared hashes and preview refer to the same input."""
    try:
        statement = _statement(statement_path)
    except OSError:
        _fail("ledger_reconciliation_io_error")
    preview = _preview_statement(workspace, statement)
    encoded = json.dumps(statement, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"schema_version": "ledger-audit-observation/0.1",
            "statement_sha256": hashlib.sha256(encoded).hexdigest(),
            "evidence_sha256": statement["evidence_sha256"], "preview": preview}
