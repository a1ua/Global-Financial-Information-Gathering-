"""Opt-in structured model calls with a durable, conservative budget ledger.

No network implementation is included. A transport must be explicitly injected.
"""

from .client import CallResult, ModelClient, ModelError, ModelResponse, Policy, TransientTransportError

__all__ = ["CallResult", "ModelClient", "ModelError", "ModelResponse", "Policy", "TransientTransportError"]
