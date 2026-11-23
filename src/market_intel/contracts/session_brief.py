"""Pure, deterministic validation for dual-template session brief manifests (v0.1)."""

from datetime import date
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import choice, fail, identifier, instant, record, text

__all__ = ["validate_session_brief_manifest"]

SCHEMA_VERSION = "session-brief-manifest/0.1"
RENDERER_VERSION = "session-brief/0.1"
RULES_VERSION = "strict-cutoff-session/0.1"
CANONICAL_JSON_VERSION = "python-json-sorted-utf8/0.1"
ARTIFACT_REFS = ["brief.html", "brief.md"]

FIELDS = set("""schema_version report_id run_id report_type market_session_date
display_timezone information_cutoff generated_at status reason_codes input_manifest
input_manifest_sha256 canonical_json_version source_config_version rules_version
template_version renderer_version market_data_as_of citation_check content_support_check
sections artifact_refs artifact_sha256 supersedes_report_id is_synthetic""".split())

INPUT_FIELDS = {
    "raw_item_ids",
    "event_version_ids",
    "evidence_ids",
    "prediction_ids",
    "market_snapshot_id",
}

SECTION_FIELDS = {
    "facts_count",
    "interpretations_count",
    "watch_items_count",
}

REPORT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

REPORT_TYPES = {"pre_market", "post_market"}
REASONS = {
    "synthetic_fixture",
    "retrospective",
    "source_metadata_only",
    "content_support_not_reviewed",
    "model_unavailable",
    "market_data_unavailable",
    "mixed_test_data",
    "supplement_revision",
}


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


def _nonneg_int(value, path):
    if type(value) is not int or value < 0:
        fail(path, "nonnegative_integer_required")


def validate_session_brief_manifest(manifest, *, expected_report_id=None):
    """Validate a session-brief-manifest/0.1 payload without I/O or mutation.

    Covers offline degraded pre_market/post_market dual-template reports
    (HTML + Markdown). Live model inference and live market data are not
    accepted by v0.1; status must remain degraded with explicit reason codes.
    """
    record(manifest, FIELDS, "session_brief")
    if manifest["schema_version"] != SCHEMA_VERSION:
        fail("session_brief.schema_version", "unsupported_schema")
    _report_id(manifest["report_id"], "session_brief.report_id")
    _report_id(manifest["run_id"], "session_brief.run_id")
    if expected_report_id is not None:
        _report_id(expected_report_id, "expected_report_id")
        if manifest["report_id"] != expected_report_id:
            fail("session_brief.report_id", "report_id_mismatch")

    supersedes = manifest["supersedes_report_id"]
    _report_id(supersedes, "session_brief.supersedes_report_id", nullable=True)
    if supersedes == manifest["report_id"]:
        fail("session_brief.supersedes_report_id", "self_reference")

    choice(manifest["report_type"], REPORT_TYPES, "session_brief.report_type")
    choice(manifest["status"], {"degraded"}, "session_brief.status")
    choice(manifest["citation_check"], {"passed"}, "session_brief.citation_check")
    choice(manifest["content_support_check"], {"not_performed"}, "session_brief.content_support_check")
    if type(manifest["is_synthetic"]) is not bool:
        fail("session_brief.is_synthetic", "boolean_required")

    session_date = manifest["market_session_date"]
    if type(session_date) is not str or not DATE_RE.fullmatch(session_date):
        fail("session_brief.market_session_date", "invalid_date")
    try:
        date.fromisoformat(session_date)
    except ValueError:
        fail("session_brief.market_session_date", "invalid_date")

    tz = manifest["display_timezone"]
    text(tz, "session_brief.display_timezone")
    if (
        tz != tz.strip()
        or any(ch.isspace() for ch in tz)
        or "\\" in tz
        or ".." in tz
        or tz.startswith("/")
        or tz.endswith(("/", "."))
    ):
        fail("session_brief.display_timezone", "unknown_timezone")
    try:
        ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError):
        fail("session_brief.display_timezone", "unknown_timezone")

    cutoff = instant(manifest["information_cutoff"], "session_brief.information_cutoff")
    generated = instant(manifest["generated_at"], "session_brief.generated_at")
    if generated < cutoff:
        fail("session_brief.generated_at", "generated_before_cutoff")

    if manifest["market_data_as_of"] is not None:
        fail("session_brief.market_data_as_of", "market_data_not_supported")

    if manifest["renderer_version"] != RENDERER_VERSION:
        fail("session_brief.renderer_version", "unsupported_renderer")
    if manifest["template_version"] != RENDERER_VERSION:
        fail("session_brief.template_version", "renderer_template_mismatch")
    if manifest["rules_version"] != RULES_VERSION:
        fail("session_brief.rules_version", "renderer_rules_mismatch")
    if manifest["canonical_json_version"] != CANONICAL_JSON_VERSION:
        fail("session_brief.canonical_json_version", "unsupported_canonical_json")

    inputs = manifest["input_manifest"]
    record(inputs, INPUT_FIELDS, "session_brief.input_manifest")
    for field in ("raw_item_ids", "event_version_ids", "evidence_ids", "prediction_ids"):
        _id_list(inputs[field], "session_brief.input_manifest." + field)
    if inputs["prediction_ids"] or inputs["market_snapshot_id"] is not None:
        fail("session_brief.input_manifest", "prediction_or_market_not_supported")
    input_presence = [bool(inputs[key]) for key in ("raw_item_ids", "event_version_ids", "evidence_ids")]
    if any(input_presence) and not all(input_presence):
        fail("session_brief.input_manifest", "incomplete_evidence_input_set")

    _sha256(manifest["input_manifest_sha256"], "session_brief.input_manifest_sha256")
    canonical = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != manifest["input_manifest_sha256"]:
        fail("session_brief.input_manifest_sha256", "input_manifest_hash_mismatch")

    config = manifest["source_config_version"]
    text(config, "session_brief.source_config_version", empty=True)
    if not inputs["raw_item_ids"]:
        if config != "":
            fail("session_brief.source_config_version", "empty_report_has_source_config")
    else:
        if not config:
            fail("session_brief.source_config_version", "source_config_required")
        configs = config.split(",")
        for config_id in configs:
            identifier(config_id, "session_brief.source_config_version")
        if configs != sorted(set(configs)):
            fail("session_brief.source_config_version", "source_configs_must_be_sorted_unique")

    sections = manifest["sections"]
    record(sections, SECTION_FIELDS, "session_brief.sections")
    for field in SECTION_FIELDS:
        _nonneg_int(sections[field], "session_brief.sections." + field)
    if sections["facts_count"] != len(inputs["event_version_ids"]):
        fail("session_brief.sections.facts_count", "facts_count_mismatch")
    if sections["interpretations_count"] != 0:
        fail("session_brief.sections.interpretations_count", "interpretations_require_verified_model")
    if sections["watch_items_count"] < 1:
        fail("session_brief.sections.watch_items_count", "degraded_watch_items_required")

    reasons = manifest["reason_codes"]
    if type(reasons) is not list:
        fail("session_brief.reason_codes", "list_required")
    for reason in reasons:
        choice(reason, REASONS, "session_brief.reason_codes")
    if len(reasons) != len(set(reasons)):
        fail("session_brief.reason_codes", "duplicate_reason")

    if manifest["is_synthetic"]:
        expected = {"synthetic_fixture", "retrospective", "model_unavailable", "market_data_unavailable"}
    else:
        expected = {
            "source_metadata_only",
            "content_support_not_reviewed",
            "model_unavailable",
            "market_data_unavailable",
        }
        if "mixed_test_data" in reasons:
            expected.add("mixed_test_data")
            if not all(input_presence):
                fail("session_brief.reason_codes", "mixed_report_requires_inputs")
    if supersedes is not None:
        expected.add("supplement_revision")
    if set(reasons) != expected:
        fail("session_brief.reason_codes", "inconsistent_report_reasons")
    if sections["watch_items_count"] != len(reasons):
        fail("session_brief.sections.watch_items_count", "watch_items_count_mismatch")

    if type(manifest["artifact_refs"]) is not list or manifest["artifact_refs"] != ARTIFACT_REFS:
        fail("session_brief.artifact_refs", "fixed_dual_artifact_paths_required")
    hashes = manifest["artifact_sha256"]
    record(hashes, set(ARTIFACT_REFS), "session_brief.artifact_sha256")
    for ref in ARTIFACT_REFS:
        _sha256(hashes[ref], f"session_brief.artifact_sha256.{ref}")
