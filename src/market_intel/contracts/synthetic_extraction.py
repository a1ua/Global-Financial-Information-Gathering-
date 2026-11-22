"""Bind a synthetic classification proposal to one fixed reference text."""

from collections import Counter

from . import EVENT_CATEGORIES, choice, instant, record, text, validate_bundle


_FIELDS = {
    "schema_version", "is_synthetic", "raw_item_id", "content_sha256",
    "normalization_version", "category", "start", "end", "quote",
}
_BINDING_FIELDS = ("raw_item_id", "content_sha256", "normalization_version")


def _reference_raw(reference_bundle, cutoff_at):
    validate_bundle(reference_bundle)
    raw = reference_bundle["raw"]
    if (raw["is_synthetic"] is not True or raw["storage_policy"] != "full_text_fixture"
            or instant(raw["available_at"], "raw.available_at") > cutoff_at):
        raise ValueError
    return raw


def _bound_category(raw, proposal):
    record(proposal, _FIELDS, "proposal")
    choice(proposal["schema_version"], {"synthetic-extraction-proposal/0.1"}, "proposal.schema_version")
    choice(proposal["category"], EVENT_CATEGORIES, "proposal.category")
    text(proposal["quote"], "proposal.quote")
    if (proposal["is_synthetic"] is not True
            or any(type(proposal[key]) is not str or proposal[key] != raw[key] for key in _BINDING_FIELDS)):
        raise ValueError
    start, end = proposal["start"], proposal["end"]
    source = raw["normalized_text"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source)
            or source[start:end] != proposal["quote"]):
        raise ValueError
    return proposal["category"]


def validate_synthetic_extraction(reference_bundle, proposal, *, cutoff):
    """Validate provenance and literal quote placement without scoring support."""
    try:
        raw = _reference_raw(reference_bundle, instant(cutoff, "cutoff"))
        category = _bound_category(raw, proposal)
        return {
            "schema_version": "synthetic-extraction-validation/0.1",
            "is_synthetic": True,
            "status": "structurally_valid",
            "raw_item_id": raw["raw_item_id"],
            "content_sha256": raw["content_sha256"],
            "category": category,
            "start": proposal["start"],
            "end": proposal["end"],
        }
    except ValueError:
        raise ValueError("synthetic_extraction_invalid") from None


def evaluate_synthetic_extraction(cases, *, cutoff):
    """Count agreement with supplied category labels for a synthetic validation set."""
    counts = dict.fromkeys(("correct", "incorrect", "invalid", "missing"), 0)
    pairs = Counter()
    seen = set()
    try:
        cutoff_at = instant(cutoff, "cutoff")
        if type(cases) is not list or len(cases) > 1000:
            raise ValueError
        for case in cases:
            record(case, {"reference_bundle", "expected_category", "proposal"}, "case")
            expected = case["expected_category"]
            choice(expected, EVENT_CATEGORIES, "case.expected_category")
            raw = _reference_raw(case["reference_bundle"], cutoff_at)
            identity = raw["raw_item_id"]
            if identity in seen:
                raise ValueError
            seen.add(identity)
            proposal = case["proposal"]
            if proposal is None:
                counts["missing"] += 1
                continue
            try:
                category = _bound_category(raw, proposal)
            except ValueError:
                counts["invalid"] += 1
                continue
            pairs[expected, category] += 1
            counts["correct" if category == expected else "incorrect"] += 1
    except ValueError:
        raise ValueError("synthetic_extraction_evaluation_invalid") from None

    return {
        "schema_version": "synthetic-extraction-evaluation/0.1",
        "is_synthetic": True,
        "counts": {"total": len(cases), **counts},
        "category_pairs": [
            {"expected_category": expected, "proposed_category": category, "count": count}
            for (expected, category), count in sorted(pairs.items())
        ],
    }
