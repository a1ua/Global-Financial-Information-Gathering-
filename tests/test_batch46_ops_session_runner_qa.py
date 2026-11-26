"""Independent adversarial QA tests for Batch46 (B46-OPS-GUARDED-BRIEF).

Covers:
1. Pre-flight validation & zero side effects on invalid inputs (incl. UNC & NTFS junctions).
2. Real multi-thread concurrency, lock lifecycle, --no-recover-expired, and corrupt lock handling.
3. Runtime failures (report_id conflict, generated_before_cutoff), supplement chains,
   and non-synthetic / mixed / empty-cutoff is_synthetic alignment.
4. ops/backup.py dual-template session-brief-manifest/0.1 integration & tamper detection.
5. End-to-end CLI exit codes and ops-plan-recovery state transitions with anti-lookahead.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from importlib.resources import files

from market_intel.cli import main as cli_main
from market_intel.contracts import ContractError
from market_intel.offline import ingest_fixture, render as render_legacy_report
from market_intel.ops.backup import create_backup, restore_backup, verify_backup
from market_intel.ops.scheduler import (
    acquire_run_lock,
    inspect_run_lock,
    plan_missed_runs,
    read_ops_status,
    record_ops_run,
    release_run_lock,
)
from market_intel.ops.session_runner import run_guarded_session_brief
from market_intel.report.session_brief import verify_session_brief
from market_intel.report.verify import verify_report
from market_intel.store import connect, insert_immutable


def _demo_fixture():
    return json.loads(files("market_intel").joinpath("fixtures/demo.json").read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _snapshot_tree(root: Path):
    snap = {}
    if not root.exists():
        return snap
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        if p.is_file():
            snap[rel] = ("file", st.st_mtime_ns, p.read_bytes())
        elif p.is_dir():
            snap[rel] = ("dir", st.st_mtime_ns, None)
        else:
            snap[rel] = ("other", st.st_mtime_ns, None)
    return snap


def _make_metadata_only_bundle(
    *,
    suffix="fed1",
    available_at="2026-11-06T00:10:00Z",
    title="Federal Reserve issues FOMC statement",
):
    sha = _sha256_text(title)
    raw_id = f"raw_{suffix}_v1"
    ev_logical_id = f"event_{suffix}"
    event_ver_id = f"{ev_logical_id}_v1"
    ev_id = f"evidence_{suffix}_v1"
    return {
        "raw": {
            "schema_version": "raw-item/0.1",
            "raw_item_id": raw_id,
            "source_id": "fed_press_all",
            "source_config_version": "sources-official-1",
            "source_item_key": f"key-{suffix}-v1",
            "original_url": f"https://www.federalreserve.gov/newsevents/pressreleases/{suffix}.htm",
            "canonical_url": f"https://www.federalreserve.gov/newsevents/pressreleases/{suffix}.htm",
            "source_tier": "primary",
            "title": title,
            "source_time_text": "2026-11-06 08:00",
            "source_timezone": "Asia/Shanghai",
            "source_time_precision": "minute",
            "time_parse_status": "parsed",
            "source_published_at": "2026-11-06T00:00:00Z",
            "source_published_date": "2026-11-06",
            "first_seen_at": "2026-11-06T00:05:00Z",
            "fetched_at": "2026-11-06T00:05:02Z",
            "persisted_at": available_at,
            "available_at": available_at,
            "storage_policy": "metadata_only",
            "content_ref": f"raw/{sha}.txt",
            "content_sha256": sha,
            "normalized_text": title,
            "normalization_version": "text-normalize/0.1",
            "supersedes_raw_item_id": None,
            "is_synthetic": False,
        },
        "event": {
            "schema_version": "event-version/0.1",
            "event_id": ev_logical_id,
            "event_version_id": event_ver_id,
            "version": 1,
            "title": title,
            "fact_summary": title,
            "category": "macro",
            "markets": ["US", "GLOBAL"],
            "entities": [],
            "evidence_ids": [ev_id],
            "input_raw_item_ids": [raw_id],
            "extraction_method": "rule",
            "extractor_version": "metadata-extractor/0.1",
            "extraction_quality": "metadata_only",
            "processed_at": available_at,
            "available_at": available_at,
            "supersedes_event_version_id": None,
            "is_synthetic": False,
        },
        "evidence": {
            "schema_version": "evidence/0.1",
            "evidence_id": ev_id,
            "event_version_id": event_ver_id,
            "raw_item_id": raw_id,
            "relation": "reports",
            "claim_key": "fact_summary",
            "normalization_version": "text-normalize/0.1",
            "locator": {
                "field": "normalized_text",
                "offset_unit": "unicode_code_point",
                "start": 0,
                "end": len(title),
            },
            "quote": title,
            "validation_status": "exact_quote_match",
            "available_at": available_at,
            "is_synthetic": False,
        },
    }


def _ingest_with_receipt(db, bundle, workspace: Path, *, committed_at: str):
    raw, event, evidence = bundle["raw"], bundle["event"], bundle["evidence"]
    path = workspace / raw["content_ref"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(raw["normalized_text"], encoding="utf-8", newline="")
    with db:
        insert_immutable(db, "raw_items", "raw_item_id", raw)
        insert_immutable(db, "event_versions", "event_version_id", event)
        insert_immutable(db, "evidence", "evidence_id", evidence)
        db.execute(
            "INSERT INTO availability_receipts VALUES (?,?)",
            (event["event_version_id"], committed_at),
        )


def _update_backup_manifest_file_entry(backup_dir: Path, rel_path: str):
    manifest_path = backup_dir / "backup-manifest.json"
    bmanifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = (backup_dir / rel_path).read_bytes()
    bmanifest["files"][rel_path] = {"sha256": _sha256_bytes(data), "size": len(data)}
    manifest_path.write_text(_canonical(bmanifest), encoding="utf-8", newline="")


class Batch46OpsSessionRunnerQATests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self._junctions = []
        db = connect(self.workspace / "market.db")
        try:
            ingest_fixture(db, _demo_fixture(), self.workspace)
        finally:
            db.close()

    def tearDown(self):
        for jpath in reversed(self._junctions):
            if jpath.exists() or jpath.is_symlink():
                try:
                    os.rmdir(jpath)
                except OSError:
                    pass
        self._tmp.cleanup()

    def _make_junction(self, link_path: Path, target_path: Path):
        if sys.platform != "win32":
            self.skipTest("NTFS directory junction test requires Windows")
        res = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            self.skipTest(f"mklink /J unavailable: {res.stderr.strip()}")
        self._junctions.append(link_path)
        return link_path

    def _base_kwargs(self, **overrides):
        params = {
            "report_type": "pre_market",
            "market_session_date": "2026-11-06",
            "cutoff": "2026-11-06T00:30:00Z",
            "run_id": "qa_run_1",
            "report_id": "pre_20261106_qa1",
            "now_utc": "2026-11-06T00:30:05Z",
        }
        params.update(overrides)
        return params

    # ------------------------------------------------------------------
    # 1. Pre-flight validation & zero side effects on invalid inputs
    # ------------------------------------------------------------------
    def test_preflight_invalid_params_fail_with_zero_side_effects(self):
        before = _snapshot_tree(self.workspace)

        invalid_cases = [
            ("report_type_collect_all", {"report_type": "collect_all"}, ValueError),
            ("report_type_manual_recovery", {"report_type": "manual_recovery"}, ValueError),
            ("report_type_unknown", {"report_type": "midday"}, ValueError),
            ("report_type_none", {"report_type": None}, ValueError),
            ("date_non_leap_feb29", {"market_session_date": "2026-02-29"}, ContractError),
            ("date_month_13", {"market_session_date": "2026-13-01"}, ContractError),
            ("date_short_day", {"market_session_date": "2026-11-6"}, ContractError),
            ("date_fullwidth_digits", {"market_session_date": "２０２６-１１-０６"}, ContractError),
            ("tz_wrong_case", {"display_timezone": "Asia/shanghai"}, ContractError),
            ("tz_trailing_space", {"display_timezone": "UTC "}, ContractError),
            ("tz_leading_space", {"display_timezone": " Asia/Shanghai"}, ContractError),
            ("tz_america_wrong_case", {"display_timezone": "America/new_york"}, ContractError),
            ("tz_nonexistent", {"display_timezone": "Mars/Olympus"}, ContractError),
            ("ttl_bool_true", {"ttl_seconds": True}, ValueError),
            ("ttl_bool_false", {"ttl_seconds": False}, ValueError),
            ("ttl_too_small", {"ttl_seconds": 29}, ValueError),
            ("ttl_too_large", {"ttl_seconds": 86401}, ValueError),
            ("ttl_negative", {"ttl_seconds": -60}, ValueError),
            ("ttl_float", {"ttl_seconds": 900.0}, ValueError),
            ("ttl_str", {"ttl_seconds": "900"}, ValueError),
            ("cutoff_date_only", {"cutoff": "2026-11-06"}, ContractError),
            ("cutoff_offset_not_z", {"cutoff": "2026-11-06T00:30:00+08:00"}, ContractError),
            ("cutoff_garbage", {"cutoff": "not-a-timestamp"}, ContractError),
            ("cutoff_none", {"cutoff": None}, ContractError),
            ("scheduled_for_invalid", {"scheduled_for": "2026-11-06 00:30:00"}, ContractError),
            ("now_utc_invalid", {"now_utc": "2026-11-06T00:30:00+00:00"}, ContractError),
            ("default_synthetic_non_bool", {"default_synthetic": 1}, ValueError),
            ("retrospective_non_bool", {"retrospective_catchup": "true"}, ValueError),
            ("recover_expired_non_bool", {"recover_expired": 0}, ValueError),
            ("pid_bool", {"pid": True}, ValueError),
            ("pid_zero", {"pid": 0}, ValueError),
            ("pid_overflow", {"pid": 2_147_483_648}, ValueError),
            ("lock_id_traversal", {"lock_id": "../evil"}, ValueError),
            ("run_id_slash", {"run_id": "run/1"}, ValueError),
            ("report_id_dot", {"report_id": "pre.20261106"}, ValueError),
            ("supersedes_bad_chars", {"supersedes_report_id": "../v1"}, ValueError),
            (
                "supersedes_self_explicit",
                {"report_id": "pre_20261106_v1", "supersedes_report_id": "pre_20261106_v1"},
                ValueError,
            ),
            (
                "supersedes_self_auto_report_id",
                {"report_id": None, "run_id": "r1", "supersedes_report_id": "pre_20261106_r1"},
                ValueError,
            ),
        ]

        for label, overrides, exc_type in invalid_cases:
            with self.subTest(case=label):
                with self.assertRaises(exc_type):
                    run_guarded_session_brief(self.workspace, **self._base_kwargs(**overrides))

        self.assertEqual(_snapshot_tree(self.workspace), before)
        self.assertFalse((self.workspace / "ops").exists())
        self.assertFalse((self.workspace / "reports").exists())

    def test_preflight_missing_db_corrupt_journal_and_duplicate_run_id_zero_side_effects(self):
        # 1. Missing market.db (empty workspace + nonexistent workspace + dir placeholder).
        empty_ws = self.root / "empty_ws"
        empty_ws.mkdir()
        before_empty = _snapshot_tree(empty_ws)
        with self.assertRaisesRegex(ValueError, "workspace_database_missing"):
            run_guarded_session_brief(empty_ws, **self._base_kwargs())
        self.assertEqual(_snapshot_tree(empty_ws), before_empty)

        missing_ws = self.root / "does_not_exist"
        with self.assertRaisesRegex(ValueError, "workspace_database_missing"):
            run_guarded_session_brief(missing_ws, **self._base_kwargs())
        self.assertFalse(missing_ws.exists())

        dir_db_ws = self.root / "dir_db_ws"
        (dir_db_ws / "market.db").mkdir(parents=True)
        before_dir_db = _snapshot_tree(dir_db_ws)
        with self.assertRaisesRegex(ValueError, "workspace_database_missing"):
            run_guarded_session_brief(dir_db_ws, **self._base_kwargs())
        self.assertEqual(_snapshot_tree(dir_db_ws), before_dir_db)

        # 2. Corrupt ops/runs.jsonl (broken JSON, missing newline, directory placeholder).
        ops_dir = self.workspace / "ops"
        ops_dir.mkdir()
        journal_path = ops_dir / "runs.jsonl"
        for label, payload in [
            ("broken_json", b"{bad-json\n"),
            ("missing_trailing_newline", b'{"schema_version":"ops-run-record/0.1"}'),
            ("duplicate_json_key", b'{"run_id":"a","run_id":"b"}\n'),
        ]:
            with self.subTest(corrupt_journal=label):
                journal_path.write_bytes(payload)
                before_corrupt = _snapshot_tree(self.workspace)
                with self.assertRaisesRegex(ValueError, "ops_run_journal_corrupt"):
                    run_guarded_session_brief(self.workspace, **self._base_kwargs(run_id=f"qa_{label}"))
                self.assertEqual(_snapshot_tree(self.workspace), before_corrupt)
                self.assertFalse((ops_dir / "run.lock").exists())

        journal_path.unlink()
        journal_path.mkdir()
        before_jdir = _snapshot_tree(self.workspace)
        with self.assertRaisesRegex(ValueError, "ops_run_journal_corrupt"):
            run_guarded_session_brief(self.workspace, **self._base_kwargs(run_id="qa_jdir"))
        self.assertEqual(_snapshot_tree(self.workspace), before_jdir)
        journal_path.rmdir()

        # 3. Duplicate run_id already present in ops/runs.jsonl (both unlocked and with active lock).
        first = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(run_id="dup_run_1", report_id="pre_20261106_dup1"),
        )
        self.assertEqual(first["status"], "degraded")
        before_dup = _snapshot_tree(self.workspace)
        with self.assertRaisesRegex(ValueError, "ops_run_id_conflict"):
            run_guarded_session_brief(
                self.workspace,
                **self._base_kwargs(run_id="dup_run_1", report_id="pre_20261106_dup2"),
            )
        self.assertEqual(_snapshot_tree(self.workspace), before_dup)
        self.assertFalse((self.workspace / "ops" / "run.lock").exists())
        self.assertFalse((self.workspace / "reports" / "pre_20261106_dup2").exists())

        # Even if an active lock exists, pre-flight duplicate run_id must fail before lock check.
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="holder_for_dup",
            now_utc="2026-11-06T00:30:00Z",
            lock_id="holder_dup_lock",
        )
        before_dup_locked = _snapshot_tree(self.workspace)
        with self.assertRaisesRegex(ValueError, "ops_run_id_conflict"):
            run_guarded_session_brief(
                self.workspace,
                **self._base_kwargs(run_id="dup_run_1", report_id="pre_20261106_dup3"),
            )
        self.assertEqual(_snapshot_tree(self.workspace), before_dup_locked)
        release_run_lock(self.workspace, lock_id="holder_dup_lock")

    def test_preflight_unc_and_windows_ntfs_junctions_rejected_zero_side_effects(self):
        # 1. UNC paths.
        for unc in (r"\\server\share\ws", "//server/share/ws"):
            with self.subTest(unc=unc):
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    run_guarded_session_brief(unc, **self._base_kwargs())

        # 2. NTFS junction as workspace and as ancestor of workspace.
        before_real = _snapshot_tree(self.workspace)
        j_ws = self._make_junction(self.root / "j_ws", self.workspace)
        for candidate in (j_ws, j_ws / "sub_ws"):
            with self.subTest(junction_workspace=str(candidate)):
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    run_guarded_session_brief(candidate, **self._base_kwargs())
        self.assertEqual(_snapshot_tree(self.workspace), before_real)

        # 3. NTFS junction at <workspace>/market.db (reparse point rejected before is_file/lock).
        ws_jdb = self.root / "ws_jdb"
        ws_jdb.mkdir()
        target_dir = self.root / "db_target_dir"
        target_dir.mkdir()
        self._make_junction(ws_jdb / "market.db", target_dir)
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            run_guarded_session_brief(ws_jdb, **self._base_kwargs())
        self.assertFalse((ws_jdb / "ops").exists())
        self.assertFalse((ws_jdb / "reports").exists())

        # 4. NTFS junction at <workspace>/ops -> outside dir.
        ws_jops = self.root / "ws_jops"
        ws_jops.mkdir()
        db = connect(ws_jops / "market.db")
        try:
            ingest_fixture(db, _demo_fixture(), ws_jops)
        finally:
            db.close()
        outside_ops = self.root / "outside_ops"
        outside_ops.mkdir()
        self._make_junction(ws_jops / "ops", outside_ops)
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            run_guarded_session_brief(ws_jops, **self._base_kwargs())
        self.assertEqual(list(outside_ops.iterdir()), [])
        self.assertFalse((ws_jops / "reports").exists())

    # ------------------------------------------------------------------
    # 2. Concurrency & lock lifecycle
    # ------------------------------------------------------------------
    def test_concurrent_guarded_runs_zero_exceptions_zero_orphans_exact_journal_and_reports(self):
        fixture = _demo_fixture()
        rounds = 10
        workers = 6

        for round_idx in range(rounds):
            ws = self.root / f"conc_ws_{round_idx}"
            ws.mkdir()
            db = connect(ws / "market.db")
            try:
                ingest_fixture(db, fixture, ws)
            finally:
                db.close()

            barrier = threading.Barrier(workers)

            def _worker(tid):
                # Vary run_id lengths to catch both lost appends and torn/interleaved JSON lines.
                rid = f"r{round_idx}_t{tid}_" + ("k" * (tid * 9))
                rep = f"pre_20261106_r{round_idx}_t{tid}"
                barrier.wait()
                return run_guarded_session_brief(
                    ws,
                    report_type="pre_market",
                    market_session_date="2026-11-06",
                    cutoff="2026-11-06T00:30:00Z",
                    run_id=rid,
                    report_id=rep,
                    now_utc="2026-11-06T00:30:05Z",
                )

            results = []
            exceptions = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [(tid, pool.submit(_worker, tid)) for tid in range(workers)]
                for tid, fut in futs:
                    try:
                        results.append((tid, fut.result()))
                    except Exception as exc:
                        exceptions.append((tid, type(exc).__name__, str(exc)))

            self.assertEqual(exceptions, [], f"round {round_idx} unhandled exceptions: {exceptions}")
            self.assertEqual(len(results), workers)

            # Lock and temporary files must be completely cleaned up.
            ops_dir = ws / "ops"
            self.assertEqual(inspect_run_lock(ws, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")
            leftover = [
                p.name
                for p in ops_dir.iterdir()
                if p.name == "run.lock"
                or p.name == ".stale-recovery.lock"
                or p.name.startswith(".lock-staging-")
            ]
            self.assertEqual(leftover, [], f"round {round_idx} leftover lock artifacts: {leftover}")

            # Journal must be completely intact with exact 1-to-1 entries for every thread.
            status = read_ops_status(ws, now_utc="2026-11-06T00:31:00Z")
            self.assertEqual(
                status["total_runs"],
                workers,
                f"round {round_idx} lost/extra journal entries: expected {workers}, got {status['total_runs']}",
            )
            journal_entries = {
                json.loads(line)["run_id"]: json.loads(line)
                for line in (ops_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            }
            self.assertEqual(len(journal_entries), workers)

            degraded_count = 0
            ro_db = connect(ws / "market.db")
            try:
                for tid, res in results:
                    rid = res["run_id"]
                    self.assertIn(rid, journal_entries, f"round {round_idx} missing run_id {rid} in runs.jsonl")
                    self.assertIn(res["status"], {"degraded", "skipped_locked"})
                    if res["status"] == "degraded":
                        degraded_count += 1
                        self.assertTrue(res["verified"])
                        self.assertTrue(res["lock_released"])
                        self.assertEqual(journal_entries[rid]["outcome"], "degraded")
                        self.assertEqual(journal_entries[rid]["report_id"], res["report_id"])
                        ver = verify_session_brief(ro_db, ws, res["report_id"])
                        self.assertEqual(ver["status"], "verified")
                    else:
                        self.assertIsNone(res["report_id"])
                        self.assertFalse(res["lock_released"])
                        self.assertEqual(journal_entries[rid]["outcome"], "skipped_locked")
                        self.assertIsNone(journal_entries[rid]["report_id"])
                        expected_rep_dir = ws / "reports" / f"pre_20261106_r{round_idx}_t{tid}"
                        self.assertFalse(expected_rep_dir.exists())
            finally:
                ro_db.close()
            self.assertGreaterEqual(degraded_count, 1)

    def test_concurrent_skipped_locked_burst_preserves_every_journal_record_without_corruption(self):
        """High-contention skipped_locked burst must never lose writes or corrupt ops/runs.jsonl."""
        fixture = _demo_fixture()
        rounds = 10
        workers = 12

        for round_idx in range(rounds):
            ws = self.root / f"burst_ws_{round_idx}"
            ws.mkdir()
            db = connect(ws / "market.db")
            try:
                ingest_fixture(db, fixture, ws)
            finally:
                db.close()

            acquire_run_lock(
                ws,
                job_name="pre_market",
                run_id=f"holder_{round_idx}",
                ttl_seconds=600,
                now_utc="2026-11-06T00:30:00Z",
                lock_id=f"holder_lock_{round_idx}",
            )
            barrier = threading.Barrier(workers)

            def _contender(tid):
                rid = f"burst_r{round_idx}_t{tid}_" + ("z" * (tid * 8))
                barrier.wait()
                return run_guarded_session_brief(
                    ws,
                    report_type="pre_market",
                    market_session_date="2026-11-06",
                    cutoff="2026-11-06T00:30:00Z",
                    run_id=rid,
                    report_id=f"pre_20261106_burst_{round_idx}_{tid}",
                    now_utc="2026-11-06T00:30:05Z",
                )

            results = []
            exceptions = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [(tid, pool.submit(_contender, tid)) for tid in range(workers)]
                for tid, fut in futs:
                    try:
                        results.append((tid, fut.result()))
                    except Exception as exc:
                        exceptions.append((tid, type(exc).__name__, str(exc)))

            release_run_lock(ws, lock_id=f"holder_lock_{round_idx}")
            self.assertEqual(exceptions, [], f"round {round_idx} unhandled exceptions: {exceptions}")
            self.assertEqual(len(results), workers)
            for tid, res in results:
                self.assertEqual(res["status"], "skipped_locked")
                self.assertTrue(res["recorded_run"])
                self.assertIsNone(res["report_id"])
                self.assertFalse((ws / "reports" / f"pre_20261106_burst_{round_idx}_{tid}").exists())

            status = read_ops_status(ws, now_utc="2026-11-06T00:31:00Z")
            self.assertEqual(
                status["total_runs"],
                workers,
                f"round {round_idx} lost/extra records in runs.jsonl: expected {workers}, got {status['total_runs']}",
            )
            self.assertEqual(status["counts_by_outcome"]["skipped_locked"], workers)

    def test_guarded_run_release_lock_survives_transient_windows_sharing_violation(self):
        """Transient WinError 32 PermissionError during release_run_lock must not leak ops/run.lock."""
        lock_path = (self.workspace / "ops" / "run.lock").resolve()
        orig_unlink = Path.unlink
        injected = {"done": False}

        def flaky_unlink(path_obj, missing_ok=False):
            if not injected["done"] and path_obj.resolve() == lock_path:
                injected["done"] = True
                raise PermissionError(13, "WinError 32 sharing violation", str(path_obj))
            return orig_unlink(path_obj, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=flaky_unlink):
            res = run_guarded_session_brief(
                self.workspace,
                **self._base_kwargs(run_id="run_win32_release", report_id="pre_20261106_win32"),
            )

        self.assertTrue(injected["done"])
        self.assertEqual(res["status"], "degraded")
        self.assertTrue(res["lock_released"])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")
        self.assertFalse(lock_path.exists())

    def test_no_recover_expired_preserves_lock_returns_exit_2_and_records_skipped_locked(self):
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="crashed_old_run",
            ttl_seconds=300,
            now_utc="2026-11-06T00:20:00Z",
            lock_id="expired_lock_preserve",
        )
        lock_file = self.workspace / "ops" / "run.lock"
        lock_before_bytes = lock_file.read_bytes()
        lock_before_mtime = lock_file.lstat().st_mtime_ns

        code, out, err = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "run_no_recover_1",
            "--report-id", "pre_20261106_no_recover",
            "--now", "2026-11-06T00:30:00Z",
            "--no-recover-expired",
        )
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "skipped_locked")
        self.assertEqual(payload["lock_status"], "expired_lock_present")
        self.assertEqual(payload["reason_code"], "stale_lock_recovery_disabled")
        self.assertEqual(payload["blocking_lock"]["lock_id"], "expired_lock_preserve")
        self.assertIsNone(payload["report_id"])
        self.assertTrue(payload["recorded_run"])
        self.assertFalse(payload["lock_released"])
        self.assertFalse((self.workspace / "reports" / "pre_20261106_no_recover").exists())

        # Expired lock must remain completely untouched.
        self.assertEqual(lock_file.read_bytes(), lock_before_bytes)
        self.assertEqual(lock_file.lstat().st_mtime_ns, lock_before_mtime)
        self.assertFalse((self.workspace / "ops" / "stale-locks").exists())

        status = read_ops_status(self.workspace, now_utc="2026-11-06T00:30:00Z")
        self.assertEqual(status["counts_by_outcome"]["skipped_locked"], 1)
        self.assertEqual(status["lock"]["state"], "expired")

    def test_corrupt_lock_variants_return_exit_1_and_never_touch_lock_or_journal(self):
        # Seed one valid run so we prove existing journal is untouched as well.
        seed = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(run_id="seed_ok_1", report_id="pre_20261106_seed1"),
        )
        self.assertEqual(seed["status"], "degraded")

        ops_dir = self.workspace / "ops"
        journal_file = ops_dir / "runs.jsonl"
        journal_before_bytes = journal_file.read_bytes()
        journal_before_mtime = journal_file.lstat().st_mtime_ns
        lock_path = ops_dir / "run.lock"

        foreign_lock = {
            "schema_version": "ops-lock/0.1",
            "lock_id": "foreign_lock_1",
            "job_name": "pre_market",
            "run_id": "foreign_run_1",
            "workspace_sha256": "0" * 64,
            "pid": 1234,
            "acquired_at": "2026-11-06T00:25:00Z",
            "expires_at": "2026-11-06T00:40:00Z",
            "ttl_seconds": 900,
            "status": "active",
            "recovered_stale_lock_id": None,
        }

        cases = [
            ("broken_json", b"{not-json"),
            ("duplicate_keys", b'{"lock_id":"a","lock_id":"b"}\n'),
            ("foreign_workspace_hash", (_canonical(foreign_lock) + "\n").encode("utf-8")),
        ]
        for label, raw_bytes in cases:
            with self.subTest(corrupt_lock=label):
                lock_path.write_bytes(raw_bytes)
                lock_mtime = lock_path.lstat().st_mtime_ns
                code, out, err = _run_cli(
                    "ops-run-session-brief",
                    "--workspace", str(self.workspace),
                    "--report-type", "pre_market",
                    "--session-date", "2026-11-06",
                    "--cutoff", "2026-11-06T00:30:00Z",
                    "--run-id", f"run_corrupt_{label}",
                    "--report-id", f"pre_corrupt_{label}",
                    "--now", "2026-11-06T00:31:00Z",
                )
                self.assertEqual(code, 1)
                self.assertEqual(err, "")
                payload = json.loads(out)
                self.assertEqual(payload["status"], "blocked_corrupt_lock")
                self.assertFalse(payload["recorded_run"])
                self.assertIsNone(payload["run_record"])
                self.assertEqual(lock_path.read_bytes(), raw_bytes)
                self.assertEqual(lock_path.lstat().st_mtime_ns, lock_mtime)
                self.assertEqual(journal_file.read_bytes(), journal_before_bytes)
                self.assertEqual(journal_file.lstat().st_mtime_ns, journal_before_mtime)
                self.assertFalse((self.workspace / "reports" / f"pre_corrupt_{label}").exists())
                lock_path.unlink()

        # Directory placeholder at ops/run.lock must also fail closed without mutating anything.
        lock_path.mkdir()
        code, out, err = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "run_corrupt_dir",
            "--now", "2026-11-06T00:31:00Z",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["status"], "blocked_corrupt_lock")
        self.assertTrue(lock_path.is_dir())
        self.assertEqual(journal_file.read_bytes(), journal_before_bytes)
        lock_path.rmdir()

    # ------------------------------------------------------------------
    # 3. Runtime failure, supplement chain, & is_synthetic alignment
    # ------------------------------------------------------------------
    def test_conflicting_report_id_fails_runtime_preserves_existing_cleans_staging_and_releases_lock(self):
        first = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(run_id="orig_run_1", report_id="pre_20261106_conflict"),
        )
        self.assertEqual(first["status"], "degraded")
        rep_dir = self.workspace / "reports" / "pre_20261106_conflict"
        orig_bytes = {name: (rep_dir / name).read_bytes() for name in ("brief.html", "brief.md", "manifest.json")}

        code, out, err = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:01:00Z",
            "--run-id", "conflict_run_2",
            "--report-id", "pre_20261106_conflict",
            "--now", "2026-11-06T00:35:00Z",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "failed_runtime")
        self.assertEqual(payload["reason"], "published_report_conflict")
        self.assertIsNone(payload["report_id"])
        self.assertTrue(payload["recorded_run"])
        self.assertTrue(payload["lock_released"])
        self.assertEqual(payload["run_record"]["outcome"], "failed_runtime")
        self.assertIsNone(payload["run_record"]["report_id"])

        # Existing report bytes untouched; zero .staging-* left; lock released.
        for name, expected_bytes in orig_bytes.items():
            self.assertEqual((rep_dir / name).read_bytes(), expected_bytes)
        staging_left = [p.name for p in (self.workspace / "reports").iterdir() if p.name.startswith(".staging-")]
        self.assertEqual(staging_left, [])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:36:00Z")["state"], "unlocked")

    def test_future_cutoff_fails_runtime_and_releases_lock_including_after_stale_recovery(self):
        # Seed an expired lock so we also verify stale_lock_recovered + failed_runtime reason alignment.
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="crashed_before_future",
            ttl_seconds=300,
            now_utc="2026-11-06T00:10:00Z",
            lock_id="stale_before_future",
        )
        code, out, err = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2099-01-01T00:00:00Z",
            "--run-id", "run_future_cutoff",
            "--report-id", "pre_20261106_future",
            "--now", "2026-11-06T00:30:05Z",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "failed_runtime")
        self.assertIn("generated_before_cutoff", payload["reason"])
        self.assertIsNone(payload["report_id"])
        self.assertTrue(payload["stale_lock_recovered"])
        self.assertEqual(payload["recovered_stale_lock_id"], "stale_before_future")
        self.assertIn("stale_lock_recovered", payload["run_record"]["reason_codes"])
        self.assertIn("runtime_error", payload["run_record"]["reason_codes"])
        self.assertTrue(payload["recorded_run"])
        self.assertTrue(payload["lock_released"])
        self.assertFalse((self.workspace / "reports" / "pre_20261106_future").exists())
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")

    def test_supplement_chain_publishes_verifies_preserves_v1_and_rejects_scope_mismatch(self):
        v1 = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(run_id="sup_run_1", report_id="pre_20261106_v1"),
        )
        self.assertEqual(v1["status"], "degraded")
        v1_dir = self.workspace / "reports" / "pre_20261106_v1"
        v1_bytes = {name: (v1_dir / name).read_bytes() for name in ("brief.html", "brief.md", "manifest.json")}

        code, out, err = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "sup_run_2",
            "--report-id", "pre_20261106_v2",
            "--supersedes", "pre_20261106_v1",
            "--now", "2026-11-06T00:35:00Z",
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        v2 = json.loads(out)
        self.assertEqual(v2["status"], "degraded")
        self.assertTrue(v2["verified"])
        self.assertTrue(v2["lock_released"])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:36:00Z")["state"], "unlocked")

        # v1 bytes completely preserved; both v1 and v2 verify read-only.
        for name, expected in v1_bytes.items():
            self.assertEqual((v1_dir / name).read_bytes(), expected)
        v2_manifest = json.loads((self.workspace / "reports" / "pre_20261106_v2" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(v2_manifest["supersedes_report_id"], "pre_20261106_v1")
        self.assertIn("supplement_revision", v2_manifest["reason_codes"])

        ro_db = connect(self.workspace / "market.db")
        try:
            self.assertEqual(verify_session_brief(ro_db, self.workspace, "pre_20261106_v1")["status"], "verified")
            self.assertEqual(verify_session_brief(ro_db, self.workspace, "pre_20261106_v2")["status"], "verified")
        finally:
            ro_db.close()

        # Cross-type supplement (post_market superseding pre_market) must fail as failed_runtime and release lock.
        bad_sup = run_guarded_session_brief(
            self.workspace,
            report_type="post_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T08:30:00Z",
            run_id="sup_run_bad_scope",
            report_id="post_20261106_bad_sup",
            supersedes_report_id="pre_20261106_v1",
            now_utc="2026-11-06T08:31:00Z",
        )
        self.assertEqual(bad_sup["status"], "failed_runtime")
        self.assertEqual(bad_sup["reason"], "supplement_scope_mismatch")
        self.assertTrue(bad_sup["lock_released"])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T08:32:00Z")["state"], "unlocked")

    def test_non_synthetic_mixed_and_empty_cutoff_is_synthetic_alignment(self):
        # 1. Pure non-synthetic (metadata-only) workspace.
        non_syn_ws = self.root / "non_syn_ws"
        non_syn_ws.mkdir()
        db = connect(non_syn_ws / "market.db")
        try:
            _ingest_with_receipt(db, _make_metadata_only_bundle(), non_syn_ws, committed_at="2026-11-06T00:11:00Z")
        finally:
            db.close()

        res_non_syn = run_guarded_session_brief(
            non_syn_ws,
            report_type="pre_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T00:30:00Z",
            run_id="run_non_syn",
            report_id="pre_20261106_non_syn",
            now_utc="2026-11-06T00:30:05Z",
        )
        self.assertEqual(res_non_syn["status"], "degraded")
        self.assertFalse(res_non_syn["is_synthetic"])
        self.assertFalse(res_non_syn["run_record"]["is_synthetic"])
        self.assertNotIn("synthetic_fixture", res_non_syn["run_record"]["reason_codes"])

        # 2. Mixed workspace (synthetic demo + non-synthetic metadata-only).
        mixed_ws = self.root / "mixed_ws"
        mixed_ws.mkdir()
        db = connect(mixed_ws / "market.db")
        try:
            ingest_fixture(db, _demo_fixture(), mixed_ws)
            _ingest_with_receipt(db, _make_metadata_only_bundle(), mixed_ws, committed_at="2026-11-06T00:11:00Z")
        finally:
            db.close()

        res_mixed = run_guarded_session_brief(
            mixed_ws,
            report_type="pre_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T00:30:00Z",
            run_id="run_mixed",
            report_id="pre_20261106_mixed",
            now_utc="2026-11-06T00:30:05Z",
        )
        self.assertEqual(res_mixed["status"], "degraded")
        self.assertFalse(res_mixed["is_synthetic"])
        self.assertFalse(res_mixed["run_record"]["is_synthetic"])
        self.assertNotIn("synthetic_fixture", res_mixed["run_record"]["reason_codes"])
        mixed_manifest = json.loads((mixed_ws / "reports" / "pre_20261106_mixed" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("mixed_test_data", mixed_manifest["reason_codes"])

        # 3. Empty cutoff (before any event available): without vs with --synthetic-empty.
        code_no_flag, out_no_flag, err_no_flag = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-05T00:00:00Z",
            "--run-id", "run_empty_real",
            "--report-id", "pre_20261106_empty_real",
            "--now", "2026-11-06T00:30:05Z",
        )
        self.assertEqual(code_no_flag, 0)
        self.assertEqual(err_no_flag, "")
        p_real = json.loads(out_no_flag)
        self.assertFalse(p_real["is_synthetic"])
        self.assertFalse(p_real["run_record"]["is_synthetic"])
        self.assertNotIn("synthetic_fixture", p_real["run_record"]["reason_codes"])

        code_flag, out_flag, err_flag = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-05T00:00:00Z",
            "--run-id", "run_empty_syn",
            "--report-id", "pre_20261106_empty_syn",
            "--now", "2026-11-06T00:31:05Z",
            "--synthetic-empty",
        )
        self.assertEqual(code_flag, 0)
        self.assertEqual(err_flag, "")
        p_syn = json.loads(out_flag)
        self.assertTrue(p_syn["is_synthetic"])
        self.assertTrue(p_syn["run_record"]["is_synthetic"])
        self.assertIn("synthetic_fixture", p_syn["run_record"]["reason_codes"])

    # ------------------------------------------------------------------
    # 4. ops/backup.py dual-template session-brief-manifest/0.1 integration
    # ------------------------------------------------------------------
    def _setup_mixed_legacy_and_chain_workspace(self):
        db = connect(self.workspace / "market.db")
        try:
            render_legacy_report(db, self.workspace, "2026-11-06T00:30:00Z", "legacy_v1")
        finally:
            db.close()
        r1 = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(run_id="bk_run_1", report_id="pre_20261106_v1"),
        )
        self.assertEqual(r1["status"], "degraded")
        r2 = run_guarded_session_brief(
            self.workspace,
            **self._base_kwargs(
                run_id="bk_run_2",
                report_id="pre_20261106_v2",
                supersedes_report_id="pre_20261106_v1",
                now_utc="2026-11-06T00:35:00Z",
            ),
        )
        self.assertEqual(r2["status"], "degraded")

    def test_backup_verify_restore_mixed_legacy_and_session_brief_supplement_chain(self):
        self._setup_mixed_legacy_and_chain_workspace()

        backup_dir = self.root / "backup_mixed"
        restored_dir = self.root / "restored_mixed"

        bk_res = create_backup(self.workspace, backup_dir)
        self.assertEqual(bk_res["status"], "backed_up")
        self.assertEqual(bk_res["reports"], 3)

        ver_res = verify_backup(backup_dir)
        self.assertEqual(ver_res["status"], "verified")
        self.assertEqual(ver_res["reports"], 3)

        rest_res = restore_backup(backup_dir, restored_dir)
        self.assertEqual(rest_res["status"], "restored")
        self.assertEqual(rest_res["reports"], 3)

        for rep_id in ("pre_20261106_v1", "pre_20261106_v2"):
            for fname in ("brief.html", "brief.md", "manifest.json"):
                self.assertEqual(
                    (restored_dir / "reports" / rep_id / fname).read_bytes(),
                    (self.workspace / "reports" / rep_id / fname).read_bytes(),
                )
        for fname in ("brief.html", "manifest.json"):
            self.assertEqual(
                (restored_dir / "reports" / "legacy_v1" / fname).read_bytes(),
                (self.workspace / "reports" / "legacy_v1" / fname).read_bytes(),
            )

        ro_db = connect(restored_dir / "market.db")
        try:
            self.assertEqual(verify_report(ro_db, restored_dir, "legacy_v1")["status"], "verified")
            self.assertEqual(verify_session_brief(ro_db, restored_dir, "pre_20261106_v1")["status"], "verified")
            self.assertEqual(verify_session_brief(ro_db, restored_dir, "pre_20261106_v2")["status"], "verified")
        finally:
            ro_db.close()

    def test_backup_catches_1byte_tamper_of_brief_md_in_source_and_backup(self):
        self._setup_mixed_legacy_and_chain_workspace()

        # Backup cleanly first.
        backup_dir = self.root / "backup_md_tamper"
        create_backup(self.workspace, backup_dir)

        md_rel = "reports/pre_20261106_v2/brief.md"
        md_path = backup_dir / md_rel
        orig_md = md_path.read_bytes()
        tampered_md = orig_md[:-1] + (b"X" if orig_md[-1:] != b"X" else b"Y")

        # 1. Raw 1-byte tamper in backup -> caught by backup-manifest hash mismatch.
        md_path.write_bytes(tampered_md)
        with self.assertRaisesRegex(ValueError, "backup_file_hash_mismatch"):
            verify_backup(backup_dir)

        # 2. Tamper brief.md AND update backup-manifest.json hash -> caught by report manifest hash check.
        _update_backup_manifest_file_entry(backup_dir, md_rel)
        with self.assertRaisesRegex(ValueError, "backup_report_artifact_corrupt"):
            verify_backup(backup_dir)

        # 3. Tamper brief.md AND update BOTH report manifest.json AND backup-manifest.json -> caught by verify_session_brief!
        rep_manifest_rel = "reports/pre_20261106_v2/manifest.json"
        rep_manifest_path = backup_dir / rep_manifest_rel
        rep_manifest = json.loads(rep_manifest_path.read_text(encoding="utf-8"))
        rep_manifest["artifact_sha256"]["brief.md"] = _sha256_bytes(tampered_md)
        rep_manifest_path.write_text(_canonical(rep_manifest), encoding="utf-8", newline="")
        _update_backup_manifest_file_entry(backup_dir, rep_manifest_rel)
        with self.assertRaisesRegex(ValueError, "published_artifact_manifest_mismatch"):
            verify_backup(backup_dir)

        # 4. 1-byte tamper of brief.md in SOURCE workspace before create_backup -> rejected, destination not created.
        src_md = self.workspace / md_rel
        src_md.write_bytes(tampered_md)
        bad_dest = self.root / "backup_from_tampered_source"
        with self.assertRaisesRegex(ValueError, "backup_report_artifact_corrupt"):
            create_backup(self.workspace, bad_dest)
        self.assertFalse(bad_dest.exists())

    def test_backup_catches_semantic_tamper_of_session_brief_manifest_even_with_updated_hashes(self):
        self._setup_mixed_legacy_and_chain_workspace()

        def _fresh_backup(name):
            dest = self.root / name
            create_backup(self.workspace, dest)
            return dest

        rep_rel = "reports/pre_20261106_v2/manifest.json"

        # Case 1: generated_at set before information_cutoff.
        b1 = _fresh_backup("bk_sem_1")
        m1 = json.loads((b1 / rep_rel).read_text(encoding="utf-8"))
        m1["generated_at"] = "2026-11-06T00:29:59Z"
        (b1 / rep_rel).write_text(_canonical(m1), encoding="utf-8", newline="")
        _update_backup_manifest_file_entry(b1, rep_rel)
        with self.assertRaisesRegex(ValueError, "generated_before_cutoff"):
            verify_backup(b1)

        # Case 2: display_timezone mutated (artifacts no longer match deterministic re-render).
        b2 = _fresh_backup("bk_sem_2")
        m2 = json.loads((b2 / rep_rel).read_text(encoding="utf-8"))
        m2["display_timezone"] = "UTC"
        (b2 / rep_rel).write_text(_canonical(m2), encoding="utf-8", newline="")
        _update_backup_manifest_file_entry(b2, rep_rel)
        with self.assertRaisesRegex(ValueError, "published_artifact_manifest_mismatch"):
            verify_backup(b2)

        # Case 3: citation_check mutated from "passed" to "failed".
        b3 = _fresh_backup("bk_sem_3")
        m3 = json.loads((b3 / rep_rel).read_text(encoding="utf-8"))
        m3["citation_check"] = "failed"
        (b3 / rep_rel).write_text(_canonical(m3), encoding="utf-8", newline="")
        _update_backup_manifest_file_entry(b3, rep_rel)
        with self.assertRaisesRegex(ValueError, "invalid_enum"):
            verify_backup(b3)

        # Case 4: duplicate JSON key smuggled into manifest.json.
        b4 = _fresh_backup("bk_sem_4")
        raw_m4 = (b4 / rep_rel).read_text(encoding="utf-8")
        self.assertTrue(raw_m4.endswith("}"))
        dup_m4 = raw_m4[:-1] + ',"status":"degraded"}'
        (b4 / rep_rel).write_text(dup_m4, encoding="utf-8", newline="")
        _update_backup_manifest_file_entry(b4, rep_rel)
        with self.assertRaisesRegex(ValueError, "(?:duplicate_json_key|invalid_report_manifest)"):
            verify_backup(b4)

        # Case 5: Drop superseded v1 from backup AND backup-manifest.json while leaving v2 intact.
        b5 = _fresh_backup("bk_sem_5")
        bm5_path = b5 / "backup-manifest.json"
        bm5 = json.loads(bm5_path.read_text(encoding="utf-8"))
        bm5["report_ids"] = [rid for rid in bm5["report_ids"] if rid != "pre_20261106_v1"]
        for fname in ("manifest.json", "brief.html", "brief.md"):
            rel = f"reports/pre_20261106_v1/{fname}"
            (b5 / rel).unlink()
            bm5["files"].pop(rel, None)
        (b5 / "reports" / "pre_20261106_v1").rmdir()
        bm5_path.write_text(_canonical(bm5), encoding="utf-8", newline="")
        with self.assertRaisesRegex(ValueError, "report_file_missing"):
            verify_backup(b5)

    def test_backup_rejects_missing_brief_md_in_source_and_backup(self):
        self._setup_mixed_legacy_and_chain_workspace()

        # 1. Missing brief.md inside backup (both intact manifest and manifest with brief.md omitted).
        backup_dir = self.root / "backup_missing_md"
        create_backup(self.workspace, backup_dir)
        md_rel = "reports/pre_20261106_v1/brief.md"
        (backup_dir / md_rel).unlink()
        with self.assertRaisesRegex(ValueError, "backup_file_missing"):
            verify_backup(backup_dir)

        bm_path = backup_dir / "backup-manifest.json"
        bm = json.loads(bm_path.read_text(encoding="utf-8"))
        bm["files"].pop(md_rel, None)
        bm_path.write_text(_canonical(bm), encoding="utf-8", newline="")
        with self.assertRaisesRegex(ValueError, "backup_file_missing"):
            verify_backup(backup_dir)

        # 2. Missing brief.md in source workspace fails create_backup and never creates destination.
        (self.workspace / md_rel).unlink()
        dest = self.root / "backup_source_missing_md"
        with self.assertRaisesRegex(ValueError, "backup_file_missing"):
            create_backup(self.workspace, dest)
        self.assertFalse(dest.exists())

    # ------------------------------------------------------------------
    # 5. End-to-end CLI exit codes & ops-plan-recovery transitions
    # ------------------------------------------------------------------
    def test_cli_exit_codes_and_ops_plan_recovery_transitions_with_anti_lookahead(self):
        # 0. Invalid args via CLI -> exit code 1, JSON on stderr, empty stdout.
        c_bad, o_bad, e_bad = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-02-29",
            "--cutoff", "2026-11-06T00:30:00Z",
        )
        self.assertEqual(c_bad, 1)
        self.assertEqual(o_bad, "")
        self.assertEqual(json.loads(e_bad)["status"], "failed")

        # 1. Initial planner state at 01:00Z: pre_market (00:30Z) is offline_or_missed; post_market (08:30Z) not yet due.
        c_p0, o_p0, e_p0 = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--session-dates", "2026-11-06",
            "--now", "2026-11-06T01:00:00Z",
        )
        self.assertEqual(c_p0, 0)
        self.assertEqual(e_p0, "")
        p0 = json.loads(o_p0)
        self.assertEqual(p0["scheduled_slots_checked"], 1)
        self.assertEqual(p0["completed_slots"], 0)
        self.assertEqual(p0["missed_slots"], 1)
        self.assertEqual(p0["pending_recovery_actions"][0]["job_name"], "pre_market")
        self.assertEqual(p0["pending_recovery_actions"][0]["miss_reason"], "offline_or_missed")
        self.assertIsNone(p0["pending_recovery_actions"][0]["last_failed_run_id"])

        # 2. Active lock -> guarded run returns exit 2 (skipped_locked) -> planner sees previous_lock_conflict.
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="active_holder",
            ttl_seconds=600,
            now_utc="2026-11-06T00:30:00Z",
            lock_id="active_holder_lock",
        )
        c_lock, o_lock, e_lock = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "tr_lock_1",
            "--now", "2026-11-06T00:31:00Z",
        )
        self.assertEqual(c_lock, 2)
        self.assertEqual(e_lock, "")
        self.assertEqual(json.loads(o_lock)["status"], "skipped_locked")
        release_run_lock(self.workspace, lock_id="active_holder_lock")

        p1 = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-06"], now_utc="2026-11-06T01:00:00Z")
        self.assertEqual(p1["pending_recovery_actions"][0]["miss_reason"], "previous_lock_conflict")
        self.assertEqual(p1["pending_recovery_actions"][0]["last_failed_run_id"], "tr_lock_1")

        # 3. Runtime failure (future cutoff) -> CLI exit 1 (failed_runtime) -> planner sees previous_runtime_failure.
        c_fail, o_fail, e_fail = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2099-01-01T00:00:00Z",
            "--run-id", "tr_fail_2",
            "--now", "2026-11-06T00:35:00Z",
        )
        self.assertEqual(c_fail, 1)
        self.assertEqual(e_fail, "")
        self.assertEqual(json.loads(o_fail)["status"], "failed_runtime")

        p2 = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-06"], now_utc="2026-11-06T01:00:00Z")
        self.assertEqual(p2["pending_recovery_actions"][0]["miss_reason"], "previous_runtime_failure")
        self.assertEqual(p2["pending_recovery_actions"][0]["last_failed_run_id"], "tr_fail_2")

        # Anti-lookahead: 1 microsecond before tr_fail_2 must still see tr_lock_1!
        p2_before = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-06"], now_utc="2026-11-06T00:34:59.999999Z")
        self.assertEqual(p2_before["pending_recovery_actions"][0]["miss_reason"], "previous_lock_conflict")
        self.assertEqual(p2_before["pending_recovery_actions"][0]["last_failed_run_id"], "tr_lock_1")

        # 4. Guarded success -> CLI exit 0 (degraded) -> planner transitions to completed_slots=1, missed_slots=0.
        c_ok, o_ok, e_ok = _run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "tr_ok_3",
            "--report-id", "pre_20261106_tr3",
            "--now", "2026-11-06T00:40:00Z",
        )
        self.assertEqual(c_ok, 0)
        self.assertEqual(e_ok, "")
        self.assertEqual(json.loads(o_ok)["status"], "degraded")

        c_p3, o_p3, e_p3 = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--session-dates", "2026-11-06",
            "--now", "2026-11-06T01:00:00Z",
        )
        self.assertEqual(c_p3, 0)
        self.assertEqual(e_p3, "")
        p3 = json.loads(o_p3)
        self.assertEqual(p3["scheduled_slots_checked"], 1)
        self.assertEqual(p3["completed_slots"], 1)
        self.assertEqual(p3["missed_slots"], 0)
        self.assertEqual(p3["pending_recovery_actions"], [])
        self.assertIn("all_due_slots_completed", p3["reason_codes"])

        # Anti-lookahead: 1 microsecond before tr_ok_3 must still see previous_runtime_failure!
        p3_before = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-06"], now_utc="2026-11-06T00:39:59.999999Z")
        self.assertEqual(p3_before["completed_slots"], 0)
        self.assertEqual(p3_before["missed_slots"], 1)
        self.assertEqual(p3_before["pending_recovery_actions"][0]["miss_reason"], "previous_runtime_failure")

        # At 08:30:00Z post_market becomes due (offline_or_missed) while pre_market stays completed.
        p4 = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-06"], now_utc="2026-11-06T08:30:00Z")
        self.assertEqual(p4["scheduled_slots_checked"], 2)
        self.assertEqual(p4["completed_slots"], 1)
        self.assertEqual(p4["missed_slots"], 1)
        self.assertEqual(p4["pending_recovery_actions"][0]["job_name"], "post_market")
        self.assertEqual(p4["pending_recovery_actions"][0]["miss_reason"], "offline_or_missed")


if __name__ == "__main__":
    unittest.main()
