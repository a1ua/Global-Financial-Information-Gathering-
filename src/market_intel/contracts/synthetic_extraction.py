"""Bind a synthetic classification proposal to one fixed reference text."""

from . import EVENT_CATEGORIES, choice, instant, record, text, validate_bundle


_FIELDS = {
    "schema_version", "is_synthetic", "raw_item_id", "content_sha256",
    "normalization_version", "category", "start", "end", "quote",
}
_BINDING_FIELDS = ("raw_item_id", "content_sha256", "normalization_version")


def validate_synthetic_extraction(reference_bundle, proposal, *, cutoff):
    """Validate provenance and literal quote placement without scoring support."""
    try:
        record(proposal, _FIELDS, "proposal")
        choice(proposal["schema_version"], {"synthetic-extraction-proposal/0.1"}, "proposal.schema_version")
        choice(proposal["category"], EVENT_CATEGORIES, "proposal.category")
        text(proposal["quote"], "proposal.quote")
        cutoff_at = instant(cutoff, "cutoff")
        validate_bundle(reference_bundle)
        raw = reference_bundle["raw"]
        if (raw["is_synthetic"] is not True or raw["storage_policy"] != "full_text_fixture"
                or proposal["is_synthetic"] is not True
                or instant(raw["available_at"], "raw.available_at") > cutoff_at):
            raise ValueError
        if any(type(proposal[key]) is not str or proposal[key] != raw[key] for key in _BINDING_FIELDS):
            raise ValueError
        start, end = proposal["start"], proposal["end"]
        source = raw["normalized_text"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source)
                or source[start:end] != proposal["quote"]):
            raise ValueError
    except ValueError:
        raise ValueError("synthetic_extraction_invalid") from None

    return {
        "schema_version": "synthetic-extraction-validation/0.1",
        "is_synthetic": True,
        "status": "structurally_valid",
        "raw_item_id": raw["raw_item_id"],
        "content_sha256": raw["content_sha256"],
        "category": proposal["category"],
        "start": start,
        "end": end,
    }
