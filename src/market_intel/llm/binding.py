"""Fixed workspace ledger identity checks, without rollback protection claims."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3

from ..contracts import ContractError, instant
from ..ops.backup import _linked
from ..ops.llm_backup import _ledger
from .client import ModelClient, ModelError, _strict_loads


_IDENTITY = re.compile(r"ledger_[0-9a-f]{32}\Z")
_FIELDS = {"schema_version", "ledger_id", "ledger_path", "created_at"}


def _fail(code):
    raise ModelError(code) from None


@contextmanager
def _safe_errors():
    try:
        yield
    except sqlite3.Error:
        _fail("ledger_binding_database_error")
    except OSError:
        _fail("ledger_binding_io_error")


def _reject_links(path):
    if any(_linked(item) for item in (path, *path.parents)):
        _fail("ledger_binding_link_forbidden")


def _canonical(path):
    return os.path.normcase(str(path.resolve()))


def _paths(workspace):
    try:
        root = Path(workspace).absolute()
    except (TypeError, ValueError):
        _fail("ledger_workspace_invalid")
    _reject_links(root)
    if root.exists() and not root.is_dir():
        _fail("ledger_workspace_invalid")
    root = root.resolve()
    ledger, binding = root / "llm-state.db", root / "llm-binding.json"
    for path in (ledger, binding):
        _reject_links(path)
        if path.exists() and not path.is_file():
            _fail("ledger_binding_file_invalid")
    return root, ledger, binding


def _identity(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(ledger_identity)")}
    if columns != {"singleton", "ledger_id", "created_at"}:
        _fail("ledger_identity_invalid")
    rows = db.execute("SELECT singleton,ledger_id,created_at FROM ledger_identity").fetchall()
    if (len(rows) != 1 or rows[0]["singleton"] != 1
            or type(rows[0]["ledger_id"]) is not str or not _IDENTITY.fullmatch(rows[0]["ledger_id"])):
        _fail("ledger_identity_invalid")
    try:
        instant(rows[0]["created_at"], "ledger_identity.created_at")
    except (ContractError, TypeError):
        _fail("ledger_identity_invalid")
    return rows[0]["ledger_id"]


def _read_identity(ledger, *, validate=False):
    db = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2, 3):
            _fail("ledger_binding_schema_unsupported")
        if validate:
            try:
                _ledger(db)
            except ValueError:
                _fail("ledger_adoption_invalid")
        return _identity(db) if version == 3 else None
    finally:
        db.close()


def _read_binding(binding):
    try:
        value = _strict_loads(binding.read_text(encoding="utf-8"))
        if (type(value) is not dict or value.keys() != _FIELDS
                or value["schema_version"] != "ledger-binding/0.1"
                or type(value["ledger_id"]) is not str or not _IDENTITY.fullmatch(value["ledger_id"])
                or type(value["ledger_path"]) is not str):
            _fail("ledger_binding_invalid")
        instant(value["created_at"], "ledger_binding.created_at")
        return value
    except (ModelError, ContractError, UnicodeError, TypeError, RecursionError):
        _fail("ledger_binding_invalid")


def _result(status, ledger, ledger_id):
    return {"status": status, "ledger": _canonical(ledger), "ledger_id": ledger_id}


def check_workspace_ledger(workspace):
    """Read-only inspection: does not create files, migrate, or read credentials."""
    with _safe_errors():
        _, ledger, binding = _paths(workspace)
        if not binding.exists():
            if not ledger.exists():
                return _result("uninitialized", ledger, None)
            return _result("unbound", ledger, _read_identity(ledger))
        value = _read_binding(binding)
        if not ledger.exists():
            _fail("bound_ledger_missing")
        if value["ledger_path"] != _canonical(ledger):
            _fail("ledger_binding_path_mismatch")
        ledger_id = _read_identity(ledger)
        if ledger_id is None or ledger_id != value["ledger_id"]:
            _fail("ledger_binding_identity_mismatch")
        return _result("bound", ledger, ledger_id)


def _publish_binding(binding, ledger, ledger_id):
    value = {"schema_version": "ledger-binding/0.1", "ledger_id": ledger_id,
             "ledger_path": _canonical(ledger),
             "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")}
    # Exclusive creation never replaces an existing binding. A crash during this
    # write can leave invalid JSON; the next invocation rejects it, not repairs it.
    with binding.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def ensure_workspace_ledger(workspace, adopt_existing=False):
    """Initialize a new workspace or explicitly adopt an unbound existing ledger."""
    if type(adopt_existing) is not bool:
        _fail("ledger_adoption_flag_invalid")
    with _safe_errors():
        root, ledger, binding = _paths(workspace)
        if (root / "ledger-backup-manifest.json").exists():
            _fail("isolated_ledger_not_live")
        current = check_workspace_ledger(root)
        if current["status"] == "bound":
            return current
        if current["status"] == "unbound":
            if not adopt_existing:
                _fail("ledger_binding_required")
            _read_identity(ledger, validate=True)
            status = "adopted"
        else:
            root.mkdir(parents=True, exist_ok=True)
            _paths(root)  # Recheck the actual created ancestors before writing.
            # Claim the fixed filename without opening an existing concurrent DB.
            with ledger.open("xb"):
                pass
            status = "initialized"
        client = ModelClient(ledger)
        ledger_id = client.ledger_id
        if type(ledger_id) is not str or not _IDENTITY.fullmatch(ledger_id):
            _fail("ledger_identity_invalid")
        _publish_binding(binding, ledger, ledger_id)
        checked = check_workspace_ledger(root)
        return _result(status, ledger, checked["ledger_id"])
