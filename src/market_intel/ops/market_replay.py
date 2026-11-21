"""Export and verify self-contained synthetic market replay artifacts."""

from functools import wraps
from os import scandir
from pathlib import Path

from ..contracts.market_snapshot import freeze_market_snapshot, load_market_snapshot
from .candidate_snapshot import _ArtifactError, _destination, _encoded, _path, _publish, _read_json


_LIMIT = 1024 * 1024
_REPLAY_FILE = "market-replay.json"
_SCHEMA = "synthetic-market-replay/0.1"
_INPUT_FIELDS = {"calendar_source", "instrument_id", "bars", "cutoff", "start_date", "end_date"}
_REPLAY_FIELDS = {"schema_version", "calendar_source", "snapshot", "bars"}


class _MarketReplayError(ValueError):
    pass


def _fail(reason):
    raise _MarketReplayError("market_replay_" + reason) from None


def _safe(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except _MarketReplayError:
            raise
        except _ArtifactError as exc:
            if str(exc) == "candidate_artifact_destination_exists":
                _fail("destination_exists")
            _fail("invalid")
        except FileExistsError:
            _fail("destination_exists")
        except OSError:
            _fail("io_error")
        except (ValueError, TypeError, RecursionError):
            _fail("invalid")
    return run


def _local_path(value):
    path = Path(value).absolute()
    if path.drive.startswith("\\\\"):
        _fail("invalid")
    return path


def _summary(snapshot, status):
    return {
        "schema_version": "synthetic-market-replay-info/0.1",
        "status": status,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "selected_count": len(snapshot["selected"]),
        "missing_count": len(snapshot["missing_sessions"]),
        "is_synthetic": True,
    }


@_safe
def create_market_replay(input_path, destination):
    """Freeze an explicit local sample and write its selected rows to a new directory."""
    input_path, destination = _local_path(input_path), _local_path(destination)
    source_path, source, _ = _read_json(input_path, _LIMIT)
    if type(source) is not dict or source.keys() != _INPUT_FIELDS:
        _fail("invalid")
    calendar, bars = source["calendar_source"], source["bars"]
    snapshot = freeze_market_snapshot(
        calendar, source["instrument_id"], bars,
        cutoff=source["cutoff"], start_date=source["start_date"], end_date=source["end_date"],
    )
    replay = {
        "schema_version": _SCHEMA,
        "calendar_source": calendar,
        "snapshot": snapshot,
        "bars": load_market_snapshot(calendar, bars, snapshot),
    }
    data = _encoded(replay, _LIMIT)
    target = _destination(destination, source_path)
    _publish(target, [(_REPLAY_FILE, data)])
    return _summary(snapshot, "created")


@_safe
def verify_market_replay(directory):
    """Validate a complete replay directory using only its bundled inputs."""
    root = _path(_local_path(directory))
    if not root.is_dir():
        _fail("invalid")
    with scandir(root) as entries:
        first = next(entries, None)
        if first is None or first.name != _REPLAY_FILE or next(entries, None) is not None:
            _fail("invalid")
    _, replay, _ = _read_json(root / _REPLAY_FILE, _LIMIT)
    if (type(replay) is not dict or replay.keys() != _REPLAY_FIELDS
            or replay["schema_version"] != _SCHEMA):
        _fail("invalid")
    snapshot, bars = replay["snapshot"], replay["bars"]
    if load_market_snapshot(replay["calendar_source"], bars, snapshot) != bars:
        _fail("invalid")
    return _summary(snapshot, "verified")
