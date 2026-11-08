"""Offline contract prototype. No network, models, prices or scheduling."""

import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from .contracts import ContractError, validate_bundle
from .contracts.report import validate_report_manifest
from .report.verify import verify_report
from .store import connect, insert_immutable, record_visibility


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamps must end in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ingest_fixture(db, bundle, workspace):
    """Only synthetic, pre-structured fixtures are accepted by this prototype."""
    if not all(bundle[k].get("is_synthetic") is True for k in ("raw", "event", "evidence")):
        raise ValueError("fixture_only")
    return ingest_bundle(db, bundle, workspace)


def ingest_bundle(db, bundle, workspace):
    validate_bundle(bundle)
    raw, event, evidence = (bundle[k] for k in ("raw", "event", "evidence"))
    expected_ref = raw["content_ref"]
    path = Path(workspace) / expected_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if digest(path.read_bytes().decode("utf-8")) != raw["content_sha256"]:
            raise ValueError("stored_content_corrupt")
    else:
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(raw["normalized_text"])
    # A crash after content storage leaves an unreferenced immutable file; replay is safe.
    with db:
        insert_immutable(db, "raw_items", "raw_item_id", raw)
        insert_immutable(db, "event_versions", "event_version_id", event)
        insert_immutable(db, "evidence", "evidence_id", evidence)
    if not event["is_synthetic"]:
        record_visibility(db, event["event_version_id"])


def render(db, workspace, cutoff, report_id, *, frozen_manifest=None, output_root=None, report_kind=None):
    if frozen_manifest is not None:
        validate_report_manifest(frozen_manifest, expected_report_id=report_id)
    limit = utc(cutoff)
    renderer_version = frozen_manifest["renderer_version"] if frozen_manifest else "evidence-brief/0.3"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", report_id):
        raise ValueError("invalid_report_id")
    # A single statement holds one SQLite read snapshot across all three objects.
    rows = db.execute("SELECT 'raw',id,payload FROM raw_items UNION ALL SELECT 'events',id,payload FROM event_versions UNION ALL SELECT 'evidence',id,payload FROM evidence UNION ALL SELECT 'receipts',event_version_id,json_object('committed_at',committed_at) FROM availability_receipts").fetchall()
    loaded = {kind: {} for kind in ("raw", "events", "evidence", "receipts")}
    for kind, key, payload in rows:
        loaded[kind][key] = json.loads(payload)
    raw, events, evidence = (loaded[k] for k in ("raw", "events", "evidence"))
    eligible = {}
    for event in events.values():
        if frozen_manifest is not None and event["event_version_id"] not in frozen_manifest["input_manifest"]["event_version_ids"]:
            continue
        refs = [evidence[k] for k in event["evidence_ids"]]
        inputs = [raw[k] for k in event["input_raw_item_ids"]]
        if any(utc(x["available_at"]) > limit for x in [event, *refs, *inputs]):
            continue
        if not event["is_synthetic"]:
            receipt = loaded["receipts"].get(event["event_version_id"])
            if receipt is None or utc(receipt["committed_at"]) > limit:
                continue
        for item in inputs:
            content = Path(workspace) / item["content_ref"]
            if not content.exists() or digest(content.read_bytes().decode("utf-8")) != item["content_sha256"]:
                raise ValueError(f"evidence_file_missing_or_corrupt: {item['raw_item_id']}")
        old = eligible.get(event["event_id"])
        if old is None or event["version"] > old["version"]:
            eligible[event["event_id"]] = event
    selected = sorted(eligible.values(), key=lambda x: x["event_version_id"])
    inputs = {
        "event_version_ids": [x["event_version_id"] for x in selected],
        "evidence_ids": sorted({k for x in selected for k in x["evidence_ids"]}),
        "raw_item_ids": sorted({k for x in selected for k in x["input_raw_item_ids"]}),
        "prediction_ids": [], "market_snapshot_id": None,
    }
    if frozen_manifest is not None:
        if inputs != frozen_manifest["input_manifest"] or digest(canonical(inputs)) != frozen_manifest["input_manifest_sha256"]:
            raise ValueError("frozen_input_mismatch")
        if renderer_version not in {"evidence-brief/0.2", "evidence-brief/0.3"} or frozen_manifest["template_version"] != renderer_version:
            raise ValueError("unsupported_replay_renderer")
        report_kind = frozen_manifest["report_type"]
    synthetic = all(raw[key]["is_synthetic"] for key in inputs["raw_item_ids"]) if selected else report_kind not in {"rss_snapshot", "source_snapshot"}
    mixed = bool(selected) and not synthetic and any(raw[key]["is_synthetic"] for key in inputs["raw_item_ids"])
    report_kind = report_kind or ("offline_fixture" if synthetic else "source_snapshot")
    parts = []
    for event in selected:
        quotes = []
        for key in event["evidence_ids"]:
            ev = evidence[key]
            source = raw[ev["raw_item_id"]]
            if source["is_synthetic"]:
                label = "合成来源"
            elif renderer_version == "evidence-brief/0.2":
                label = "官方 RSS 来源链接"
            else:
                label = {"fed_press_all": "美联储 · 官方来源链接", "nbs_releases": "国家统计局 · 官方来源链接"}.get(source["source_id"], "原始来源链接")
            quotes.append(f'<blockquote>{html.escape(ev["quote"])} <a href="{html.escape(source["original_url"], quote=True)}">{label}</a> · {html.escape(ev["relation"])} · {html.escape(source["storage_policy"])}<br>来源发布时间：{html.escape(source["source_time_text"] or "未知")}；系统获取：{html.escape(source["fetched_at"])}</blockquote>')
        parts.append(f'<article><h2>{html.escape(event["title"])}</h2><p>{html.escape(event["fact_summary"])}</p>{"".join(quotes)}</article>')
    real_heading = "官方 RSS · 信息快照" if renderer_version == "evidence-brief/0.2" else "官方信息 · 信息快照"
    heading = "离线合成样本 · 事件简报" if synthetic else ("混合测试数据 · 不可用于市场研究" if mixed else real_heading)
    note = "仅用于开发验证；没有真实抓取、模型推理或行情评价。" if synthetic else "仅展示来源标题或原文摘要摘录；未执行模型解读、全文核实或行情评价。"
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + heading + '</title><style>body{max-width:900px;margin:40px auto;padding:20px;font:16px/1.8 "Microsoft YaHei",sans-serif;color:#183048}article{border-top:1px solid #ccd8e4;margin-top:24px}blockquote{background:#f0f5fa;padding:18px}aside{background:#fff0ce;padding:18px}a{color:#175b91}</style><h1>' + heading + '</h1><aside>' + note + '</aside><p>严格信息截点：' + html.escape(cutoff) + '</p>' + (''.join(parts) or '<p>截点前无可用事件。</p>') + '</html>'
    if frozen_manifest is not None and digest(document) != frozen_manifest["artifact_sha256"]:
        raise ValueError("replay_artifact_mismatch")
    manifest = {
        "schema_version": "report-manifest/0.1", "report_id": report_id, "run_id": report_id,
        "report_type": report_kind, "market_session_date": None,
        "display_timezone": "Asia/Shanghai", "information_cutoff": cutoff,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "degraded", "reason_codes": (["synthetic_fixture", "retrospective"] if synthetic else ["rss_excerpt_only" if renderer_version == "evidence-brief/0.2" else "source_metadata_only", "content_support_not_reviewed"]) + ["market_data_unavailable"] + (["mixed_test_data"] if mixed else []),
        "input_manifest": inputs, "input_manifest_sha256": digest(canonical(inputs)),
        "canonical_json_version": "python-json-sorted-utf8/0.1",
        "source_config_version": ",".join(sorted({raw[k]["source_config_version"] for k in inputs["raw_item_ids"]})), "rules_version": "strict-cutoff/0.2" if renderer_version == "evidence-brief/0.2" else "strict-cutoff/0.3",
        "template_version": renderer_version, "renderer_version": renderer_version,
        "market_data_as_of": None, "citation_check": "passed", "content_support_check": "not_performed",
        "artifact_refs": ["brief.html"], "artifact_sha256": digest(document),
        "supersedes_report_id": None, "is_synthetic": synthetic,
    }
    validate_report_manifest(manifest, expected_report_id=report_id)
    reports = Path(output_root) if output_root else Path(workspace) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / report_id
    if target.exists():
        previous = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if any(previous[k] != manifest[k] for k in manifest if k != "generated_at") or digest((target / "brief.html").read_bytes().decode("utf-8")) != manifest["artifact_sha256"]:
            raise ValueError("published_report_conflict")
        return target
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=reports))
    (staging / "brief.html").write_text(document, encoding="utf-8", newline="")
    (staging / "manifest.json").write_text(canonical(manifest), encoding="utf-8", newline="")
    os.rename(staging, target)
    return target


def replay_report(db, workspace, report_id, destination):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", report_id):
        raise ValueError("invalid_report_id")
    try:
        verify_report(db, workspace, report_id)
    except ContractError as exc:
        raise ValueError("invalid_report_manifest") from exc
    published = Path(workspace) / "reports" / report_id
    manifest = json.loads((published / "manifest.json").read_text(encoding="utf-8"))
    if manifest["report_id"] != report_id or digest(canonical(manifest["input_manifest"])) != manifest["input_manifest_sha256"]:
        raise ValueError("invalid_report_manifest")
    if digest((published / "brief.html").read_bytes().decode("utf-8")) != manifest["artifact_sha256"]:
        raise ValueError("published_artifact_corrupt")
    return render(db, workspace, manifest["information_cutoff"], report_id,
                  frozen_manifest=manifest, output_root=destination)
