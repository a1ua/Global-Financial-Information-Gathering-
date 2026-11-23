import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from market_intel.cli import main as cli_main
from market_intel.contracts import ContractError
from market_intel.contracts.ops_schedule import (
    validate_ops_lock,
    validate_ops_recovery_plan,
    validate_ops_run_record,
)
from market_intel.ops.scheduler import (
    acquire_run_lock,
    inspect_run_lock,
    plan_missed_runs,
    read_ops_status,
    record_ops_run,
    release_run_lock,
    render_windows_task_template,
)


def _sample_run(
    *,
    run_id="run_20261123_pre_1",
    job_name="pre_market",
    session_date="2026-11-23",
    scheduled_for="2026-11-23T00:30:00Z",
    started_at="2026-11-23T00:30:05Z",
    finished_at="2026-11-23T00:31:00Z",
    outcome="degraded",
    reason_codes=None,
    report_id="pre_20261123_v1",
    lock_id="lock_001",
    stale_lock_recovered=False,
    is_synthetic=True,
):
    if reason_codes is None:
        reason_codes = ["degraded_no_model", "degraded_no_market_data", "synthetic_fixture"]
    return {
        "schema_version": "ops-run-record/0.1",
        "run_id": run_id,
        "job_name": job_name,
        "market_session_date": session_date,
        "scheduled_for": scheduled_for,
        "started_at": started_at,
        "finished_at": finished_at,
        "outcome": outcome,
        "reason_codes": reason_codes,
        "report_id": report_id,
        "lock_id": lock_id,
        "stale_lock_recovered": stale_lock_recovered,
        "is_synthetic": is_synthetic,
    }


class OpsSchedulerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_lock_acquire_conflict_owner_release_and_read_only_inspect(self):
        # Inspect on empty workspace must not create ops/
        empty_status = read_ops_status(self.workspace, now_utc="2026-11-23T00:30:00Z")
        self.assertEqual(empty_status["lock"]["state"], "unlocked")
        self.assertEqual(empty_status["total_runs"], 0)
        self.assertFalse((self.workspace / "ops").exists())

        first = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_1",
            ttl_seconds=600,
            now_utc="2026-11-23T00:30:00Z",
            lock_id="lock_alpha",
        )
        self.assertTrue(first["acquired"])
        self.assertEqual(first["lock"]["expires_at"], "2026-11-23T00:40:00Z")
        validate_ops_lock(first["lock"])

        # Second concurrent acquire before expiry must be blocked without overwriting.
        second = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_2",
            ttl_seconds=600,
            now_utc="2026-11-23T00:39:59.999999Z",
            lock_id="lock_beta",
        )
        self.assertFalse(second["acquired"])
        self.assertEqual(second["status"], "locked")
        self.assertEqual(second["reason_code"], "lock_held_active")
        self.assertEqual(second["active_lock"]["lock_id"], "lock_alpha")

        # Wrong owner cannot release.
        with self.assertRaisesRegex(ValueError, "lock_owner_mismatch"):
            release_run_lock(self.workspace, lock_id="lock_beta")
        self.assertTrue((self.workspace / "ops" / "run.lock").is_file())

        # Correct owner releases cleanly.
        released = release_run_lock(self.workspace, lock_id="lock_alpha")
        self.assertEqual(released["status"], "released")
        self.assertEqual(inspect_run_lock(self.workspace, now_utc="2026-11-23T00:35:00Z")["state"], "unlocked")

    def test_expired_lock_archival_recovery_and_corrupt_lock_fail_closed(self):
        acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_old",
            ttl_seconds=300,
            now_utc="2026-11-23T00:30:00Z",
            lock_id="lock_stale_1",
        )
        # Exactly at expires_at, lock is expired.
        insp = inspect_run_lock(self.workspace, now_utc="2026-11-23T00:35:00Z")
        self.assertEqual(insp["state"], "expired")

        # When recover_expired=False, lock is preserved and not overwritten.
        denied = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_new",
            ttl_seconds=300,
            now_utc="2026-11-23T00:35:00Z",
            lock_id="lock_new_1",
            recover_expired=False,
        )
        self.assertFalse(denied["acquired"])
        self.assertEqual(denied["status"], "expired_lock_present")

        # When recover_expired=True, old lock is archived under ops/stale-locks/.
        recovered = acquire_run_lock(
            self.workspace,
            job_name="pre_market",
            run_id="run_new",
            ttl_seconds=300,
            now_utc="2026-11-23T00:35:00Z",
            lock_id="lock_new_1",
            recover_expired=True,
        )
        self.assertTrue(recovered["acquired"])
        self.assertTrue(recovered["stale_lock_recovered"])
        self.assertEqual(recovered["recovered_stale_lock_id"], "lock_stale_1")
        archived = self.workspace / recovered["archived_stale_lock"]
        self.assertTrue(archived.is_file())
        self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["lock_id"], "lock_stale_1")

        # Corrupt lock fails closed without overwriting.
        lock_file = self.workspace / "ops" / "run.lock"
        lock_file.write_text("{corrupt", encoding="utf-8")
        blocked = acquire_run_lock(
            self.workspace,
            job_name="post_market",
            run_id="run_after_corrupt",
            now_utc="2026-11-24T00:00:00Z",
        )
        self.assertFalse(blocked["acquired"])
        self.assertEqual(blocked["status"], "blocked_corrupt_lock")
        self.assertEqual(lock_file.read_text(encoding="utf-8"), "{corrupt")

    def test_run_journal_append_idempotency_conflict_and_status(self):
        rec1 = _sample_run()
        res1 = record_ops_run(self.workspace, rec1)
        self.assertTrue(res1["recorded"])

        # Exact duplicate is idempotent.
        res1_dup = record_ops_run(self.workspace, copy.deepcopy(rec1))
        self.assertEqual(res1_dup["status"], "idempotent_duplicate")
        self.assertFalse(res1_dup["recorded"])

        # Same run_id with modified payload is rejected.
        mutated = copy.deepcopy(rec1)
        mutated["report_id"] = "pre_20261123_v2"
        with self.assertRaisesRegex(ValueError, "ops_run_id_conflict"):
            record_ops_run(self.workspace, mutated)

        rec2 = _sample_run(
            run_id="run_20261123_post_1",
            job_name="post_market",
            scheduled_for="2026-11-23T08:30:00Z",
            started_at="2026-11-23T08:30:02Z",
            finished_at="2026-11-23T08:30:10Z",
            outcome="failed_network",
            reason_codes=["network_unreachable"],
            report_id=None,
            is_synthetic=False,
        )
        record_ops_run(self.workspace, rec2)

        status = read_ops_status(self.workspace, now_utc="2026-11-23T09:00:00Z")
        self.assertEqual(status["total_runs"], 2)
        self.assertEqual(status["counts_by_outcome"]["degraded"], 1)
        self.assertEqual(status["counts_by_outcome"]["failed_network"], 1)
        self.assertEqual(status["last_run_by_job"]["post_market"]["run_id"], "run_20261123_post_1")

    def test_plan_missed_runs_anti_lookahead_and_failure_reasons(self):
        # Day 1 pre_market degraded (counts as completed), post_market failed_network (missed).
        record_ops_run(self.workspace, _sample_run(
            run_id="run_d1_pre",
            job_name="pre_market",
            session_date="2026-11-23",
            scheduled_for="2026-11-23T00:30:00Z",
            started_at="2026-11-23T00:30:05Z",
            finished_at="2026-11-23T00:31:00Z",
            outcome="degraded",
            reason_codes=["degraded_no_model", "synthetic_fixture"],
            report_id="pre_20261123_v1",
            is_synthetic=True,
        ))
        record_ops_run(self.workspace, _sample_run(
            run_id="run_d1_post_fail",
            job_name="post_market",
            session_date="2026-11-23",
            scheduled_for="2026-11-23T08:30:00Z",
            started_at="2026-11-23T08:30:05Z",
            finished_at="2026-11-23T08:30:20Z",
            outcome="failed_network",
            reason_codes=["network_unreachable"],
            report_id=None,
            is_synthetic=False,
        ))
        # A future catchup run finished AFTER evaluated_at must NOT be visible at earlier now_utc!
        record_ops_run(self.workspace, _sample_run(
            run_id="run_d1_post_future_catchup",
            job_name="post_market",
            session_date="2026-11-23",
            scheduled_for="2026-11-23T08:30:00Z",
            started_at="2026-11-24T05:00:00Z",
            finished_at="2026-11-24T05:01:00Z",
            outcome="degraded",
            reason_codes=["degraded_no_model", "retrospective_catchup", "synthetic_fixture"],
            report_id="post_20261123_catchup",
            is_synthetic=True,
        ))

        # Evaluate at 2026-11-24T01:00:00Z (= 2026-11-24 09:00 Asia/Shanghai):
        # Due slots: 11-23 pre (done), 11-23 post (missed: previous_network_failure),
        #            11-24 pre (missed: offline_or_missed).
        # Future slot 11-24 post (08:30Z = 16:30 Asia/Shanghai) must NOT be included!
        plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-24", "2026-11-23"],
            now_utc="2026-11-24T01:00:00Z",
            display_timezone="Asia/Shanghai",
            pre_market_local="08:30",
            post_market_local="16:30",
        )
        validate_ops_recovery_plan(plan)
        self.assertEqual(plan["scheduled_slots_checked"], 3)
        self.assertEqual(plan["completed_slots"], 1)
        self.assertEqual(plan["missed_slots"], 2)
        self.assertFalse(plan["auto_execute"])
        self.assertEqual(
            [(a["market_session_date"], a["job_name"], a["miss_reason"], a["last_failed_run_id"])
             for a in plan["pending_recovery_actions"]],
            [
                ("2026-11-23", "post_market", "previous_network_failure", "run_d1_post_fail"),
                ("2026-11-24", "pre_market", "offline_or_missed", None),
            ],
        )

        # At 2026-11-24T06:00:00Z, the catchup run at 05:01Z IS visible, so 11-23 post is completed.
        later_plan = plan_missed_runs(
            self.workspace,
            scheduled_dates=["2026-11-23", "2026-11-24"],
            now_utc="2026-11-24T06:00:00Z",
        )
        self.assertEqual(later_plan["completed_slots"], 2)
        self.assertEqual(later_plan["missed_slots"], 1)

    def test_windows_task_template_is_dry_run_safe_xml_and_idempotent(self):
        out_xml = self.workspace / "templates" / "pre_market.xml"
        res = render_windows_task_template(
            job_name="pre_market",
            task_name="market_intel_pre",
            trigger_local_time="08:30",
            display_timezone="Asia/Shanghai",
            workspace_rel="data/live",
            start_date="2026-11-24",
            output_path=out_xml,
        )
        self.assertFalse(res["auto_installed"])
        self.assertTrue(res["dry_run_template_only"])
        self.assertFalse(res["enabled_in_template"])
        self.assertTrue(out_xml.is_file())
        root = ET.fromstring(res["xml"])
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns), "IgnoreNew")
        self.assertEqual(root.findtext("t:Settings/t:Enabled", namespaces=ns), "false")
        self.assertEqual(root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns), "%MARKET_INTEL_PYTHON%")

        # Idempotent same output succeeds; conflicting output rejected.
        render_windows_task_template(
            job_name="pre_market",
            task_name="market_intel_pre",
            trigger_local_time="08:30",
            display_timezone="Asia/Shanghai",
            workspace_rel="data/live",
            start_date="2026-11-24",
            output_path=out_xml,
        )
        with self.assertRaisesRegex(ValueError, "template_output_conflict"):
            render_windows_task_template(
                job_name="post_market",
                task_name="market_intel_pre",
                trigger_local_time="16:30",
                workspace_rel="data/live",
                output_path=out_xml,
            )

    def test_contract_validators_reject_forged_payloads(self):
        bad_run = _sample_run(outcome="succeeded", reason_codes=["normal_completion", "degraded_no_model"])
        with self.assertRaises(ContractError):
            validate_ops_run_record(bad_run)

        bad_lock = {
            "schema_version": "ops-lock/0.1",
            "lock_id": "lock_1",
            "job_name": "pre_market",
            "run_id": "run_1",
            "workspace_sha256": "a" * 64,
            "pid": 1234,
            "acquired_at": "2026-11-23T00:00:00Z",
            "expires_at": "2026-11-23T00:10:00Z",
            "ttl_seconds": 300,  # mismatch with 600s delta
            "status": "active",
            "recovered_stale_lock_id": None,
        }
        with self.assertRaises(ContractError):
            validate_ops_lock(bad_lock)

    def test_cli_end_to_end_ops_roundtrip(self):
        def run_cli(*argv):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli_main(list(argv))
            return code, out.getvalue(), err.getvalue()

        code, out, _ = run_cli(
            "ops-lock-acquire",
            "--workspace", str(self.workspace),
            "--job", "pre_market",
            "--run-id", "cli_run_1",
            "--lock-id", "cli_lock_1",
            "--ttl-seconds", "300",
            "--now", "2026-11-23T00:30:00Z",
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["acquired"])

        # Concurrent acquire returns exit code 2 (locked)
        code2, out2, _ = run_cli(
            "ops-lock-acquire",
            "--workspace", str(self.workspace),
            "--job", "pre_market",
            "--run-id", "cli_run_2",
            "--now", "2026-11-23T00:31:00Z",
        )
        self.assertEqual(code2, 2)
        self.assertEqual(json.loads(out2)["status"], "locked")

        # Record a run via CLI
        rec_file = self.workspace / "run1.json"
        rec_file.write_text(json.dumps(_sample_run(run_id="cli_run_1")), encoding="utf-8")
        code3, out3, _ = run_cli("ops-record-run", "--workspace", str(self.workspace), "--input", str(rec_file))
        self.assertEqual(code3, 0)
        self.assertEqual(json.loads(out3)["status"], "recorded")

        # Release lock via CLI
        code4, out4, _ = run_cli("ops-lock-release", "--workspace", str(self.workspace), "--lock-id", "cli_lock_1")
        self.assertEqual(code4, 0)
        self.assertEqual(json.loads(out4)["status"], "released")

        # Plan recovery via CLI
        code5, out5, _ = run_cli(
            "ops-plan-recovery",
            "--workspace", str(self.workspace),
            "--session-dates", "2026-11-23",
            "--now", "2026-11-23T09:00:00Z",
        )
        self.assertEqual(code5, 0)
        plan = json.loads(out5)
        self.assertEqual(plan["completed_slots"], 1)
        self.assertEqual(plan["missed_slots"], 1)

        # Render template via CLI
        code6, out6, _ = run_cli(
            "ops-render-task-template",
            "--job", "pre_market",
            "--task-name", "cli_pre_task",
            "--trigger-time", "08:30",
        )
        self.assertEqual(code6, 0)
        self.assertFalse(json.loads(out6)["auto_installed"])


if __name__ == "__main__":
    unittest.main()
