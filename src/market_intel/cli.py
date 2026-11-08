import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from .capture import SOURCES, collect_all, collect_source, now
from .offline import connect, ingest_fixture, render, replay_report
from .pipeline.capture_state import checkpoint
from .ops.backup import create_backup, restore_backup, verify_backup
from .report.verify import verify_report
from .llm import ModelClient, ModelError, Policy
from .llm.deepseek import DeepSeekTransport
from .ops.llm_backup import create_ledger_backup, restore_ledger_backup, verify_ledger_backup


def _deepseek_policy(*, enabled=False):
    return Policy(provider="deepseek", model="deepseek-flash", enabled=enabled,
                  budget_currency="CNY", daily_micro_units=10_000_000, daily_tokens=100_000,
                  input_micro_units_per_million_tokens=2_000_000,
                  output_micro_units_per_million_tokens=8_000_000,
                  max_input_tokens=16384, max_retries=0)


def _deepseek_command(args):
    ledger = args.workspace / "llm-state.db"
    if args.command == "deepseek-check":
        return {"status": "configured_not_called", "provider": "deepseek", "model": "deepseek-flash",
                "currency": "CNY", "daily_limit_micro_cny": 10_000_000, "daily_tokens": 100_000,
                "budget_day_timezone": "UTC", "live_enabled": False,
                "ledger": str(ledger), "ledger_exists": ledger.is_file(),
                "key_env": "DEEPSEEK_API_KEY", "key_checked": False,
                "account_wide_limit": False}
    if not args.live:
        raise ModelError("explicit_live_flag_required")
    if (args.workspace / "ledger-backup-manifest.json").exists():
        raise ModelError("isolated_ledger_not_live")
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise ModelError("deepseek_key_not_configured")
    transport = DeepSeekTransport(key)
    client = ModelClient(ledger, _deepseek_policy(enabled=True), transport)
    started_day = now()[:10]
    result = client.generate(
        {"title": "Synthetic integration check; no market fact.", "is_synthetic": True},
        system_prompt='Return JSON {"category":"other"} for this synthetic integration check only.',
        prompt_version="deepseek-smoke/0.1", rules_version="synthetic-only/0.1",
        output_schema={"type": "object", "properties": {"category": {"type": "string", "enum": ["other"]}},
                       "required": ["category"], "additionalProperties": False},
        schema_version="synthetic-category/0.1", parameters={"temperature": 0})
    return {"status": "validated_synthetic_smoke", "synthetic": True, "provider": "deepseek",
            "model": "deepseek-flash", "call_id": result.call_id, "cache_hit": result.cache_hit,
            "output": result.value,
            "budget_by_utc_day": {day: client.usage(day) for day in sorted({started_day, now()[:10]})}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-first market intelligence; bounded source capture and recovery")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Generate a clearly synthetic offline example")
    demo.add_argument("--workspace", type=Path, default=Path("out/demo"))
    demo.add_argument("--fixture", type=Path)
    for command in ("collect-fed", "collect-nbs", "collect-all"):
        collect = sub.add_parser(command, help="Discover a fixed official list and consume queued metadata")
        collect.add_argument("--workspace", type=Path, default=Path("data/live"))
        collect.add_argument("--limit", type=int, default=5)
        collect.add_argument("--transport", choices=("python", "node"), default="python")
    resume = sub.add_parser("resume", help="Consume persisted pending work without network access")
    resume.add_argument("--workspace", type=Path, default=Path("data/live"))
    resume.add_argument("--source", choices=("fed", "nbs", "all"), required=True)
    resume.add_argument("--limit", type=int, default=5)
    brief = sub.add_parser("brief", help="Generate an evidence snapshot, without model or price analysis")
    brief.add_argument("--workspace", type=Path, default=Path("data/live"))
    brief.add_argument("--cutoff", default=None)
    brief.add_argument("--report-id", default=None)
    replay = sub.add_parser("replay", help="Replay exact published input versions into a separate destination")
    replay.add_argument("--workspace", type=Path, default=Path("data/live"))
    replay.add_argument("--report-id", required=True)
    replay.add_argument("--destination", type=Path, default=Path("out/replay"))
    status = sub.add_parser("status")
    status.add_argument("--workspace", type=Path, default=Path("data/live"))
    validate = sub.add_parser("validate-report", help="Verify published manifest, evidence closure and file hashes")
    validate.add_argument("--workspace", type=Path, default=Path("data/live"))
    validate.add_argument("--report-id", required=True)
    backup = sub.add_parser("backup", help="Create a SQLite-consistent evidence backup at a new destination")
    backup.add_argument("--workspace", type=Path, default=Path("data/live"))
    backup.add_argument("--destination", type=Path, required=True)
    verify = sub.add_parser("verify-backup", help="Validate a backup without restoring it")
    verify.add_argument("--backup", type=Path, required=True)
    restore = sub.add_parser("restore", help="Restore a verified backup into a new workspace only")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    for command in ("deepseek-check", "deepseek-smoke"):
        model = sub.add_parser(command, help="Inspect configuration or explicitly run one synthetic DeepSeek call")
        model.add_argument("--workspace", type=Path, default=Path("data/live"))
        if command == "deepseek-smoke":
            model.add_argument("--live", action="store_true", help="Explicitly allow the configured paid API call")
    ledger_backup = sub.add_parser("ledger-backup", help="Snapshot a model budget ledger to a new directory")
    ledger_backup.add_argument("--ledger", type=Path, required=True)
    ledger_backup.add_argument("--destination", type=Path, required=True)
    ledger_verify = sub.add_parser("verify-ledger-backup", help="Verify a budget ledger snapshot read-only")
    ledger_verify.add_argument("--backup", type=Path, required=True)
    ledger_restore = sub.add_parser("restore-ledger", help="Restore a ledger snapshot as a new isolated copy")
    ledger_restore.add_argument("--backup", type=Path, required=True)
    ledger_restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("deepseek-check", "deepseek-smoke", "ledger-backup", "verify-ledger-backup", "restore-ledger"):
            if args.command.startswith("deepseek-"):
                result = _deepseek_command(args)
            elif args.command == "ledger-backup":
                result = create_ledger_backup(args.ledger, args.destination)
            elif args.command == "verify-ledger-backup":
                result = verify_ledger_backup(args.backup)
            else:
                result = restore_ledger_backup(args.backup, args.destination)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in ("backup", "verify-backup", "restore"):
            if args.command == "backup":
                result = create_backup(args.workspace, args.destination)
            elif args.command == "verify-backup":
                result = verify_backup(args.backup)
            else:
                result = restore_backup(args.backup, args.destination)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command not in ("demo", "collect-fed", "collect-nbs", "collect-all") and not (args.workspace / "market.db").exists():
            raise ValueError("workspace_database_missing")
        db = sqlite3.connect((args.workspace / "market.db").resolve().as_uri() + "?mode=ro", uri=True) if args.command == "validate-report" else connect(args.workspace / "market.db")
        try:
            if args.command == "demo":
                fixture = args.fixture.read_text(encoding="utf-8") if args.fixture else files("market_intel").joinpath("fixtures/demo.json").read_text(encoding="utf-8")
                ingest_fixture(db, json.loads(fixture), args.workspace)
                path = render(db, args.workspace, "2026-11-06T00:30:00Z", "demo_A_pre_v3")
                result = {"status": "degraded", "synthetic": True, "report": str((path / "brief.html").resolve())}
            elif args.command == "collect-all":
                result = collect_all(db, args.workspace, limit=args.limit, transport=args.transport)
            elif args.command in ("collect-fed", "collect-nbs"):
                result = collect_source(db, args.workspace, source=args.command.split("-")[1], limit=args.limit, transport=args.transport)
            elif args.command == "resume":
                result = collect_all(db, args.workspace, limit=args.limit, resume=True) if args.source == "all" else collect_source(db, args.workspace, source=args.source, limit=args.limit, resume=True)
            elif args.command == "brief":
                path = render(db, args.workspace, args.cutoff or now(), args.report_id or "source_" + uuid4().hex, report_kind="source_snapshot")
                result = {"status": "degraded", "report": str((path / "brief.html").resolve())}
            elif args.command == "replay":
                path = replay_report(db, args.workspace, args.report_id, args.destination)
                result = {"status": "replayed", "report": str((path / "brief.html").resolve())}
            elif args.command == "validate-report":
                result = verify_report(db, args.workspace, args.report_id)
            else:
                result = {"schema_version": db.execute("PRAGMA user_version").fetchone()[0], "counts": {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("raw_items", "event_versions", "evidence")}}
                result["sources"] = {key: checkpoint(db, value["id"]) for key, value in SOURCES.items()}
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    if result.get("status") == "failed":
        return 1
    if any(source.get("status") == "failed" for source in result.get("sources", []) if isinstance(source, dict)):
        return 2
    return 0
