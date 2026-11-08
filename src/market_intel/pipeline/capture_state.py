"""Persistent single-writer capture queue. Schema is installed by store migrations."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re

from ..contracts import http_url


ITEM_FIELDS = {
    "source_item_key", "original_url", "title", "normalized_text",
    "source_time_text", "source_published_at", "source_time_precision",
    "source_timezone", "time_parse_status",
}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("invalid_capture_id")


def _queue_id(value):
    if type(value) is not int or value < 1:
        raise ValueError("invalid_queue_id")


def _time(value):
    if type(value) is not str or not _UTC.fullmatch(value):
        raise ValueError("capture_utc_timestamp_required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid_capture_timestamp") from exc


@contextmanager
def _write(db):
    if db.in_transaction:
        raise ValueError("capture_requires_clean_transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _item(value):
    if type(value) is not dict or value.keys() != ITEM_FIELDS:
        raise ValueError("invalid_capture_item_shape")
    # Keep only the declared RSS metadata shape. Never persist feed descriptions.
    item = dict(value)
    item["normalized_text"] = item["title"]
    for key in ITEM_FIELDS:
        field = item[key]
        if field is None and key in {"source_time_text", "source_published_at", "source_timezone"}:
            continue
        if type(field) is not str or not field.strip():
            raise ValueError("invalid_capture_item_field")
        try:
            field.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("invalid_capture_unicode") from exc
    # Reject credential-bearing or clearly unsafe links before they can enter
    # the durable inbox. Full bundle semantics are checked during consumption.
    http_url(item["original_url"], "capture.original_url")
    fingerprint = hashlib.sha256(_canonical({"title": item["title"], "text": item["title"]}).encode("utf-8")).hexdigest()
    return item, fingerprint


def discover(db, source_id, items, observed_at):
    """Atomically enqueue every changed title in a complete parsed small feed.

    Duplicate equal items in one snapshot are collapsed. Conflicting titles for
    one source key reject the entire snapshot before any scan progress is saved.
    """
    _id(source_id)
    observed = _time(observed_at)
    if type(items) is not list:
        raise ValueError("capture_items_list_required")
    validated = {}
    duplicates = 0
    for value in items:
        item, fingerprint = _item(value)
        key = item["source_item_key"]
        if key in validated:
            if validated[key][1] != fingerprint:
                raise ValueError("conflicting_snapshot_item")
            duplicates += 1
            continue
        validated[key] = (item, fingerprint)
    discovered = unchanged = 0
    with _write(db):
        row = db.execute("SELECT last_successful_scan_at FROM capture_sources WHERE source_id=?", (source_id,)).fetchone()
        if row and observed < _time(row[0]):
            raise ValueError("stale_capture_snapshot")
        if row is None:
            db.execute("INSERT INTO capture_sources(source_id,last_successful_scan_at,scan_items) VALUES (?,?,?)", (source_id, observed_at, len(items)))
        for key, (item, fingerprint) in validated.items():
            last = db.execute("SELECT last_fingerprint,observation_no FROM capture_observations WHERE source_id=? AND source_item_key=?", (source_id, key)).fetchone()
            if last and last[0] == fingerprint:
                unchanged += 1
                db.execute("UPDATE capture_observations SET last_observed_at=? WHERE source_id=? AND source_item_key=?", (observed_at, source_id, key))
                continue
            sequence = last[1] + 1 if last else 1
            db.execute("INSERT INTO capture_queue(source_id,source_item_key,observation_no,fingerprint,item_json,observed_at,state) VALUES (?,?,?,?,?,?,'pending')", (source_id, key, sequence, fingerprint, _canonical(item), observed_at))
            db.execute("INSERT INTO capture_observations(source_id,source_item_key,last_fingerprint,observation_no,last_observed_at) VALUES (?,?,?,?,?) ON CONFLICT(source_id,source_item_key) DO UPDATE SET last_fingerprint=excluded.last_fingerprint,observation_no=excluded.observation_no,last_observed_at=excluded.last_observed_at", (source_id, key, fingerprint, sequence, observed_at))
            discovered += 1
        db.execute("UPDATE capture_sources SET last_successful_scan_at=?,scan_items=? WHERE source_id=?", (observed_at, len(items), source_id))
    return {"discovered": discovered, "unchanged": unchanged, "scan_items": len(items), "duplicates": duplicates}


def pending(db, source_id, limit, *, exclude_queue_ids=()):
    """Return per-item FIFO heads; reading is not claiming or completing work.

    A consumer can exclude IDs already attempted in its current run. Exclusion
    does not unblock later revisions of that same item: only completion does.
    Lower-attempt heads run first so a persistent failure cannot starve healthy
    items across repeated limited runs. Queue ID breaks scheduling ties.
    """
    _id(source_id)
    if type(limit) is not int or limit < 1:
        raise ValueError("positive_capture_limit_required")
    if type(exclude_queue_ids) not in (tuple, list, set, frozenset):
        raise ValueError("capture_exclusions_collection_required")
    for queue_id in exclude_queue_ids:
        _queue_id(queue_id)
    exclusions = sorted(set(exclude_queue_ids))
    exclusion_sql = ""
    if exclusions:
        exclusion_sql = " AND q.queue_id NOT IN (" + ",".join("?" for _ in exclusions) + ")"
    rows = db.execute("""SELECT q.queue_id,q.source_item_key,q.observation_no,q.fingerprint,
        q.item_json,q.observed_at,q.attempts,q.last_error
        FROM capture_queue q WHERE q.source_id=? AND q.state='pending'
        AND NOT EXISTS (SELECT 1 FROM capture_queue older
          WHERE older.source_id=q.source_id AND older.source_item_key=q.source_item_key
          AND older.state='pending' AND older.queue_id<q.queue_id)"""
        + exclusion_sql + " ORDER BY q.attempts,q.queue_id LIMIT ?", (source_id, *exclusions, limit)).fetchall()
    return [{"queue_id": row[0], "source_id": source_id, "source_item_key": row[1],
             "observation_no": row[2], "fingerprint": row[3], "item": json.loads(row[4]),
             "observed_at": row[5], "attempts": row[6], "last_error": row[7]} for row in rows]


def complete(db, queue_id, event_version_id):
    """Mark done only after the matching latest event and receipt are committed."""
    _queue_id(queue_id)
    _id(event_version_id)
    with _write(db):
        row = db.execute("SELECT source_id,source_item_key,item_json,state,event_version_id FROM capture_queue WHERE queue_id=?", (queue_id,)).fetchone()
        if row is None:
            raise ValueError("capture_queue_missing")
        source_id, item_key, item_json, state, recorded_event = row
        if state == "done":
            if recorded_event != event_version_id:
                raise ValueError("capture_completion_conflict")
            return
        if db.execute("SELECT 1 FROM capture_queue WHERE source_id=? AND source_item_key=? AND state='pending' AND queue_id<? LIMIT 1", (source_id, item_key, queue_id)).fetchone():
            raise ValueError("capture_item_order_violation")
        committed = db.execute("SELECT e.payload FROM event_versions e JOIN availability_receipts r ON r.event_version_id=e.id WHERE e.id=?", (event_version_id,)).fetchone()
        if committed is None:
            raise ValueError("capture_receipt_required")
        event = json.loads(committed[0])
        latest = db.execute("SELECT id FROM event_versions WHERE json_extract(payload,'$.event_id')=? ORDER BY CAST(json_extract(payload,'$.version') AS INTEGER) DESC LIMIT 1", (event["event_id"],)).fetchone()
        if latest[0] != event_version_id:
            raise ValueError("capture_latest_event_required")
        raw_ids = event["input_raw_item_ids"]
        if len(raw_ids) != 1:
            raise ValueError("capture_single_raw_required")
        stored = db.execute("SELECT payload FROM raw_items WHERE id=?", (raw_ids[0],)).fetchone()
        if stored is None:
            raise ValueError("capture_raw_required")
        raw, item = json.loads(stored[0]), json.loads(item_json)
        if (raw["source_id"] != source_id or raw["source_item_key"] != item_key
                or raw["title"] != item["title"] or raw["normalized_text"] != item["title"]
                or raw["storage_policy"] != "metadata_only" or event["title"] != item["title"]
                or event["fact_summary"] != item["title"] or raw["is_synthetic"] is not False
                or event["is_synthetic"] is not False):
            raise ValueError("capture_completion_content_mismatch")
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        db.execute("UPDATE capture_queue SET state='done',event_version_id=?,completed_at=?,attempts=attempts+1,last_error=NULL WHERE queue_id=?", (event_version_id, stamp, queue_id))
        earliest = db.execute("SELECT MIN(queue_id) FROM capture_queue WHERE source_id=? AND state='pending'", (source_id,)).fetchone()[0]
        prefix = db.execute("SELECT MAX(queue_id) FROM capture_queue WHERE source_id=? AND state='done' AND (? IS NULL OR queue_id<?)", (source_id, earliest, earliest)).fetchone()[0]
        db.execute("UPDATE capture_sources SET consumed_through_queue_id=?,last_completed_at=? WHERE source_id=?", (prefix, stamp, source_id))


def fail(db, queue_id, reason):
    """Record a failed consumption attempt; keep the item pending for retry."""
    _queue_id(queue_id)
    if type(reason) is not str or not re.fullmatch(r"[A-Za-z0-9_.: -]{1,180}", reason):
        raise ValueError("capture_reason_code_required")
    with _write(db):
        row = db.execute("SELECT state FROM capture_queue WHERE queue_id=?", (queue_id,)).fetchone()
        if row is None:
            raise ValueError("capture_queue_missing")
        if row[0] != "pending":
            raise ValueError("capture_already_done")
        db.execute("UPDATE capture_queue SET attempts=attempts+1,last_error=? WHERE queue_id=?", (reason, queue_id))


def checkpoint(db, source_id):
    """Read discovery progress separately from the contiguous consumed prefix."""
    _id(source_id)
    row = db.execute("""SELECT s.last_successful_scan_at,s.scan_items,
        s.consumed_through_queue_id,s.last_completed_at,
        (SELECT COUNT(*) FROM capture_queue q WHERE q.source_id=s.source_id AND q.state='pending'),
        (SELECT COUNT(*) FROM capture_queue q WHERE q.source_id=s.source_id AND q.state='done')
        FROM capture_sources s WHERE s.source_id=?""", (source_id,)).fetchone()
    if row is None:
        row = (None, 0, None, None, 0, 0)
    return dict(zip(("source_id", "last_successful_scan_at", "scan_items", "consumed_through_queue_id", "last_completed_at", "pending", "done"), (source_id, *row)))
