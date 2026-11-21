"""Validate a bounded synthetic prediction and its fixed input manifest."""

from . import choice, identifier, instant, record, text
from .candidate_snapshot import canonical_json, payload_sha256, validate_candidate_snapshot


_LIMIT = 1_048_576
_CONTENT_FIELDS = set("""schema_version prediction_id prediction_family_id event_version_ids evidence_ids
cluster_version_id model_call_id model_ledger_id model_call_manifest_sha256 created_at
target_instrument_id benchmark_instrument_id direction direction_basis judgment_confidence reasoning
counter_evidence abstention_reason evaluation_protocol_id evaluation_protocol_sha256 calendar_snapshot_id
calendar_snapshot_sha256 rules_version input_manifest_sha256 supersedes_prediction_id is_synthetic""".split())
_INPUT_FIELDS = {"schema_version", "evidence_snapshot", "model_call", "protocol", "calendar", "rules_version"}
_OUTPUT_FIELDS = ("direction", "direction_basis", "judgment_confidence", "reasoning",
                  "counter_evidence", "abstention_reason")
_FIXTURE_FIELDS = {"schema_version", "is_synthetic", "available_at"}


def _invalid():
    raise ValueError("prediction_input_invalid") from None


def _bounded_json(value):
    nodes = string_bytes = 0

    def visit(item, depth):
        nonlocal nodes, string_bytes
        nodes += 1
        if depth > 16 or nodes > 32768:
            _invalid()
        kind = type(item)
        if kind is dict:
            for key, member in item.items():
                if type(key) is not str:
                    _invalid()
                visit(key, depth + 1)
                visit(member, depth + 1)
        elif kind is list:
            for member in item:
                visit(member, depth + 1)
        elif kind is str:
            if len(item) > 65536:
                _invalid()
            size = len(item.encode("utf-8"))
            string_bytes += size
            if size > 65536 or string_bytes > _LIMIT:
                _invalid()
        elif kind is int:
            if not -(2**63) <= item < 2**63:
                _invalid()
        elif kind is not bool and item is not None:
            _invalid()

    visit(value, 0)
    if len(canonical_json(value).encode("utf-8")) > _LIMIT:
        _invalid()


def _fixture(value, version, fields, created):
    record(value, _FIXTURE_FIELDS | fields, "fixture")
    available = instant(value["available_at"], "available_at")
    if value["schema_version"] != version or value["is_synthetic"] is not True or available > created:
        _invalid()
    return available


def _validate(value):
    record(value, {"content", "inputs"}, "prediction")
    content, inputs = value["content"], value["inputs"]
    record(content, _CONTENT_FIELDS, "content")
    record(inputs, _INPUT_FIELDS, "inputs")
    if (content["schema_version"] != "prediction-content/0.1"
            or content["is_synthetic"] is not True or content["cluster_version_id"] is not None
            or inputs["schema_version"] != "prediction-input-manifest/0.1"
            or content["rules_version"] != inputs["rules_version"]):
        _invalid()
    for field in ("prediction_id", "prediction_family_id", "model_call_id", "model_ledger_id",
                  "target_instrument_id", "benchmark_instrument_id", "evaluation_protocol_id",
                  "calendar_snapshot_id", "rules_version"):
        identifier(content[field], field)
    predecessor = content["supersedes_prediction_id"]
    identifier(predecessor, "supersedes_prediction_id", nullable=True)
    if predecessor == content["prediction_id"]:
        _invalid()

    choice(content["direction"], {"positive", "negative", "neutral", "mixed", "uncertain"}, "direction")
    choice(content["direction_basis"], {"absolute_return", "benchmark_relative"}, "direction_basis")
    choice(content["judgment_confidence"], {"low", "medium", "high"}, "judgment_confidence")
    text(content["reasoning"], "reasoning")
    if len(content["reasoning"].encode("utf-8")) > 4096:
        _invalid()
    reason = content["abstention_reason"]
    if content["direction"] == "uncertain":
        text(reason, "abstention_reason")
        if len(reason.encode("utf-8")) > 1024:
            _invalid()
    elif reason is not None:
        _invalid()

    created = instant(content["created_at"], "created_at")
    snapshot = inputs["evidence_snapshot"]
    validate_candidate_snapshot(snapshot)
    manifest = snapshot["input_manifest"]
    cutoff = instant(manifest["cutoff"], "cutoff")
    candidates = manifest["candidates"]
    if not candidates or cutoff > created or any(not candidate["is_synthetic"] for candidate in candidates):
        _invalid()
    for field, key in (("event_version_ids", "event_version_id"), ("evidence_ids", "evidence_id")):
        if content[field] != sorted(candidate[key] for candidate in candidates):
            _invalid()
    counter = content["counter_evidence"]
    if (type(counter) is not list or any(type(item) is not str or item not in content["evidence_ids"] for item in counter)
            or counter != sorted(set(counter))):
        _invalid()

    model_call, protocol, calendar = inputs["model_call"], inputs["protocol"], inputs["calendar"]
    model_available = _fixture(model_call, "prediction-fixture-call/0.1",
                               {"ledger_id", "call_id", "evidence_manifest_sha256", "output_sha256"}, created)
    if (model_available < cutoff or model_call["ledger_id"] != content["model_ledger_id"]
            or model_call["call_id"] != content["model_call_id"]
            or model_call["evidence_manifest_sha256"] != snapshot["input_manifest_sha256"]
            or model_call["output_sha256"] != payload_sha256({key: content[key] for key in _OUTPUT_FIELDS})):
        _invalid()

    shared_protocol_fields = {"target_instrument_id", "benchmark_instrument_id",
                              "direction_basis", "calendar_snapshot_id"}
    _fixture(protocol, "prediction-fixture-protocol/0.1",
             shared_protocol_fields | {"protocol_id", "horizon_sessions"}, created)
    if (protocol["protocol_id"] != content["evaluation_protocol_id"]
            or any(protocol[field] != content[field] for field in shared_protocol_fields)):
        _invalid()

    _fixture(calendar, "prediction-fixture-calendar/0.1", {"calendar_snapshot_id", "sessions"}, created)
    sessions, horizon = calendar["sessions"], protocol["horizon_sessions"]
    if (calendar["calendar_snapshot_id"] != content["calendar_snapshot_id"]
            or type(sessions) is not list or not 1 <= len(sessions) <= 32
            or type(horizon) is not int or not 1 <= horizon <= min(5, len(sessions))):
        _invalid()
    previous_close = None
    for session in sessions:
        record(session, {"opens_at", "closes_at"}, "session")
        opens = instant(session["opens_at"], "opens_at")
        closes = instant(session["closes_at"], "closes_at")
        if opens >= closes or (previous_close is not None and opens <= previous_close):
            _invalid()
        previous_close = closes

    for key, payload in (("input_manifest_sha256", inputs), ("model_call_manifest_sha256", model_call),
                         ("evaluation_protocol_sha256", protocol), ("calendar_snapshot_sha256", calendar)):
        if content[key] != payload_sha256(payload):
            _invalid()


def validate_prediction_input(value):
    """Validate fixed synthetic input structure and hashes without I/O."""
    try:
        _bounded_json(value)
        _validate(value)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _invalid()
