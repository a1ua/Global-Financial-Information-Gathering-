"""Explicit, bounded candidate artifacts; no model calls or source refreshes."""

from functools import wraps
import hashlib
import os
from pathlib import Path
import sqlite3

from ..contracts.candidate_snapshot import (
    canonical_json, describe_candidate_bundle, validate_candidate_snapshot,
)
from ..llm.client import _safe_json, _strict_loads
from ..pipeline.candidate_snapshot import load_candidate_snapshot_inputs, verify_candidate_snapshot
from ..pipeline.evidence_candidates import plan_evidence_candidates
from .backup import _linked


MANIFEST_LIMIT = 1024 * 1024
INPUTS_LIMIT = 64 * 1024 * 1024
MANIFEST_FILE = "candidate-manifest.json"
INPUTS_FILE = "candidate-inputs.json"


class _ArtifactError(ValueError):
    pass


def _fail(code):
    raise _ArtifactError("candidate_artifact_" + code) from None


def _safe(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except _ArtifactError:
            raise
        except OSError:
            _fail("io_error")
        except sqlite3.Error:
            _fail("database_error")
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            _fail("invalid")
    return run


def _path(value):
    try:
        path = Path(value).absolute()
        if any(_linked(part) for part in (path, *path.parents)):
            _fail("link_forbidden")
        return path.resolve(strict=False)
    except _ArtifactError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        _fail("path_invalid")


def _destination(destination, *sources):
    target = _path(destination)
    if target.exists():
        _fail("destination_exists")
    for source in sources:
        source = _path(source)
        if target.is_relative_to(source) or source.is_relative_to(target):
            _fail("directories_overlap")
    return target


def _read_json(path, limit):
    path = _path(path)
    if not path.is_file():
        _fail("file_missing")
    if path.stat().st_size > limit:
        _fail("capacity_exceeded")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        _fail("capacity_exceeded")
    value = _strict_loads(data.decode("utf-8"))
    _safe_json(value)
    return path, value, data


def _read_snapshot(path):
    path, snapshot, data = _read_json(path, MANIFEST_LIMIT)
    validate_candidate_snapshot(snapshot)
    return path, snapshot, data


def _encoded(value, limit):
    data = canonical_json(value).encode("utf-8")
    if len(data) > limit:
        _fail("capacity_exceeded")
    return data


def _publish(destination, files):
    # All validation and serialization precede creating any parent directories.
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    for name, data in files:
        with (destination / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def _artifact_summary(snapshot, destination, status):
    return {"schema_version": "evidence-candidate-artifact/0.1", "status": status,
            "destination": str(destination),
            "selected_count": len(snapshot["input_manifest"]["candidates"]),
            "input_manifest_sha256": snapshot["input_manifest_sha256"], "model_called": False}


def _check_replay(snapshot, replay):
    if (type(replay) is not dict or replay.keys() != {"schema_version", "input_manifest_sha256", "bundles"}
            or replay["schema_version"] != "evidence-candidate-replay/0.1"
            or replay["input_manifest_sha256"] != snapshot["input_manifest_sha256"]
            or type(replay["bundles"]) is not list):
        _fail("replay_invalid")
    candidates = snapshot["input_manifest"]["candidates"]
    if len(replay["bundles"]) != len(candidates):
        _fail("replay_invalid")
    for bundle, descriptor in zip(replay["bundles"], candidates):
        if type(bundle) is not dict or bundle.keys() != {"raw", "event", "evidence", "receipt_committed_at"}:
            _fail("bundle_invalid")
        objects = {key: bundle[key] for key in ("raw", "event", "evidence")}
        if describe_candidate_bundle(objects, bundle["receipt_committed_at"]) != descriptor:
            _fail("descriptor_mismatch")


@_safe
def freeze_candidate_snapshot(workspace, destination, cutoff, max_candidates=5, *, include_synthetic=False):
    """Freeze one planner result in a new directory without copying source text."""
    plan = plan_evidence_candidates(workspace, cutoff, max_candidates, include_synthetic=include_synthetic)
    snapshot = {"schema_version": "evidence-candidate-snapshot/0.1",
                "input_manifest": plan["input_manifest"], "input_manifest_sha256": plan["input_manifest_sha256"]}
    validate_candidate_snapshot(snapshot)
    data = _encoded(snapshot, MANIFEST_LIMIT)
    target = _destination(destination, workspace)
    _publish(target, [(MANIFEST_FILE, data)])
    return _artifact_summary(snapshot, target, "frozen")


@_safe
def verify_candidate_snapshot_file(workspace, manifest_path):
    """Verify the listed exact source inputs; return a text-free summary."""
    _, snapshot, _ = _read_snapshot(manifest_path)
    return verify_candidate_snapshot(workspace, snapshot)


@_safe
def replay_candidate_snapshot(workspace, manifest_path, destination):
    """Export the same verified input closure exactly once, without a new plan."""
    manifest_path, snapshot, _ = _read_snapshot(manifest_path)
    target = _destination(destination, workspace, manifest_path.parent)
    loaded = load_candidate_snapshot_inputs(workspace, snapshot)
    replay = {"schema_version": "evidence-candidate-replay/0.1",
              "input_manifest_sha256": snapshot["input_manifest_sha256"], "bundles": loaded["bundles"]}
    _check_replay(snapshot, replay)
    manifest_data = _encoded(snapshot, MANIFEST_LIMIT)
    inputs_data = _encoded(replay, INPUTS_LIMIT)
    _publish(target, [(MANIFEST_FILE, manifest_data), (INPUTS_FILE, inputs_data)])
    result = _artifact_summary(snapshot, target, "replayed")
    result["replay_sha256"] = hashlib.sha256(inputs_data).hexdigest()
    return result


@_safe
def verify_candidate_replay(directory):
    """Validate a self-contained replay without consulting any source paths."""
    root = _path(directory)
    if not root.is_dir() or {item.name for item in root.iterdir()} != {MANIFEST_FILE, INPUTS_FILE}:
        _fail("inventory_invalid")
    _, snapshot, _ = _read_snapshot(root / MANIFEST_FILE)
    _, replay, inputs_data = _read_json(root / INPUTS_FILE, INPUTS_LIMIT)
    _check_replay(snapshot, replay)
    flags = [item["is_synthetic"] for item in snapshot["input_manifest"]["candidates"]]
    synthetic = bool(flags) and all(flags)
    mixed = bool(flags) and any(flags) and not all(flags)
    return {"schema_version": "evidence-candidate-replay-verification/0.1", "status": "verified_replay",
            "read_only": True, "model_called": False, "content_support_reviewed": False,
            "selected_count": len(flags), "input_manifest_sha256": snapshot["input_manifest_sha256"],
            "replay_sha256": hashlib.sha256(inputs_data).hexdigest(),
            "data_status": "empty" if not flags else "mixed" if mixed else "synthetic" if synthetic else "real",
            "is_synthetic": synthetic, "mixed_test_data": mixed}
