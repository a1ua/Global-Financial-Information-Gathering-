"""Read-only recovery comparisons, never an authorization to switch ledgers."""

import sqlite3

from ..llm.binding import check_workspace_ledger
from .llm_backup import _folder, _ledger, _readonly, _source, verify_ledger_backup


def _fail(code):
    raise ValueError(code) from None


def _rows(db, table, key):
    return {row[key]: dict(row) for row in db.execute("SELECT * FROM " + table)}


def _differences(current, candidate):
    return (len(current.keys() - candidate.keys()),
            len(candidate.keys() - current.keys()),
            sum(current[key] != candidate[key] for key in current.keys() & candidate.keys()))


def preflight_ledger_recovery(workspace, backup):
    """Compare two observed valid snapshots without modifying or activating either.

    Each connection owns one read transaction. They are not a cross-database atomic
    snapshot; validation cannot make a later production switch safe.
    """
    try:
        bound = check_workspace_ledger(workspace)
        if bound["status"] != "bound":
            _fail("ledger_recovery_binding_required")
        current_path = _source(bound["ledger"])
        if (current_path.parent / "ledger-backup-manifest.json").exists():
            _fail("isolated_ledger_not_live")
        checked = verify_ledger_backup(backup)
        if checked["database_schema_version"] != 3:
            _fail("ledger_recovery_schema3_required")
        ledger_id = bound["ledger_id"]
        if checked["ledger_id"] != ledger_id:
            _fail("ledger_recovery_identity_mismatch")
        candidate_path = _source(_folder(backup) / "ledger.db")
        with _readonly(current_path) as current, _readonly(candidate_path) as candidate:
            current.execute("BEGIN")
            candidate.execute("BEGIN")
            for db in (current, candidate):
                observed = _ledger(db)
                if observed["database_schema_version"] != 3:
                    _fail("ledger_recovery_schema3_required")
                if observed["ledger_id"] != ledger_id:
                    _fail("ledger_recovery_identity_mismatch")
            # Re-observe the external binding as well as the identities read in
            # the pinned database transactions. This is not a switch lease.
            rebound = check_workspace_ledger(workspace)
            if rebound["status"] != "bound" or rebound["ledger_id"] != ledger_id:
                _fail("ledger_recovery_identity_mismatch")
            current_calls = _rows(current, "calls", "call_id")
            candidate_calls = _rows(candidate, "calls", "call_id")
            calls = _differences(current_calls, candidate_calls)
            days = _differences(_rows(current, "days", "day"), _rows(candidate, "days", "day"))
            cache = _differences(_rows(current, "cache", "cache_key"),
                                 _rows(candidate, "cache", "cache_key"))
        equivalent = not any((*calls, *days, *cache))
        blockers = ["trusted_high_water_unavailable", "reconciliation_not_verified",
                    "production_switch_not_implemented"]
        if not equivalent:
            blockers.append("snapshot_not_equivalent")
        return {"schema_version": "ledger-recovery-preflight/0.1",
                "status": "equivalent_observation" if equivalent else "not_equivalent",
                "ledger_id": ledger_id, "read_only": True, "switch_allowed": False,
                "trusted_high_water": False, "current_calls": len(current_calls),
                "candidate_calls": len(candidate_calls),
                "candidate_missing_calls": calls[0], "candidate_extra_calls": calls[1],
                "changed_calls": calls[2], "missing_days": days[0], "extra_days": days[1],
                "changed_days": days[2], "missing_cache": cache[0], "extra_cache": cache[1],
                "changed_cache": cache[2], "blockers": blockers}
    except OSError:
        _fail("ledger_recovery_io_error")
    except sqlite3.Error:
        _fail("ledger_recovery_database_error")
