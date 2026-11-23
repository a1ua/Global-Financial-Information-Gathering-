import argparse
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from .contracts.weekly_review import summarize_synthetic_week
from .contracts.synthetic_extraction import evaluate_synthetic_extraction
from .capture import SOURCES, collect_all, collect_source, now
from .offline import connect, ingest_fixture, render, replay_report
from .pipeline.capture_state import checkpoint
from .ops.backup import create_backup, restore_backup, verify_backup
from .report.verify import verify_report
from .report.session_brief import render_session_brief, replay_session_brief, verify_session_brief
from .report.weekly_review import render_synthetic_week_markdown
from .llm import ModelClient, ModelError, Policy
from .llm.deepseek import DeepSeekTransport
from .llm.correlation import response_id_sha256
from .llm.binding import check_workspace_ledger, ensure_workspace_ledger
from .ops.llm_backup import create_ledger_backup, restore_ledger_backup, verify_ledger_backup
from .ops.reconciliation import preview_reconciliation, prepare_audit_observation
from .ops.audit_journal import append_observation, verify_audit_journal
from .ops.recovery_preflight import preflight_ledger_recovery
from .pipeline.candidates import select_candidates
from .pipeline.process.cluster import (
    adjudicate_synthetic_event_clusters,
    evaluate_synthetic_event_clusters,
    plan_synthetic_event_clusters,
)
from .pipeline.evidence_candidates import plan_evidence_candidates
from .pipeline.market_sample_audit import audit_sse_index_sample, audit_szse_index_sample, compare_index_samples
from .ops.candidate_snapshot import (freeze_candidate_snapshot, verify_candidate_snapshot_file,
                                     replay_candidate_snapshot, verify_candidate_replay)
from .ops.market_replay import create_market_replay, verify_market_replay
from .ops.model_calls import inspect_model_call
from .ops.provider_preflight import preflight_provider_evidence
from .ops.provider_receipt import compare_provider_receipt
from .ops.scheduler import (
    acquire_run_lock,
    plan_missed_runs,
    read_ops_status,
    record_ops_run,
    release_run_lock,
    render_windows_task_template,
)
from .llm.batch import run_mock_candidates
from .llm.client import _strict_loads
from .ops.backup import _linked


def _deepseek_policy(*, enabled=False):
    return Policy(provider="deepseek", model="deepseek-flash", enabled=enabled,
                  budget_currency="CNY", daily_micro_units=10_000_000, daily_tokens=100_000,
                  input_micro_units_per_million_tokens=2_000_000,
                  output_micro_units_per_million_tokens=8_000_000,
                  max_input_tokens=16384, max_retries=0)


def _load_candidate_input(path):
    try:
        path = path.absolute()
        if any(_linked(item) for item in (path, *path.parents)):
            raise ValueError("candidate_input_link_forbidden")
        if not path.is_file():
            raise ValueError("candidate_input_missing")
        with path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("candidate_input_too_large")
        try:
            return _strict_loads(raw.decode("utf-8"))
        except (ModelError, UnicodeError):
            raise ValueError("candidate_input_invalid") from None
    except OSError:
        raise ValueError("candidate_input_io_error") from None


def _read_local_sample_file(path, *, limit, role):
    try:
        path = path.absolute()
        if path.drive.startswith("\\\\") or any(_linked(item) for item in (path, *path.parents)):
            raise ValueError(f"{role}_unsupported")
        if not path.is_file():
            raise ValueError(f"{role}_missing")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        raise ValueError(f"{role}_io_error") from None
    if len(raw) > limit:
        raise ValueError(f"{role}_too_large")
    return raw


def _hash_provider_response_id():
    if sys.stdin.isatty():
        raise ValueError("provider_correlation_invalid")
    try:
        # One 256-byte ID, an optional CRLF, and one byte to detect excess input.
        raw = sys.stdin.buffer.read(259)
    except OSError:
        raise ValueError("provider_response_id_input_error") from None
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        value = raw.decode("ascii")
    except UnicodeError:
        raise ValueError("provider_correlation_invalid") from None
    return {"response_id_sha256": response_id_sha256(value)}


def _candidate_command(args):
    batch = _load_candidate_input(args.input)
    selection = select_candidates(batch, args.cutoff, args.max_candidates)
    if args.command == "candidate-plan":
        return {**{k: v for k, v in selection.items() if k != "selected"},
                "selected_ids": [c["candidate_id"] for c in selection["selected"]]}
    policy = Policy(provider="mock", model="mock-candidates/0.1", enabled=True,
                    budget_currency="CNY", daily_micro_units=10_000_000, daily_tokens=100_000,
                    input_micro_units_per_million_tokens=2_000_000,
                    output_micro_units_per_million_tokens=8_000_000,
                    max_input_tokens=16384, max_retries=0)
    binding = ensure_workspace_ledger(args.workspace) if selection["selected"] else None
    return run_mock_candidates(batch, args.workspace / "llm-state.db", args.cutoff, args.max_candidates,
                               policy=policy, expected_ledger_id=binding["ledger_id"] if binding else None)


def _deepseek_command(args):
    ledger = args.workspace / "llm-state.db"
    if args.command == "deepseek-check":
        binding = check_workspace_ledger(args.workspace)
        return {"status": "configured_not_called", "provider": "deepseek", "model": "deepseek-flash",
                "currency": "CNY", "daily_limit_micro_cny": 10_000_000, "daily_tokens": 100_000,
                "budget_day_timezone": "UTC", "live_enabled": False,
                "ledger": binding["ledger"], "ledger_exists": ledger.is_file(), "binding": binding,
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
    binding = ensure_workspace_ledger(args.workspace)
    client = ModelClient(Path(binding["ledger"]), _deepseek_policy(enabled=True), transport)
    if client.ledger_id != binding["ledger_id"]:
        raise ModelError("ledger_identity_mismatch")
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
            "output": result.value, "ledger_id": client.ledger_id,
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
    sb = sub.add_parser("session-brief", help="Generate a dual-template (HTML + Markdown) degraded session brief")
    sb.add_argument("--workspace", type=Path, default=Path("data/live"))
    sb.add_argument("--report-type", choices=("pre_market", "post_market"), required=True)
    sb.add_argument("--session-date", required=True)
    sb.add_argument("--cutoff", default=None)
    sb.add_argument("--report-id", default=None)
    sb.add_argument("--run-id", default=None)
    sb.add_argument("--display-timezone", default="Asia/Shanghai")
    sb.add_argument("--supersedes", default=None)
    sb.add_argument("--synthetic-empty", action="store_true")
    sb_verify = sub.add_parser("verify-session-brief", help="Verify published dual-template session brief read-only")
    sb_verify.add_argument("--workspace", type=Path, default=Path("data/live"))
    sb_verify.add_argument("--report-id", required=True)
    sb_replay = sub.add_parser("replay-session-brief", help="Replay a verified dual-template session brief into a separate destination")
    sb_replay.add_argument("--workspace", type=Path, default=Path("data/live"))
    sb_replay.add_argument("--report-id", required=True)
    sb_replay.add_argument("--destination", type=Path, default=Path("out/replay-session"))
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
    ledger_bind = sub.add_parser("ledger-bind", help="Initialize or explicitly adopt a fixed workspace ledger")
    ledger_bind.add_argument("--workspace", type=Path, default=Path("data/live"))
    ledger_bind.add_argument("--adopt-existing", action="store_true")
    ledger_backup = sub.add_parser("ledger-backup", help="Snapshot a model budget ledger to a new directory")
    ledger_backup.add_argument("--ledger", type=Path, required=True)
    ledger_backup.add_argument("--destination", type=Path, required=True)
    ledger_verify = sub.add_parser("verify-ledger-backup", help="Verify a budget ledger snapshot read-only")
    ledger_verify.add_argument("--backup", type=Path, required=True)
    ledger_restore = sub.add_parser("restore-ledger", help="Restore a ledger snapshot as a new isolated copy")
    ledger_restore.add_argument("--backup", type=Path, required=True)
    ledger_restore.add_argument("--destination", type=Path, required=True)
    reconciliation = sub.add_parser("ledger-reconcile-preview", help="Compare an unverified statement read-only; never settle fees")
    reconciliation.add_argument("--workspace", type=Path, default=Path("data/live"))
    reconciliation.add_argument("--statement", type=Path, required=True)
    preflight = sub.add_parser("ledger-recovery-preflight", help="Compare a recovery candidate read-only; never switch production")
    preflight.add_argument("--workspace", type=Path, default=Path("data/live"))
    preflight.add_argument("--backup", type=Path, required=True)
    audit = sub.add_parser("ledger-audit-record", help="Explicitly append an unverified preview observation to a local audit journal")
    audit.add_argument("--workspace", type=Path, default=Path("data/live"))
    audit.add_argument("--statement", type=Path, required=True)
    audit.add_argument("--journal", type=Path, required=True)
    audit_verify = sub.add_parser("verify-ledger-audit", help="Check a local audit chain; no external trust or switch permission")
    audit_verify.add_argument("--journal", type=Path, required=True)
    for command in ("candidate-plan", "candidate-mock-run"):
        candidate = sub.add_parser(command, help="Plan or explicitly run bounded synthetic candidates with mock responses only")
        candidate.add_argument("--input", type=Path, required=True)
        candidate.add_argument("--cutoff", required=True)
        candidate.add_argument("--max-candidates", type=int, default=5)
        if command == "candidate-mock-run":
            candidate.add_argument("--workspace", type=Path, default=Path("out/candidate-mock"))
    evidence_candidates = sub.add_parser("evidence-candidate-plan", help="Read existing evidence versions and visibility receipts; no models or capture")
    evidence_candidates.add_argument("--workspace", type=Path, default=Path("data/live"))
    evidence_candidates.add_argument("--cutoff", required=True)
    evidence_candidates.add_argument("--max-candidates", type=int, default=5)
    evidence_candidates.add_argument("--include-synthetic", action="store_true")
    for command in ("freeze-evidence-candidates", "verify-evidence-candidates", "replay-evidence-candidates"):
        snapshot = sub.add_parser(command, help="Freeze or verify exact evidence inputs; no models or source refresh")
        snapshot.add_argument("--workspace", type=Path, default=Path("data/live"))
        if command == "freeze-evidence-candidates":
            snapshot.add_argument("--cutoff", required=True)
            snapshot.add_argument("--max-candidates", type=int, default=5)
            snapshot.add_argument("--include-synthetic", action="store_true")
        else:
            snapshot.add_argument("--manifest", type=Path, required=True)
        if command != "verify-evidence-candidates":
            snapshot.add_argument("--destination", type=Path, required=True)
    replay_verify = sub.add_parser("verify-candidate-replay", help="Verify a self-contained candidate replay offline")
    replay_verify.add_argument("--replay", type=Path, required=True)
    call_info = sub.add_parser("model-call-info", help="Read one bound model call summary; no model or settlement")
    call_info.add_argument("--workspace", type=Path, default=Path("data/live"))
    call_info.add_argument("--call-id", required=True)
    provider_preflight = sub.add_parser("provider-evidence-preflight", help="List supplier evidence gaps read-only; never verify or settle invoices")
    provider_preflight.add_argument("--workspace", type=Path, default=Path("data/live"))
    provider_preflight.add_argument("--call-id", required=True)
    receipt = sub.add_parser("compare-provider-receipt", help="Compare a local, unverified receipt claim")
    receipt.add_argument("--workspace", type=Path, required=True)
    receipt.add_argument("--call-id", required=True)
    receipt.add_argument("--claim", type=Path, required=True)
    sub.add_parser("hash-provider-response-id", help="Hash one provider response ID from redirected stdin")
    for exchange in ("sse", "szse"):
        market_audit = sub.add_parser(
            f"{exchange}-index-sample-audit",
            help=f"Audit a local index response against fixed {exchange.upper()} scheduled dates")
        market_audit.add_argument("--calendar", type=Path, required=True)
        market_audit.add_argument("--response", type=Path, required=True)
        market_audit.add_argument("--symbol", required=True)
        market_audit.add_argument("--start-date", required=True)
        market_audit.add_argument("--end-date", required=True)
        market_audit.add_argument("--explain-scope", action="store_true",
                                  help="Separate unexpected dates outside the range from unscheduled dates inside it")
    market_compare = sub.add_parser("compare-index-samples", help="Compare two local index samples against one schedule")
    market_compare.add_argument("--exchange", choices=("SSE", "SZSE"), required=True)
    for flag in ("--calendar", "--before", "--after"):
        market_compare.add_argument(flag, type=Path, required=True)
    for flag in ("--symbol", "--start-date", "--end-date"):
        market_compare.add_argument(flag, required=True)
    market_replay = sub.add_parser("create-synthetic-market-replay", help="Save a self-contained synthetic market replay")
    market_replay.add_argument("--input", type=Path, required=True)
    market_replay.add_argument("--destination", type=Path, required=True)
    market_verify = sub.add_parser("verify-synthetic-market-replay", help="Verify a saved synthetic market replay offline")
    market_verify.add_argument("--replay", type=Path, required=True)
    weekly_review = sub.add_parser("summarize-synthetic-week", help="Summarize local synthetic evaluation results")
    weekly_review.add_argument("--input", type=Path, required=True)
    weekly_review.add_argument("--week-monday", required=True)
    weekly_review.add_argument("--format", choices=("json", "markdown"), default="json")
    extraction_eval = sub.add_parser("evaluate-synthetic-extraction", help="Score local labeled synthetic extraction cases")
    extraction_eval.add_argument("--input", type=Path, required=True)
    extraction_eval.add_argument("--cutoff", required=True)
    extraction_eval.add_argument("--include-provenance", action="store_true",
                                 help="Include the SHA-256 of the input bytes and the applied UTC cutoff")
    extraction_eval.add_argument("--include-diagnostics", action="store_true",
                                 help="List the input positions of incorrect, invalid, and missing proposals")
    for command, help_text in (
        ("plan-synthetic-event-clusters", "Group local synthetic event candidates"),
        ("evaluate-synthetic-event-clusters", "Score exact candidates against labeled synthetic pairs"),
        ("adjudicate-synthetic-event-clusters", "Validate human decisions on synthetic title-review pairs"),
    ):
        event_clusters = sub.add_parser(command, help=help_text)
        event_clusters.add_argument("--input", type=Path, required=True)
        event_clusters.add_argument("--cutoff", required=True)
        if command == "evaluate-synthetic-event-clusters":
            event_clusters.add_argument("--include-title-review", action="store_true",
                                        help="Report labeled pairs added by the title review queue")
    ops_st = sub.add_parser("ops-status", help="Inspect workspace lock and run journal read-only")
    ops_st.add_argument("--workspace", type=Path, default=Path("data/live"))
    ops_st.add_argument("--now", default=None)
    ops_acq = sub.add_parser("ops-lock-acquire", help="Atomically acquire workspace single-instance run lock")
    ops_acq.add_argument("--workspace", type=Path, default=Path("data/live"))
    ops_acq.add_argument("--job", choices=("pre_market", "post_market", "collect_all", "manual_recovery"), required=True)
    ops_acq.add_argument("--run-id", required=True)
    ops_acq.add_argument("--ttl-seconds", type=int, default=900)
    ops_acq.add_argument("--now", default=None)
    ops_acq.add_argument("--lock-id", default=None)
    ops_acq.add_argument("--no-recover-expired", action="store_true")
    ops_rel = sub.add_parser("ops-lock-release", help="Release workspace single-instance run lock by owner lock_id")
    ops_rel.add_argument("--workspace", type=Path, default=Path("data/live"))
    ops_rel.add_argument("--lock-id", required=True)
    ops_rec = sub.add_parser("ops-record-run", help="Append one validated ops-run-record/0.1 entry to runs.jsonl")
    ops_rec.add_argument("--workspace", type=Path, default=Path("data/live"))
    ops_rec.add_argument("--input", type=Path, required=True)
    ops_plan = sub.add_parser("ops-plan-recovery", help="Plan missed pre/post market runs read-only; no auto execution")
    ops_plan.add_argument("--workspace", type=Path, default=Path("data/live"))
    ops_plan_src = ops_plan.add_mutually_exclusive_group(required=True)
    ops_plan_src.add_argument("--session-dates", default=None, help="Comma-separated YYYY-MM-DD dates")
    ops_plan_src.add_argument("--calendar-file", type=Path, default=None, help="JSON scheduled-session-snapshot/0.1 file")
    ops_plan.add_argument("--now", default=None)
    ops_plan.add_argument("--display-timezone", default="Asia/Shanghai")
    ops_plan.add_argument("--pre-market-local", default="08:30")
    ops_plan.add_argument("--post-market-local", default="16:30")
    ops_tpl = sub.add_parser("ops-render-task-template", help="Render dry-run Windows Task Scheduler XML template; never installs")
    ops_tpl.add_argument("--job", choices=("pre_market", "post_market"), required=True)
    ops_tpl.add_argument("--task-name", required=True)
    ops_tpl.add_argument("--trigger-time", required=True)
    ops_tpl.add_argument("--display-timezone", default="Asia/Shanghai")
    ops_tpl.add_argument("--workspace-rel", default="data/live")
    ops_tpl.add_argument("--start-date", default="2026-11-24")
    ops_tpl.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "ops-status":
            print(json.dumps(read_ops_status(args.workspace, now_utc=args.now), ensure_ascii=False))
            return 0
        if args.command == "ops-lock-acquire":
            result = acquire_run_lock(
                args.workspace,
                job_name=args.job,
                run_id=args.run_id,
                ttl_seconds=args.ttl_seconds,
                now_utc=args.now,
                lock_id=args.lock_id,
                recover_expired=not args.no_recover_expired,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["acquired"] else 2
        if args.command == "ops-lock-release":
            print(json.dumps(release_run_lock(args.workspace, lock_id=args.lock_id), ensure_ascii=False))
            return 0
        if args.command == "ops-record-run":
            raw = _read_local_sample_file(args.input, limit=65_536, role="ops_run_record")
            try:
                payload = _strict_loads(raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("ops_run_record_invalid") from None
            print(json.dumps(record_ops_run(args.workspace, payload), ensure_ascii=False))
            return 0
        if args.command == "ops-plan-recovery":
            if args.calendar_file is not None:
                raw = _read_local_sample_file(args.calendar_file, limit=262_144, role="ops_calendar_file")
                try:
                    scheduled = _strict_loads(raw.decode("utf-8"))
                except (ModelError, UnicodeError):
                    raise ValueError("ops_calendar_file_invalid") from None
            else:
                scheduled = [part.strip() for part in args.session_dates.split(",") if part.strip()]
            result = plan_missed_runs(
                args.workspace,
                scheduled_dates=scheduled,
                now_utc=args.now,
                display_timezone=args.display_timezone,
                pre_market_local=args.pre_market_local,
                post_market_local=args.post_market_local,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "ops-render-task-template":
            result = render_windows_task_template(
                job_name=args.job,
                task_name=args.task_name,
                trigger_local_time=args.trigger_time,
                display_timezone=args.display_timezone,
                workspace_rel=args.workspace_rel,
                start_date=args.start_date,
                output_path=args.output,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in {"create-synthetic-market-replay", "verify-synthetic-market-replay"}:
            result = (create_market_replay(args.input, args.destination)
                      if args.command == "create-synthetic-market-replay"
                      else verify_market_replay(args.replay))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "provider-evidence-preflight":
            print(json.dumps(preflight_provider_evidence(args.workspace, args.call_id), ensure_ascii=False))
            return 0
        if args.command == "compare-provider-receipt":
            raw = _read_local_sample_file(args.claim, limit=16 * 1024, role="provider_receipt_claim")
            try:
                claim = _strict_loads(raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("provider_receipt_claim_invalid") from None
            print(json.dumps(compare_provider_receipt(args.workspace, args.call_id, claim), ensure_ascii=False))
            return 0
        if args.command == "hash-provider-response-id":
            print(json.dumps(_hash_provider_response_id()))
            return 0
        if args.command == "model-call-info":
            print(json.dumps(inspect_model_call(args.workspace, args.call_id), ensure_ascii=False))
            return 0
        if args.command in ("freeze-evidence-candidates", "verify-evidence-candidates",
                            "replay-evidence-candidates", "verify-candidate-replay"):
            if args.command == "freeze-evidence-candidates":
                result = freeze_candidate_snapshot(args.workspace, args.destination, args.cutoff,
                                                   args.max_candidates, include_synthetic=args.include_synthetic)
            elif args.command == "verify-evidence-candidates":
                result = verify_candidate_snapshot_file(args.workspace, args.manifest)
            elif args.command == "replay-evidence-candidates":
                result = replay_candidate_snapshot(args.workspace, args.manifest, args.destination)
            else:
                result = verify_candidate_replay(args.replay)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in {"plan-synthetic-event-clusters", "evaluate-synthetic-event-clusters",
                            "adjudicate-synthetic-event-clusters"}:
            raw = _read_local_sample_file(args.input, limit=1_048_576, role="synthetic_event_cluster_input")
            try:
                payload = _strict_loads(raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("synthetic_event_cluster_input_invalid") from None
            if args.command == "evaluate-synthetic-event-clusters":
                if type(payload) is not dict or payload.keys() != {"bundles", "labels"}:
                    raise ValueError("synthetic_event_cluster_evaluation_invalid")
                result = evaluate_synthetic_event_clusters(
                    payload["bundles"], payload["labels"], cutoff=args.cutoff,
                    include_title_review=args.include_title_review,
                )
            elif args.command == "adjudicate-synthetic-event-clusters":
                if type(payload) is not dict or payload.keys() != {"bundles", "decisions"}:
                    raise ValueError("synthetic_event_cluster_adjudication_invalid")
                result = adjudicate_synthetic_event_clusters(payload["bundles"], payload["decisions"],
                                                            cutoff=args.cutoff)
            else:
                result = plan_synthetic_event_clusters(payload, cutoff=args.cutoff)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "evaluate-synthetic-extraction":
            raw = _read_local_sample_file(args.input, limit=1_048_576, role="synthetic_extraction_input")
            try:
                cases = _strict_loads(raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("synthetic_extraction_input_invalid") from None
            report = evaluate_synthetic_extraction(cases, cutoff=args.cutoff,
                                                   include_diagnostics=args.include_diagnostics)
            if args.include_provenance:
                report["provenance"] = {"input_sha256": sha256(raw).hexdigest(), "cutoff": args.cutoff}
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.command == "summarize-synthetic-week":
            raw = _read_local_sample_file(args.input, limit=1_048_576, role="weekly_review_input")
            try:
                results = _strict_loads(raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("weekly_review_input_invalid") from None
            summary = summarize_synthetic_week(results, week_monday=args.week_monday)
            if args.format == "markdown":
                print(render_synthetic_week_markdown(summary))
            else:
                print(json.dumps(summary, ensure_ascii=False))
            return 0
        if args.command in {"sse-index-sample-audit", "szse-index-sample-audit", "compare-index-samples"}:
            calendar_raw = _read_local_sample_file(args.calendar, limit=262_144, role="market_sample_file")
            try:
                calendar = _strict_loads(calendar_raw.decode("utf-8"))
            except (ModelError, UnicodeError):
                raise ValueError("market_sample_calendar_invalid") from None
            if args.command == "compare-index-samples":
                result = compare_index_samples(
                    _read_local_sample_file(args.before, limit=262_144, role="market_sample_before"),
                    _read_local_sample_file(args.after, limit=262_144, role="market_sample_after"),
                    calendar, exchange=args.exchange, symbol=args.symbol,
                    start_date=args.start_date, end_date=args.end_date,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 2 if result["status"] == "coverage_incomplete" else 0
            audit = audit_sse_index_sample if args.command == "sse-index-sample-audit" else audit_szse_index_sample
            result = audit(
                _read_local_sample_file(args.response, limit=262_144, role="market_sample_file"), calendar, symbol=args.symbol,
                start_date=args.start_date, end_date=args.end_date, explain_scope=args.explain_scope)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["audit"]["status"] == "complete" else 2
        if args.command == "evidence-candidate-plan":
            print(json.dumps(plan_evidence_candidates(args.workspace, args.cutoff, args.max_candidates,
                                                      include_synthetic=args.include_synthetic), ensure_ascii=False))
            return 0
        if args.command in ("candidate-plan", "candidate-mock-run"):
            result = _candidate_command(args)
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result.get("status") == "stopped" else 0
        if args.command == "verify-ledger-audit":
            print(json.dumps(verify_audit_journal(args.journal), ensure_ascii=False))
            return 0
        if args.command == "ledger-audit-record":
            try:
                root = args.workspace.resolve()
                journal = args.journal.resolve()
                roles = (args.statement, root / "llm-state.db", root / "llm-binding.json")
                if journal.is_relative_to(root) or any(
                        journal == path.resolve() or (journal.exists() and path.exists() and journal.samefile(path))
                        for path in roles):
                    raise ValueError("ledger_audit_path_conflict")
            except OSError:
                raise ValueError("ledger_audit_path_error") from None
            observation = prepare_audit_observation(args.workspace, args.statement)
            print(json.dumps(append_observation(args.journal, observation), ensure_ascii=False))
            return 0
        if args.command in ("ledger-reconcile-preview", "ledger-recovery-preflight"):
            result = (preview_reconciliation(args.workspace, args.statement)
                      if args.command == "ledger-reconcile-preview"
                      else preflight_ledger_recovery(args.workspace, args.backup))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in ("deepseek-check", "deepseek-smoke", "ledger-bind", "ledger-backup", "verify-ledger-backup", "restore-ledger"):
            if args.command.startswith("deepseek-"):
                result = _deepseek_command(args)
            elif args.command == "ledger-bind":
                result = ensure_workspace_ledger(args.workspace, adopt_existing=args.adopt_existing)
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
        db = sqlite3.connect((args.workspace / "market.db").resolve().as_uri() + "?mode=ro", uri=True) if args.command in ("validate-report", "verify-session-brief") else connect(args.workspace / "market.db")
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
            elif args.command == "session-brief":
                path = render_session_brief(
                    db,
                    args.workspace,
                    cutoff=args.cutoff or now(),
                    report_id=args.report_id or f"{args.report_type}_{uuid4().hex}",
                    report_type=args.report_type,
                    market_session_date=args.session_date,
                    run_id=args.run_id,
                    display_timezone=args.display_timezone,
                    supersedes_report_id=args.supersedes,
                    default_synthetic=args.synthetic_empty,
                )
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                result = {
                    "status": manifest["status"],
                    "report_id": manifest["report_id"],
                    "run_id": manifest["run_id"],
                    "report_type": manifest["report_type"],
                    "market_session_date": manifest["market_session_date"],
                    "is_synthetic": manifest["is_synthetic"],
                    "supersedes_report_id": manifest["supersedes_report_id"],
                    "html": str((path / "brief.html").resolve()),
                    "markdown": str((path / "brief.md").resolve()),
                    "manifest": str((path / "manifest.json").resolve()),
                }
            elif args.command == "verify-session-brief":
                result = verify_session_brief(db, args.workspace, args.report_id)
            elif args.command == "replay-session-brief":
                path = replay_session_brief(db, args.workspace, args.report_id, args.destination)
                result = {
                    "status": "replayed",
                    "report_id": args.report_id,
                    "html": str((path / "brief.html").resolve()),
                    "markdown": str((path / "brief.md").resolve()),
                    "manifest": str((path / "manifest.json").resolve()),
                }
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
