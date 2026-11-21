"""Plan an offline evaluation window from a synthetic prediction receipt."""

from . import instant, record
from .candidate_snapshot import payload_sha256
from .prediction_input import validate_prediction_input


_RECEIPT_FIELDS = {"schema_version", "prediction_id", "content_sha256", "committed_at"}


def _invalid():
    raise ValueError("synthetic_evaluation_window_invalid") from None


def plan_synthetic_evaluation_window(value, receipt):
    """Select a fixed session window using the receipt's post-commit time."""
    try:
        validate_prediction_input(value)
        content = value["content"]
        record(receipt, _RECEIPT_FIELDS, "receipt")
        if (type(receipt["schema_version"]) is not str
                or receipt["schema_version"] != "prediction-receipt/0.1"
                or type(receipt["prediction_id"]) is not str
                or receipt["prediction_id"] != content["prediction_id"]
                or type(receipt["content_sha256"]) is not str
                or receipt["content_sha256"] != payload_sha256(content)):
            _invalid()
        committed = instant(receipt["committed_at"], "committed_at")
        if committed < instant(content["created_at"], "created_at"):
            _invalid()

        horizon = value["inputs"]["protocol"]["horizon_sessions"]
        sessions = []
        for session in value["inputs"]["calendar"]["sessions"]:
            if instant(session["opens_at"], "opens_at") > committed:
                sessions.append(dict(session))
                if len(sessions) == horizon:
                    break
        return {
            "schema_version": "synthetic-evaluation-window/0.1",
            "is_synthetic": True,
            "prediction_id": content["prediction_id"],
            "content_sha256": receipt["content_sha256"],
            "committed_at": receipt["committed_at"],
            "calendar_snapshot_sha256": content["calendar_snapshot_sha256"],
            "evaluation_protocol_sha256": content["evaluation_protocol_sha256"],
            "horizon_sessions": horizon,
            "status": "planned" if len(sessions) == horizon else "pending",
            "sessions": sessions,
        }
    except ValueError:
        _invalid()
