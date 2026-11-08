"""Pure, deterministic validation of a single evidence bundle (contract 0.1)."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import ipaddress
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["ContractError", "validate_bundle"]


class ContractError(ValueError):
    """An external bundle violates the declared structural contract."""


RAW_FIELDS = set("""schema_version raw_item_id source_id source_config_version
source_item_key original_url canonical_url source_tier title source_time_text
source_timezone source_time_precision time_parse_status source_published_at
source_published_date first_seen_at fetched_at persisted_at available_at
storage_policy content_ref content_sha256 normalized_text normalization_version
supersedes_raw_item_id is_synthetic""".split())
EVENT_FIELDS = set("""schema_version event_id event_version_id version title fact_summary
category markets entities evidence_ids input_raw_item_ids extraction_method
extractor_version extraction_quality processed_at available_at
supersedes_event_version_id is_synthetic""".split())
EVIDENCE_FIELDS = set("""schema_version evidence_id event_version_id raw_item_id relation
claim_key normalization_version locator quote validation_status available_at
is_synthetic""".split())
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def fail(path, reason):
    # Do not echo untrusted payload values into errors/logs.
    raise ContractError(f"{path}: {reason}")


def record(value, fields, path):
    if type(value) is not dict:
        fail(path, "object_required")
    if value.keys() != fields:
        fail(path, "missing_or_unknown_fields")


def text(value, path, *, nullable=False, empty=False):
    if value is None and nullable:
        return
    if type(value) is not str or (not empty and not value.strip()):
        fail(path, "string_required")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        fail(path, "invalid_unicode")


def identifier(value, path, *, nullable=False):
    if value is None and nullable:
        return
    text(value, path)
    if not ID.fullmatch(value):
        fail(path, "invalid_id")


def choice(value, values, path):
    if type(value) is not str or value not in values:
        fail(path, "invalid_enum")


def instant(value, path, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or not UTC.fullmatch(value):
        fail(path, "utc_z_timestamp_required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail(path, "invalid_timestamp")


def source_zone(value):
    if value in {"UTC", "GMT", "Z"}:
        return timezone.utc
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", value)
    if match:
        hours, minutes = int(match[2]), int(match[3])
        if hours > 23 or minutes > 59:
            fail("raw.source_timezone", "invalid_offset")
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(delta if match[1] == "+" else -delta)
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        fail("raw.source_timezone", "unknown_timezone")


def http_url(value, path):
    text(value, path)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or any(char in value for char in "\\<>\"'"):
        fail(path, "unsafe_url")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        if parts.scheme not in {"http", "https"} or not host or parts.username is not None or parts.password is not None or port == 0:
            fail(path, "unsafe_url")
        if "%" in host or host.endswith("."):
            fail(path, "unsafe_host")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            ascii_host = host.encode("idna").decode("ascii").lower()
            if "." not in ascii_host or ascii_host.endswith((".local", ".localhost", ".internal")):
                fail(path, "nonpublic_host")
            labels = ascii_host.split(".")
            if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
                fail(path, "unsafe_host")
            if all(label.isdigit() for label in labels):
                fail(path, "ambiguous_ip_host")
        else:
            if not address.is_global:
                fail(path, "nonpublic_host")
    except (ValueError, UnicodeError):
        fail(path, "invalid_url")


def one_reference(value, expected, path):
    if type(value) is not list or value != [expected]:
        fail(path, "single_bundle_reference_required")


def validate_bundle(bundle, *, allow_synthetic=True):
    """Validate one raw/event/evidence bundle without I/O or input mutation.

    This checks structural consistency, not semantic support or source permission.
    Only the single-raw/single-event/single-evidence shape is supported in v0.1.
    """
    if type(allow_synthetic) is not bool:
        fail("allow_synthetic", "boolean_required")
    record(bundle, {"raw", "event", "evidence"}, "bundle")
    raw, event, evidence = (bundle[k] for k in ("raw", "event", "evidence"))
    for obj, fields, schema, name in (
        (raw, RAW_FIELDS, "raw-item/0.1", "raw"),
        (event, EVENT_FIELDS, "event-version/0.1", "event"),
        (evidence, EVIDENCE_FIELDS, "evidence/0.1", "evidence"),
    ):
        record(obj, fields, name)
        if obj["schema_version"] != schema:
            fail(name + ".schema_version", "unsupported_schema")
        if type(obj["is_synthetic"]) is not bool:
            fail(name + ".is_synthetic", "boolean_required")
    synthetic = raw["is_synthetic"]
    if event["is_synthetic"] != synthetic or evidence["is_synthetic"] != synthetic:
        fail("bundle", "mixed_synthetic_status")
    if synthetic and not allow_synthetic:
        fail("bundle", "synthetic_not_allowed")

    for obj, name, keys in (
        (raw, "raw", ("raw_item_id", "source_id", "source_config_version")),
        (event, "event", ("event_id", "event_version_id")),
        (evidence, "evidence", ("evidence_id", "event_version_id", "raw_item_id")),
    ):
        for key in keys:
            identifier(obj[key], name + "." + key)
    for obj, name, key, own_key in (
        (raw, "raw", "supersedes_raw_item_id", "raw_item_id"),
        (event, "event", "supersedes_event_version_id", "event_version_id"),
    ):
        identifier(obj[key], name + "." + key, nullable=True)
        if obj[key] == obj[own_key]:
            fail(name + "." + key, "self_reference")
    for key in ("source_item_key", "title", "normalized_text", "normalization_version"):
        text(raw[key], "raw." + key)
    for key in ("title", "fact_summary", "extractor_version"):
        text(event[key], "event." + key)
    text(evidence["quote"], "evidence.quote")
    text(evidence["normalization_version"], "evidence.normalization_version")
    choice(raw["source_tier"], {"primary", "secondary"}, "raw.source_tier")
    choice(raw["storage_policy"], {"full_text", "excerpt_metadata", "metadata_only", "full_text_fixture"}, "raw.storage_policy")
    if not synthetic and raw["storage_policy"] == "full_text_fixture":
        fail("raw.storage_policy", "fixture_policy_requires_synthetic")
    for key in ("original_url", "canonical_url"):
        http_url(raw[key], "raw." + key)

    choice(raw["source_time_precision"], {"second", "minute", "date", "day", "unknown"}, "raw.source_time_precision")
    choice(raw["time_parse_status"], {"parsed", "date_only", "missing", "failed", "ambiguous", "timezone_missing", "invalid"}, "raw.time_parse_status")
    text(raw["source_time_text"], "raw.source_time_text", nullable=True)
    text(raw["source_timezone"], "raw.source_timezone", nullable=True)
    if raw["source_timezone"] is not None and raw["time_parse_status"] == "parsed":
        source_zone(raw["source_timezone"])
    published = instant(raw["source_published_at"], "raw.source_published_at", nullable=True)
    published_date = raw["source_published_date"]
    if published_date is not None:
        if type(published_date) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_date):
            fail("raw.source_published_date", "invalid_date")
        try:
            date.fromisoformat(published_date)
        except ValueError:
            fail("raw.source_published_date", "invalid_date")
    status, precision = raw["time_parse_status"], raw["source_time_precision"]
    if status == "parsed":
        if published is None or precision not in {"second", "minute"} or raw["source_timezone"] is None or raw["source_time_text"] is None:
            fail("raw", "inconsistent_parsed_time")
        if published_date is not None and published.astimezone(source_zone(raw["source_timezone"])).date().isoformat() != published_date:
            fail("raw.source_published_date", "local_date_mismatch")
    elif status == "date_only":
        if published is not None or published_date is None or precision not in {"date", "day"}:
            fail("raw", "inconsistent_date_only")
    elif published is not None or precision != "unknown":
        fail("raw", "unparsed_time_must_be_unknown")
    raw_times = [instant(raw[key], "raw." + key) for key in ("first_seen_at", "fetched_at", "persisted_at", "available_at")]
    processed = instant(event["processed_at"], "event.processed_at")
    event_available = instant(event["available_at"], "event.available_at")
    evidence_available = instant(evidence["available_at"], "evidence.available_at")
    if raw_times != sorted(raw_times) or raw_times[2] != raw_times[3] or processed != event_available or event_available < raw_times[-1] or evidence_available < raw_times[-1]:
        fail("bundle", "timestamp_order_invalid")
    if published is not None and published > raw_times[1]:
        fail("raw.source_published_at", "publication_after_fetch")

    if type(event["version"]) is not int or event["version"] < 1:
        fail("event.version", "invalid_event_version")
    choice(event["category"], {"macro", "policy", "company", "fund_flow", "geopolitics", "sentiment", "calendar", "other"}, "event.category")
    if type(event["markets"]) is not list or not event["markets"]:
        fail("event.markets", "nonempty_list_required")
    for market in event["markets"]:
        choice(market, {"A", "US", "GLOBAL"}, "event.markets")
    if len(event["markets"]) != len(set(event["markets"])):
        fail("event.markets", "duplicate_market")
    if type(event["entities"]) is not list:
        fail("event.entities", "list_required")
    for entity in event["entities"]:
        record(entity, {"name", "code", "type"}, "event.entities")
        text(entity["name"], "event.entities.name")
        text(entity["code"], "event.entities.code", nullable=True)
        choice(entity["type"], {"index", "stock", "sector", "commodity", "currency", "institution", "country", "other"}, "event.entities.type")
    choice(event["extraction_method"], {"fixture", "rule", "model", "manual"}, "event.extraction_method")
    choice(event["extraction_quality"], {"validated_fixture", "structurally_valid", "needs_review", "metadata_only"}, "event.extraction_quality")
    if not synthetic and (event["extraction_method"] == "fixture" or event["extraction_quality"] == "validated_fixture"):
        fail("event", "fixture_extraction_requires_synthetic")
    one_reference(event["input_raw_item_ids"], raw["raw_item_id"], "event.input_raw_item_ids")
    one_reference(event["evidence_ids"], evidence["evidence_id"], "event.evidence_ids")
    if evidence["raw_item_id"] != raw["raw_item_id"] or evidence["event_version_id"] != event["event_version_id"]:
        fail("evidence", "broken_reference")

    choice(evidence["relation"], {"supports", "reports", "contradicts"}, "evidence.relation")
    choice(evidence["claim_key"], {"fact_summary", "title"}, "evidence.claim_key")
    choice(evidence["validation_status"], {"exact_quote_match"}, "evidence.validation_status")
    if evidence["normalization_version"] != raw["normalization_version"]:
        fail("evidence.normalization_version", "normalization_mismatch")
    loc = evidence["locator"]
    record(loc, {"field", "offset_unit", "start", "end"}, "evidence.locator")
    choice(loc["field"], {"normalized_text"}, "evidence.locator.field")
    choice(loc["offset_unit"], {"unicode_code_point"}, "evidence.locator.offset_unit")
    if type(loc["start"]) is not int or type(loc["end"]) is not int or not 0 <= loc["start"] < loc["end"] <= len(raw["normalized_text"]):
        fail("evidence.locator", "invalid_locator")
    if raw["normalized_text"][loc["start"]:loc["end"]] != evidence["quote"]:
        fail("evidence.quote", "quote_mismatch")
    if type(raw["content_sha256"]) is not str or not SHA256.fullmatch(raw["content_sha256"]) or hashlib.sha256(raw["normalized_text"].encode("utf-8")).hexdigest() != raw["content_sha256"]:
        fail("raw.content_sha256", "content_hash_mismatch")
    if raw["content_ref"] != f"raw/{raw['content_sha256']}.txt":
        fail("raw.content_ref", "content_address_required")
    if raw["storage_policy"] == "metadata_only":
        if raw["normalized_text"] != raw["title"] or event["fact_summary"] != raw["title"] or event["title"] != raw["title"] or evidence["quote"] != raw["title"] or evidence["relation"] != "reports" or event["extraction_quality"] != "metadata_only":
            fail("bundle", "metadata_only_cannot_assert_body_facts")
