"""Append-only storage for validated synthetic predictions."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from ..contracts import identifier, instant
from ..contracts.candidate_snapshot import canonical_json, payload_sha256
from ..contracts.prediction_input import validate_prediction_input


_CONTEXT = ("target_instrument_id", "benchmark_instrument_id", "direction_basis",
            "evaluation_protocol_id", "evaluation_protocol_sha256",
            "calendar_snapshot_id", "calendar_snapshot_sha256")


def _fail(code):
    raise ValueError("prediction_" + code) from None


def migrate_predictions(db):
    """Install schema 5 objects inside the caller's migration transaction."""
    if not db.in_transaction:
        _fail("migration_transaction_required")
    db.execute("""CREATE TABLE predictions(
        id TEXT PRIMARY KEY, family_id TEXT NOT NULL,
        predecessor_id TEXT UNIQUE REFERENCES predictions(id),
        payload TEXT NOT NULL, content_sha256 TEXT NOT NULL
    ) WITHOUT ROWID""")
    db.execute("""CREATE UNIQUE INDEX prediction_family_root ON predictions(family_id)
        WHERE predecessor_id IS NULL""")
    db.execute("""CREATE TABLE prediction_refs(
        prediction_id TEXT NOT NULL REFERENCES predictions(id),
        event_version_id TEXT NOT NULL REFERENCES event_versions(id),
        evidence_id TEXT NOT NULL REFERENCES evidence(id),
        PRIMARY KEY(prediction_id,event_version_id),
        UNIQUE(prediction_id,evidence_id)
    ) WITHOUT ROWID""")
    db.execute("""CREATE TABLE prediction_receipts(
        prediction_id TEXT PRIMARY KEY REFERENCES predictions(id),
        content_sha256 TEXT NOT NULL, committed_at TEXT NOT NULL
    ) WITHOUT ROWID""")
    for table in ("predictions", "prediction_refs", "prediction_receipts"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER {table}_no_{operation.lower()}
                BEFORE {operation} ON {table}
                BEGIN SELECT RAISE(ABORT,'append_only'); END""")

    # Compare materialized identities and protect all unique keys even when
    # recursive_triggers is off, including the partial index for family roots.
    context_match = " AND ".join(
        f"json_extract(p.payload,'$.content.{field}') IS json_extract(NEW.payload,'$.content.{field}')"
        for field in _CONTEXT
    )
    db.execute(f"""CREATE TRIGGER predictions_insert_guard BEFORE INSERT ON predictions
        WHEN json_valid(NEW.payload)=0
        OR json_extract(NEW.payload,'$.content.prediction_id') IS NOT NEW.id
        OR json_extract(NEW.payload,'$.content.prediction_family_id') IS NOT NEW.family_id
        OR json_extract(NEW.payload,'$.content.supersedes_prediction_id') IS NOT NEW.predecessor_id
        OR EXISTS(SELECT 1 FROM predictions p WHERE p.id=NEW.id
                   OR p.predecessor_id=NEW.predecessor_id
                   OR (p.predecessor_id IS NULL AND NEW.predecessor_id IS NULL
                       AND p.family_id=NEW.family_id))
        OR (NEW.predecessor_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM predictions p JOIN prediction_receipts r ON r.prediction_id=p.id
            WHERE p.id=NEW.predecessor_id AND p.family_id=NEW.family_id AND {context_match}))
        BEGIN SELECT RAISE(ABORT,'prediction_insert_invalid'); END""")
    db.execute("""CREATE TRIGGER prediction_refs_insert_guard BEFORE INSERT ON prediction_refs
        WHEN EXISTS(SELECT 1 FROM prediction_receipts WHERE prediction_id=NEW.prediction_id)
        OR EXISTS(SELECT 1 FROM prediction_refs WHERE prediction_id=NEW.prediction_id
                  AND (event_version_id=NEW.event_version_id OR evidence_id=NEW.evidence_id))
        OR NOT EXISTS(
            SELECT 1 FROM predictions p
            JOIN json_each(p.payload,'$.inputs.evidence_snapshot.input_manifest.candidates') c
            JOIN evidence e ON e.id=NEW.evidence_id AND e.event_version_id=NEW.event_version_id
                AND e.raw_item_id=json_extract(c.value,'$.raw_item_id')
            WHERE p.id=NEW.prediction_id AND e.id=json_extract(c.value,'$.evidence_id')
                AND e.event_version_id=json_extract(c.value,'$.event_version_id'))
        BEGIN SELECT RAISE(ABORT,'prediction_ref_invalid'); END""")
    db.execute("""CREATE TRIGGER prediction_receipts_insert_guard BEFORE INSERT ON prediction_receipts
        WHEN EXISTS(SELECT 1 FROM prediction_receipts WHERE prediction_id=NEW.prediction_id)
        OR NOT EXISTS(SELECT 1 FROM predictions p WHERE p.id=NEW.prediction_id
            AND p.content_sha256=NEW.content_sha256
            AND (p.predecessor_id IS NULL OR EXISTS(
                SELECT 1 FROM prediction_receipts r WHERE r.prediction_id=p.predecessor_id))
            AND json_array_length(p.payload,'$.content.evidence_ids') =
                (SELECT count(*) FROM prediction_refs WHERE prediction_id=p.id))
        BEGIN SELECT RAISE(ABORT,'prediction_receipt_invalid'); END""")


@contextmanager
def _transaction(db, *, write):
    db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


@contextmanager
def _read_transaction(db):
    if db.in_transaction:
        yield
    else:
        with _transaction(db, write=False):
            yield


def _schema(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 5:
        _fail("schema_unsupported")


def _candidate_pairs(value):
    candidates = value["inputs"]["evidence_snapshot"]["input_manifest"]["candidates"]
    return sorted((candidate["event_version_id"], candidate["evidence_id"]) for candidate in candidates)


def _stored(db, prediction_id):
    row = db.execute("""SELECT p.id,p.family_id,p.predecessor_id,p.payload,p.content_sha256,
        r.prediction_id,r.content_sha256,r.committed_at FROM predictions p
        LEFT JOIN prediction_receipts r ON r.prediction_id=p.id WHERE p.id=?""",
                     (prediction_id,)).fetchone()
    if row is None:
        return None
    identity, family, predecessor, payload, digest, receipt_id, receipt_hash, stamp = row
    value = json.loads(payload)
    validate_prediction_input(value)
    content = value["content"]
    if (payload != canonical_json(value) or identity != content["prediction_id"]
            or family != content["prediction_family_id"]
            or predecessor != content["supersedes_prediction_id"]
            or digest != payload_sha256(content)):
        _fail("record_invalid")
    links = db.execute("""SELECT event_version_id,evidence_id FROM prediction_refs
        WHERE prediction_id=? ORDER BY event_version_id,evidence_id""", (identity,))
    if [tuple(link) for link in links] != _candidate_pairs(value):
        _fail("record_invalid")
    receipt = None
    if receipt_id is not None:
        if (receipt_hash != digest
                or instant(stamp, "committed_at") < instant(content["created_at"], "created_at")):
            _fail("record_invalid")
        receipt = {"schema_version": "prediction-receipt/0.1", "prediction_id": identity,
                   "content_sha256": receipt_hash, "committed_at": stamp}
    return {**value, "receipt": receipt}


def _assert_parent(child, parent):
    content, receipt = child["content"], child["receipt"]
    if parent is None or parent["receipt"] is None:
        _fail("predecessor_invalid")
    base = parent["content"]
    if (base["prediction_family_id"] != content["prediction_family_id"]
            or any(base[field] != content[field] for field in _CONTEXT)):
        _fail("predecessor_invalid")
    if receipt is not None and instant(receipt["committed_at"], "committed_at") < instant(
            parent["receipt"]["committed_at"], "committed_at"):
        _fail("record_invalid")


def _parent(db, record):
    predecessor = record["content"]["supersedes_prediction_id"]
    if predecessor is None:
        return None
    parent = _stored(db, predecessor)
    _assert_parent(record, parent)
    return parent


def _verify_evidence(db, root, value, *, verify_database=True):
    # Import lazily because the candidate pipeline uses backup path utilities.
    from ..pipeline.candidate_snapshot import _load

    previous = db.row_factory
    try:
        db.row_factory = sqlite3.Row
        _load(db, root, value["inputs"]["evidence_snapshot"], verify_database=verify_database)
    except (OSError, ValueError, sqlite3.Error):
        _fail("inputs_unavailable")
    finally:
        db.row_factory = previous


def _workspace(db, workspace):
    from ..pipeline.evidence_candidates import _paths

    try:
        root, database = _paths(workspace)
        main = next(row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main")
        if not main or Path(main).resolve(strict=True) != database:
            _fail("workspace_invalid")
        return root
    except (OSError, ValueError):
        _fail("workspace_invalid")


def _system_clock():
    return datetime.now(timezone.utc)


def _stamp(clock, record, parent):
    value = clock()
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        _fail("clock_invalid")
    bound = instant(record["content"]["created_at"], "created_at")
    if parent is not None:
        bound = max(bound, instant(parent["receipt"]["committed_at"], "committed_at"))
    if value < bound:
        _fail("clock_regressed")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def submit_prediction(db, workspace, value, *, clock=_system_clock):
    """Persist one prediction, taking a visibility sample after its content commits."""
    if db.in_transaction:
        _fail("active_transaction")
    _schema(db)
    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        _fail("foreign_keys_required")
    validate_prediction_input(value)
    payload = canonical_json(value)
    value = json.loads(payload)
    content = value["content"]
    identity, predecessor = content["prediction_id"], content["supersedes_prediction_id"]
    digest = payload_sha256(content)
    root = _workspace(db, workspace)
    try:
        with _transaction(db, write=True):
            existing = _stored(db, identity)
            if existing is not None and (existing["content"] != content or existing["inputs"] != value["inputs"]):
                _fail("id_conflict")
            _verify_evidence(db, root, value)
            if existing is None:
                _parent(db, {**value, "receipt": None})
                db.execute("INSERT INTO predictions VALUES (?,?,?,?,?)",
                           (identity, content["prediction_family_id"], predecessor, payload, digest))
                db.executemany("INSERT INTO prediction_refs VALUES (?,?,?)",
                               ((identity, *pair) for pair in _candidate_pairs(value)))
            elif existing["receipt"] is not None:
                _parent(db, existing)
                return existing

        # In a separate write transaction another retry may already have sealed
        # this identity. Keep its receipt and never sample a new time for it.
        with _transaction(db, write=True):
            record = _stored(db, identity)
            if record is None:
                _fail("record_invalid")
            parent = _parent(db, record)
            if record["receipt"] is None:
                stamp = _stamp(clock, record, parent)
                db.execute("INSERT INTO prediction_receipts VALUES (?,?,?)", (identity, digest, stamp))
                record = _stored(db, identity)
        return record
    except sqlite3.IntegrityError:
        _fail("write_conflict")
    except sqlite3.Error:
        _fail("storage_error")


def read_prediction(db, prediction_id):
    """Read one validated, receipted prediction by its exact identity."""
    if db.in_transaction:
        _fail("active_transaction")
    try:
        identifier(prediction_id, "prediction_id")
        with _read_transaction(db):
            _schema(db)
            record = _stored(db, prediction_id)
            if record is None or record["receipt"] is None:
                return None
            _parent(db, record)
            return record
    except (ValueError, TypeError, sqlite3.Error, RecursionError):
        _fail("record_invalid")


def _schema_objects(db):
    return [tuple(row) for row in db.execute(
        """SELECT type,name,tbl_name,sql FROM sqlite_schema
        WHERE tbl_name IN ('predictions','prediction_refs','prediction_receipts')
        ORDER BY type,name""")]


def _verify_schema_objects(db):
    from contextlib import closing

    with closing(sqlite3.connect(":memory:")) as scratch:
        with _transaction(scratch, write=True):
            migrate_predictions(scratch)
        if _schema_objects(db) != _schema_objects(scratch):
            _fail("inventory_invalid")


def verify_prediction_inventory(db, workspace):
    """Validate prediction contents, exact evidence, receipts and correction chains."""
    try:
        with _read_transaction(db):
            _schema(db)
            _verify_schema_objects(db)
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                _fail("inventory_invalid")
            roots, successors = set(), {}
            records = {}
            for (identity,) in db.execute("SELECT id FROM predictions"):
                record = _stored(db, identity)
                _verify_evidence(db, Path(workspace), record, verify_database=False)
                content = record["content"]
                family, predecessor = content["prediction_family_id"], content["supersedes_prediction_id"]
                if predecessor is None:
                    if family in roots:
                        _fail("inventory_invalid")
                    roots.add(family)
                else:
                    if predecessor in successors:
                        _fail("inventory_invalid")
                    successors[predecessor] = identity
                records[identity] = record

            # Follow each root once. Missing parents, cycles and disconnected
            # chains cannot be reached, even if someone rewrote all their rows.
            visited = set()
            for identity, record in records.items():
                if record["content"]["supersedes_prediction_id"] is not None:
                    continue
                while identity is not None:
                    if identity in visited:
                        _fail("inventory_invalid")
                    visited.add(identity)
                    next_id = successors.get(identity)
                    if next_id is not None:
                        _assert_parent(records[next_id], records[identity])
                    identity = next_id
            if len(visited) != len(records):
                _fail("inventory_invalid")
            return {"predictions": len(records),
                    "receipted_predictions": sum(row["receipt"] is not None for row in records.values())}
    except (ValueError, TypeError, OSError, sqlite3.Error, RecursionError):
        _fail("inventory_invalid")
