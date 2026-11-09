"""Pure validation for fixed candidate identities; hashes are not signatures."""

import hashlib
import json

from . import ContractError, SHA256, identifier, instant, record, validate_bundle


FIELDS = set("""event_id event_version_id version event_available_at receipt_committed_at
effective_available_at raw_item_id evidence_id source_id source_config_version content_ref
content_sha256 raw_payload_sha256 event_payload_sha256 evidence_payload_sha256 is_synthetic""".split())


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_sha256(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fail():
    raise ValueError("candidate_snapshot_invalid") from None


def _normalized(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_candidate_snapshot(snapshot):
    """Validate structure and self-consistency, without selecting or reading inputs."""
    try:
        record(snapshot, {"schema_version", "input_manifest", "input_manifest_sha256"}, "snapshot")
        if snapshot["schema_version"] != "evidence-candidate-snapshot/0.1":
            _fail()
        manifest = snapshot["input_manifest"]
        record(manifest, {"schema_version", "selection_version", "cutoff", "max_candidates",
                          "include_synthetic", "candidates"}, "manifest")
        if manifest["schema_version"] != "evidence-candidate-input/0.1" or manifest["selection_version"] != "latest-available/0.1":
            _fail()
        cutoff = instant(manifest["cutoff"], "cutoff")
        cap, include, candidates = (manifest[k] for k in ("max_candidates", "include_synthetic", "candidates"))
        if type(cap) is not int or not 0 <= cap <= 100 or type(include) is not bool or type(candidates) is not list or len(candidates) > cap:
            _fail()
        identities = {k: set() for k in ("event_id", "event_version_id", "evidence_id")}
        raw_hashes, previous = {}, None
        for item in candidates:
            record(item, FIELDS, "candidate")
            for key in ("event_id", "event_version_id", "raw_item_id", "evidence_id", "source_id", "source_config_version"):
                identifier(item[key], "candidate.id")
            if type(item["version"]) is not int or item["version"] < 1 or type(item["is_synthetic"]) is not bool:
                _fail()
            for key in ("content_sha256", "raw_payload_sha256", "event_payload_sha256", "evidence_payload_sha256"):
                if type(item[key]) is not str or not SHA256.fullmatch(item[key]):
                    _fail()
            if item["content_ref"] != "raw/" + item["content_sha256"] + ".txt":
                _fail()
            event_at = instant(item["event_available_at"], "event_available_at")
            effective = instant(item["effective_available_at"], "effective_available_at")
            if item["effective_available_at"] != _normalized(effective) or effective < event_at or effective > cutoff:
                _fail()
            if item["is_synthetic"]:
                if not include or item["receipt_committed_at"] is not None:
                    _fail()
            elif instant(item["receipt_committed_at"], "receipt") != effective:
                _fail()
            order = effective, item["event_id"], item["event_version_id"]
            if previous is not None and order <= previous:
                _fail()
            previous = order
            for key, seen in identities.items():
                if item[key] in seen:
                    _fail()
                seen.add(item[key])
            raw_id, raw_hash = item["raw_item_id"], item["raw_payload_sha256"]
            if raw_id in raw_hashes and raw_hashes[raw_id] != raw_hash:
                _fail()
            raw_hashes[raw_id] = raw_hash
        if type(snapshot["input_manifest_sha256"]) is not str or snapshot["input_manifest_sha256"] != payload_sha256(manifest):
            _fail()
    except (ContractError, KeyError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail()


def describe_candidate_bundle(bundle, receipt_committed_at):
    """Return the exact 09B descriptor from a validated single bundle and receipt."""
    try:
        record(bundle, {"raw", "event", "evidence"}, "bundle")
        validate_bundle(bundle)
        raw, event, evidence = (bundle[k] for k in ("raw", "event", "evidence"))
        effective = max(instant(bundle[k]["available_at"], "available_at") for k in bundle)
        if event["is_synthetic"]:
            if receipt_committed_at is not None:
                _fail()
        else:
            receipt = instant(receipt_committed_at, "receipt")
            if receipt < effective:
                _fail()
            effective = receipt
        return {"event_id": event["event_id"], "event_version_id": event["event_version_id"],
                "version": event["version"], "event_available_at": event["available_at"],
                "receipt_committed_at": receipt_committed_at, "effective_available_at": _normalized(effective),
                "raw_item_id": raw["raw_item_id"], "evidence_id": evidence["evidence_id"],
                "source_id": raw["source_id"], "source_config_version": raw["source_config_version"],
                "content_ref": raw["content_ref"], "content_sha256": raw["content_sha256"],
                "raw_payload_sha256": payload_sha256(raw), "event_payload_sha256": payload_sha256(event),
                "evidence_payload_sha256": payload_sha256(evidence), "is_synthetic": event["is_synthetic"]}
    except (ContractError, KeyError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail()
