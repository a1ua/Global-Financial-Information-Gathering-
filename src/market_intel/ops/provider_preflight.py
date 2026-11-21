"""Local supplier-evidence gaps; never invoice authentication or settlement."""

from .model_calls import inspect_model_call


def preflight_provider_evidence(workspace, call_id):
    """Compose one validated read-only call snapshot without external evidence reads."""
    summary = inspect_model_call(workspace, call_id)
    gaps = []
    if summary["response_id_sha256"] is None:
        gaps.append("response_hash_missing")
    if summary["input_tokens"] is None or summary["output_tokens"] is None:
        gaps.append("usage_missing")
    gaps.append("supplier_receipt_missing")
    return {
        "schema_version": "provider-evidence-preflight/0.1",
        "status": "evidence_incomplete",
        "read_only": True,
        "model_called": False,
        "invoice_verified": False,
        "settlement_allowed": False,
        "switch_allowed": False,
        "call_summary": summary,
        "budget_day_utc": summary["started_at"][:10],
        "evidence_gaps": gaps,
        "supplier_receipt_requirements": [
            "response_id_hash", "provider", "model", "utc_day", "currency",
            "input_tokens", "output_tokens", "billed_amount", "provenance",
        ],
    }
