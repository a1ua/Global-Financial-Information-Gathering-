"""Pure deterministic selection of bounded, explicitly synthetic candidates."""

import re

from ..contracts import ContractError, instant


_BATCH_FIELDS = {"schema_version", "candidates"}
_CANDIDATE_FIELDS = {"candidate_id", "available_at", "title", "is_synthetic"}
_ID = re.compile(r"candidate_[A-Za-z0-9_-]{1,96}\Z")


def _fail(code):
    raise ValueError(code) from None


def _instant(value):
    try:
        return instant(value, "candidate.timestamp")
    except ContractError:
        _fail("candidate_timestamp_invalid")


def select_candidates(batch, cutoff, max_candidates=5):
    """Validate every input before deduplication, cutoff filtering and truncation."""
    if type(max_candidates) is not int or not 0 <= max_candidates <= 100:
        _fail("candidate_limit_invalid")
    limit = _instant(cutoff)
    if (type(batch) is not dict or batch.keys() != _BATCH_FIELDS
            or batch["schema_version"] != "synthetic-candidate-batch/0.1"
            or type(batch["candidates"]) is not list or len(batch["candidates"]) > 1000):
        _fail("candidate_batch_invalid")
    validated = []
    for candidate in batch["candidates"]:
        if (type(candidate) is not dict or candidate.keys() != _CANDIDATE_FIELDS
                or type(candidate["candidate_id"]) is not str
                or _ID.fullmatch(candidate["candidate_id"]) is None
                or candidate["is_synthetic"] is not True
                or type(candidate["title"]) is not str or not candidate["title"].strip()):
            _fail("candidate_invalid")
        try:
            if len(candidate["title"].encode("utf-8")) > 4096:
                _fail("candidate_invalid")
        except UnicodeError:
            _fail("candidate_invalid")
        stamp = _instant(candidate["available_at"])
        # Copy the strict scalar fields so returned records cannot mutate inputs.
        validated.append((dict(candidate), stamp))
    unique = {}
    for candidate, stamp in validated:
        candidate_id = candidate["candidate_id"]
        previous = unique.get(candidate_id)
        if previous is not None and previous[0] != candidate:
            _fail("candidate_conflict")
        unique[candidate_id] = candidate, stamp
    eligible = [(candidate, stamp) for candidate, stamp in unique.values() if stamp <= limit]
    eligible.sort(key=lambda item: (item[1], item[0]["candidate_id"]))
    selected = [candidate for candidate, _ in eligible[:max_candidates]]
    return {"schema_version": "candidate-selection/0.1", "is_synthetic": True,
            "cutoff": cutoff, "max_candidates": max_candidates,
            "input_count": len(validated), "unique_count": len(unique),
            "duplicate_count": len(validated) - len(unique),
            "future_count": len(unique) - len(eligible), "eligible_count": len(eligible),
            "limited_count": len(eligible) - len(selected), "selected_count": len(selected),
            "selected": selected}
