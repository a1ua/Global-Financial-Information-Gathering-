import copy
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from market_intel.cli import main as cli_main
from market_intel.contracts import ContractError
from market_intel.contracts.session_brief import validate_session_brief_manifest
from market_intel.offline import ingest_bundle, ingest_fixture
from market_intel.report.session_brief import (
    render_session_brief,
    replay_session_brief,
    verify_session_brief,
)
from market_intel.store import connect


def _demo_bundle():
    return json.loads(files("market_intel").joinpath("fixtures/demo.json").read_text(encoding="utf-8"))


def _make_bundle(
    *,
    suffix,
    available_at="2026-11-06T00:06:00Z",
    category="policy",
    title="合成测试标题",
    text="示例公告正文：支持先进制造业发展。",
    is_synthetic=True,
    source_id="fixture_official",
    storage_policy="full_text_fixture",
):
    if storage_policy == "metadata_only":
        text = title
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    raw_id = f"raw_{suffix}_v1"
    event_id = f"event_{suffix}"
    event_ver_id = f"event_{suffix}_v1"
    ev_id = f"evidence_{suffix}_v1"
    return {
        "raw": {
            "schema_version": "raw-item/0.1",
            "raw_item_id": raw_id,
            "source_id": source_id,
            "source_config_version": "sources-demo-1",
            "source_item_key": f"key-{suffix}",
            "original_url": f"https://example.com/items/{suffix}",
            "canonical_url": f"https://example.com/items/{suffix}",
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
            "storage_policy": storage_policy,
            "content_ref": f"raw/{sha}.txt",
            "content_sha256": sha,
            "normalized_text": text,
            "normalization_version": "text-normalize/0.1",
            "supersedes_raw_item_id": None,
            "is_synthetic": is_synthetic,
        },
        "event": {
            "schema_version": "event-version/0.1",
            "event_id": event_id,
            "event_version_id": event_ver_id,
            "version": 1,
            "title": title,
            "fact_summary": text,
            "category": category,
            "markets": ["A"],
            "entities": [],
            "evidence_ids": [ev_id],
            "input_raw_item_ids": [raw_id],
            "extraction_method": "fixture" if is_synthetic else "rule",
            "extractor_version": "fixture-extractor/0.1",
            "extraction_quality": "validated_fixture" if is_synthetic else "metadata_only",
            "processed_at": available_at,
            "available_at": available_at,
            "supersedes_event_version_id": None,
            "is_synthetic": is_synthetic,
        },
        "evidence": {
            "schema_version": "evidence/0.1",
            "evidence_id": ev_id,
            "event_version_id": event_ver_id,
            "raw_item_id": raw_id,
            "relation": "supports" if is_synthetic else "reports",
            "claim_key": "fact_summary",
            "normalization_version": "text-normalize/0.1",
            "locator": {
                "field": "normalized_text",
                "offset_unit": "unicode_code_point",
                "start": 0,
                "end": len(text),
            },
            "quote": text,
            "validation_status": "exact_quote_match",
            "available_at": available_at,
            "is_synthetic": is_synthetic,
        },
    }


class SessionBriefTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        self.db = connect(self.workspace / "market.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_render_and_verify_pre_market_dual_templates(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_20261106_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="run_20261106_01",
        )
        html_text = (out / "brief.html").read_text(encoding="utf-8")
        md_text = (out / "brief.md").read_text(encoding="utf-8")
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

        validate_session_brief_manifest(manifest, expected_report_id="pre_20261106_v1")
        self.assertEqual(manifest["report_type"], "pre_market")
        self.assertEqual(manifest["market_session_date"], "2026-11-06")
        self.assertEqual(manifest["run_id"], "run_20261106_01")
        self.assertEqual(manifest["status"], "degraded")
        self.assertIsNone(manifest["market_data_as_of"])
        self.assertEqual(manifest["sections"]["facts_count"], 1)
        self.assertEqual(manifest["sections"]["interpretations_count"], 0)
        self.assertGreaterEqual(manifest["sections"]["watch_items_count"], 1)
        self.assertEqual(manifest["artifact_refs"], ["brief.html", "brief.md"])

        for doc in (html_text, md_text):
            self.assertIn("2026-11-06T00:30:00Z", doc)
            self.assertIn("run_20261106_01", doc)
            self.assertIn("degraded", doc)
            self.assertIn("model_unavailable", doc)
            self.assertIn("market_data_unavailable", doc)
            self.assertIn("合成机构发布支持文件", doc)
            self.assertIn("一、已核验事实（Facts）", doc)
            self.assertIn("二、模型解读（Interpretations）", doc)
            self.assertIn("三、观察事项与缺口（Watch Items）", doc)

        verified = verify_session_brief(self.db, self.workspace, "pre_20261106_v1")
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["events"], 1)
        self.assertTrue(verified["is_synthetic"])

    def test_strict_cutoff_excludes_future_and_avoids_filling_empty_topics(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:05:59Z",
            report_id="pre_empty_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            default_synthetic=True,
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sections"]["facts_count"], 0)
        self.assertEqual(manifest["source_config_version"], "")
        self.assertIn("截点前无可用事件，不强行填充主题", (out / "brief.html").read_text(encoding="utf-8"))
        self.assertIn("截点前无可用事件，不强行填充主题", (out / "brief.md").read_text(encoding="utf-8"))
        verified = verify_session_brief(self.db, self.workspace, "pre_empty_v1")
        self.assertEqual(verified["events"], 0)

    def test_non_synthetic_requires_committed_receipt_at_or_before_cutoff(self):
        real_bundle = _make_bundle(
            suffix="real_fed_1",
            available_at="2026-11-06T00:06:00Z",
            category="macro",
            title="Fed metadata release",
            text="Fed metadata release",
            is_synthetic=False,
            source_id="fed_press_all",
            storage_policy="metadata_only",
        )
        ingest_bundle(self.db, real_bundle, self.workspace)
        committed_at = self.db.execute(
            "SELECT committed_at FROM availability_receipts WHERE event_version_id=?",
            ("event_real_fed_1_v1",),
        ).fetchone()[0]
        # Cutoff after event.available_at but strictly before receipt committed_at -> excluded.
        early = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="post_early_v1",
            report_type="post_market",
            market_session_date="2026-11-06",
        )
        early_manifest = json.loads((early / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(early_manifest["sections"]["facts_count"], 0)
        self.assertFalse(early_manifest["is_synthetic"])

        # Cutoff equal to committed_at -> included.
        later = render_session_brief(
            self.db,
            self.workspace,
            cutoff=committed_at,
            report_id="post_later_v1",
            report_type="post_market",
            market_session_date="2026-11-06",
        )
        later_manifest = json.loads((later / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(later_manifest["sections"]["facts_count"], 1)
        self.assertFalse(later_manifest["is_synthetic"])
        self.assertIn("source_metadata_only", later_manifest["reason_codes"])
        self.assertIn("美联储 · 官方来源链接", (later / "brief.md").read_text(encoding="utf-8"))
        verified = verify_session_brief(self.db, self.workspace, "post_later_v1")
        self.assertEqual(verified["events"], 1)

    def test_corrupt_evidence_refuses_publication_and_leaves_no_staging(self):
        bundle = _demo_bundle()
        ingest_fixture(self.db, bundle, self.workspace)
        content_file = self.workspace / bundle["raw"]["content_ref"]
        content_file.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "report_evidence_corrupt"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T00:30:00Z",
                report_id="pre_corrupt_v1",
                report_type="pre_market",
                market_session_date="2026-11-06",
            )
        reports_dir = self.workspace / "reports"
        self.assertFalse((reports_dir / "pre_corrupt_v1").exists())
        if reports_dir.exists():
            self.assertEqual(list(reports_dir.glob(".staging-*")), [])

    def test_supplement_revision_preserves_old_version_and_verifies_chain(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        v1 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_20261106_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        v1_html_before = (v1 / "brief.html").read_bytes()
        v1_md_before = (v1 / "brief.md").read_bytes()
        v1_manifest_before = (v1 / "manifest.json").read_bytes()

        second = _make_bundle(
            suffix="supp_002",
            available_at="2026-11-06T00:45:00Z",
            category="macro",
            title="合成补充宏观事件",
            text="补充公告：发布月度宏观数据。",
        )
        ingest_fixture(self.db, second, self.workspace)

        v2 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T01:00:00Z",
            report_id="pre_20261106_v2",
            report_type="pre_market",
            market_session_date="2026-11-06",
            supersedes_report_id="pre_20261106_v1",
        )
        self.assertEqual((v1 / "brief.html").read_bytes(), v1_html_before)
        self.assertEqual((v1 / "brief.md").read_bytes(), v1_md_before)
        self.assertEqual((v1 / "manifest.json").read_bytes(), v1_manifest_before)

        v2_manifest = json.loads((v2 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(v2_manifest["supersedes_report_id"], "pre_20261106_v1")
        self.assertIn("supplement_revision", v2_manifest["reason_codes"])
        self.assertEqual(v2_manifest["sections"]["facts_count"], 2)
        self.assertIn("pre_20261106_v1", (v2 / "brief.md").read_text(encoding="utf-8"))

        verified = verify_session_brief(self.db, self.workspace, "pre_20261106_v2")
        self.assertEqual(verified["supersedes_report_id"], "pre_20261106_v1")
        self.assertEqual(verified["events"], 2)

        # Tampering the superseded artifact must fail chain verification on v2.
        (v1 / "brief.md").write_text("tampered v1", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "superseded_artifact_corrupt"):
            verify_session_brief(self.db, self.workspace, "pre_20261106_v2")

    def test_supplement_rejects_scope_mismatch_and_self_reference(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_20261106_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        with self.assertRaisesRegex(ValueError, "supplement_scope_mismatch"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T01:00:00Z",
                report_id="post_20261106_v2",
                report_type="post_market",
                market_session_date="2026-11-06",
                supersedes_report_id="pre_20261106_v1",
            )
        with self.assertRaisesRegex(ValueError, "supplement_scope_mismatch"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T01:00:00Z",
                report_id="pre_20261109_v2",
                report_type="pre_market",
                market_session_date="2026-11-09",
                supersedes_report_id="pre_20261106_v1",
            )
        with self.assertRaisesRegex(ValueError, "supplement_self_reference"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T01:00:00Z",
                report_id="pre_self",
                report_type="pre_market",
                market_session_date="2026-11-06",
                supersedes_report_id="pre_self",
            )

    def test_idempotent_publish_and_conflict_refusal_without_overwrite(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out1 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_20261106_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="run_1",
        )
        original_manifest = (out1 / "manifest.json").read_bytes()
        # Same inputs and metadata -> idempotent success.
        out2 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_20261106_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="run_1",
        )
        self.assertEqual(out1, out2)
        # Different run_id on same report_id -> conflict without overwriting.
        with self.assertRaisesRegex(ValueError, "published_report_conflict"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T00:30:00Z",
                report_id="pre_20261106_v1",
                report_type="pre_market",
                market_session_date="2026-11-06",
                run_id="run_2",
            )
        self.assertEqual((out1 / "manifest.json").read_bytes(), original_manifest)

    def test_verify_detects_html_or_markdown_tampering(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_tamper_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        orig_md = (out / "brief.md").read_bytes()
        (out / "brief.md").write_bytes(orig_md + b" ")
        with self.assertRaisesRegex(ValueError, "published_artifact_corrupt"):
            verify_session_brief(self.db, self.workspace, "pre_tamper_v1")
        (out / "brief.md").write_bytes(orig_md)

        orig_html = (out / "brief.html").read_bytes()
        (out / "brief.html").write_bytes(orig_html + b" ")
        with self.assertRaisesRegex(ValueError, "published_artifact_corrupt"):
            verify_session_brief(self.db, self.workspace, "pre_tamper_v1")

    def test_replay_reproduces_identical_dual_artifacts(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        src_dir = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_replay_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        dest_root = Path(self._tmp.name) / "replayed"
        replayed_dir = replay_session_brief(self.db, self.workspace, "pre_replay_v1", dest_root)
        self.assertEqual((src_dir / "brief.html").read_bytes(), (replayed_dir / "brief.html").read_bytes())
        self.assertEqual((src_dir / "brief.md").read_bytes(), (replayed_dir / "brief.md").read_bytes())

    def test_mixed_synthetic_and_real_data_marked_mixed(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        real_bundle = _make_bundle(
            suffix="real_mix_1",
            available_at="2026-11-06T00:06:00Z",
            category="macro",
            title="国家统计局统计信息标题",
            text="国家统计局统计信息标题",
            is_synthetic=False,
            source_id="nbs_releases",
            storage_policy="metadata_only",
        )
        ingest_bundle(self.db, real_bundle, self.workspace)
        committed_at = self.db.execute(
            "SELECT committed_at FROM availability_receipts WHERE event_version_id=?",
            ("event_real_mix_1_v1",),
        ).fetchone()[0]
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff=committed_at,
            report_id="pre_mixed_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["is_synthetic"])
        self.assertIn("mixed_test_data", manifest["reason_codes"])
        verified = verify_session_brief(self.db, self.workspace, "pre_mixed_v1")
        self.assertEqual(verified["events"], 2)

    def test_manifest_validator_enforces_degraded_and_zero_interpretations(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="pre_contract_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        base = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

        bad_status = copy.deepcopy(base)
        bad_status["status"] = "complete"
        with self.assertRaises(ContractError):
            validate_session_brief_manifest(bad_status)

        bad_interp = copy.deepcopy(base)
        bad_interp["sections"]["interpretations_count"] = 1
        with self.assertRaises(ContractError):
            validate_session_brief_manifest(bad_interp)

        bad_market = copy.deepcopy(base)
        bad_market["market_data_as_of"] = "2026-11-06T00:30:00Z"
        with self.assertRaises(ContractError):
            validate_session_brief_manifest(bad_market)

        bad_reason = copy.deepcopy(base)
        bad_reason["reason_codes"].append("supplement_revision")
        with self.assertRaises(ContractError):
            validate_session_brief_manifest(bad_reason)

    def test_cli_session_brief_verify_and_replay_roundtrip(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        self.db.close()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli_main([
                "session-brief",
                "--workspace", str(self.workspace),
                "--report-type", "pre_market",
                "--session-date", "2026-11-06",
                "--cutoff", "2026-11-06T00:30:00Z",
                "--report-id", "cli_pre_v1",
                "--run-id", "cli_run_01",
            ])
        self.assertEqual(rc, 0, stderr.getvalue())
        created = json.loads(stdout.getvalue())
        self.assertEqual(created["status"], "degraded")
        self.assertTrue(Path(created["html"]).is_file())
        self.assertTrue(Path(created["markdown"]).is_file())

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = cli_main([
                "verify-session-brief",
                "--workspace", str(self.workspace),
                "--report-id", "cli_pre_v1",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "verified")

        replay_dest = Path(self._tmp.name) / "cli_replay"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = cli_main([
                "replay-session-brief",
                "--workspace", str(self.workspace),
                "--report-id", "cli_pre_v1",
                "--destination", str(replay_dest),
            ])
        self.assertEqual(rc, 0)
        replayed = json.loads(stdout.getvalue())
        self.assertEqual(replayed["status"], "replayed")
        self.assertEqual(
            Path(created["markdown"]).read_bytes(),
            Path(replayed["markdown"]).read_bytes(),
        )

        # Invalid session date must exit 1 with structured error on stderr.
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli_main([
                "session-brief",
                "--workspace", str(self.workspace),
                "--report-type", "pre_market",
                "--session-date", "2026-02-30",
                "--cutoff", "2026-11-06T00:30:00Z",
                "--report-id", "cli_bad_date",
            ])
        self.assertEqual(rc, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["reason"], "invalid_market_session_date")
        # Re-open db so tearDown closes cleanly.
        self.db = connect(self.workspace / "market.db")


if __name__ == "__main__":
    unittest.main()
