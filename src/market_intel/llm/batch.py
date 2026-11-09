"""Bounded synthetic candidates using the existing mock ledger and cache only."""

import re

from .client import ModelClient, ModelError, ModelResponse, Policy
from .deepseek import DeepSeekTransport
from ..pipeline.candidates import select_candidates


_REQUEST = {
    "system_prompt": 'Return JSON {"category":"other"} for synthetic data only.',
    "prompt_version": "synthetic-candidate/0.1", "rules_version": "synthetic-only/0.1",
    "schema_version": "synthetic-category/0.1", "parameters": {"temperature": 0},
    "output_schema": {"type": "object", "properties": {"category": {"type": "string", "enum": ["other"]}},
                      "required": ["category"], "additionalProperties": False},
}


def _synthetic_transport(_request, _timeout):
    return ModelResponse('{"category":"other"}', 10, 5)


def run_mock_candidates(batch, state_path, cutoff, max_candidates=5, *, policy,
                        transport=None, clock=None, expected_ledger_id=None):
    """Stop at the first model error; all successful/reserved ledger rows remain."""
    if type(policy) is not Policy or policy.provider != "mock" or policy.enabled is not True:
        raise ModelError("candidate_mock_policy_required")
    if transport is not None and (not callable(transport) or isinstance(transport, DeepSeekTransport)):
        raise ModelError("candidate_mock_transport_required")
    if expected_ledger_id is not None and (type(expected_ledger_id) is not str or
                                          not re.fullmatch(r"ledger_[0-9a-f]{32}", expected_ledger_id)):
        raise ModelError("candidate_ledger_identity_invalid")
    selected = select_candidates(batch, cutoff, max_candidates)["selected"]
    results = []
    stopped = False
    if selected:
        client = ModelClient(state_path, policy, _synthetic_transport if transport is None else transport, clock=clock)
        if expected_ledger_id is not None and client.ledger_id != expected_ledger_id:
            raise ModelError("ledger_identity_mismatch")
        for candidate in selected:
            result = {"candidate_id": candidate["candidate_id"]}
            if stopped:
                result["status"] = "not_attempted"
            else:
                try:
                    generated = client.generate(candidate, **_REQUEST)
                except ModelError as error:
                    result.update(status="failed", reason=str(error))
                    stopped = True
                else:
                    result.update(status="succeeded", call_id=generated.call_id, cache_hit=generated.cache_hit)
            results.append(result)
    return {"schema_version": "synthetic-candidate-run/0.1", "status": "stopped" if stopped else "completed",
            "is_synthetic": True, "provider": "mock", "live_called": False, "max_candidates": max_candidates,
            "selected_count": len(selected), "succeeded_count": sum(r["status"] == "succeeded" for r in results),
            "failed_count": sum(r["status"] == "failed" for r in results),
            "not_attempted_count": sum(r["status"] == "not_attempted" for r in results), "results": results}
