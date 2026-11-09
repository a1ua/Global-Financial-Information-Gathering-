"""Verify precisely frozen evidence inputs without selecting current versions."""

import hashlib
import sqlite3

from ..contracts.candidate_snapshot import describe_candidate_bundle, validate_candidate_snapshot
from ..ops.backup import _file
from .evidence_candidates import _paths, _payload


def _fail(code):
    raise ValueError(code) from None


def _load(db, root, snapshot):
    if db.execute("PRAGMA user_version").fetchone()[0] != 4:
        _fail("candidate_snapshot_schema_unsupported")
    if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
        _fail("candidate_snapshot_database_invalid")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        _fail("candidate_snapshot_foreign_keys_invalid")
    bundles = []
    for expected in snapshot["input_manifest"]["candidates"]:
        _, event = _payload(db, "event_versions", expected["event_version_id"], "event_version_id")
        _, raw = _payload(db, "raw_items", expected["raw_item_id"], "raw_item_id")
        row, evidence = _payload(db, "evidence", expected["evidence_id"], "evidence_id")
        if row["raw_item_id"] != expected["raw_item_id"] or row["event_version_id"] != expected["event_version_id"]:
            _fail("candidate_snapshot_identity_invalid")
        receipt = None
        if not expected["is_synthetic"]:
            row = db.execute("SELECT committed_at FROM availability_receipts WHERE event_version_id=?",
                             (expected["event_version_id"],)).fetchone()
            if row is None:
                _fail("candidate_snapshot_receipt_missing")
            receipt = row[0]
        bundle = {"raw": raw, "event": event, "evidence": evidence}
        if describe_candidate_bundle(bundle, receipt) != expected:
            _fail("candidate_snapshot_descriptor_mismatch")
        try:
            content = _file(root, raw["content_ref"]).read_bytes()
        except ValueError:
            _fail("candidate_snapshot_file_invalid")
        if content != raw["normalized_text"].encode("utf-8") or hashlib.sha256(content).hexdigest() != raw["content_sha256"]:
            _fail("candidate_snapshot_content_invalid")
        bundles.append({**bundle, "receipt_committed_at": receipt})
    flags = [bundle["event"]["is_synthetic"] for bundle in bundles]
    synthetic = bool(flags) and all(flags)
    mixed = any(flags) and not all(flags)
    verification = {
        "schema_version": "evidence-candidate-verification/0.1", "status": "verified_inputs",
        "read_only": True, "model_called": False, "content_support_reviewed": False,
        "selected_count": len(bundles), "input_manifest_sha256": snapshot["input_manifest_sha256"],
        "data_status": "empty" if not flags else "mixed" if mixed else "synthetic" if synthetic else "real",
        "is_synthetic": synthetic, "mixed_test_data": mixed,
    }
    return {"verification": verification, "bundles": bundles}


def load_candidate_snapshot_inputs(workspace, snapshot):
    """Load only selected immutable identities in one read-only DB transaction.

    The returned bundles are the already verified input snapshot; callers must not
    re-plan or re-read objects when exporting them. SQLite and raw files are not
    a jointly atomic snapshot, and WAL may maintain coordination side files.
    """
    validate_candidate_snapshot(snapshot)
    db = None
    try:
        root, database = _paths(workspace)
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return _load(db, root, snapshot)
    except OSError:
        _fail("candidate_snapshot_io_error")
    except sqlite3.Error:
        _fail("candidate_snapshot_database_error")
    except (UnicodeError, RecursionError):
        _fail("candidate_snapshot_data_invalid")
    finally:
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                _fail("candidate_snapshot_database_error")


def verify_candidate_snapshot(workspace, snapshot):
    """Return a metadata-only verification receipt, never candidate bodies."""
    return load_candidate_snapshot_inputs(workspace, snapshot)["verification"]
