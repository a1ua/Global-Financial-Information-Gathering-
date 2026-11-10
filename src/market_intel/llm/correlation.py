"""Pure, optional response correlation; neither invoice proof nor settlement."""

import hashlib
import re


_ID = re.compile(r"[A-Za-z0-9_.-]{1,256}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _fail():
    raise ValueError("provider_correlation_invalid") from None


def response_id_sha256(value):
    if type(value) is not str or not _ID.fullmatch(value):
        _fail()
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def validate_response_hash(value):
    if value is not None and (type(value) is not str or not _SHA.fullmatch(value)):
        _fail()


def validate_provider_response(value):
    if (type(value) is not dict or value.keys() != {"schema_version", "response_id_sha256", "input_tokens", "output_tokens"}
            or value["schema_version"] != "provider-response-correlation/0.1"):
        _fail()
    validate_response_hash(value["response_id_sha256"])
    if any(type(value[key]) is not int or not 1 <= value[key] <= 10**12 for key in ("input_tokens", "output_tokens")):
        _fail()


def validate_provider_failure(value):
    if (type(value) is not dict or value.keys() != {"schema_version", "response_id_sha256"}
            or value["schema_version"] != "provider-failure-correlation/0.1"
            or value["response_id_sha256"] is None):
        _fail()
    validate_response_hash(value["response_id_sha256"])


def validate_call_correlation(metadata, call):
    if type(metadata) is not dict:
        _fail()
    success, failure = "provider_response" in metadata, "provider_failure" in metadata
    if success and failure:
        _fail()
    if not success and not failure:
        return
    value = metadata["provider_failure" if failure else "provider_response"]
    (validate_provider_failure if failure else validate_provider_response)(value)
    try:
        status, incoming, outgoing = (call[key] for key in ("status", "input_tokens", "output_tokens"))
    except (TypeError, KeyError, IndexError):
        _fail()
    if failure:
        if status != "failed" or incoming is not None or outgoing is not None:
            _fail()
        return
    if status != "succeeded" or any(type(actual) is not int or actual != value[key]
                                    for key, actual in (("input_tokens", incoming), ("output_tokens", outgoing))):
        _fail()
