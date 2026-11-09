"""Local append-only observations, without an external trust or rollback claim."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from ..contracts import ContractError, instant
from ..llm.client import ModelError, _strict_loads
from .backup import _linked


_ZERO = "0" * 64
_OBSERVATION_FIELDS = {"schema_version", "statement_sha256", "evidence_sha256", "preview"}
_PREVIEW_FIELDS = set("""schema_version status ledger_id utc_day currency provider evidence_kind
    read_only evidence_authenticated settlement_allowed local_calls statement_records missing_records
    pending_calls difference_records local_estimated_micro_units statement_micro_units delta_micro_units""".split())
_COLUMNS = ("seq", "event_id", "observation_key", "ledger_id", "recorded_at",
            "previous_sha256", "payload", "event_sha256")
_TABLE = """CREATE TABLE audit_events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    observation_key TEXT UNIQUE NOT NULL,
    ledger_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    previous_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    event_sha256 TEXT UNIQUE NOT NULL
)"""
_TRIGGERS = {
    "audit_events_no_update": """CREATE TRIGGER audit_events_no_update
        BEFORE UPDATE ON audit_events BEGIN
        SELECT RAISE(ABORT, 'audit_journal_append_only'); END""",
    "audit_events_no_delete": """CREATE TRIGGER audit_events_no_delete
        BEFORE DELETE ON audit_events BEGIN
        SELECT RAISE(ABORT, 'audit_journal_append_only'); END""",
    "audit_events_insert_guard": """CREATE TRIGGER audit_events_insert_guard
        BEFORE INSERT ON audit_events BEGIN
        SELECT CASE WHEN NEW.seq != COALESCE((SELECT MAX(seq) FROM audit_events),0)+1
            OR NEW.previous_sha256 != COALESCE(
                (SELECT event_sha256 FROM audit_events ORDER BY seq DESC LIMIT 1),
                '0000000000000000000000000000000000000000000000000000000000000000')
            OR EXISTS (SELECT 1 FROM audit_events WHERE seq=NEW.seq OR event_id=NEW.event_id
                OR observation_key=NEW.observation_key OR event_sha256=NEW.event_sha256)
            THEN RAISE(ABORT, 'audit_journal_insert_invalid') END; END""",
}


def _fail(code):
    raise ValueError(code) from None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pattern(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _integer(value, limit, *, signed=False):
    return type(value) is int and (-limit if signed else 0) <= value <= limit


def _observation(value):
    if type(value) is not dict or value.keys() != _OBSERVATION_FIELDS:
        _fail("audit_observation_invalid")
    if (value["schema_version"] != "ledger-audit-observation/0.1"
            or not _pattern(value["statement_sha256"], r"[0-9a-f]{64}")
            or not _pattern(value["evidence_sha256"], r"[0-9a-f]{64}")):
        _fail("audit_observation_invalid")
    p = value["preview"]
    if type(p) is not dict or p.keys() != _PREVIEW_FIELDS:
        _fail("audit_observation_invalid")
    if (p["schema_version"] != "ledger-reconciliation-preview/0.1"
            or not _pattern(p["ledger_id"], r"ledger_[0-9a-f]{32}")
            or p["currency"] not in ("USD", "CNY") or p["provider"] not in ("mock", "deepseek")
            or p["evidence_kind"] not in ("synthetic", "manual_statement")
            or p["read_only"] is not True or p["evidence_authenticated"] is not False
            or p["settlement_allowed"] is not False):
        _fail("audit_observation_invalid")
    try:
        if date.fromisoformat(p["utc_day"]).isoformat() != p["utc_day"]:
            _fail("audit_observation_invalid")
    except (TypeError, ValueError):
        _fail("audit_observation_invalid")
    for key in ("local_calls", "statement_records", "missing_records", "pending_calls", "difference_records"):
        if not _integer(p[key], 10**7):
            _fail("audit_observation_invalid")
    if (p["statement_records"] + p["missing_records"] != p["local_calls"]
            or p["pending_calls"] > p["local_calls"]
            or p["difference_records"] > p["statement_records"]):
        _fail("audit_observation_invalid")
    for key in ("local_estimated_micro_units", "statement_micro_units"):
        if not _integer(p[key], 10**19):
            _fail("audit_observation_invalid")
    if (not _integer(p["delta_micro_units"], 10**19, signed=True)
            or p["delta_micro_units"] != p["statement_micro_units"] - p["local_estimated_micro_units"]):
        _fail("audit_observation_invalid")
    if ((not p["local_calls"] and p["local_estimated_micro_units"] != 0)
            or (not p["statement_records"] and p["statement_micro_units"] != 0)
            or (not p["missing_records"] and not p["difference_records"] and p["delta_micro_units"] != 0)):
        _fail("audit_observation_invalid")
    expected = ("incomplete" if p["missing_records"] or p["pending_calls"] else
                "differences" if p["difference_records"] else "matched_estimates")
    if p["status"] != expected:
        _fail("audit_observation_invalid")
    try:
        payload = _canonical(value)
        _hash(payload)
        return payload
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("audit_observation_invalid")


def _stamp(value):
    try:
        return instant(value, "audit.recorded_at")
    except (ContractError, TypeError):
        _fail("audit_journal_time_invalid")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _path(path):
    try:
        path = Path(path).absolute()
        if any(_linked(part) for part in (path, *path.parents)):
            _fail("audit_journal_link_forbidden")
        if path.exists() and not path.is_file():
            _fail("audit_journal_file_invalid")
        return path.resolve()
    except (TypeError, ValueError) as exc:
        if type(exc) is ValueError and str(exc).startswith("audit_"):
            raise
        _fail("audit_journal_path_invalid")


@contextmanager
def _database(path, *, readonly=False):
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                             uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        if readonly:
            db.execute("PRAGMA query_only=ON")
        with db:
            yield db
    finally:
        if db is not None:
            db.close()


def _normalized(sql):
    return " ".join(sql.split())


def _verify(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        _fail("audit_journal_schema_invalid")
    if db.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok":
        _fail("audit_journal_database_invalid")
    objects = {row["name"]: (row["type"], row["sql"]) for row in db.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    expected = {"audit_events": ("table", _TABLE),
                **{name: ("trigger", sql) for name, sql in _TRIGGERS.items()}}
    if (objects.keys() != expected.keys() or any(
            objects[name][0] != kind or _normalized(objects[name][1] or "") != _normalized(sql)
            for name, (kind, sql) in expected.items())):
        _fail("audit_journal_schema_invalid")
    rows = db.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
    previous, last_time = _ZERO, None
    for seq, row in enumerate(rows, 1):
        if (row["seq"] != seq or not _pattern(row["event_id"], r"audit_[0-9a-f]{32}")
                or not _pattern(row["observation_key"], r"[0-9a-f]{64}")
                or not _pattern(row["event_sha256"], r"[0-9a-f]{64}")
                or row["previous_sha256"] != previous):
            _fail("audit_journal_chain_invalid")
        moment = _stamp(row["recorded_at"])
        if last_time is not None and moment < last_time:
            _fail("audit_journal_time_invalid")
        try:
            observation = _strict_loads(row["payload"])
            payload = _observation(observation)
        except (ModelError, TypeError, ValueError, UnicodeError, RecursionError):
            _fail("audit_journal_payload_invalid")
        if (payload != row["payload"] or _hash(payload) != row["observation_key"]
                or row["ledger_id"] != observation["preview"]["ledger_id"]):
            _fail("audit_journal_chain_invalid")
        material = {key: row[key] for key in _COLUMNS if key != "event_sha256"}
        if _hash(_canonical(material)) != row["event_sha256"]:
            _fail("audit_journal_chain_invalid")
        previous, last_time = row["event_sha256"], moment
    return rows


@contextmanager
def _safe_errors():
    try:
        yield
    except OSError:
        _fail("audit_journal_io_error")
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0)
        _fail("audit_journal_busy" if (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
              else "audit_journal_database_error")
    except (UnicodeError, RecursionError):
        _fail("audit_journal_data_invalid")


def append_observation(journal_path, observation):
    """Explicitly append an unverified observation; never modify a model ledger."""
    with _safe_errors():
        payload = _observation(observation)
        key = _hash(payload)
        ledger_id = json.loads(payload)["preview"]["ledger_id"]
        path = _path(journal_path)
        created = not path.exists()
        if created:
            path.parent.mkdir(parents=True, exist_ok=True)
            path = _path(path)
            with path.open("xb"):
                pass
        with _database(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if created:
                db.execute(_TABLE)
                for sql in _TRIGGERS.values():
                    db.execute(sql)
                db.execute("PRAGMA user_version=1")
            rows = _verify(db)
            existing = next((row for row in rows if row["observation_key"] == key), None)
            if existing is None:
                stamp = _now()
                moment = _stamp(stamp)
                if rows and moment < _stamp(rows[-1]["recorded_at"]):
                    _fail("audit_journal_clock_regression")
                material = {"seq": len(rows) + 1, "event_id": "audit_" + uuid4().hex,
                            "observation_key": key, "ledger_id": ledger_id,
                            "recorded_at": stamp, "previous_sha256": rows[-1]["event_sha256"] if rows else _ZERO,
                            "payload": payload}
                material["event_sha256"] = _hash(_canonical(material))
                db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?)",
                           tuple(material[column] for column in _COLUMNS))
                existing, count, status = material, len(rows) + 1, "recorded"
            else:
                count, status = len(rows), "already_recorded"
            return {"schema_version": "ledger-audit-result/0.1", "status": status,
                    **{field: existing[field] for field in ("event_id", "seq", "ledger_id", "event_sha256")},
                    "events": count, "trusted_high_water": False,
                    "settlement_allowed": False, "switch_allowed": False}


def verify_audit_journal(journal_path):
    """Read-only local schema/chain validation, without external authenticity."""
    with _safe_errors():
        path = _path(journal_path)
        if not path.is_file():
            _fail("audit_journal_missing")
        with _database(path, readonly=True) as db:
            db.execute("BEGIN")
            rows = _verify(db)
            return {"schema_version": "ledger-audit-verification/0.1", "status": "verified_local_chain",
                    "events": len(rows), "last_event_sha256": rows[-1]["event_sha256"] if rows else _ZERO,
                    "trusted_high_water": False, "settlement_allowed": False, "switch_allowed": False}
