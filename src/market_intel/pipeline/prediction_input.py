"""Load the exact evidence versions bound to a validated synthetic prediction."""

from ..contracts.prediction_input import validate_prediction_input
from .candidate_snapshot import load_candidate_snapshot_inputs


def load_prediction_inputs(workspace, value):
    """Validate first, then verify the fixed evidence snapshot in read-only mode."""
    validate_prediction_input(value)
    try:
        return load_candidate_snapshot_inputs(workspace, value["inputs"]["evidence_snapshot"])
    except (ValueError, OSError):
        raise ValueError("prediction_inputs_unavailable") from None
