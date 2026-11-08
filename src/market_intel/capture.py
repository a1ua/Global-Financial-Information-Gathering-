"""Bounded official-source capture with a durable metadata inbox."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .adapters.news.rss import parse_rss
from .adapters.news.nbs import parse_nbs_list
from .offline import canonical, digest, ingest_bundle
from .pipeline.capture_state import checkpoint, complete, discover, fail, pending
from .store import record_visibility
from .transport import ENDPOINTS, fetch

FED_URL = ENDPOINTS["fed"]
NBS_URL = ENDPOINTS["nbs"]
SOURCES = {
    "fed": {"id": "fed_press_all", "version": "fed-rss-0.1", "markets": ["US", "GLOBAL"], "category": "other", "normalization": "rss-text/0.1"},
    "nbs": {"id": "nbs_releases", "version": "nbs-list-0.1", "markets": ["A"], "category": "macro", "normalization": "nbs-list/0.1"},
}


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_fed():
    return fetch("fed")


def make_bundle(db, item, *, fetched_at, excerpt=False, source="fed"):
    """Preserve source text verbatim; metadata mode never invents body facts."""
    config = SOURCES[source]
    source_id = config["id"]
    text = item["normalized_text"][:350] if excerpt and item["normalized_text"] else item["title"]
    metadata_only = not excerpt or not item["normalized_text"]
    fingerprint = digest(canonical({"title": item["title"], "text": text}))
    item_identity = digest(source_id + "\n" + item["source_item_key"])
    raw_id = "raw_" + digest(item_identity + fingerprint)
    event_id = "event_" + item_identity
    previous = db.execute("SELECT payload FROM event_versions WHERE json_extract(payload,'$.event_id')=? ORDER BY CAST(json_extract(payload,'$.version') AS INTEGER) DESC LIMIT 1", (event_id,)).fetchone()
    previous = json.loads(previous[0]) if previous else None
    if previous and previous["input_raw_item_ids"] == [raw_id]:
        record_visibility(db, previous["event_version_id"])
        return None
    existing = db.execute("SELECT payload FROM raw_items WHERE id=?", (raw_id,)).fetchone()
    available = now()
    content_hash = digest(text)
    raw = json.loads(existing[0]) if existing else {
        "schema_version": "raw-item/0.1", "raw_item_id": raw_id, "source_id": source_id,
        "source_config_version": config["version"], "source_item_key": item["source_item_key"],
        "original_url": item["original_url"], "canonical_url": item["original_url"],
        "source_tier": "primary", "title": item["title"],
        "source_time_text": item["source_time_text"], "source_timezone": item["source_timezone"],
        "source_time_precision": item["source_time_precision"], "time_parse_status": item["time_parse_status"],
        "source_published_at": item["source_published_at"],
        "source_published_date": item["source_time_text"] if item["time_parse_status"] == "date_only" else None,
        "first_seen_at": fetched_at, "fetched_at": fetched_at, "persisted_at": available, "available_at": available,
        "storage_policy": "metadata_only" if metadata_only else "excerpt_metadata",
        "content_ref": f"raw/{content_hash}.txt", "content_sha256": content_hash,
        "normalized_text": text, "normalization_version": config["normalization"],
        "supersedes_raw_item_id": previous["input_raw_item_ids"][0] if previous else None,
        "is_synthetic": False,
    }
    version = previous["version"] + 1 if previous else 1
    version_id = "ev_" + digest(event_id + str(version) + raw_id)
    evidence_id = "evidence_" + digest(version_id)
    event = {
        "schema_version": "event-version/0.1", "event_id": event_id, "event_version_id": version_id,
        "version": version, "title": item["title"], "fact_summary": text, "category": config["category"],
        "markets": list(config["markets"]), "entities": [], "evidence_ids": [evidence_id],
        "input_raw_item_ids": [raw_id], "extraction_method": "rule", "extractor_version": "rss-verbatim/0.1",
        "extraction_quality": "metadata_only" if metadata_only else "structurally_valid",
        "processed_at": available, "available_at": available,
        "supersedes_event_version_id": previous["event_version_id"] if previous else None,
        "is_synthetic": False,
    }
    evidence = {
        "schema_version": "evidence/0.1", "evidence_id": evidence_id,
        "event_version_id": version_id, "raw_item_id": raw_id, "relation": "reports",
        "claim_key": "fact_summary", "normalization_version": config["normalization"],
        "locator": {"field": "normalized_text", "offset_unit": "unicode_code_point", "start": 0, "end": len(text)},
        "quote": text, "validation_status": "exact_quote_match", "available_at": available, "is_synthetic": False,
    }
    return {"raw": raw, "event": event, "evidence": evidence}


def consume_pending(db, workspace, source, limit):
    source_id = SOURCES[source]["id"]
    attempted = []
    result = {"inserted": 0, "unchanged": 0, "consumed": 0, "quarantined": []}
    while len(attempted) < limit:
        rows = pending(db, source_id, 1, exclude_queue_ids=attempted)
        if not rows:
            break
        row = rows[0]
        attempted.append(row["queue_id"])
        try:
            bundle = make_bundle(db, row["item"], fetched_at=row["observed_at"], source=source)
            if bundle is None:
                event_id = "event_" + digest(source_id + "\n" + row["source_item_key"])
                event_version_id = db.execute("SELECT id FROM event_versions WHERE json_extract(payload,'$.event_id')=? ORDER BY CAST(json_extract(payload,'$.version') AS INTEGER) DESC LIMIT 1", (event_id,)).fetchone()[0]
                result["unchanged"] += 1
            else:
                ingest_bundle(db, bundle, workspace)
                event_version_id = bundle["event"]["event_version_id"]
                result["inserted"] += 1
            complete(db, row["queue_id"], event_version_id)
            result["consumed"] += 1
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            # Retain failed work; never persist arbitrary source text in errors.
            fail(db, row["queue_id"], type(exc).__name__)
            result["quarantined"].append({"queue_id": row["queue_id"], "error_type": type(exc).__name__})
    result["checkpoint"] = checkpoint(db, source_id)
    result["attempted"] = len(attempted)
    return result


def collect_source(db, workspace, *, source="fed", limit=5, transport="python", fetcher=None, resume=False):
    if source not in SOURCES:
        raise ValueError("unknown_source")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit_must_be_1_to_100")
    source_id = SOURCES[source]["id"]
    run = {"run_id": "capture_" + uuid4().hex, "started_at": now(), "status": "failed", "source_url": ENDPOINTS[source],
           "source_id": source_id, "mode": "resume" if resume else "discover_and_consume",
           "is_synthetic": False, "retention_mode": "metadata_only"}
    try:
        if not resume:
            data, response = fetcher() if fetcher else fetch(source, transport=transport)
            run["response"] = response
            items = parse_rss(data, feed_url=FED_URL) if source == "fed" else parse_nbs_list(data, page_url=NBS_URL)
            run["discovery"] = discover(db, source_id, items, response["fetched_at"])
        elif checkpoint(db, source_id)["last_successful_scan_at"] is None:
            raise ValueError("source_never_discovered")
        run.update(consume_pending(db, workspace, source, limit))
        run["status"] = "degraded" if run["quarantined"] or run["checkpoint"]["pending"] else "succeeded"
        return run
    except Exception as exc:
        run["error_type"] = type(exc).__name__
        run["error"] = str(exc)[:180]
        raise
    finally:
        run["finished_at"] = now()
        folder = Path(workspace) / "runs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (run["run_id"] + ".json")).write_text(canonical(run), encoding="utf-8", newline="")


def collect_fed(db, workspace, *, limit=5, excerpt=False, fetcher=fetch_fed):
    if excerpt:
        raise ValueError("durable_capture_is_metadata_only")
    return collect_source(db, workspace, source="fed", limit=limit, fetcher=fetcher)


def collect_all(db, workspace, *, limit=5, transport="python", resume=False, fetchers=None):
    results = []
    for source in SOURCES:
        try:
            results.append(collect_source(db, workspace, source=source, limit=limit, transport=transport,
                                          resume=resume, fetcher=(fetchers or {}).get(source)))
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            results.append({"source_id": SOURCES[source]["id"], "status": "failed", "error_type": type(exc).__name__})
    states = [run["status"] for run in results]
    return {"status": "succeeded" if all(s == "succeeded" for s in states) else ("failed" if all(s == "failed" for s in states) else "degraded"), "sources": results}
