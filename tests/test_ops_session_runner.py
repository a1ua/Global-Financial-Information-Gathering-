import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from market_intel.cli import main as cli_main
from market_intel.offline import ingest_fixture
from market_intel.ops.backup import create_backup, restore_backup, verify_backup
from market_intel.ops.scheduler import (
    acquire_run_lock,
    inspect_run_lock,
    plan_missed_runs,
    read_ops_status,
)
from market_intel.ops.session_runner import run_guarded_session_brief
from market_intel.report.session_brief import replay_session_brief, verify_session_brief
from market_intel.store import connect


def _demo_fixture():
    return json.loads(files("market_intel").joinpath("fixtures/demo.json").read_text(encoding="utf-8"))


class OpsSessionRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        db = connect(self.workspace / "market.db")
        try:
            ingest_fixture(db, _demo_fixture(), self.workspace)
        finally:
            db.close()

    def tearDown(self):
        self._tmp.cleanup()

    def _run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_guarded_run_publishes_verifies_records_and_releases_lock(self):
        res = run_guarded_session_brief(
            self.workspace,
            report_type="pre_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T00:30:00Z",
            run_id="run_pre_1",
            report_id="pre_20261106_v1",
            scheduled_for="2026-11-06T00:30:00Z",
            now_utc="2026-11-06T00:30:05Z",
        )
        self.assertEqual(res["status"], "degraded")
        self.assertTrue(res["verified"])
        self.assertTrue(res["recorded_run"])
        self.assertTrue(res["lock_released"])
        self.assertTrue(res["is_synthetic"])
        self.assertEqual(
            res["run_record"]["reason_codes"],
            ["degraded_no_model", "degraded_no_market_data", "synthetic_fixture"],
        )
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")

        status = read_ops_status(self.workspace, now_utc="2026-11-06T00:31:00Z")
        self.assertEqual(status["total_runs"], 1)
        self.assertEqual(status["counts_by_outcome"]["degraded"], 1)

        plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-06"],
            now_utc="2026-11-06T09:00:00Z",
        )
        self.assertEqual(plan["completed_slots"], 1)
        self.assertEqual(plan["missed_slots"], 1)
        self.assertEqual(plan["pending_recovery_actions"][0]["job_name"], "post_market")

    def test_active_lock_skips_cleanly_and_records_skipped_locked(self):
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="holder_run",
            ttl_seconds=600,
            now_utc="2026-11-06T00:30:00Z",
            lock_id="holder_lock",
        )
        code, out, err = self._run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "blocked_run_1",
            "--report-id", "pre_20261106_blocked",
            "--now", "2026-11-06T00:31:00Z",
        )
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "skipped_locked")
        self.assertTrue(payload["recorded_run"])
        self.assertFalse(payload["lock_released"])
        self.assertFalse((self.workspace / "reports" / "pre_20261106_blocked").exists())
        self.assertEqual(
            inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["lock"]["lock_id"],
            "holder_lock",
        )

        plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-06"],
            now_utc="2026-11-06T01:00:00Z",
        )
        self.assertEqual(plan["missed_slots"], 1)
        self.assertEqual(plan["pending_recovery_actions"][0]["miss_reason"], "previous_lock_conflict")
        self.assertEqual(plan["pending_recovery_actions"][0]["last_failed_run_id"], "blocked_run_1")

    def test_expired_lock_recovers_archives_and_publishes(self):
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="old_crashed_run",
            ttl_seconds=300,
            now_utc="2026-11-06T00:20:00Z",
            lock_id="stale_lock_01",
        )
        res = run_guarded_session_brief(
            self.workspace,
            report_type="pre_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T00:30:00Z",
            run_id="recovery_run_1",
            report_id="pre_20261106_recovered",
            now_utc="2026-11-06T00:30:05Z",
            retrospective_catchup=True,
        )
        self.assertEqual(res["status"], "degraded")
        self.assertTrue(res["stale_lock_recovered"])
        self.assertEqual(res["recovered_stale_lock_id"], "stale_lock_01")
        self.assertTrue((self.workspace / res["archived_stale_lock"]).is_file())
        self.assertIn("stale_lock_recovered", res["run_record"]["reason_codes"])
        self.assertIn("retrospective_catchup", res["run_record"]["reason_codes"])
        self.assertTrue(res["lock_released"])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")

    def test_runtime_failure_records_failed_runtime_and_releases_lock(self):
        # Corrupt raw evidence file so render_session_brief fails closed.
        raw_files = list((self.workspace / "raw").glob("*.txt"))
        self.assertTrue(raw_files)
        raw_files[0].write_text("tampered evidence content", encoding="utf-8")

        code, out, err = self._run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "run_fail_1",
            "--report-id", "pre_20261106_fail",
            "--now", "2026-11-06T00:30:05Z",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "failed_runtime")
        self.assertEqual(payload["reason"], "report_evidence_corrupt")
        self.assertTrue(payload["recorded_run"])
        self.assertTrue(payload["lock_released"])
        self.assertIsNone(payload["report_id"])
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-06T00:31:00Z")["state"], "unlocked")
        self.assertFalse((self.workspace / "reports" / "pre_20261106_fail").exists())

        plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-06"],
            now_utc="2026-11-06T01:00:00Z",
        )
        self.assertEqual(plan["pending_recovery_actions"][0]["miss_reason"], "previous_runtime_failure")
        self.assertEqual(plan["pending_recovery_actions"][0]["last_failed_run_id"], "run_fail_1")

    def test_corrupt_lock_fails_closed_without_mutating_lock_or_journal(self):
        ops_dir = self.workspace / "ops"
        ops_dir.mkdir(parents=True, exist_ok=True)
        lock_file = ops_dir / "run.lock"
        lock_file.write_text("{broken-json", encoding="utf-8")

        code, out, err = self._run_cli(
            "ops-run-session-brief",
            "--workspace", str(self.workspace),
            "--report-type", "pre_market",
            "--session-date", "2026-11-06",
            "--cutoff", "2026-11-06T00:30:00Z",
            "--run-id", "run_corrupt_blocked",
            "--now", "2026-11-06T00:30:05Z",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "blocked_corrupt_lock")
        self.assertFalse(payload["recorded_run"])
        self.assertEqual(lock_file.read_text(encoding="utf-8"), "{broken-json")
        self.assertFalse((ops_dir / "runs.jsonl").exists())

    def test_vertical_integration_guarded_run_backup_restore_replay_and_catchup(self):
        # 1. Guarded pre_market publish
        pre = run_guarded_session_brief(
            self.workspace,
            report_type="pre_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T00:30:00Z",
            run_id="vert_pre_1",
            report_id="pre_20261106_v1",
            now_utc="2026-11-06T00:30:05Z",
        )
        self.assertEqual(pre["status"], "degraded")

        # 2. Backup + verify + isolated restore of evidence workspace
        backup_dir = self.root / "backup_1"
        restored_ws = self.root / "restored_ws"
        create_backup(self.workspace, backup_dir)
        self.assertEqual(verify_backup(backup_dir)["status"], "verified")
        restore_backup(backup_dir, restored_ws)

        # 3. Deterministic replay from original workspace and verify on restored DB
        replay_dir = self.root / "replay_1"
        db = connect(self.workspace / "market.db")
        try:
            replayed = replay_session_brief(db, self.workspace, "pre_20261106_v1", replay_dir)
        finally:
            db.close()
        for ref in ("brief.html", "brief.md"):
            replayed_hash = hashlib.sha256((replayed / ref).read_bytes()).hexdigest()
            self.assertEqual(replayed_hash, pre["artifact_sha256"][ref])

        # 4. Run guarded post_market catchup on restored workspace -> verify -> planner sees completed
        post = run_guarded_session_brief(
            restored_ws,
            report_type="post_market",
            market_session_date="2026-11-06",
            cutoff="2026-11-06T08:30:00Z",
            run_id="vert_post_catchup",
            report_id="post_20261106_catchup",
            now_utc="2026-11-06T08:35:00Z",
            retrospective_catchup=True,
        )
        self.assertEqual(post["status"], "degraded")
        ro_db = connect(restored_ws / "market.db")
        try:
            self.assertEqual(verify_session_brief(ro_db, restored_ws, "post_20261106_catchup")["status"], "verified")
        finally:
            ro_db.close()

        plan = plan_missed_runs(
            restored_ws,
            scheduled_dates=["2026-11-06"],
            now_utc="2026-11-06T09:00:00Z",
        )
        self.assertEqual(plan["completed_slots"], 1)
        self.assertEqual(plan["missed_slots"], 1)
        self.assertEqual(plan["pending_recovery_actions"][0]["job_name"], "pre_market")


if __name__ == "__main__":
    unittest.main()
