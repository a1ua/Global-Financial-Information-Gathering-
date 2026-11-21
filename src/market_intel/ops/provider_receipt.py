"""Compare unverified supplier claims with one local estimate snapshot."""

from datetime import date
import re

from .model_calls import inspect_model_call


_FIELDS = {"schema_version", "call_id", "response_id_sha256", "provider", "model",
           "utc_day", "currency", "input_tokens", "output_tokens", "billed_micro_units"}


def _invalid():
    raise ValueError("provider_receipt_claim_invalid") from None


def _matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _validate(call_id, receipt):
    if (type(receipt) is not dict or receipt.keys() != _FIELDS
            or not _matches(call_id, r"call_[0-9a-f]{32}")):
        _invalid()
    if (type(receipt["schema_version"]) is not str
            or receipt["schema_version"] != "provider-receipt-claim/0.1"
            or not _matches(receipt["call_id"], r"call_[0-9a-f]{32}")
            or receipt["call_id"] != call_id
            or not _matches(receipt["response_id_sha256"], r"[0-9a-f]{64}")
            or type(receipt["provider"]) is not str or receipt["provider"] not in ("mock", "deepseek")
            or not _matches(receipt["model"], r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
            or type(receipt["currency"]) is not str or receipt["currency"] not in ("CNY", "USD")
            or not _matches(receipt["utc_day"], r"[0-9]{4}-[0-9]{2}-[0-9]{2}")):
        _invalid()
    try:
        date.fromisoformat(receipt["utc_day"])
    except ValueError:
        _invalid()
    for field, maximum in (("input_tokens", 10**9), ("output_tokens", 10**9),
                           ("billed_micro_units", 10**15)):
        if type(receipt[field]) is not int or not 0 <= receipt[field] <= maximum:
            _invalid()


def compare_provider_receipt(workspace, call_id, receipt):
    """Read-only comparison; an equal manual claim never authenticates an invoice."""
    _validate(call_id, receipt)
    summary = inspect_model_call(workspace, call_id)
    day = summary["started_at"][:10]
    missing = [field for field in ("response_id_sha256", "input_tokens", "output_tokens")
               if summary[field] is None]
    mismatches = []
    for field in ("provider", "model", "utc_day", "currency", "response_id_sha256",
                  "input_tokens", "output_tokens"):
        local = day if field == "utc_day" else summary[field]
        if local is not None and receipt[field] != local:
            mismatches.append(field)
    same_currency = receipt["currency"] == summary["currency"]
    if same_currency and receipt["billed_micro_units"] != summary["charged_cost_micro_units"]:
        mismatches.append("billed_micro_units")
    return {
        "schema_version": "provider-receipt-comparison/0.1",
        "status": "unverified_comparison", "read_only": True,
        "evidence_authenticated": False, "invoice_verified": False,
        "settlement_allowed": False, "switch_allowed": False, "model_called": False,
        "call_summary": summary, "budget_day_utc": day,
        "missing_local_fields": missing, "mismatched_fields": mismatches,
        "amount_comparison": ("configured_estimate_only" if same_currency
                              else "not_comparable_currency_mismatch"),
    }
