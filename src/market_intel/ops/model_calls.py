"""Read-only summaries of bound model calls, not supplier invoice evidence."""

import re
import sqlite3

from ..llm.binding import check_workspace_ledger
from .llm_backup import _ledger, _parse, _readonly, _source


class _CallInfoError(ValueError):
    pass


def _fail(reason):
    raise _CallInfoError("model_call_" + reason) from None


def inspect_model_call(workspace, call_id):
    """Inspect one exact call in a single validated, read-only ledger snapshot.

    The binding and database are not a cross-file atomic snapshot or switch lease.
    SQLite can maintain WAL coordination files during a read-only observation.
    """
    if type(call_id) is not str or not re.fullmatch(r"call_[0-9a-f]{32}", call_id):
        _fail("id_invalid")
    try:
        bound = check_workspace_ledger(workspace)
        if bound["status"] != "bound":
            _fail("binding_required")
        database = _source(bound["ledger"])
        with _readonly(database) as db:
            db.execute("BEGIN")
            observed = _ledger(db)
            if observed["database_schema_version"] != 3:
                _fail("schema3_required")
            if observed["ledger_id"] != bound["ledger_id"]:
                _fail("identity_mismatch")
            call = db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if call is None:
                _fail("missing")
            metadata = _parse(call["request_metadata"])
            currency = db.execute("SELECT currency FROM days WHERE day=?", (call["day"],)).fetchone()[0]
            correlation = metadata.get("provider_response")
            response_hash = correlation["response_id_sha256"] if correlation is not None else None
            correlation_status = ("absent" if correlation is None else
                                  "id_unavailable" if response_hash is None else "recorded")
            return {
                "schema_version": "model-call-info/0.1", "status": "observed", "read_only": True,
                "model_called": False, "invoice_verified": False, "settlement_allowed": False,
                "ledger_id": observed["ledger_id"], "call_id": call["call_id"],
                "call_status": call["status"], "attempt": call["attempt"],
                "provider": call["provider"], "model": call["model"],
                "started_at": call["started_at"], "finished_at": call["finished_at"], "currency": currency,
                "accounting_basis": "configured_rate_estimate", "reserved_tokens": call["reserved_tokens"],
                "charged_tokens": call["charged_tokens"], "reserved_cost_micro_units": call["reserved_cost"],
                "charged_cost_micro_units": call["charged_cost"], "input_tokens": call["input_tokens"],
                "output_tokens": call["output_tokens"],
                "input_rate_micro_units_per_million": metadata.get(
                    "input_micro_units_per_million_tokens", metadata["input_micro_usd_per_token"] * 1_000_000),
                "output_rate_micro_units_per_million": metadata.get(
                    "output_micro_units_per_million_tokens", metadata["output_micro_usd_per_token"] * 1_000_000),
                "correlation_status": correlation_status, "response_id_sha256": response_hash,
            }
    except _CallInfoError:
        raise
    except OSError:
        _fail("io_error")
    except sqlite3.Error:
        _fail("database_error")
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("invalid")
