"""Independent adversarial QA tests for Batch40 (B40-SESSION-BRIEF)."""

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.resources import files
from pathlib import Path

from market_intel.cli import main as cli_main
from market_intel.contracts import ContractError
from market_intel.contracts.session_brief import validate_session_brief_manifest
from market_intel.offline import ingest_fixture
from market_intel.report.session_brief import (
    _safe_file,
    render_session_brief,
    replay_session_brief,
    verify_session_brief,
)
from market_intel.store import connect, insert_immutable


def _demo_bundle():
    return json.loads(files("market_intel").joinpath("fixtures/demo.json").read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _make_bundle(
    *,
    suffix,
    event_id=None,
    version=1,
    raw_available_at="2026-11-06T00:06:00Z",
    event_available_at=None,
    evidence_available_at=None,
    category="policy",
    title="合成测试标题",
    text="示例公告正文：支持先进制造业发展。",
    quote=None,
    fact_summary=None,
    source_time_text="2026-11-06 08:00",
    time_parse_status="parsed",
    source_time_precision="minute",
    source_published_at="2026-11-06T00:00:00Z",
    source_published_date="2026-11-06",
    source_timezone="Asia/Shanghai",
    is_synthetic=True,
    source_id="fixture_official",
    source_config_version="sources-demo-1",
    storage_policy="full_text_fixture",
):
    event_available_at = raw_available_at if event_available_at is None else event_available_at
    evidence_available_at = raw_available_at if evidence_available_at is None else evidence_available_at
    if storage_policy == "metadata_only":
        text = title
    quote_val = text if quote is None else quote
    summary_val = text if fact_summary is None else fact_summary
    start_idx = text.index(quote_val)
    end_idx = start_idx + len(quote_val)
    sha = _sha256_text(text)
    raw_id = f"raw_{suffix}_v{version}"
    ev_logical_id = event_id or f"event_{suffix}"
    event_ver_id = f"{ev_logical_id}_v{version}"
    ev_id = f"evidence_{suffix}_v{version}"
    return {
        "raw": {
            "schema_version": "raw-item/0.1",
            "raw_item_id": raw_id,
            "source_id": source_id,
            "source_config_version": source_config_version,
            "source_item_key": f"key-{suffix}-v{version}",
            "original_url": f"https://example.com/items/{suffix}/v{version}",
            "canonical_url": f"https://example.com/items/{suffix}/v{version}",
            "source_tier": "primary",
            "title": title,
            "source_time_text": source_time_text,
            "source_timezone": source_timezone,
            "source_time_precision": source_time_precision,
            "time_parse_status": time_parse_status,
            "source_published_at": source_published_at,
            "source_published_date": source_published_date,
            "first_seen_at": "2026-11-06T00:05:00Z",
            "fetched_at": "2026-11-06T00:05:02Z",
            "persisted_at": raw_available_at,
            "available_at": raw_available_at,
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
            "event_id": ev_logical_id,
            "event_version_id": event_ver_id,
            "version": version,
            "title": title,
            "fact_summary": summary_val,
            "category": category,
            "markets": ["A"],
            "entities": [],
            "evidence_ids": [ev_id],
            "input_raw_item_ids": [raw_id],
            "extraction_method": "fixture" if is_synthetic else "rule",
            "extractor_version": "fixture-extractor/0.1",
            "extraction_quality": "validated_fixture" if is_synthetic else "metadata_only",
            "processed_at": event_available_at,
            "available_at": event_available_at,
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
                "start": start_idx,
                "end": end_idx,
            },
            "quote": quote_val,
            "validation_status": "exact_quote_match",
            "available_at": evidence_available_at,
            "is_synthetic": is_synthetic,
        },
    }


def _ingest_with_explicit_receipt(db, bundle, workspace, *, committed_at):
    """Persist a validated bundle with an explicit committed_at (or None to omit receipt)."""
    raw, event, evidence = bundle["raw"], bundle["event"], bundle["evidence"]
    path = Path(workspace) / raw["content_ref"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(raw["normalized_text"], encoding="utf-8", newline="")
    with db:
        insert_immutable(db, "raw_items", "raw_item_id", raw)
        insert_immutable(db, "event_versions", "event_version_id", event)
        insert_immutable(db, "evidence", "evidence_id", evidence)
        if committed_at is not None:
            db.execute(
                "INSERT INTO availability_receipts VALUES (?,?)",
                (event["event_version_id"], committed_at),
            )


def _valid_manifest(*, is_synthetic=True, supersedes=None, report_type="pre_market", session_date="2026-11-06"):
    inputs = {
        "raw_item_ids": ["raw_1"],
        "event_version_ids": ["event_1_v1"],
        "evidence_ids": ["evidence_1_v1"],
        "prediction_ids": [],
        "market_snapshot_id": None,
    }
    if is_synthetic:
        reasons = ["synthetic_fixture", "retrospective", "model_unavailable", "market_data_unavailable"]
    else:
        reasons = [
            "source_metadata_only",
            "content_support_not_reviewed",
            "model_unavailable",
            "market_data_unavailable",
        ]
    if supersedes is not None:
        reasons.append("supplement_revision")
    return {
        "schema_version": "session-brief-manifest/0.1",
        "report_id": "qa_pre_v1",
        "run_id": "qa_run_v1",
        "report_type": report_type,
        "market_session_date": session_date,
        "display_timezone": "Asia/Shanghai",
        "information_cutoff": "2026-11-06T00:30:00Z",
        "generated_at": "2026-11-06T00:30:00Z",
        "status": "degraded",
        "reason_codes": reasons,
        "input_manifest": inputs,
        "input_manifest_sha256": _sha256_text(_canonical(inputs)),
        "canonical_json_version": "python-json-sorted-utf8/0.1",
        "source_config_version": "sources-demo-1",
        "rules_version": "strict-cutoff-session/0.1",
        "template_version": "session-brief/0.1",
        "renderer_version": "session-brief/0.1",
        "market_data_as_of": None,
        "citation_check": "passed",
        "content_support_check": "not_performed",
        "sections": {
            "facts_count": 1,
            "interpretations_count": 0,
            "watch_items_count": len(reasons),
        },
        "artifact_refs": ["brief.html", "brief.md"],
        "artifact_sha256": {
            "brief.html": "a" * 64,
            "brief.md": "b" * 64,
        },
        "supersedes_report_id": supersedes,
        "is_synthetic": is_synthetic,
    }


class _WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self.db = connect(self.workspace / "market.db")

    def tearDown(self):
        try:
            self.db.close()
        finally:
            self._tmp.cleanup()


class CutoffAndAntiLookaheadQATests(_WorkspaceTestCase):
    def test_one_microsecond_after_cutoff_excluded_for_raw_event_and_evidence(self):
        cutoff = "2026-11-06T00:30:00Z"
        at_cutoff = _make_bundle(
            suffix="at_boundary",
            raw_available_at="2026-11-06T00:30:00Z",
            event_available_at="2026-11-06T00:30:00Z",
            evidence_available_at="2026-11-06T00:30:00Z",
            title="边界可见事件",
            text="精确等于截点的公告内容。",
        )
        raw_late = _make_bundle(
            suffix="raw_late_1us",
            raw_available_at="2026-11-06T00:30:00.000001Z",
            event_available_at="2026-11-06T00:30:00.000001Z",
            evidence_available_at="2026-11-06T00:30:00.000001Z",
            title="RAW晚1微秒不可见",
            text="RAW晚1微秒正文。",
        )
        event_late = _make_bundle(
            suffix="event_late_1us",
            raw_available_at="2026-11-06T00:30:00Z",
            event_available_at="2026-11-06T00:30:00.000001Z",
            evidence_available_at="2026-11-06T00:30:00Z",
            title="EVENT晚1微秒不可见",
            text="EVENT晚1微秒正文。",
        )
        evidence_late = _make_bundle(
            suffix="ev_late_1us",
            raw_available_at="2026-11-06T00:30:00Z",
            event_available_at="2026-11-06T00:30:00Z",
            evidence_available_at="2026-11-06T00:30:00.000001Z",
            title="EVIDENCE晚1微秒不可见",
            text="EVIDENCE晚1微秒正文。",
        )
        for bundle in (at_cutoff, raw_late, event_late, evidence_late):
            ingest_fixture(self.db, bundle, self.workspace)

        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff=cutoff,
            report_id="qa_1us_cutoff",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["input_manifest"]["event_version_ids"], ["event_at_boundary_v1"])
        self.assertEqual(manifest["sections"]["facts_count"], 1)

        for doc in ((out / "brief.html").read_text(encoding="utf-8"), (out / "brief.md").read_text(encoding="utf-8")):
            self.assertIn("边界可见事件", doc)
            self.assertNotIn("RAW晚1微秒不可见", doc)
            self.assertNotIn("EVENT晚1微秒不可见", doc)
            self.assertNotIn("EVIDENCE晚1微秒不可见", doc)

    def test_same_event_higher_version_one_microsecond_after_cutoff_not_leaked(self):
        v1 = _make_bundle(
            suffix="ver_a",
            event_id="event_shared",
            version=1,
            raw_available_at="2026-11-06T00:30:00Z",
            title="事件初版V1",
            text="初版正文V1。",
        )
        v2 = _make_bundle(
            suffix="ver_b",
            event_id="event_shared",
            version=2,
            raw_available_at="2026-11-06T00:30:00.000001Z",
            title="事件修订版V2",
            text="修订版正文V2。",
        )
        ingest_fixture(self.db, v1, self.workspace)
        ingest_fixture(self.db, v2, self.workspace)

        out_v1 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_ver_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        m1 = json.loads((out_v1 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m1["input_manifest"]["event_version_ids"], ["event_shared_v1"])
        self.assertNotIn("事件修订版V2", (out_v1 / "brief.md").read_text(encoding="utf-8"))
        self.assertNotIn("事件修订版V2", (out_v1 / "brief.html").read_text(encoding="utf-8"))

        out_v2 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00.000001Z",
            report_id="qa_ver_v2",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        m2 = json.loads((out_v2 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m2["input_manifest"]["event_version_ids"], ["event_shared_v2"])
        self.assertEqual(m2["sections"]["facts_count"], 1)

    def test_non_synthetic_missing_receipt_or_committed_one_microsecond_after_cutoff_excluded(self):
        missing_receipt = _make_bundle(
            suffix="real_no_rcpt",
            raw_available_at="2026-11-06T00:10:00Z",
            category="macro",
            title="Real item missing receipt",
            text="Real item missing receipt",
            is_synthetic=False,
            source_id="fed_press_all",
            storage_policy="metadata_only",
        )
        late_receipt = _make_bundle(
            suffix="real_late_rcpt",
            raw_available_at="2026-11-06T00:10:00Z",
            category="macro",
            title="Real item receipt 1us late",
            text="Real item receipt 1us late",
            is_synthetic=False,
            source_id="fed_press_all",
            storage_policy="metadata_only",
        )
        exact_receipt = _make_bundle(
            suffix="real_exact_rcpt",
            raw_available_at="2026-11-06T00:10:00Z",
            category="macro",
            title="Real item receipt exact cutoff",
            text="Real item receipt exact cutoff",
            is_synthetic=False,
            source_id="nbs_releases",
            storage_policy="metadata_only",
        )
        _ingest_with_explicit_receipt(self.db, missing_receipt, self.workspace, committed_at=None)
        _ingest_with_explicit_receipt(
            self.db, late_receipt, self.workspace, committed_at="2026-11-06T00:30:00.000001Z"
        )
        _ingest_with_explicit_receipt(
            self.db, exact_receipt, self.workspace, committed_at="2026-11-06T00:30:00Z"
        )

        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_receipt_boundary",
            report_type="post_market",
            market_session_date="2026-11-06",
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["input_manifest"]["event_version_ids"], ["event_real_exact_rcpt_v1"])
        self.assertFalse(manifest["is_synthetic"])
        for doc in ((out / "brief.html").read_text(encoding="utf-8"), (out / "brief.md").read_text(encoding="utf-8")):
            self.assertIn("Real item receipt exact cutoff", doc)
            self.assertNotIn("Real item missing receipt", doc)
            self.assertNotIn("Real item receipt 1us late", doc)

        # Moving cutoff forward by 1 microsecond includes late_receipt, still excludes missing_receipt.
        out_plus = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00.000001Z",
            report_id="qa_receipt_boundary_plus1us",
            report_type="post_market",
            market_session_date="2026-11-06",
        )
        manifest_plus = json.loads((out_plus / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest_plus["input_manifest"]["event_version_ids"],
            ["event_real_exact_rcpt_v1", "event_real_late_rcpt_v1"],
        )

    def test_empty_cutoff_never_peeks_past_cutoff_for_synthetic_flag_or_topics(self):
        future_syn = _make_bundle(
            suffix="future_syn",
            raw_available_at="2026-11-06T00:30:00Z",
            title="未来合成事件标题",
            text="未来合成事件正文。",
            is_synthetic=True,
        )
        ingest_fixture(self.db, future_syn, self.workspace)
        # Corrupt the future content file: an earlier cutoff must not inspect or leak it.
        (self.workspace / future_syn["raw"]["content_ref"]).write_text("corrupt-future", encoding="utf-8")

        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:29:59.999999Z",
            report_id="qa_empty_non_syn",
            report_type="pre_market",
            market_session_date="2026-11-06",
            default_synthetic=False,
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["is_synthetic"])
        self.assertEqual(manifest["sections"]["facts_count"], 0)
        self.assertEqual(manifest["source_config_version"], "")
        self.assertNotIn("synthetic_fixture", manifest["reason_codes"])

        for doc in ((out / "brief.html").read_text(encoding="utf-8"), (out / "brief.md").read_text(encoding="utf-8")):
            self.assertIn("截点前无可用事件，不强行填充主题", doc)
            self.assertNotIn("未来合成事件标题", doc)
            self.assertNotIn("政策监管 (policy)", doc)

        # Also verify opposite direction: future non-synthetic record with default_synthetic=True stays synthetic.
        ws2 = self.root / "ws2"
        ws2.mkdir()
        db2 = connect(ws2 / "market.db")
        try:
            future_real = _make_bundle(
                suffix="future_real",
                raw_available_at="2026-11-06T00:30:00Z",
                title="Future real title",
                text="Future real title",
                is_synthetic=False,
                source_id="fed_press_all",
                storage_policy="metadata_only",
            )
            _ingest_with_explicit_receipt(db2, future_real, ws2, committed_at="2026-11-06T00:30:00Z")
            out2 = render_session_brief(
                db2,
                ws2,
                cutoff="2026-11-06T00:29:59.999999Z",
                report_id="qa_empty_syn",
                report_type="post_market",
                market_session_date="2026-11-06",
                default_synthetic=True,
            )
            m2 = json.loads((out2 / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(m2["is_synthetic"])
            self.assertEqual(m2["sections"]["facts_count"], 0)
            self.assertIn("synthetic_fixture", m2["reason_codes"])
        finally:
            db2.close()


class ContractAndAntiForgeryQATests(_WorkspaceTestCase):
    def test_validate_manifest_strict_rejections_and_no_mutation(self):
        for synthetic in (True, False):
            m = _valid_manifest(is_synthetic=synthetic, session_date="2024-02-29")
            before = copy.deepcopy(m)
            validate_session_brief_manifest(m, expected_report_id="qa_pre_v1")
            self.assertEqual(m, before)

        mutations = [
            ("non_dict", lambda _: []),
            ("missing_field", lambda m: m.pop("status")),
            ("extra_field", lambda m: m.__setitem__("extra", 1)),
            ("bad_status", lambda m: m.__setitem__("status", "complete")),
            ("interpretations_1", lambda m: m["sections"].__setitem__("interpretations_count", 1)),
            ("interpretations_bool", lambda m: m["sections"].__setitem__("interpretations_count", False)),
            ("watch_zero", lambda m: m["sections"].__setitem__("watch_items_count", 0)),
            ("watch_mismatch_high", lambda m: m["sections"].__setitem__("watch_items_count", 9)),
            ("watch_bool", lambda m: m["sections"].__setitem__("watch_items_count", True)),
            ("facts_mismatch", lambda m: m["sections"].__setitem__("facts_count", 2)),
            ("sections_extra", lambda m: m["sections"].__setitem__("extra", 0)),
            ("market_data_not_none", lambda m: m.__setitem__("market_data_as_of", "2026-11-06T00:30:00Z")),
            ("invalid_tz_unknown", lambda m: m.__setitem__("display_timezone", "Not/AZone")),
            ("invalid_tz_traversal", lambda m: m.__setitem__("display_timezone", "../UTC")),
            ("invalid_tz_null", lambda m: m.__setitem__("display_timezone", "Asia/Shanghai\x00")),
            ("invalid_tz_empty", lambda m: m.__setitem__("display_timezone", "")),
            ("invalid_leap_2026_02_29", lambda m: m.__setitem__("market_session_date", "2026-02-29")),
            ("invalid_date_2026_02_30", lambda m: m.__setitem__("market_session_date", "2026-02-30")),
            ("invalid_date_2026_13_01", lambda m: m.__setitem__("market_session_date", "2026-13-01")),
            ("invalid_date_format", lambda m: m.__setitem__("market_session_date", "2026-11-6")),
            ("generated_before_cutoff_1us", lambda m: m.__setitem__("generated_at", "2026-11-06T00:29:59.999999Z")),
            ("cutoff_non_z_offset", lambda m: m.__setitem__("information_cutoff", "2026-11-06T00:30:00+00:00")),
            ("self_supersedes", lambda m: m.__setitem__("supersedes_report_id", m["report_id"])),
            ("artifact_refs_swapped", lambda m: m.__setitem__("artifact_refs", ["brief.md", "brief.html"])),
            ("artifact_refs_missing", lambda m: m.__setitem__("artifact_refs", ["brief.html"])),
            ("artifact_refs_traversal", lambda m: m.__setitem__("artifact_refs", ["../brief.html", "brief.md"])),
            ("artifact_sha_upper", lambda m: m["artifact_sha256"].__setitem__("brief.html", "A" * 64)),
            ("artifact_sha_short", lambda m: m["artifact_sha256"].__setitem__("brief.md", "b" * 63)),
            ("artifact_sha_extra", lambda m: m["artifact_sha256"].__setitem__("extra.txt", "c" * 64)),
            ("artifact_sha_missing", lambda m: m["artifact_sha256"].pop("brief.md")),
            ("prediction_ids_nonempty", lambda m: m["input_manifest"].__setitem__("prediction_ids", ["p1"])),
            ("market_snapshot_nonnull", lambda m: m["input_manifest"].__setitem__("market_snapshot_id", "snap1")),
            ("input_manifest_extra", lambda m: m["input_manifest"].__setitem__("extra", [])),
            ("input_hash_mismatch", lambda m: m.__setitem__("input_manifest_sha256", "0" * 64)),
            ("is_synthetic_int", lambda m: m.__setitem__("is_synthetic", 1)),
            ("duplicate_reason", lambda m: m["reason_codes"].append("model_unavailable")),
            ("spurious_supplement_reason", lambda m: m["reason_codes"].append("supplement_revision")),
            ("missing_supplement_reason", lambda m: m.__setitem__("supersedes_report_id", "qa_pre_v0")),
            ("mixed_on_synthetic", lambda m: m["reason_codes"].append("mixed_test_data")),
            ("bad_report_type", lambda m: m.__setitem__("report_type", "intraday")),
            ("bad_citation_check", lambda m: m.__setitem__("citation_check", "failed")),
            ("bad_content_support", lambda m: m.__setitem__("content_support_check", "verified")),
        ]
        for name, mutator in mutations:
            with self.subTest(case=name):
                candidate = _valid_manifest()
                res = mutator(candidate)
                target = res if name == "non_dict" else candidate
                with self.assertRaises(ContractError):
                    validate_session_brief_manifest(target)

    def test_validate_manifest_rejects_whitespace_padded_timezone(self):
        # On Windows NTFS, ZoneInfo("UTC ") / ZoneInfo("UTC.") can resolve due to trailing
        # space/dot stripping, which breaks cross-platform determinism on POSIX.
        for bad_tz in ("UTC ", " UTC", "Asia/Shanghai ", "UTC.", "Asia/Shanghai.", r"Asia\Shanghai"):
            with self.subTest(tz=bad_tz):
                candidate = _valid_manifest()
                candidate["display_timezone"] = bad_tz
                with self.assertRaises(ContractError):
                    validate_session_brief_manifest(candidate)

    def test_verify_and_replay_reject_duplicate_json_keys_and_nonfinite_numbers(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_json_strict",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        orig_text = (out / "manifest.json").read_text(encoding="utf-8")
        dest = self.root / "replay_bad_json"

        # Duplicate JSON key
        dup_text = orig_text[:-1] + ',"status":"degraded"}'
        (out / "manifest.json").write_text(dup_text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            verify_session_brief(self.db, self.workspace, "qa_json_strict")
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            replay_session_brief(self.db, self.workspace, "qa_json_strict", dest)

        # Non-finite JSON constants (NaN / Infinity)
        for const in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=const):
                bad_num = orig_text.replace('"facts_count":1', f'"facts_count":{const}')
                (out / "manifest.json").write_text(bad_num, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "nonfinite_json"):
                    verify_session_brief(self.db, self.workspace, "qa_json_strict")
                with self.assertRaisesRegex(ValueError, "nonfinite_json"):
                    replay_session_brief(self.db, self.workspace, "qa_json_strict", dest)

    def test_html_escaping_neutralizes_script_and_special_chars(self):
        payload_title = '<script>alert("xss")</script> & <img src=x onerror=alert(1)>'
        payload_text = '正文 <script>alert(2)</script> "quoted" & \'single\''
        bundle = _make_bundle(
            suffix="html_xss",
            title=payload_title,
            text=payload_text,
            source_time_text="<script>alert(3)</script>",
            time_parse_status="missing",
            source_time_precision="unknown",
            source_published_at=None,
            source_published_date=None,
            source_timezone=None,
        )
        ingest_fixture(self.db, bundle, self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_html_escape",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        html_doc = (out / "brief.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", html_doc)
        self.assertNotIn("<img ", html_doc)
        self.assertIn("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;", html_doc)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", html_doc)
        self.assertIn("&lt;script&gt;alert(3)&lt;/script&gt;", html_doc)

    def test_markdown_injection_protection_in_title_summary_and_quote(self):
        malicious_title = (
            r"<script>alert(1)</script> [click](https://evil.example) "
            r"\[bypass\](https://evil.example)" + "\n## Fake Heading"
        )
        malicious_text = (
            "## 二、模型解读（Interpretations）\n"
            "<script>alert(2)</script>\n"
            "[phish](https://evil.example) ![track](https://evil.example/pixel.png)"
        )
        bundle = _make_bundle(
            suffix="md_inj",
            title=malicious_title,
            text=malicious_text,
        )
        ingest_fixture(self.db, bundle, self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_md_inject",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        md_doc = (out / "brief.md").read_text(encoding="utf-8")
        # 1. Raw HTML <script> tags must not survive unescaped into Markdown.
        with self.subTest(vector="raw_html_script_in_markdown"):
            self.assertNotIn("<script>", md_doc)
        # 2. Untrusted quote must not inject active Markdown links or remote tracking images.
        with self.subTest(vector="unescaped_link_and_image_in_quote"):
            self.assertNotIn("[phish](https://evil.example)", md_doc)
            self.assertNotIn("![track](https://evil.example/pixel.png)", md_doc)
        # 3. Backslash + bracket sequence in title must not produce an unescaped link (`\\[...\\](...)`).
        with self.subTest(vector="backslash_bracket_bypass_in_title"):
            self.assertNotIn(r"\\[bypass\\](https://evil.example)", md_doc)
        # 4. Untrusted fact_summary must not spoof a level-2 heading (`## 二、模型解读...`) inside Section 1.
        with self.subTest(vector="section_heading_spoof_in_fact_summary"):
            h2_lines = [line for line in md_doc.splitlines() if line.startswith("## ")]
            self.assertEqual(
                h2_lines,
                [
                    "## 元数据",
                    "## 一、已核验事实（Facts）",
                    "## 二、模型解读（Interpretations）",
                    "## 三、观察事项与缺口（Watch Items）",
                ],
            )


class ArchiveConflictAndSupplementQATests(_WorkspaceTestCase):
    def test_conflicting_report_id_never_overwrites_artifacts_or_leaves_staging(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_conflict_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="run_orig",
        )
        orig_files = {
            name: (out / name).read_bytes()
            for name in ("brief.html", "brief.md", "manifest.json")
        }

        conflicts = [
            {"run_id": "run_other"},
            {"cutoff": "2026-11-06T00:31:00Z"},
            {"report_type": "post_market"},
            {"market_session_date": "2026-11-07"},
            {"display_timezone": "UTC"},
        ]
        for overrides in conflicts:
            params = {
                "cutoff": "2026-11-06T00:30:00Z",
                "report_id": "qa_conflict_v1",
                "report_type": "pre_market",
                "market_session_date": "2026-11-06",
                "run_id": "run_orig",
                "display_timezone": "Asia/Shanghai",
            }
            params.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, "published_report_conflict"):
                    render_session_brief(self.db, self.workspace, **params)
                for name, expected in orig_files.items():
                    self.assertEqual((out / name).read_bytes(), expected)
                self.assertEqual(list((self.workspace / "reports").glob(".staging-*")), [])

        # Existing regular file at target report_id path must also be refused without overwrite.
        file_target = self.workspace / "reports" / "qa_existing_file"
        file_target.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(ValueError, "published_report_conflict"):
            render_session_brief(
                self.db,
                self.workspace,
                cutoff="2026-11-06T00:30:00Z",
                report_id="qa_existing_file",
                report_type="pre_market",
                market_session_date="2026-11-06",
            )
        self.assertEqual(file_target.read_bytes(), b"do-not-overwrite")

    def test_supplement_chain_v3_v2_v1_scope_mismatch_and_cycle_detection(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        v1 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_chain_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        v1_snap = {n: (v1 / n).read_bytes() for n in ("brief.html", "brief.md", "manifest.json")}

        ingest_fixture(
            self.db,
            _make_bundle(suffix="ch2", raw_available_at="2026-11-06T00:35:00Z", category="macro", title="补充二"),
            self.workspace,
        )
        v2 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:40:00Z",
            report_id="qa_chain_v2",
            report_type="pre_market",
            market_session_date="2026-11-06",
            supersedes_report_id="qa_chain_v1",
        )
        v2_snap = {n: (v2 / n).read_bytes() for n in ("brief.html", "brief.md", "manifest.json")}

        ingest_fixture(
            self.db,
            _make_bundle(suffix="ch3", raw_available_at="2026-11-06T00:45:00Z", category="company", title="补充三"),
            self.workspace,
        )
        v3 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:50:00Z",
            report_id="qa_chain_v3",
            report_type="pre_market",
            market_session_date="2026-11-06",
            supersedes_report_id="qa_chain_v2",
        )
        self.assertEqual({n: (v1 / n).read_bytes() for n in v1_snap}, v1_snap)
        self.assertEqual({n: (v2 / n).read_bytes() for n in v2_snap}, v2_snap)

        res3 = verify_session_brief(self.db, self.workspace, "qa_chain_v3")
        self.assertEqual(res3["status"], "verified")
        self.assertEqual(res3["events"], 3)
        self.assertEqual(res3["supersedes_report_id"], "qa_chain_v2")

        # Tampering v1 (grandparent) by 1 byte must fail verification of v3.
        orig_v1_html = (v1 / "brief.html").read_bytes()
        (v1 / "brief.html").write_bytes(orig_v1_html[:-1] + (b"!" if orig_v1_html[-1:] != b"!" else b"?"))
        with self.assertRaisesRegex(ValueError, "superseded_artifact_corrupt"):
            verify_session_brief(self.db, self.workspace, "qa_chain_v3")
        (v1 / "brief.html").write_bytes(orig_v1_html)

        # Cycle v1 <-> v2 must be rejected on verify (both starting from v2 and from v3 -> v2 -> v1 -> v2).
        m1 = json.loads((v1 / "manifest.json").read_text(encoding="utf-8"))
        m1["supersedes_report_id"] = "qa_chain_v2"
        m1["reason_codes"].append("supplement_revision")
        m1["sections"]["watch_items_count"] = len(m1["reason_codes"])
        (v1 / "manifest.json").write_text(_canonical(m1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "supplement_cycle_detected"):
            verify_session_brief(self.db, self.workspace, "qa_chain_v2")
        with self.assertRaisesRegex(ValueError, "supplement_cycle_detected"):
            verify_session_brief(self.db, self.workspace, "qa_chain_v3")

    def test_verify_is_strictly_read_only_api_and_cli(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_ro_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        db_path = self.workspace / "market.db"

        def _snapshot():
            files_map = {}
            for p in sorted(self.workspace.rglob("*")):
                if p.is_file():
                    st = p.stat()
                    files_map[str(p.relative_to(self.workspace))] = (st.st_mtime_ns, p.read_bytes())
            return files_map

        before_api = _snapshot()
        res = verify_session_brief(self.db, self.workspace, "qa_ro_v1")
        self.assertEqual(res["status"], "verified")
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(_snapshot(), before_api)

        self.db.close()
        before_cli = _snapshot()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli_main([
                "verify-session-brief",
                "--workspace", str(self.workspace),
                "--report-id", "qa_ro_v1",
            ])
        self.assertEqual(rc, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["status"], "verified")
        self.assertEqual(_snapshot(), before_cli)
        self.assertTrue(db_path.is_file())
        self.db = connect(db_path)

    def test_verify_detects_one_byte_tamper_on_artifacts_and_manifest_syntax(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_1byte_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        for fname in ("brief.html", "brief.md"):
            with self.subTest(artifact=fname):
                orig = (out / fname).read_bytes()
                flipped = bytes([orig[0] ^ 0x01]) + orig[1:]
                (out / fname).write_bytes(flipped)
                with self.assertRaisesRegex(ValueError, "published_artifact_corrupt"):
                    verify_session_brief(self.db, self.workspace, "qa_1byte_v1")
                (out / fname).write_bytes(orig)

        orig_m = (out / "manifest.json").read_bytes()
        (out / "manifest.json").write_bytes(orig_m + b"x")
        with self.assertRaises(ValueError):
            verify_session_brief(self.db, self.workspace, "qa_1byte_v1")
        (out / "manifest.json").write_bytes(orig_m)

    def test_verify_detects_one_byte_semantic_manifest_tampering(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_sem_tamper",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="run_1",
        )
        orig_bytes = (out / "manifest.json").read_bytes()
        orig = json.loads(orig_bytes.decode("utf-8"))

        semantic_tampers = [
            ("watch_items_count", lambda m: m["sections"].__setitem__("watch_items_count", 9)),
            ("market_session_date", lambda m: m.__setitem__("market_session_date", "2026-11-07")),
            ("run_id", lambda m: m.__setitem__("run_id", "run_2")),
            ("report_type", lambda m: m.__setitem__("report_type", "post_market")),
            ("information_cutoff", lambda m: m.__setitem__("information_cutoff", "2026-11-06T00:30:01Z")),
            ("display_timezone", lambda m: m.__setitem__("display_timezone", "UTC")),
        ]
        for field_name, mutate in semantic_tampers:
            with self.subTest(tampered_field=field_name):
                modified = copy.deepcopy(orig)
                mutate(modified)
                (out / "manifest.json").write_text(_canonical(modified), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_session_brief(self.db, self.workspace, "qa_sem_tamper")
                (out / "manifest.json").write_bytes(orig_bytes)

        # Forging brief.html AND updating artifact_sha256 in manifest.json must also fail verify.
        orig_html = (out / "brief.html").read_bytes()
        forged_html = orig_html.replace(
            "模型解读未启用".encode("utf-8"),
            "伪造模型解读结论".encode("utf-8"),
        )
        forged_manifest = copy.deepcopy(orig)
        forged_manifest["artifact_sha256"]["brief.html"] = _sha256_bytes(forged_html)
        (out / "brief.html").write_bytes(forged_html)
        (out / "manifest.json").write_text(_canonical(forged_manifest), encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError, "published_artifact_manifest_mismatch"):
                verify_session_brief(self.db, self.workspace, "qa_sem_tamper")
        finally:
            (out / "brief.html").write_bytes(orig_html)
            (out / "manifest.json").write_bytes(orig_bytes)


class ReplayAndPathSafetyQATests(_WorkspaceTestCase):
    def test_replay_byte_identical_after_late_versions_and_on_supplement(self):
        v1_bundle = _make_bundle(
            suffix="rep_a",
            event_id="event_rep",
            version=1,
            raw_available_at="2026-11-06T00:10:00Z",
            title="初始事件V1",
            text="初始事件正文V1。",
        )
        ingest_fixture(self.db, v1_bundle, self.workspace)
        rep_v1 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_rep_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="rep_run_1",
        )
        # Ingest v2 (same event_id, ALSO <= 00:30:00Z!) and a supplement report v2.
        v2_bundle = _make_bundle(
            suffix="rep_b",
            event_id="event_rep",
            version=2,
            raw_available_at="2026-11-06T00:20:00Z",
            title="晚到修订事件V2",
            text="晚到修订事件正文V2。",
        )
        ingest_fixture(self.db, v2_bundle, self.workspace)
        rep_v2 = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:35:00Z",
            report_id="qa_rep_v2",
            report_type="pre_market",
            market_session_date="2026-11-06",
            run_id="rep_run_2",
            supersedes_report_id="qa_rep_v1",
        )

        # Replay v1 must freeze exact event_rep_v1 and produce byte-identical HTML & MD.
        dest1 = self.root / "replay_dest_v1"
        out1 = replay_session_brief(self.db, self.workspace, "qa_rep_v1", dest1)
        self.assertEqual((rep_v1 / "brief.html").read_bytes(), (out1 / "brief.html").read_bytes())
        self.assertEqual((rep_v1 / "brief.md").read_bytes(), (out1 / "brief.md").read_bytes())
        self.assertEqual(
            _sha256_bytes((rep_v1 / "brief.html").read_bytes()),
            _sha256_bytes((out1 / "brief.html").read_bytes()),
        )
        self.assertEqual(
            _sha256_bytes((rep_v1 / "brief.md").read_bytes()),
            _sha256_bytes((out1 / "brief.md").read_bytes()),
        )

        # Replay supplement v2 into an isolated destination (without v1 in destination).
        dest2 = self.root / "replay_dest_v2"
        out2 = replay_session_brief(self.db, self.workspace, "qa_rep_v2", dest2)
        self.assertEqual((rep_v2 / "brief.html").read_bytes(), (out2 / "brief.html").read_bytes())
        self.assertEqual((rep_v2 / "brief.md").read_bytes(), (out2 / "brief.md").read_bytes())

    def test_path_traversal_unc_and_invalid_report_id_rejected(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_valid_id",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )

        bad_ids = [
            "../escape",
            "..",
            ".",
            "a/b",
            r"a\b",
            "",
            "a" * 129,
            "ok\n",
            "C:bad",
            r"\\server\share",
        ]
        for bad_id in bad_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaisesRegex(ValueError, "invalid_report_id"):
                    render_session_brief(
                        self.db,
                        self.workspace,
                        cutoff="2026-11-06T00:30:00Z",
                        report_id=bad_id,
                        report_type="pre_market",
                        market_session_date="2026-11-06",
                    )
                with self.assertRaisesRegex(ValueError, "invalid_report_id"):
                    verify_session_brief(self.db, self.workspace, bad_id)
                with self.assertRaisesRegex(ValueError, "invalid_report_id"):
                    replay_session_brief(self.db, self.workspace, bad_id, self.root / "dest")

        # Direct traversal attempt on _safe_file.
        outside = self.root / "outside_secret.txt"
        outside.write_text("secret", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "report_file_outside_workspace"):
            _safe_file(self.workspace, "../outside_secret.txt")

        # UNC paths rejected on Windows.
        if os.name == "nt":
            for unc in (r"\\127.0.0.1\share\ws", "//127.0.0.1/share/ws"):
                with self.subTest(unc=unc):
                    with self.assertRaisesRegex(ValueError, "report_path_unsupported"):
                        render_session_brief(
                            self.db,
                            Path(unc),
                            cutoff="2026-11-06T00:30:00Z",
                            report_id="qa_unc",
                            report_type="pre_market",
                            market_session_date="2026-11-06",
                        )
                    with self.assertRaisesRegex(ValueError, "report_path_unsupported"):
                        replay_session_brief(self.db, self.workspace, "qa_valid_id", Path(unc))
                    with self.assertRaisesRegex(ValueError, "report_path_unsupported"):
                        verify_session_brief(self.db, Path(unc), "qa_valid_id")

    def test_reparse_point_junction_rejected_on_windows(self):
        if os.name != "nt":
            self.skipTest("NTFS directory junction test is Windows-only")
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_junc_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        junc_ws = self.root / "ws_junction"
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junc_ws), str(self.workspace)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            self.skipTest(f"mklink /J unavailable: {proc.stderr or proc.stdout}")
        with self.assertRaisesRegex(ValueError, "report_symlink_not_allowed"):
            verify_session_brief(self.db, junc_ws, "qa_junc_v1")
        with self.assertRaisesRegex(ValueError, "report_symlink_not_allowed"):
            render_session_brief(
                self.db,
                junc_ws,
                cutoff="2026-11-06T00:30:00Z",
                report_id="qa_junc_v2",
                report_type="pre_market",
                market_session_date="2026-11-06",
            )
        with self.assertRaisesRegex(ValueError, "report_symlink_not_allowed"):
            replay_session_brief(self.db, self.workspace, "qa_junc_v1", junc_ws / "replay_out")

    def test_symlink_rejected_when_supported(self):
        ingest_fixture(self.db, _demo_bundle(), self.workspace)
        out = render_session_brief(
            self.db,
            self.workspace,
            cutoff="2026-11-06T00:30:00Z",
            report_id="qa_sym_v1",
            report_type="pre_market",
            market_session_date="2026-11-06",
        )
        outside = self.root / "external.md"
        outside.write_text("external", encoding="utf-8")
        link_ws = self.root / "ws_symlink"
        try:
            os.symlink(self.workspace, link_ws, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS symlink privilege unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "report_symlink_not_allowed"):
            verify_session_brief(self.db, link_ws, "qa_sym_v1")
        (out / "brief.md").unlink()
        os.symlink(outside, out / "brief.md")
        with self.assertRaisesRegex(ValueError, "report_symlink_not_allowed"):
            verify_session_brief(self.db, self.workspace, "qa_sym_v1")


if __name__ == "__main__":
    unittest.main()
