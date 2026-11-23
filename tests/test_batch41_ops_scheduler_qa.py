from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import copy
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
import xml.etree.ElementTree as ET

from market_intel.cli import main as cli_main
from market_intel.contracts import ContractError
from market_intel.contracts.ops_schedule import (
    validate_hhmm,
    validate_ops_lock,
    validate_ops_recovery_plan,
    validate_ops_run_record,
    validate_timezone_strict,
)
import market_intel.ops.scheduler as sched
from market_intel.ops.scheduler import (
    acquire_run_lock,
    inspect_run_lock,
    plan_missed_runs,
    read_ops_status,
    record_ops_run,
    release_run_lock,
    render_windows_task_template,
)


def _run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _sample_run(
    *,
    run_id="qa_run_001",
    job_name="pre_market",
    market_session_date="2026-11-23",
    scheduled_for="2026-11-23T00:30:00Z",
    started_at="2026-11-23T00:30:05Z",
    finished_at="2026-11-23T00:31:00Z",
    outcome="degraded",
    reason_codes=None,
    report_id="pre_20261123_v1",
    lock_id="lock_qa_001",
    stale_lock_recovered=False,
    is_synthetic=True,
):
    if reason_codes is None:
        reason_codes = ["degraded_no_model", "synthetic_fixture"]
    return {
        "schema_version": "ops-run-record/0.1",
        "run_id": run_id,
        "job_name": job_name,
        "market_session_date": market_session_date,
        "scheduled_for": scheduled_for,
        "started_at": started_at,
        "finished_at": finished_at,
        "outcome": outcome,
        "reason_codes": list(reason_codes),
        "report_id": report_id,
        "lock_id": lock_id,
        "stale_lock_recovered": stale_lock_recovered,
        "is_synthetic": is_synthetic,
    }


def _snapshot_tree(root):
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


class Batch41OpsSchedulerQATests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self._junctions = []

    def tearDown(self):
        for jpath in reversed(self._junctions):
            if jpath.exists() or jpath.is_symlink():
                try:
                    os.rmdir(jpath)
                except OSError:
                    pass
        self._tmp.cleanup()

    def _make_junction(self, link_path, target_path):
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

    # ------------------------------------------------------------------
    # 1. Single-instance lock: microsecond boundary, concurrency, corruption
    # ------------------------------------------------------------------
    def test_lock_microsecond_expiry_boundary_and_stale_recovery(self):
        first = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_orig",
            ttl_seconds=600,
            now_utc="2026-11-23T00:30:00Z",
            lock_id="lock_orig",
        )
        self.assertTrue(first["acquired"])
        self.assertEqual(first["lock"]["expires_at"], "2026-11-23T00:40:00Z")
        lock_file = self.workspace / "ops" / "run.lock"
        orig_bytes = lock_file.read_bytes()

        # Exactly 1us before expires_at: still active -> locked, untouched.
        at_minus_1us = "2026-11-23T00:39:59.999999Z"
        insp_active = inspect_run_lock(self.workspace, now_utc=at_minus_1us)
        self.assertEqual(insp_active["state"], "active")
        self.assertTrue(insp_active["read_only"])

        blocked = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_contender",
            ttl_seconds=600,
            now_utc=at_minus_1us,
            lock_id="lock_contender",
            recover_expired=True,
        )
        self.assertFalse(blocked["acquired"])
        self.assertEqual(blocked["status"], "locked")
        self.assertEqual(blocked["reason_code"], "lock_held_active")
        self.assertEqual(lock_file.read_bytes(), orig_bytes)

        # Exactly at expires_at: expired.
        at_exact = "2026-11-23T00:40:00Z"
        insp_exp = inspect_run_lock(self.workspace, now_utc=at_exact)
        self.assertEqual(insp_exp["state"], "expired")

        # recover_expired=False refuses to take over.
        no_rec = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_contender",
            ttl_seconds=600,
            now_utc=at_exact,
            lock_id="lock_contender",
            recover_expired=False,
        )
        self.assertFalse(no_rec["acquired"])
        self.assertEqual(no_rec["status"], "expired_lock_present")
        self.assertEqual(lock_file.read_bytes(), orig_bytes)

        # Same lock_id collision during stale recovery is rejected.
        with self.assertRaisesRegex(ValueError, "stale_lock_id_collision"):
            acquire_run_lock(
                self.workspace,
                job_name="pre_market",
                run_id="run_contender",
                ttl_seconds=600,
                now_utc=at_exact,
                lock_id="lock_orig",
                recover_expired=True,
            )
        self.assertEqual(lock_file.read_bytes(), orig_bytes)

        # recover_expired=True archives old lock and acquires new lock cleanly.
        rec = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_contender",
            ttl_seconds=600,
            now_utc=at_exact,
            lock_id="lock_contender",
            recover_expired=True,
        )
        self.assertTrue(rec["acquired"])
        self.assertTrue(rec["stale_lock_recovered"])
        self.assertEqual(rec["recovered_stale_lock_id"], "lock_orig")
        archived_path = self.workspace / rec["archived_stale_lock"]
        self.assertTrue(archived_path.is_file())
        self.assertEqual(archived_path.read_bytes(), orig_bytes)
        self.assertEqual(list((self.workspace / "ops").glob(".lock-staging-*")), [])

    def test_concurrent_acquire_fresh_workspace_has_single_winner_and_no_errors(self):
        # Multiple rounds of 8 concurrent contenders on a fresh workspace (ops/ not yet created).
        for round_idx in range(6):
            ws = self.root / f"concurrent_fresh_{round_idx}"
            ws.mkdir()
            barrier = threading.Barrier(8)

            def worker(idx):
                barrier.wait()
                return acquire_run_lock(
                    ws,
                    job_name="pre_market",
                    run_id=f"run_r{round_idx}_{idx}",
                    ttl_seconds=600,
                    now_utc="2026-11-23T00:30:00Z",
                    lock_id=f"lock_r{round_idx}_{idx}",
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(worker, range(8)))

            winners = [r for r in results if r["acquired"]]
            losers = [r for r in results if not r["acquired"]]
            self.assertEqual(len(winners), 1, f"round {round_idx}: expected 1 winner, got {results}")
            self.assertEqual(len(losers), 7)
            winner_id = winners[0]["lock"]["lock_id"]
            for loser in losers:
                self.assertEqual(loser["status"], "locked", f"round {round_idx}: unexpected loser {loser}")
                self.assertEqual(loser["active_lock"]["lock_id"], winner_id)
            self.assertEqual(list((ws / "ops").glob(".lock-staging-*")), [])

    def test_concurrent_stale_lock_recovery_toctou_cannot_double_acquire_or_steal_active_lock(self):
        # Deterministic TOCTOU reproducer:
        # Thread B reads expired lock_old and pauses right before os.rename.
        # Thread A recovers lock_old and creates fresh active lock_A.
        # Thread B resumes: it MUST NOT rename/steal lock_A or acquire lock_B.
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_expired",
            ttl_seconds=30,
            now_utc="2026-11-23T00:00:00Z",
            lock_id="lock_old",
        )
        orig_rename = os.rename
        b_at_rename = threading.Event()
        a_done = threading.Event()
        results = {}

        def hooked_rename(src, dst):
            if threading.current_thread().name == "contender_B":
                b_at_rename.set()
                a_done.wait(timeout=5)
            return orig_rename(src, dst)

        def run_a():
            b_at_rename.wait(timeout=5)
            results["A"] = acquire_run_lock(
                self.workspace,
                job_name="pre_market",
                run_id="run_A",
                ttl_seconds=600,
                now_utc="2026-11-23T00:05:00Z",
                lock_id="lock_A",
                recover_expired=True,
            )
            a_done.set()

        def run_b():
            results["B"] = acquire_run_lock(
                self.workspace,
                job_name="pre_market",
                run_id="run_B",
                ttl_seconds=600,
                now_utc="2026-11-23T00:05:00Z",
                lock_id="lock_B",
                recover_expired=True,
            )

        with mock.patch.object(sched.os, "rename", side_effect=hooked_rename):
            tb = threading.Thread(target=run_b, name="contender_B")
            ta = threading.Thread(target=run_a, name="contender_A")
            tb.start()
            ta.start()
            tb.join(timeout=10)
            ta.join(timeout=10)

        acquired_list = [k for k, v in results.items() if v["acquired"]]
        self.assertEqual(
            len(acquired_list),
            1,
            f"Double lock acquisition during stale recovery: A={results['A']}, B={results['B']}",
        )
        # Ensure active lock_A was NEVER archived under stale-locks/.
        stale_dir = self.workspace / "ops" / "stale-locks"
        archived_ids = [
            json.loads(p.read_text(encoding="utf-8"))["lock_id"]
            for p in stale_dir.glob("*.json")
        ]
        self.assertEqual(archived_ids, ["lock_old"])
        self.assertEqual(list((self.workspace / "ops").glob(".lock-staging-*")), [])
        self.assertEqual(list((self.workspace / "ops").glob(".stale-recovery.lock")), [])

    def test_concurrent_stale_lock_recovery_stress_never_false_corrupt(self):
        # Un-mocked multi-thread race on an expired lock must yield 1 acquired + 7 locked, never false corrupt.
        for round_idx in range(10):
            ws = self.root / f"concurrent_stale_{round_idx}"
            ws.mkdir()
            acquire_run_lock(
                ws,
                job_name="pre_market",
                run_id="run_old",
                ttl_seconds=30,
                now_utc="2026-11-23T00:00:00Z",
                lock_id="lock_old",
            )
            barrier = threading.Barrier(8)

            def worker(idx):
                barrier.wait()
                return acquire_run_lock(
                    ws,
                    job_name="pre_market",
                    run_id=f"run_s{round_idx}_{idx}",
                    ttl_seconds=600,
                    now_utc="2026-11-23T00:10:00Z",
                    lock_id=f"lock_s{round_idx}_{idx}",
                    recover_expired=True,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(worker, range(8)))

            winners = [r for r in results if r["acquired"]]
            statuses = [r["status"] for r in results]
            self.assertEqual(len(winners), 1, f"round {round_idx}: {statuses}")
            self.assertEqual(statuses.count("locked"), 7, f"round {round_idx}: unexpected statuses {statuses}")
            self.assertEqual(list((ws / "ops").glob(".lock-staging-*")), [])
            self.assertEqual(list((ws / "ops").glob(".stale-recovery.lock")), [])

    def test_stale_lock_recovery_handles_transient_windows_sharing_violation(self):
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_old_share",
            ttl_seconds=30,
            now_utc="2026-11-23T00:00:00Z",
            lock_id="lock_old_share",
        )
        orig_rename = os.rename
        calls = {"n": 0}

        def flaky_rename(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                err = PermissionError(13, "The process cannot access the file because it is being used by another process")
                err.winerror = 32
                raise err
            return orig_rename(src, dst)

        with mock.patch.object(sched.os, "rename", side_effect=flaky_rename):
            res = acquire_run_lock(
                self.workspace,
                job_name="pre_market",
                run_id="run_new_share",
                ttl_seconds=600,
                now_utc="2026-11-23T00:10:00Z",
                lock_id="lock_new_share",
                recover_expired=True,
            )

        self.assertTrue(res["acquired"])
        self.assertTrue(res["stale_lock_recovered"])
        self.assertEqual(res["recovered_stale_lock_id"], "lock_old_share")
        self.assertEqual(list((self.workspace / "ops").glob(".lock-staging-*")), [])
        self.assertEqual(list((self.workspace / "ops").glob(".stale-recovery.lock")), [])

    def test_corrupt_lock_files_fail_closed_without_mutation(self):
        ws_hash = hashlib.sha256(str(self.workspace.resolve()).encode("utf-8")).hexdigest()
        valid_lock = {
            "schema_version": "ops-lock/0.1",
            "lock_id": "lock_base",
            "job_name": "pre_market",
            "run_id": "run_base",
            "workspace_sha256": ws_hash,
            "pid": 1234,
            "acquired_at": "2026-11-23T00:00:00Z",
            "expires_at": "2026-11-23T00:10:00Z",
            "ttl_seconds": 600,
            "status": "active",
            "recovered_stale_lock_id": None,
        }
        dup_key_json = (
            '{"schema_version":"ops-lock/0.1","lock_id":"a","lock_id":"b","job_name":"pre_market",'
            f'"run_id":"r1","workspace_sha256":"{ws_hash}","pid":1234,'
            '"acquired_at":"2026-11-23T00:00:00Z","expires_at":"2026-11-23T00:10:00Z",'
            '"ttl_seconds":600,"status":"active","recovered_stale_lock_id":null}\n'
        ).encode("utf-8")
        nan_json = (
            '{"schema_version":"ops-lock/0.1","lock_id":"a","job_name":"pre_market",'
            f'"run_id":"r1","workspace_sha256":"{ws_hash}","pid":NaN,'
            '"acquired_at":"2026-11-23T00:00:00Z","expires_at":"2026-11-23T00:10:00Z",'
            '"ttl_seconds":600,"status":"active","recovered_stale_lock_id":null}\n'
        ).encode("utf-8")
        oversized_json = (json.dumps(valid_lock) + (" " * 66_000) + "\n").encode("utf-8")
        self.assertGreater(len(oversized_json), 65_536)

        bad_ttl = copy.deepcopy(valid_lock)
        bad_ttl["ttl_seconds"] = 300  # mismatch with 600s delta

        bad_pid_bool = copy.deepcopy(valid_lock)
        bad_pid_bool["pid"] = True

        foreign_ws_lock = copy.deepcopy(valid_lock)
        foreign_ws_lock["workspace_sha256"] = "0" * 64

        vectors = [
            ("invalid_json", b"{corrupt_json"),
            ("duplicate_keys", dup_key_json),
            ("nan_value", nan_json),
            ("oversized_gt_64kb", oversized_json),
            ("ttl_mismatch", json.dumps(bad_ttl).encode("utf-8")),
            ("bool_pid", json.dumps(bad_pid_bool).encode("utf-8")),
            ("foreign_workspace_sha256", json.dumps(foreign_ws_lock).encode("utf-8")),
            ("invalid_utf8", b"\xff\xfe\xfd"),
        ]

        ops_dir = self.workspace / "ops"
        ops_dir.mkdir(exist_ok=True)
        lock_file = ops_dir / "run.lock"

        for name, raw_bytes in vectors:
            with self.subTest(vector=name):
                if lock_file.is_dir():
                    lock_file.rmdir()
                lock_file.write_bytes(raw_bytes)
                before_mtime = lock_file.lstat().st_mtime_ns

                insp = inspect_run_lock(self.workspace, now_utc="2026-11-24T00:00:00Z")
                self.assertEqual(insp["state"], "corrupt")
                self.assertEqual(insp["reason_code"], "lock_corrupt_manual_check_required")

                acq = acquire_run_lock(
                    self.workspace,
                    job_name="post_market",
                    run_id="run_after_corrupt",
                    now_utc="2026-11-24T00:00:00Z",
                    recover_expired=True,
                )
                self.assertFalse(acq["acquired"])
                self.assertEqual(acq["status"], "blocked_corrupt_lock")
                self.assertEqual(acq["reason_code"], "lock_corrupt_manual_check_required")

                code, out, _ = _run_cli(
                    "ops-lock-acquire",
                    "--workspace", str(self.workspace),
                    "--job", "post_market",
                    "--run-id", "run_cli_corrupt",
                    "--now", "2026-11-24T00:00:00Z",
                )
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["status"], "blocked_corrupt_lock")

                with self.assertRaisesRegex(ValueError, "lock_corrupt_manual_check_required"):
                    release_run_lock(self.workspace, lock_id="lock_base")

                self.assertEqual(lock_file.read_bytes(), raw_bytes)
                self.assertEqual(lock_file.lstat().st_mtime_ns, before_mtime)
                self.assertEqual(list(ops_dir.glob(".lock-staging-*")), [])

        # Also test ops/run.lock being a directory.
        lock_file.unlink()
        lock_file.mkdir()
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-24T00:00:00Z")["state"], "corrupt")
        acq_dir = acquire_run_lock(
            self.workspace,
            job_name="post_market",
            run_id="run_dir_lock",
            now_utc="2026-11-24T00:00:00Z",
        )
        self.assertEqual(acq_dir["status"], "blocked_corrupt_lock")
        self.assertTrue(lock_file.is_dir())

    def test_release_owner_safety_and_workspace_path_privacy(self):
        secret_ws = self.root / "secret_user_alice_9981" / "private_desk_ws"
        secret_ws.mkdir(parents=True)

        # Missing lock cannot be released.
        with self.assertRaisesRegex(ValueError, "lock_not_found"):
            release_run_lock(secret_ws, lock_id="lock_none")

        acq = acquire_run_lock(
            secret_ws,
            job_name="pre_market",
            run_id="run_priv_1",
            ttl_seconds=600,
            now_utc="2026-11-23T00:30:00Z",
            lock_id="lock_owner_1",
        )
        self.assertTrue(acq["acquired"])
        lock_file = secret_ws / "ops" / "run.lock"
        raw_text = lock_file.read_text(encoding="utf-8")

        # Raw path / username MUST NOT appear anywhere inside run.lock.
        self.assertNotIn("secret_user_alice_9981", raw_text)
        self.assertNotIn("private_desk_ws", raw_text)
        self.assertNotIn(str(secret_ws), raw_text)
        expected_hash = hashlib.sha256(str(secret_ws.resolve()).encode("utf-8")).hexdigest()
        self.assertEqual(acq["lock"]["workspace_sha256"], expected_hash)

        # Wrong owner or invalid lock_id rejected; lock remains intact.
        for bad_id, pattern in [
            ("lock_other", "lock_owner_mismatch"),
            ("../run.lock", "invalid_lock_id"),
            ("", "invalid_lock_id"),
            ("lock with space", "invalid_lock_id"),
        ]:
            with self.subTest(bad_id=bad_id):
                with self.assertRaisesRegex(ValueError, pattern):
                    release_run_lock(secret_ws, lock_id=bad_id)
                self.assertTrue(lock_file.is_file())
                self.assertEqual(lock_file.read_text(encoding="utf-8"), raw_text)

        rel = release_run_lock(secret_ws, lock_id="lock_owner_1")
        self.assertEqual(rel["status"], "released")
        self.assertFalse(lock_file.exists())

    # ------------------------------------------------------------------
    # 2. Read-only guarantees & append-only run journal integrity
    # ------------------------------------------------------------------
    def test_read_only_commands_never_create_or_mutate_workspace(self):
        # Empty workspace: read-only APIs and CLIs must not create ops/.
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-23T00:30:00Z")["state"], "unlocked")
        self.assertEqual(read_ops_status(self.workspace, now_utc="2026-11-23T00:30:00Z")["total_runs"], 0)
        plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-23"],
            now_utc="2026-11-23T09:00:00Z",
        )
        self.assertFalse(plan["auto_execute"])
        self.assertEqual(plan["missed_slots"], 2)

        code1, _, _ = _run_cli("ops-status", "--workspace", str(self.workspace), "--now", "2026-11-23T00:30:00Z")
        self.assertEqual(code1, 0)
        code2, _, _ = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--session-dates", "2026-11-23",
            "--now", "2026-11-23T09:00:00Z",
        )
        self.assertEqual(code2, 0)
        self.assertFalse((self.workspace / "ops").exists())

        # Populated workspace: lock + stale archive + journal -> bytes and mtime_ns strictly unchanged.
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="r_old",
            ttl_seconds=30,
            now_utc="2026-11-23T00:00:00Z",
            lock_id="l_old",
        )
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="r_cur",
            ttl_seconds=600,
            now_utc="2026-11-23T00:30:00Z",
            lock_id="l_cur",
            recover_expired=True,
        )
        record_ops_run(self.workspace, _sample_run(run_id="r_cur"))

        before = _snapshot_tree(self.workspace)
        inspect_run_lock(self.workspace, now_utc="2026-11-23T00:35:00Z")
        st = read_ops_status(self.workspace, now_utc="2026-11-23T00:35:00Z")
        self.assertEqual(st["stale_locks_archived_count"], 1)
        plan_missed_runs(self.workspace, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")
        c3, _, _ = _run_cli("ops-status", "--workspace", str(self.workspace), "--now", "2026-11-23T00:35:00Z")
        c4, _, _ = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--session-dates", "2026-11-23",
            "--now", "2026-11-23T09:00:00Z",
        )
        self.assertEqual(c3, 0)
        self.assertEqual(c4, 0)
        after = _snapshot_tree(self.workspace)
        self.assertEqual(before, after)

    def test_run_journal_rejects_corruption_and_conflicts_while_allowing_idempotent_replay(self):
        rec1 = _sample_run(run_id="run_j_1")
        r1 = record_ops_run(self.workspace, rec1)
        self.assertTrue(r1["recorded"])
        journal = self.workspace / "ops" / "runs.jsonl"
        orig_bytes = journal.read_bytes()
        self.assertTrue(orig_bytes.endswith(b"\n"))

        # Exact idempotent replay succeeds without modifying journal.
        r1_dup = record_ops_run(self.workspace, copy.deepcopy(rec1))
        self.assertEqual(r1_dup["status"], "idempotent_duplicate")
        self.assertFalse(r1_dup["recorded"])
        self.assertEqual(journal.read_bytes(), orig_bytes)

        # Payload conflict on same run_id rejected without modifying journal.
        conflict = copy.deepcopy(rec1)
        conflict["report_id"] = "pre_20261123_v2"
        with self.assertRaisesRegex(ValueError, "ops_run_id_conflict"):
            record_ops_run(self.workspace, conflict)
        self.assertEqual(journal.read_bytes(), orig_bytes)

        valid_line = orig_bytes.decode("utf-8").strip()
        dup_key_line = valid_line.replace('"run_id":"run_j_1"', '"run_id":"run_j_1","run_id":"run_j_1"')
        nan_line = valid_line.replace('"is_synthetic":true', '"is_synthetic":NaN')

        bad_journals = [
            ("partial_trailing_line_no_newline", valid_line.encode("utf-8"), "ops_run_journal_corrupt"),
            ("blank_line", (valid_line + "\n\n").encode("utf-8"), "ops_run_journal_corrupt"),
            ("duplicate_json_keys", (dup_key_line + "\n").encode("utf-8"), "ops_run_journal_corrupt"),
            ("nan_in_line", (nan_line + "\n").encode("utf-8"), "ops_run_journal_corrupt"),
            ("duplicate_run_id_same", (valid_line + "\n" + valid_line + "\n").encode("utf-8"), "ops_duplicate_run_id"),
            ("invalid_utf8", b"\xff\xfe\n", "ops_run_journal_corrupt"),
        ]

        rec2 = _sample_run(run_id="run_j_2")
        for name, content, expected_err in bad_journals:
            with self.subTest(journal_case=name):
                journal.write_bytes(content)
                with self.assertRaisesRegex(ValueError, expected_err):
                    read_ops_status(self.workspace, now_utc="2026-11-23T09:00:00Z")
                with self.assertRaisesRegex(ValueError, expected_err):
                    record_ops_run(self.workspace, rec2)
                with self.assertRaisesRegex(ValueError, expected_err):
                    plan_missed_runs(self.workspace, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")

        # CLI ops-record-run rejects duplicate JSON keys and NaN in input file.
        journal.write_bytes(orig_bytes)
        bad_in_dup = self.workspace / "bad_dup.json"
        bad_in_dup.write_text(dup_key_line, encoding="utf-8")
        c_dup, _, e_dup = _run_cli("ops-record-run", "--workspace", str(self.workspace), "--input", str(bad_in_dup))
        self.assertEqual(c_dup, 1)
        self.assertIn("ops_run_record_invalid", e_dup)

        bad_in_nan = self.workspace / "bad_nan.json"
        bad_in_nan.write_text(nan_line, encoding="utf-8")
        c_nan, _, e_nan = _run_cli("ops-record-run", "--workspace", str(self.workspace), "--input", str(bad_in_nan))
        self.assertEqual(c_nan, 1)
        self.assertIn("ops_run_record_invalid", e_nan)

    # ------------------------------------------------------------------
    # 3. Contract validator adversarial checks
    # ------------------------------------------------------------------
    def test_contract_validators_cross_field_and_type_safety(self):
        base_lock = {
            "schema_version": "ops-lock/0.1",
            "lock_id": "lock_v1",
            "job_name": "pre_market",
            "run_id": "run_v1",
            "workspace_sha256": "a" * 64,
            "pid": 100,
            "acquired_at": "2026-11-23T00:00:00Z",
            "expires_at": "2026-11-23T00:10:00Z",
            "ttl_seconds": 600,
            "status": "active",
            "recovered_stale_lock_id": None,
        }
        validate_ops_lock(base_lock)

        # Bool masquerading as int for pid / ttl_seconds, out-of-range, self-reference, mismatch.
        for label, mutator in [
            ("bool_pid", lambda d: d.__setitem__("pid", True)),
            ("bool_ttl", lambda d: d.__setitem__("ttl_seconds", True)),
            ("ttl_too_small", lambda d: d.update({"ttl_seconds": 29, "expires_at": "2026-11-23T00:00:29Z"})),
            ("ttl_too_large", lambda d: d.update({"ttl_seconds": 86401, "expires_at": "2026-11-24T00:00:01Z"})),
            ("ttl_mismatch", lambda d: d.__setitem__("ttl_seconds", 300)),
            ("self_ref_stale", lambda d: d.__setitem__("recovered_stale_lock_id", "lock_v1")),
            ("bad_status", lambda d: d.__setitem__("status", "released")),
            ("extra_field", lambda d: d.__setitem__("extra", 1)),
        ]:
            with self.subTest(lock_case=label):
                bad = copy.deepcopy(base_lock)
                mutator(bad)
                with self.assertRaises(ContractError):
                    validate_ops_lock(bad)

        # Non-session jobs may omit market_session_date; session jobs cannot.
        validate_ops_run_record(
            _sample_run(
                job_name="collect_all",
                market_session_date=None,
                outcome="succeeded",
                reason_codes=["normal_completion"],
                report_id=None,
                is_synthetic=False,
            )
        )

        bad_runs = [
            ("finished_before_started", _sample_run(started_at="2026-11-23T00:31:00Z", finished_at="2026-11-23T00:30:59.999999Z")),
            ("pre_market_missing_date", _sample_run(job_name="pre_market", market_session_date=None)),
            ("post_market_missing_date", _sample_run(job_name="post_market", market_session_date=None)),
            ("invalid_leap_date", _sample_run(market_session_date="2026-02-29")),
            (
                "skipped_locked_with_report_id",
                _sample_run(outcome="skipped_locked", reason_codes=["lock_held_active"], report_id="rep_1", is_synthetic=False),
            ),
            (
                "failed_network_with_report_id",
                _sample_run(outcome="failed_network", reason_codes=["network_unreachable"], report_id="rep_1", is_synthetic=False),
            ),
            (
                "failed_runtime_with_report_id",
                _sample_run(outcome="failed_runtime", reason_codes=["runtime_error"], report_id="rep_1", is_synthetic=False),
            ),
            (
                "stale_true_without_reason",
                _sample_run(stale_lock_recovered=True, reason_codes=["degraded_no_model", "synthetic_fixture"]),
            ),
            (
                "stale_false_with_reason",
                _sample_run(stale_lock_recovered=False, reason_codes=["degraded_no_model", "synthetic_fixture", "stale_lock_recovered"]),
            ),
            (
                "synthetic_true_without_reason_degraded",
                _sample_run(outcome="degraded", is_synthetic=True, reason_codes=["degraded_no_model"]),
            ),
            (
                "synthetic_false_with_reason",
                _sample_run(outcome="degraded", is_synthetic=False, reason_codes=["degraded_no_model", "synthetic_fixture"]),
            ),
            (
                "duplicate_reasons",
                _sample_run(outcome="degraded", reason_codes=["degraded_no_model", "degraded_no_model", "synthetic_fixture"]),
            ),
            (
                "failed_network_with_normal_completion",
                _sample_run(outcome="failed_network", reason_codes=["network_unreachable", "normal_completion"], report_id=None, is_synthetic=False),
            ),
            (
                "failed_runtime_with_normal_completion",
                _sample_run(outcome="failed_runtime", reason_codes=["runtime_error", "normal_completion"], report_id=None, is_synthetic=False),
            ),
            (
                "skipped_locked_with_normal_completion",
                _sample_run(outcome="skipped_locked", reason_codes=["lock_held_active", "normal_completion"], report_id=None, is_synthetic=False),
            ),
            (
                "degraded_with_normal_completion",
                _sample_run(outcome="degraded", reason_codes=["degraded_no_model", "normal_completion", "synthetic_fixture"]),
            ),
        ]
        for label, payload in bad_runs:
            with self.subTest(run_case=label):
                with self.assertRaises(ContractError):
                    validate_ops_run_record(payload)

        # validate_hhmm must reject non-ASCII Unicode digits (e.g. fullwidth/Arabic-Indic).
        for bad_hhmm in ["0\uff18:3\uff10", "\uff108:\uff130", "0\u0668:30", "24:00", "08:60", "8:30", "08:30:00"]:
            with self.subTest(hhmm=bad_hhmm):
                with self.assertRaises(ContractError):
                    validate_hhmm(bad_hhmm, "ops_plan.pre_market_local")

        # validate_ops_recovery_plan rejects bool counts & auto_execute=True.
        plan = plan_missed_runs(self.workspace, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")
        validate_ops_recovery_plan(plan)
        for label, mutator in [
            ("auto_execute_true", lambda d: d.__setitem__("auto_execute", True)),
            ("bool_completed_slots", lambda d: d.__setitem__("completed_slots", False)),
            ("bool_missed_slots", lambda d: d.__setitem__("missed_slots", True)),
            ("slot_mismatch", lambda d: d.__setitem__("scheduled_slots_checked", 99)),
        ]:
            with self.subTest(plan_case=label):
                bad_plan = copy.deepcopy(plan)
                mutator(bad_plan)
                with self.assertRaises(ContractError):
                    validate_ops_recovery_plan(bad_plan)

    # ------------------------------------------------------------------
    # 4. Missed-run recovery planner: anti-lookahead, calendar, DST, tz, 4 miss reasons
    # ------------------------------------------------------------------
    def test_plan_missed_runs_exact_microsecond_anti_lookahead_and_all_four_miss_reasons(self):
        # 2026-11-23 08:30 Asia/Shanghai == 2026-11-23T00:30:00Z
        # 1us before slot: NOT due yet.
        plan_before = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-23"],
            now_utc="2026-11-23T00:29:59.999999Z",
            display_timezone="Asia/Shanghai",
            pre_market_local="08:30",
            post_market_local="16:30",
        )
        self.assertEqual(plan_before["scheduled_slots_checked"], 0)
        self.assertEqual(plan_before["missed_slots"], 0)
        self.assertIn("no_due_slots_yet", plan_before["reason_codes"])

        # Exact slot instant: due and missed.
        plan_exact = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-23"],
            now_utc="2026-11-23T00:30:00Z",
            display_timezone="Asia/Shanghai",
            pre_market_local="08:30",
            post_market_local="16:30",
        )
        self.assertEqual(plan_exact["scheduled_slots_checked"], 1)
        self.assertEqual(plan_exact["missed_slots"], 1)
        self.assertEqual(plan_exact["pending_recovery_actions"][0]["miss_reason"], "offline_or_missed")

        # Populate all 4 miss reasons across 2 days (4 slots), including out-of-order attempts + future catch-up:
        # 11-23 pre_market: skipped_locked at 00:30:10Z, THEN failed_network at 00:31:00Z (latest),
        #                   AND a catch-up degraded run at 2026-11-24T12:00:00.000001Z (1us AFTER now_utc!).
        # Write later run FIRST to verify chronological max (not file order).
        record_ops_run(
            self.workspace,
            _sample_run(
                run_id="r_23_pre_net",
                job_name="pre_market",
                market_session_date="2026-11-23",
                scheduled_for="2026-11-23T00:30:00Z",
                started_at="2026-11-23T00:30:50Z",
                finished_at="2026-11-23T00:31:00Z",
                outcome="failed_network",
                reason_codes=["network_unreachable"],
                report_id=None,
                is_synthetic=False,
            ),
        )
        record_ops_run(
            self.workspace,
            _sample_run(
                run_id="r_23_pre_lock_earlier",
                job_name="pre_market",
                market_session_date="2026-11-23",
                scheduled_for="2026-11-23T00:30:00Z",
                started_at="2026-11-23T00:30:01Z",
                finished_at="2026-11-23T00:30:10Z",
                outcome="skipped_locked",
                reason_codes=["lock_held_active"],
                report_id=None,
                is_synthetic=False,
            ),
        )
        record_ops_run(
            self.workspace,
            _sample_run(
                run_id="r_23_pre_catchup_future_1us",
                job_name="pre_market",
                market_session_date="2026-11-23",
                scheduled_for="2026-11-23T00:30:00Z",
                started_at="2026-11-24T11:59:59Z",
                finished_at="2026-11-24T12:00:00.000001Z",
                outcome="degraded",
                reason_codes=["degraded_no_model", "retrospective_catchup", "synthetic_fixture"],
                report_id="pre_20261123_catchup",
                is_synthetic=True,
            ),
        )
        # 11-23 post_market: failed_runtime
        record_ops_run(
            self.workspace,
            _sample_run(
                run_id="r_23_post_rt",
                job_name="post_market",
                market_session_date="2026-11-23",
                scheduled_for="2026-11-23T08:30:00Z",
                started_at="2026-11-23T08:30:05Z",
                finished_at="2026-11-23T08:30:20Z",
                outcome="failed_runtime",
                reason_codes=["runtime_error"],
                report_id=None,
                is_synthetic=False,
            ),
        )
        # 11-24 pre_market: skipped_locked
        record_ops_run(
            self.workspace,
            _sample_run(
                run_id="r_24_pre_locked",
                job_name="pre_market",
                market_session_date="2026-11-24",
                scheduled_for="2026-11-24T00:30:00Z",
                started_at="2026-11-24T00:30:01Z",
                finished_at="2026-11-24T00:30:02Z",
                outcome="skipped_locked",
                reason_codes=["lock_held_active"],
                report_id=None,
                is_synthetic=False,
            ),
        )
        # 11-24 post_market: no run at all -> offline_or_missed.

        # At 2026-11-24T12:00:00Z: catchup finished 1us later MUST NOT be counted!
        plan_at_t = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-24", "2026-11-23"],
            now_utc="2026-11-24T12:00:00Z",
        )
        self.assertEqual(plan_at_t["scheduled_slots_checked"], 4)
        self.assertEqual(plan_at_t["completed_slots"], 0)
        self.assertEqual(plan_at_t["missed_slots"], 4)
        self.assertEqual(
            [
                (a["market_session_date"], a["job_name"], a["miss_reason"], a["last_failed_run_id"])
                for a in plan_at_t["pending_recovery_actions"]
            ],
            [
                ("2026-11-23", "pre_market", "previous_network_failure", "r_23_pre_net"),
                ("2026-11-23", "post_market", "previous_runtime_failure", "r_23_post_rt"),
                ("2026-11-24", "pre_market", "previous_lock_conflict", "r_24_pre_locked"),
                ("2026-11-24", "post_market", "offline_or_missed", None),
            ],
        )

        # At 2026-11-24T12:00:00.000001Z: catchup run IS visible -> 11-23 pre_market completed!
        plan_after_1us = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-23", "2026-11-24"],
            now_utc="2026-11-24T12:00:00.000001Z",
        )
        self.assertEqual(plan_after_1us["completed_slots"], 1)
        self.assertEqual(plan_after_1us["missed_slots"], 3)

    def test_plan_missed_runs_calendar_snapshot_dst_and_strict_timezone(self):
        cal_file = self.workspace / "calendar.json"
        cal_payload = {
            "schema_version": "scheduled-session-snapshot/0.1",
            "exchange": "SSE",
            "scheduled_sessions": ["2026-11-24", "2026-11-23"],
        }
        cal_file.write_text(json.dumps(cal_payload), encoding="utf-8")

        # Via API dict and CLI --calendar-file
        plan_api = plan_missed_runs(
            self.workspace,
            scheduled_dates=cal_payload,
            now_utc="2026-11-24T01:00:00Z",
        )
        code, out, _ = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--calendar-file", str(cal_file),
            "--now", "2026-11-24T01:00:00Z",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), plan_api)
        self.assertEqual(plan_api["scheduled_slots_checked"], 3)

        # Invalid calendar snapshots / dates rejected.
        for bad_cal in [
            {"schema_version": "scheduled-session-snapshot/9.9", "scheduled_sessions": ["2026-11-23"]},
            {"schema_version": "scheduled-session-snapshot/0.1", "scheduled_sessions": []},
            {"schema_version": "scheduled-session-snapshot/0.1", "scheduled_sessions": ["2026-11-23", "2026-11-23"]},
            {"schema_version": "scheduled-session-snapshot/0.1", "scheduled_sessions": ["2026-02-29"]},
            ["2026-02-29"],
            ["2026-11-23", "2026-11-23"],
            [],
        ]:
            with self.subTest(bad_cal=bad_cal):
                with self.assertRaises(ValueError):
                    plan_missed_runs(self.workspace, scheduled_dates=bad_cal, now_utc="2026-11-24T01:00:00Z")

        # CLI --calendar-file rejects duplicate JSON keys & NaN.
        bad_cal_file = self.workspace / "bad_cal.json"
        bad_cal_file.write_text(
            '{"schema_version":"scheduled-session-snapshot/0.1","schema_version":"scheduled-session-snapshot/0.1","scheduled_sessions":["2026-11-23"]}',
            encoding="utf-8",
        )
        c_bad, _, e_bad = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--calendar-file", str(bad_cal_file),
            "--now", "2026-11-24T01:00:00Z",
        )
        self.assertEqual(c_bad, 1)
        self.assertIn("ops_calendar_file_invalid", e_bad)

        # DST: America/New_York spring-forward nonexistent wall time 2026-03-08 02:30 rejected.
        with self.assertRaisesRegex(ValueError, "nonexistent_local_schedule_time"):
            plan_missed_runs(
                self.workspace,
                scheduled_dates=["2026-03-08"],
                now_utc="2026-03-09T00:00:00Z",
                display_timezone="America/New_York",
                pre_market_local="02:30",
                post_market_local="16:30",
            )

        # DST: Valid EST (UTC-5) and EDT (UTC-4) exact conversions.
        dst_plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-01-15", "2026-07-15"],
            now_utc="2026-07-16T00:00:00Z",
            display_timezone="America/New_York",
            pre_market_local="08:30",
            post_market_local="16:30",
        )
        self.assertEqual(
            [(a["market_session_date"], a["job_name"], a["scheduled_for"]) for a in dst_plan["pending_recovery_actions"]],
            [
                ("2026-01-15", "pre_market", "2026-01-15T13:30:00Z"),
                ("2026-01-15", "post_market", "2026-01-15T21:30:00Z"),
                ("2026-07-15", "pre_market", "2026-07-15T12:30:00Z"),
                ("2026-07-15", "post_market", "2026-07-15T20:30:00Z"),
            ],
        )

        # Cross-platform timezone strictness (including canonical IANA case sensitivity).
        for bad_tz in [
            "Asia/Shanghai ",
            " Asia/Shanghai",
            "UTC.",
            "Asia/Shanghai.",
            "Asia\\Shanghai",
            "../UTC",
            "/UTC",
            "Asia/Shanghai/",
            "Asia\tShanghai",
            "Asia/shanghai",
            "America/new_york",
            "utc",
            "",
        ]:
            with self.subTest(bad_tz=bad_tz):
                with self.assertRaises(ContractError):
                    validate_timezone_strict(bad_tz, "tz")
                with self.assertRaises(ContractError):
                    plan_missed_runs(
                        self.workspace,
                        scheduled_dates=["2026-11-23"],
                        now_utc="2026-11-24T00:00:00Z",
                        display_timezone=bad_tz,
                    )

    # ------------------------------------------------------------------
    # 5. Windows Task Scheduler XML template security & idempotency
    # ------------------------------------------------------------------
    def test_windows_task_template_injection_safety_and_conflict_handling(self):
        out_xml = self.workspace / "tpl" / "pre.xml"
        res = render_windows_task_template(
            job_name="pre_market",
            task_name="market_intel_pre_qa",
            trigger_local_time="08:30",
            display_timezone="Asia/Shanghai",
            workspace_rel="data/live",
            start_date="2026-11-24",
            output_path=out_xml,
        )
        self.assertFalse(res["auto_installed"])
        self.assertTrue(res["dry_run_template_only"])
        self.assertFalse(res["enabled_in_template"])

        root = ET.fromstring(res["xml"])
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.attrib.get("version"), "1.2")
        self.assertEqual(root.findtext("t:Triggers/t:CalendarTrigger/t:Enabled", namespaces=ns), "false")
        self.assertEqual(root.findtext("t:Settings/t:Enabled", namespaces=ns), "false")
        self.assertEqual(root.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns), "IgnoreNew")
        self.assertEqual(root.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns), "true")
        self.assertEqual(root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns), "%MARKET_INTEL_PYTHON%")

        # No credentials or secrets embedded in XML.
        for forbidden in ("Password", "UserId", "LogonType", "DEEPSEEK_API_KEY", "Secret", "Token"):
            self.assertNotIn(forbidden, res["xml"])

        # Unsafe workspace_rel rejected.
        for bad_ws in [
            "C:/data/live",
            "C:\\data\\live",
            "/etc/passwd",
            "\\\\server\\share\\ws",
            "../data",
            "data/../live",
            "data/./live",
            "data\\live",
            'data/"live"',
            "data/'live'",
            "data/%TEMP%",
            "data/$HOME",
            "data/live&calc",
            "data/live;calc",
            "data/live|calc",
            "data/<live>",
            "data/my live",
            " data/live",
            "data/live\n",
            "data//live",
            "--now",
            "-workspace",
            ".hidden",
            "data/.hidden",
            "data/-flag",
            "",
            "a" * 129,
        ]:
            with self.subTest(bad_ws=bad_ws):
                with self.assertRaisesRegex(ValueError, "invalid_workspace_rel"):
                    render_windows_task_template(
                        job_name="pre_market",
                        task_name="valid_task",
                        trigger_local_time="08:30",
                        workspace_rel=bad_ws,
                    )

        # Unsafe task_name and invalid job_name rejected.
        for bad_task in ["task name", "a/b", "a\\b", "..", "<task>", "a&b", 'a"b', "a;b", "a|b", "%x%", "$x", "", "t" * 65]:
            with self.subTest(bad_task=bad_task):
                with self.assertRaisesRegex(ValueError, "invalid_task_name"):
                    render_windows_task_template(
                        job_name="pre_market",
                        task_name=bad_task,
                        trigger_local_time="08:30",
                    )
        with self.assertRaisesRegex(ValueError, "invalid_job_name"):
            render_windows_task_template(
                job_name="collect_all",
                task_name="valid_task",
                trigger_local_time="08:30",
            )

        # Conflicting output file rejected without overwriting or leaving staging files.
        orig_bytes = out_xml.read_bytes()
        orig_mtime = out_xml.lstat().st_mtime_ns
        with self.assertRaisesRegex(ValueError, "template_output_conflict"):
            render_windows_task_template(
                job_name="post_market",
                task_name="market_intel_pre_qa",
                trigger_local_time="16:30",
                workspace_rel="data/live",
                output_path=out_xml,
            )
        self.assertEqual(out_xml.read_bytes(), orig_bytes)
        self.assertEqual(out_xml.lstat().st_mtime_ns, orig_mtime)
        self.assertEqual(list(out_xml.parent.glob(".template-staging-*")), [])

        # Idempotent identical write succeeds.
        res2 = render_windows_task_template(
            job_name="pre_market",
            task_name="market_intel_pre_qa",
            trigger_local_time="08:30",
            display_timezone="Asia/Shanghai",
            workspace_rel="data/live",
            start_date="2026-11-24",
            output_path=out_xml,
        )
        self.assertEqual(res2["xml_sha256"], res["xml_sha256"])
        self.assertEqual(list(out_xml.parent.glob(".template-staging-*")), [])

    # ------------------------------------------------------------------
    # 6. Path safety: UNC paths & Windows NTFS directory junctions
    # ------------------------------------------------------------------
    def test_unc_paths_rejected_across_all_ops_entrypoints(self):
        rec = _sample_run(run_id="run_unc_1")
        for unc in [r"\\server\share\ws", "//server/share/ws"]:
            with self.subTest(unc=unc):
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    inspect_run_lock(unc, now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    acquire_run_lock(unc, job_name="pre_market", run_id="r1", now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    release_run_lock(unc, lock_id="l1")
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    record_ops_run(unc, rec)
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    read_ops_status(unc, now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    plan_missed_runs(unc, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")
                with self.assertRaisesRegex(ValueError, "ops_path_unsupported"):
                    render_windows_task_template(
                        job_name="pre_market",
                        task_name="unc_task",
                        trigger_local_time="08:30",
                        output_path=unc + r"\task.xml",
                    )

    def test_windows_ntfs_junctions_rejected_across_all_ops_entrypoints(self):
        real_target = self.root / "real_target"
        real_target.mkdir()
        j_ws = self._make_junction(self.root / "junction_ws", real_target)
        rec = _sample_run(run_id="run_j_1")

        # 1. Junction as workspace itself and as ancestor of workspace / output / CLI inputs.
        for candidate in [j_ws, j_ws / "nested_ws"]:
            with self.subTest(junction_workspace=str(candidate)):
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    inspect_run_lock(candidate, now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    acquire_run_lock(candidate, job_name="pre_market", run_id="r1", now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    release_run_lock(candidate, lock_id="l1")
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    record_ops_run(candidate, rec)
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    read_ops_status(candidate, now_utc="2026-11-23T00:30:00Z")
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    plan_missed_runs(candidate, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")
                with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
                    render_windows_task_template(
                        job_name="pre_market",
                        task_name="j_task",
                        trigger_local_time="08:30",
                        output_path=candidate / "out.xml",
                    )

        # CLI --input and --calendar-file through a junction must also be rejected.
        (real_target / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        (real_target / "cal.json").write_text(
            json.dumps({"schema_version": "scheduled-session-snapshot/0.1", "scheduled_sessions": ["2026-11-23"]}),
            encoding="utf-8",
        )
        c_in, _, e_in = _run_cli("ops-record-run", "--workspace", str(self.workspace), "--input", str(j_ws / "run.json"))
        self.assertEqual(c_in, 1)
        self.assertIn("ops_run_record_unsupported", e_in)

        c_cal, _, e_cal = _run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--calendar-file", str(j_ws / "cal.json"),
            "--now", "2026-11-23T09:00:00Z",
        )
        self.assertEqual(c_cal, 1)
        self.assertIn("ops_calendar_file_unsupported", e_cal)

        # 2. Junction at <workspace>/ops -> outside dir.
        ws_ops_j = self.root / "ws_ops_j"
        ws_ops_j.mkdir()
        outside_ops = self.root / "outside_ops"
        outside_ops.mkdir()
        self._make_junction(ws_ops_j / "ops", outside_ops)

        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            inspect_run_lock(ws_ops_j, now_utc="2026-11-23T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            acquire_run_lock(ws_ops_j, job_name="pre_market", run_id="r1", now_utc="2026-11-23T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            record_ops_run(ws_ops_j, rec)
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            read_ops_status(ws_ops_j, now_utc="2026-11-23T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            plan_missed_runs(ws_ops_j, scheduled_dates=["2026-11-23"], now_utc="2026-11-23T09:00:00Z")

        # 3. Junction at <workspace>/ops/stale-locks -> outside dir.
        ws_stale_j = self.root / "ws_stale_j"
        (ws_stale_j / "ops").mkdir(parents=True)
        outside_stale = self.root / "outside_stale"
        outside_stale.mkdir()
        self._make_junction(ws_stale_j / "ops" / "stale-locks", outside_stale)

        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            acquire_run_lock(ws_stale_j, job_name="pre_market", run_id="r1", now_utc="2026-11-23T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "ops_symlink_not_allowed"):
            read_ops_status(ws_stale_j, now_utc="2026-11-23T00:30:00Z")


if __name__ == "__main__":
    unittest.main()
