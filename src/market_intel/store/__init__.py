"""Versioned SQLite evidence storage and mutable capture checkpoints."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 4


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError("unsupported_database_version")
        if version == 0:
            db.execute("BEGIN IMMEDIATE")
            for table, key in (("raw_items", "raw_item_id"), ("event_versions", "event_version_id"), ("evidence", "evidence_id")):
                extra = ", raw_item_id TEXT NOT NULL REFERENCES raw_items(id), event_version_id TEXT NOT NULL REFERENCES event_versions(id)" if table == "evidence" else ""
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL{extra})")
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'append_only'); END")
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_valid_id BEFORE INSERT ON {table} WHEN json_valid(NEW.payload)=0 OR json_extract(NEW.payload, '$.{key}') IS NOT NEW.id BEGIN SELECT RAISE(ABORT, 'invalid_payload_identity'); END")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS event_logical_version ON event_versions(json_extract(payload, '$.event_id'), json_extract(payload, '$.version'))")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS raw_content_identity ON raw_items(json_extract(payload, '$.source_id'), json_extract(payload, '$.source_item_key'), json_extract(payload, '$.content_sha256'))")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS availability_receipts (event_version_id TEXT PRIMARY KEY REFERENCES event_versions(id), committed_at TEXT NOT NULL)")
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS receipts_no_{operation.lower()} BEFORE {operation} ON availability_receipts BEGIN SELECT RAISE(ABORT, 'append_only'); END")
            db.execute("INSERT INTO schema_migrations VALUES (1, ?, 'Evidence schema and immutable identities')", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),))
            db.execute("PRAGMA user_version=1")
            db.commit()
            version = 1
        if version == 1:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DROP INDEX IF EXISTS raw_content_identity")
            db.execute("CREATE UNIQUE INDEX raw_content_identity ON raw_items(json_extract(payload, '$.source_id'), json_extract(payload, '$.source_item_key'), json_extract(payload, '$.content_sha256'), json_extract(payload, '$.title'))")
            db.execute("INSERT INTO schema_migrations VALUES (2, ?, 'Include title in RSS content identity')", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),))
            db.execute("PRAGMA user_version=2")
            db.commit()
            version = 2
        if version == 2:
            db.execute("BEGIN IMMEDIATE")
            for table in ("raw_items", "event_versions", "evidence", "availability_receipts"):
                key = "event_version_id" if table == "availability_receipts" else "id"
                conflict = f"EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key})"
                if table == "event_versions":
                    conflict += " OR EXISTS(SELECT 1 FROM event_versions WHERE json_extract(payload,'$.event_id') IS json_extract(NEW.payload,'$.event_id') AND json_extract(payload,'$.version') IS json_extract(NEW.payload,'$.version'))"
                elif table == "raw_items":
                    terms = " AND ".join(f"json_extract(payload,'$.{field}') IS json_extract(NEW.payload,'$.{field}')" for field in ("source_id", "source_item_key", "content_sha256", "title"))
                    conflict += " OR EXISTS(SELECT 1 FROM raw_items WHERE " + terms + ")"
                db.execute(f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN {conflict} BEGIN SELECT RAISE(ABORT, 'append_only_replace'); END")
            db.execute("INSERT INTO schema_migrations VALUES (3, ?, 'Reject replacement across immutable keys')", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),))
            db.execute("PRAGMA user_version=3")
            db.commit()
            version = 3
        if version == 3:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE capture_sources(source_id TEXT PRIMARY KEY,last_successful_scan_at TEXT NOT NULL,scan_items INTEGER NOT NULL,consumed_through_queue_id INTEGER,last_completed_at TEXT)")
            db.execute("CREATE TABLE capture_observations(source_id TEXT NOT NULL REFERENCES capture_sources(source_id),source_item_key TEXT NOT NULL,last_fingerprint TEXT NOT NULL,observation_no INTEGER NOT NULL,last_observed_at TEXT NOT NULL,PRIMARY KEY(source_id,source_item_key))")
            db.execute("CREATE TABLE capture_queue(queue_id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL REFERENCES capture_sources(source_id),source_item_key TEXT NOT NULL,observation_no INTEGER NOT NULL,fingerprint TEXT NOT NULL,item_json TEXT NOT NULL,observed_at TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','done')),attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,event_version_id TEXT REFERENCES event_versions(id),completed_at TEXT,UNIQUE(source_id,source_item_key,observation_no))")
            db.execute("CREATE INDEX capture_pending ON capture_queue(source_id,state,queue_id)")
            db.execute("INSERT INTO schema_migrations VALUES (4, ?, 'Durable source inbox and consumption checkpoints')", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),))
            db.execute("PRAGMA user_version=4")
            db.commit()
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("database_foreign_key_violation")
        return db
    except Exception:
        db.rollback()
        db.close()
        raise


def insert_immutable(db, table, key, obj):
    allowed = {"raw_items": "raw_item_id", "event_versions": "event_version_id", "evidence": "evidence_id"}
    if allowed.get(table) != key:
        raise ValueError("invalid_store_target")
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (obj[key],)).fetchone()
    if row:
        if row[0] != payload:
            raise ValueError(f"immutable_id_conflict: {obj[key]}")
        return
    if table == "evidence":
        db.execute("INSERT INTO evidence VALUES (?,?,?,?)", (obj[key], payload, obj["raw_item_id"], obj["event_version_id"]))
    else:
        db.execute(f"INSERT INTO {table} VALUES (?,?)", (obj[key], payload))


def record_visibility(db, event_version_id):
    """Conservative fence measured after the content transaction has committed."""
    if db.in_transaction:
        raise ValueError("visibility_requires_committed_content")
    if db.execute("SELECT 1 FROM availability_receipts WHERE event_version_id=?", (event_version_id,)).fetchone():
        return
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with db:
        db.execute("INSERT INTO availability_receipts VALUES (?,?)", (event_version_id, stamp))
