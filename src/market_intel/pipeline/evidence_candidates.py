"""Read-only, versioned evidence candidate plans; no model or source access."""

import hashlib
import json
from pathlib import Path
import sqlite3

from ..contracts import ContractError, instant, validate_bundle
from ..llm.client import ModelError, _safe_json, _strict_loads
from ..ops.backup import _file, _linked


def _fail(code):
    raise ValueError(code) from None


def _stamp(value):
    try:
        return instant(value, "evidence_candidate.timestamp")
    except (ContractError, TypeError):
        _fail("evidence_candidate_timestamp_invalid")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse(payload):
    try:
        value = _strict_loads(payload)
        _safe_json(value)
        return value
    except (ModelError, TypeError, UnicodeError, RecursionError):
        _fail("evidence_candidate_json_invalid")


def _paths(workspace):
    try:
        root = Path(workspace).absolute()
    except (TypeError, ValueError):
        _fail("evidence_candidate_workspace_invalid")
    if any(_linked(path) for path in (root, *root.parents)):
        _fail("evidence_candidate_link_forbidden")
    if not root.is_dir():
        _fail("evidence_candidate_workspace_missing")
    root = root.resolve(strict=True)
    database = root / "market.db"
    if _linked(database):
        _fail("evidence_candidate_link_forbidden")
    if not database.is_file():
        _fail("evidence_candidate_database_missing")
    return root, database


def _payload(db, table, key, identity):
    row = db.execute("SELECT * FROM " + table + " WHERE id=?", (key,)).fetchone()
    if row is None:
        _fail("evidence_candidate_reference_missing")
    value = _parse(row["payload"])
    if type(value) is not dict or value.get(identity) != row["id"]:
        _fail("evidence_candidate_identity_invalid")
    return row, value


def _bundles(db):
    result, logical_versions = [], set()
    for row in db.execute("SELECT id,payload FROM event_versions").fetchall():
        event = _parse(row["payload"])
        if type(event) is not dict or event.get("event_version_id") != row["id"]:
            _fail("evidence_candidate_identity_invalid")
        for field in ("input_raw_item_ids", "evidence_ids"):
            if type(event.get(field)) is not list or len(event[field]) != 1 or type(event[field][0]) is not str:
                _fail("evidence_candidate_bundle_invalid")
        raw_id, evidence_id = event["input_raw_item_ids"][0], event["evidence_ids"][0]
        _, raw = _payload(db, "raw_items", raw_id, "raw_item_id")
        evidence_row, evidence = _payload(db, "evidence", evidence_id, "evidence_id")
        if evidence_row["raw_item_id"] != raw_id or evidence_row["event_version_id"] != row["id"]:
            _fail("evidence_candidate_identity_invalid")
        bundle = {"raw": raw, "event": event, "evidence": evidence}
        try:
            validate_bundle(bundle)
        except (ContractError, KeyError, TypeError, ValueError, UnicodeError):
            _fail("evidence_candidate_bundle_invalid")
        logical = event["event_id"], event["version"]
        if logical in logical_versions:
            _fail("evidence_candidate_version_conflict")
        logical_versions.add(logical)
        result.append(bundle)
    return result


def _descriptor(bundle, effective, receipt):
    raw, event, evidence = (bundle[key] for key in ("raw", "event", "evidence"))
    return {"event_id": event["event_id"], "event_version_id": event["event_version_id"],
            "version": event["version"], "event_available_at": event["available_at"],
            "receipt_committed_at": receipt,
            "effective_available_at": effective.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "raw_item_id": raw["raw_item_id"], "evidence_id": evidence["evidence_id"],
            "source_id": raw["source_id"], "source_config_version": raw["source_config_version"],
            "content_ref": raw["content_ref"], "content_sha256": raw["content_sha256"],
            "raw_payload_sha256": _hash(raw), "event_payload_sha256": _hash(event),
            "evidence_payload_sha256": _hash(evidence), "is_synthetic": event["is_synthetic"]}


def _plan(db, root, cutoff, limit, max_candidates, include_synthetic):
    if db.execute("PRAGMA user_version").fetchone()[0] != 4:
        _fail("evidence_candidate_schema_unsupported")
    if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
        _fail("evidence_candidate_database_invalid")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        _fail("evidence_candidate_foreign_keys_invalid")
    bundles = _bundles(db)
    excluded = missing = after = eligible_versions = 0
    latest = {}
    for bundle in bundles:
        event = bundle["event"]
        if event["is_synthetic"] and not include_synthetic:
            excluded += 1
            continue
        effective = max(_stamp(bundle[key]["available_at"]) for key in ("raw", "event", "evidence"))
        receipt_text = None
        if not event["is_synthetic"]:
            receipt = db.execute("SELECT committed_at FROM availability_receipts WHERE event_version_id=?",
                                 (event["event_version_id"],)).fetchone()
            if receipt is None:
                missing += 1
                continue
            receipt_text = receipt[0]
            receipt_time = _stamp(receipt_text)
            if receipt_time < effective:
                _fail("evidence_candidate_receipt_invalid")
            effective = max(effective, receipt_time)
        if effective > limit:
            after += 1
            continue
        eligible_versions += 1
        previous = latest.get(event["event_id"])
        if previous is None or event["version"] > previous[0]["event"]["version"]:
            latest[event["event_id"]] = bundle, effective, receipt_text
    planned = []
    for bundle, effective, receipt in latest.values():
        raw = bundle["raw"]
        try:
            content = _file(root, raw["content_ref"]).read_bytes()
        except ValueError:
            _fail("evidence_candidate_file_invalid")
        if content != raw["normalized_text"].encode("utf-8") or hashlib.sha256(content).hexdigest() != raw["content_sha256"]:
            _fail("evidence_candidate_content_invalid")
        planned.append((_descriptor(bundle, effective, receipt), effective))
    planned.sort(key=lambda item: (item[1], item[0]["event_id"], item[0]["event_version_id"]))
    candidates = [item[0] for item in planned[:max_candidates]]
    flags = [candidate["is_synthetic"] for candidate in candidates]
    synthetic = bool(flags) and all(flags)
    mixed = bool(flags) and any(flags) and not all(flags)
    manifest = {"schema_version": "evidence-candidate-input/0.1", "selection_version": "latest-available/0.1",
                "cutoff": cutoff, "max_candidates": max_candidates, "include_synthetic": include_synthetic,
                "candidates": candidates}
    return {"schema_version": "evidence-candidate-plan/0.1", "status": "planned", "read_only": True,
            "model_called": False, "content_support_reviewed": False,
            "data_status": "empty" if not flags else "mixed" if mixed else "synthetic" if synthetic else "real",
            "is_synthetic": synthetic, "mixed_test_data": mixed,
            "event_versions_count": len(bundles), "excluded_synthetic_count": excluded,
            "missing_receipt_count": missing, "after_cutoff_count": after,
            "eligible_versions_count": eligible_versions, "superseded_count": eligible_versions - len(latest),
            "eligible_events_count": len(latest), "limited_count": len(latest) - len(candidates),
            "selected_count": len(candidates), "input_manifest": manifest, "input_manifest_sha256": _hash(manifest)}


def plan_evidence_candidates(workspace, cutoff, max_candidates=5, *, include_synthetic=False):
    """Observe an existing schema4 evidence snapshot without modifying business state."""
    if type(max_candidates) is not int or not 0 <= max_candidates <= 100:
        _fail("evidence_candidate_limit_invalid")
    if type(include_synthetic) is not bool:
        _fail("evidence_candidate_scope_invalid")
    limit = _stamp(cutoff)
    db = None
    try:
        root, database = _paths(workspace)
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return _plan(db, root, cutoff, limit, max_candidates, include_synthetic)
    except OSError:
        _fail("evidence_candidate_io_error")
    except sqlite3.Error:
        _fail("evidence_candidate_database_error")
    except (UnicodeError, RecursionError):
        _fail("evidence_candidate_data_invalid")
    finally:
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                _fail("evidence_candidate_database_error")
