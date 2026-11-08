"""Pure validation for currently supported, published evidence reports."""

from datetime import date
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import choice, fail, identifier, instant, record, text

__all__ = ["validate_report_manifest"]

FIELDS = set("""schema_version report_id run_id report_type market_session_date
display_timezone information_cutoff generated_at status reason_codes input_manifest
input_manifest_sha256 canonical_json_version source_config_version rules_version
template_version renderer_version market_data_as_of citation_check content_support_check
artifact_refs artifact_sha256 supersedes_report_id is_synthetic""".split())
INPUT_FIELDS = {"raw_item_ids", "event_version_ids", "evidence_ids", "prediction_ids", "market_snapshot_id"}
REPORT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REASONS = {"synthetic_fixture", "retrospective", "rss_excerpt_only", "source_metadata_only",
           "content_support_not_reviewed", "market_data_unavailable", "mixed_test_data"}


def _report_id(value, path, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not REPORT_ID.fullmatch(value):
        fail(path, "invalid_report_id")


def _sha256(value, path):
    if type(value) is not str or not SHA256.fullmatch(value):
        fail(path, "sha256_required")


def _id_list(value, path):
    if type(value) is not list:
        fail(path, "list_required")
    for element in value:
        identifier(element, path)
    if len(value) != len(set(value)):
        fail(path, "duplicate_id")


def validate_report_manifest(manifest, *, expected_report_id=None):
    """Validate shape and internal consistency without I/O or input mutation.

    This covers actual renderer 0.2/0.3 manifests, not future model/price reports.
    A valid hash is not a signature, proof of disk contents, or fact verification.
    """
    record(manifest, FIELDS, "report")
    if manifest["schema_version"] != "report-manifest/0.1":
        fail("report.schema_version", "unsupported_schema")
    _report_id(manifest["report_id"], "report.report_id")
    _report_id(manifest["run_id"], "report.run_id")
    if expected_report_id is not None:
        _report_id(expected_report_id, "expected_report_id")
        if manifest["report_id"] != expected_report_id:
            fail("report.report_id", "report_id_mismatch")
    _report_id(manifest["supersedes_report_id"], "report.supersedes_report_id", nullable=True)
    if manifest["supersedes_report_id"] == manifest["report_id"]:
        fail("report.supersedes_report_id", "self_reference")
    choice(manifest["report_type"], {"offline_fixture", "rss_snapshot", "source_snapshot"}, "report.report_type")
    # These renderers cannot produce complete research/market reports.
    choice(manifest["status"], {"degraded"}, "report.status")
    choice(manifest["citation_check"], {"passed"}, "report.citation_check")
    choice(manifest["content_support_check"], {"not_performed"}, "report.content_support_check")
    if type(manifest["is_synthetic"]) is not bool:
        fail("report.is_synthetic", "boolean_required")

    cutoff = instant(manifest["information_cutoff"], "report.information_cutoff")
    generated = instant(manifest["generated_at"], "report.generated_at")
    if generated < cutoff:
        fail("report.generated_at", "generated_before_cutoff")
    session_date = manifest["market_session_date"]
    if session_date is not None:
        if type(session_date) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", session_date):
            fail("report.market_session_date", "invalid_date")
        try:
            date.fromisoformat(session_date)
        except ValueError:
            fail("report.market_session_date", "invalid_date")
    text(manifest["display_timezone"], "report.display_timezone")
    try:
        ZoneInfo(manifest["display_timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        fail("report.display_timezone", "unknown_timezone")
    if manifest["market_data_as_of"] is not None:
        fail("report.market_data_as_of", "market_data_not_supported")

    version = manifest["renderer_version"]
    choice(version, {"evidence-brief/0.2", "evidence-brief/0.3"}, "report.renderer_version")
    if manifest["template_version"] != version:
        fail("report.template_version", "renderer_template_mismatch")
    if manifest["rules_version"] != "strict-cutoff/" + version.rsplit("/", 1)[1]:
        fail("report.rules_version", "renderer_rules_mismatch")
    if manifest["canonical_json_version"] != "python-json-sorted-utf8/0.1":
        fail("report.canonical_json_version", "unsupported_canonical_json")

    inputs = manifest["input_manifest"]
    record(inputs, INPUT_FIELDS, "report.input_manifest")
    for field in ("raw_item_ids", "event_version_ids", "evidence_ids", "prediction_ids"):
        _id_list(inputs[field], "report.input_manifest." + field)
    if inputs["prediction_ids"] or inputs["market_snapshot_id"] is not None:
        fail("report.input_manifest", "prediction_or_market_not_supported")
    input_presence = [bool(inputs[key]) for key in ("raw_item_ids", "event_version_ids", "evidence_ids")]
    if any(input_presence) and not all(input_presence):
        fail("report.input_manifest", "incomplete_evidence_input_set")
    _sha256(manifest["input_manifest_sha256"], "report.input_manifest_sha256")
    canonical = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != manifest["input_manifest_sha256"]:
        fail("report.input_manifest_sha256", "input_manifest_hash_mismatch")

    config = manifest["source_config_version"]
    text(config, "report.source_config_version", empty=True)
    if not inputs["raw_item_ids"]:
        if config != "":
            fail("report.source_config_version", "empty_report_has_source_config")
    else:
        if not config:
            fail("report.source_config_version", "source_config_required")
        configs = config.split(",")
        for config_id in configs:
            identifier(config_id, "report.source_config_version")
        if configs != sorted(set(configs)):
            fail("report.source_config_version", "source_configs_must_be_sorted_unique")

    reasons = manifest["reason_codes"]
    if type(reasons) is not list:
        fail("report.reason_codes", "list_required")
    for reason in reasons:
        choice(reason, REASONS, "report.reason_codes")
    if len(reasons) != len(set(reasons)):
        fail("report.reason_codes", "duplicate_reason")
    if manifest["is_synthetic"]:
        expected = {"synthetic_fixture", "retrospective", "market_data_unavailable"}
        if manifest["report_type"] != "offline_fixture":
            fail("report.report_type", "synthetic_report_type_mismatch")
    else:
        expected = {"rss_excerpt_only" if version == "evidence-brief/0.2" else "source_metadata_only",
                    "content_support_not_reviewed", "market_data_unavailable"}
        if manifest["report_type"] == "offline_fixture":
            fail("report.report_type", "real_report_type_mismatch")
        if "mixed_test_data" in reasons:
            expected.add("mixed_test_data")
            if not all(input_presence):
                fail("report.reason_codes", "mixed_report_requires_inputs")
    if set(reasons) != expected:
        fail("report.reason_codes", "inconsistent_report_reasons")

    if type(manifest["artifact_refs"]) is not list or manifest["artifact_refs"] != ["brief.html"]:
        fail("report.artifact_refs", "fixed_artifact_path_required")
    _sha256(manifest["artifact_sha256"], "report.artifact_sha256")
