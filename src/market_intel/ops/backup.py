"""Consistent SQLite/evidence backups and restoration into new directories only."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
from uuid import uuid4

from ..store import SCHEMA_VERSION


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REPORT = re.compile(r"[A-Za-z0-9_-]+\Z")
_MANIFEST = "backup-manifest.json"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _linked(path):
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def _root(path):
    path = Path(path).absolute()
    if _linked(path) or not path.is_dir():
        raise ValueError("backup_root_must_be_regular_directory")
    return path.resolve(strict=True)


def _relative(value):
    if type(value) is not str or not value or any(c in value for c in ("\\", ":", "\x00")):
        raise ValueError("unsafe_backup_path")
    parts = PurePosixPath(value)
    if parts.is_absolute() or any(p in (".", "..", "") for p in value.split("/")) or str(parts) != value:
        raise ValueError("unsafe_backup_path")
    return parts


def _file(root, relative):
    relative = _relative(relative)
    path = root
    for part in relative.parts:
        path = path / part
        if _linked(path):
            raise ValueError("backup_symlink_forbidden")
    if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("backup_file_missing")
    return path


def _destination(source, destination):
    requested = Path(destination).absolute()
    if requested.exists() or _linked(requested):
        raise ValueError("backup_destination_exists")
    # Refuse existing symlink/junction parent components before resolving them.
    for parent in requested.parents:
        if _linked(parent):
            raise ValueError("backup_destination_symlink_forbidden")
    destination = requested.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("backup_directories_overlap")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _hash_file(path):
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            checksum.update(chunk)
    return {"sha256": checksum.hexdigest(), "size": size}


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_backup_json") from exc


def _readonly(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    db.execute("PRAGMA query_only=ON")
    return db


def _integrity(db):
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("backup_database_integrity_failed")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("backup_database_foreign_keys_failed")


def _schema_version(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if not 0 <= version <= SCHEMA_VERSION:
        raise ValueError("backup_database_version_unsupported")
    return version


def _raw_refs(db):
    refs = {}
    rows = db.execute("SELECT id,payload FROM raw_items").fetchall()
    for row_id, payload in rows:
        try:
            raw = json.loads(payload)
            if type(raw) is not dict or type(raw.get("normalized_text")) is not str:
                raise ValueError("backup_invalid_raw_record")
            checksum, ref = raw["content_sha256"], raw["content_ref"]
            if raw["raw_item_id"] != row_id or type(checksum) is not str or not _HASH.fullmatch(checksum) or ref != f"raw/{checksum}.txt":
                raise ValueError("backup_invalid_raw_reference")
            if hashlib.sha256(raw["normalized_text"].encode("utf-8")).hexdigest() != checksum:
                raise ValueError("backup_raw_payload_hash_mismatch")
            refs[ref] = checksum
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("backup_invalid_raw_record") from exc
    return refs, len(rows)


def _report(root, report_id, db):
    if type(report_id) is not str or not _REPORT.fullmatch(report_id):
        raise ValueError("invalid_backup_report_id")
    relative = f"reports/{report_id}/manifest.json"
    manifest = _read_json(_file(root, relative))
    try:
        if manifest["report_id"] != report_id or manifest["artifact_refs"] != ["brief.html"]:
            raise ValueError("backup_report_identity_mismatch")
        checksum = manifest["artifact_sha256"]
        if type(checksum) is not str or not _HASH.fullmatch(checksum):
            raise ValueError("backup_report_hash_invalid")
        if _hash_file(_file(root, f"reports/{report_id}/brief.html"))["sha256"] != checksum:
            raise ValueError("backup_report_artifact_corrupt")
        inputs = manifest["input_manifest"]
        if hashlib.sha256(_canonical(inputs).encode("utf-8")).hexdigest() != manifest["input_manifest_sha256"]:
            raise ValueError("backup_report_input_hash_mismatch")
        for field, table in (("raw_item_ids", "raw_items"), ("event_version_ids", "event_versions"), ("evidence_ids", "evidence")):
            ids = inputs[field]
            if type(ids) is not list or len(ids) != len(set(ids)) or any(type(value) is not str for value in ids):
                raise ValueError("backup_report_input_list_invalid")
            for value in ids:
                if db.execute(f"SELECT 1 FROM {table} WHERE id=?", (value,)).fetchone() is None:
                    raise ValueError("backup_report_input_missing_from_snapshot")
    except (KeyError, TypeError) as exc:
        raise ValueError("backup_report_manifest_invalid") from exc
    from ..report.verify import verify_report
    verify_report(db, root, report_id)
    return (relative, f"reports/{report_id}/brief.html")


def _reports(root):
    folder = root / "reports"
    if not folder.exists():
        if _linked(folder):
            raise ValueError("backup_symlink_forbidden")
        return []
    if _linked(folder) or not folder.is_dir():
        raise ValueError("backup_report_root_invalid")
    result = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue  # Unpublished staging output is deliberately excluded.
        if _linked(path):
            raise ValueError("backup_symlink_forbidden")
        if not path.is_dir() or not _REPORT.fullmatch(path.name):
            raise ValueError("backup_report_directory_invalid")
        result.append(path.name)
    return result


def _copy(source_root, destination_root, ref):
    source = _file(source_root, ref)
    destination = destination_root / _relative(ref)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while chunk := input_stream.read(1024 * 1024):
            output_stream.write(chunk)


def create_backup(workspace: Path, destination: Path) -> dict:
    """Back up one SQLite snapshot and exactly its evidence/published reports."""
    workspace = _root(workspace)
    database = _file(workspace, "market.db")
    destination = _destination(workspace, destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    source_db = _readonly(database)
    snapshot = sqlite3.connect(staging / "market.db")
    try:
        source_db.backup(snapshot)
        # A backup of a WAL database may retain WAL mode in its header. Convert
        # only the new snapshot to a self-contained rollback-journal database.
        snapshot.execute("PRAGMA journal_mode=DELETE")
    finally:
        snapshot.close()
        source_db.close()
    snapshot = _readonly(staging / "market.db")
    try:
        _integrity(snapshot)
        schema_version = _schema_version(snapshot)
        refs, raw_count = _raw_refs(snapshot)
        report_ids = _reports(workspace)
        file_refs = {"market.db", *refs}
        for report_id in report_ids:
            file_refs.update(_report(workspace, report_id, snapshot))
        for ref in sorted(file_refs - {"market.db"}):
            _copy(workspace, staging, ref)
        files = {ref: _hash_file(_file(staging, ref)) for ref in sorted(file_refs)}
        for ref, checksum in refs.items():
            if files[ref]["sha256"] != checksum:
                raise ValueError("backup_evidence_hash_mismatch")
        manifest = {
            "schema_version": "workspace-backup/0.1", "backup_id": "backup_" + uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "database_schema_version": schema_version,
            "raw_item_count": raw_count, "report_ids": report_ids, "files": files,
        }
    finally:
        snapshot.close()
    (staging / _MANIFEST).write_text(_canonical(manifest), encoding="utf-8", newline="")
    verify_backup(staging)
    os.rename(staging, destination)
    return {"status": "backed_up", "backup": str(destination), "files": len(files), "raw_items": raw_count, "reports": len(report_ids)}


def verify_backup(backup: Path) -> dict:
    """Read-only corruption/reference checks; hashes are not signatures."""
    backup = _root(backup)
    manifest = _read_json(_file(backup, _MANIFEST))
    required = {"schema_version", "backup_id", "created_at", "database_schema_version", "raw_item_count", "report_ids", "files"}
    if type(manifest) is not dict or manifest.keys() != required or manifest["schema_version"] != "workspace-backup/0.1":
        raise ValueError("backup_manifest_schema_invalid")
    if (type(manifest["backup_id"]) is not str or not re.fullmatch(r"backup_[0-9a-f]{32}", manifest["backup_id"])
            or type(manifest["created_at"]) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", manifest["created_at"])):
        raise ValueError("backup_manifest_metadata_invalid")
    try:
        datetime.fromisoformat(manifest["created_at"][:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("backup_manifest_metadata_invalid") from exc
    files, report_ids = manifest["files"], manifest["report_ids"]
    if type(files) is not dict or "market.db" not in files or type(report_ids) is not list or any(type(value) is not str or not _REPORT.fullmatch(value) for value in report_ids) or report_ids != sorted(set(report_ids)):
        raise ValueError("backup_manifest_inventory_invalid")
    for ref, recorded in files.items():
        _relative(ref)
        if type(recorded) is not dict or recorded.keys() != {"sha256", "size"} or type(recorded["size"]) is not int or recorded["size"] < 0 or type(recorded["sha256"]) is not str or not _HASH.fullmatch(recorded["sha256"]):
            raise ValueError("backup_manifest_file_invalid")
        if _hash_file(_file(backup, ref)) != recorded:
            raise ValueError("backup_file_hash_mismatch")
    db = _readonly(_file(backup, "market.db"))
    try:
        _integrity(db)
        schema_version = _schema_version(db)
        refs, raw_count = _raw_refs(db)
        if type(manifest["raw_item_count"]) is not int or raw_count != manifest["raw_item_count"] or type(manifest["database_schema_version"]) is not int or schema_version != manifest["database_schema_version"]:
            raise ValueError("backup_snapshot_metadata_mismatch")
        expected = {"market.db", *refs}
        if _reports(backup) != report_ids:
            raise ValueError("backup_report_inventory_mismatch")
        for report_id in report_ids:
            expected.update(_report(backup, report_id, db))
        if expected != files.keys():
            raise ValueError("backup_unexpected_or_missing_files")
        for ref, checksum in refs.items():
            if files[ref]["sha256"] != checksum:
                raise ValueError("backup_evidence_hash_mismatch")
    finally:
        db.close()
    # Catch hidden/extra files and nested links even if not listed by the manifest.
    actual = set()
    for root, directories, names in os.walk(backup, followlinks=False):
        for name in (*directories, *names):
            path = Path(root) / name
            if _linked(path):
                raise ValueError("backup_symlink_forbidden")
        actual.update((Path(root) / name).relative_to(backup).as_posix() for name in names)
    if actual != set(files) | {_MANIFEST}:
        raise ValueError("backup_unexpected_or_missing_files")
    return {"status": "verified", "backup": str(backup), "files": len(files), "raw_items": raw_count, "reports": len(report_ids)}


def restore_backup(backup: Path, destination: Path) -> dict:
    """Restore only into a fresh sibling/outside directory, never overwrite."""
    backup = _root(backup)
    verify_backup(backup)
    destination = _destination(backup, destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    manifest = _read_json(_file(backup, _MANIFEST))
    for ref in (*sorted(manifest["files"]), _MANIFEST):
        _copy(backup, staging, ref)
    verify_backup(staging)
    os.rename(staging, destination)
    return {"status": "restored", "workspace": str(destination), "files": len(manifest["files"]), "raw_items": manifest["raw_item_count"], "reports": len(manifest["report_ids"])}
