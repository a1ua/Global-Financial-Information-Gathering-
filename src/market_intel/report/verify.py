"""Read-only report validation against the exact persisted evidence versions."""

import hashlib
import json
from pathlib import Path
import re

from ..contracts import instant, validate_bundle
from ..contracts.report import validate_report_manifest


def _file(workspace, relative):
    root = Path(workspace).resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("report_file_outside_workspace")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("report_symlink_not_allowed")
        current = current.parent
    if not path.is_file():
        raise ValueError("report_file_missing")
    return path


def _payload(db, table, key):
    row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise ValueError("report_input_missing")
    return json.loads(row[0])


def verify_report(db, workspace, report_id):
    """Check structure, closure, timestamps and bytes, without rewriting files."""
    if not isinstance(report_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", report_id):
        raise ValueError("invalid_report_id")
    manifest = json.loads(_file(workspace, f"reports/{report_id}/manifest.json").read_text(encoding="utf-8"))
    validate_report_manifest(manifest, expected_report_id=report_id)
    document = _file(workspace, f"reports/{report_id}/brief.html").read_bytes()
    if hashlib.sha256(document).hexdigest() != manifest["artifact_sha256"]:
        raise ValueError("published_artifact_corrupt")
    # One read transaction prevents cross-version reads from separate SELECTs.
    if db.in_transaction:
        raise ValueError("report_verification_requires_clean_transaction")
    raw_ids, evidence_ids = set(), set()
    synthetic_flags = []
    source_configs = set()
    from datetime import datetime
    cutoff = datetime.fromisoformat(manifest["information_cutoff"].replace("Z", "+00:00"))
    db.execute("BEGIN")
    try:
        for version_id in manifest["input_manifest"]["event_version_ids"]:
            event = _payload(db, "event_versions", version_id)
            if type(event) is not dict or type(event.get("input_raw_item_ids")) is not list or type(event.get("evidence_ids")) is not list or len(event["input_raw_item_ids"]) != 1 or len(event["evidence_ids"]) != 1:
                raise ValueError("unsupported_report_bundle_shape")
            raw_id, evidence_id = event["input_raw_item_ids"][0], event["evidence_ids"][0]
            raw = _payload(db, "raw_items", raw_id)
            evidence = _payload(db, "evidence", evidence_id)
            validate_bundle({"raw": raw, "event": event, "evidence": evidence})
            if event["event_version_id"] != version_id or raw["raw_item_id"] != raw_id or evidence["evidence_id"] != evidence_id:
                raise ValueError("report_input_identity_mismatch")
            for record in (raw, event, evidence):
                if datetime.fromisoformat(record["available_at"].replace("Z", "+00:00")) > cutoff:
                    raise ValueError("report_input_after_cutoff")
            if not event["is_synthetic"]:
                receipt = db.execute("SELECT committed_at FROM availability_receipts WHERE event_version_id=?", (version_id,)).fetchone()
                if receipt is None or instant(receipt[0], "report.receipt.committed_at") > cutoff:
                    raise ValueError("report_receipt_missing_or_after_cutoff")
            content = _file(workspace, raw["content_ref"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != raw["content_sha256"]:
                raise ValueError("report_evidence_corrupt")
            raw_ids.add(raw_id)
            evidence_ids.add(evidence_id)
            synthetic_flags.append(event["is_synthetic"])
            source_configs.add(raw["source_config_version"])
        if raw_ids != set(manifest["input_manifest"]["raw_item_ids"]) or evidence_ids != set(manifest["input_manifest"]["evidence_ids"]):
            raise ValueError("report_input_closure_mismatch")
        if synthetic_flags and manifest["is_synthetic"] != all(synthetic_flags):
            raise ValueError("report_synthetic_status_mismatch")
        if synthetic_flags and ("mixed_test_data" in manifest["reason_codes"]) != (any(synthetic_flags) and not all(synthetic_flags)):
            raise ValueError("report_mixed_data_status_mismatch")
        if manifest["source_config_version"] != ",".join(sorted(source_configs)):
            raise ValueError("report_source_config_mismatch")
    finally:
        db.rollback()
    return {"status": "verified", "report_id": report_id, "events": len(synthetic_flags),
            "artifact_sha256": manifest["artifact_sha256"], "is_synthetic": manifest["is_synthetic"]}
