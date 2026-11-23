"""Dual-template (HTML + Markdown) session brief renderer, verifier, and replay.

Implements offline degraded pre_market and post_market briefs with strict
cutoff filtering, evidence citation closure, supplement revision linking,
and atomic archive publication. No network, live model, or live market calls.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..contracts import ContractError, instant, validate_bundle
from ..contracts.session_brief import (
    ARTIFACT_REFS,
    CANONICAL_JSON_VERSION,
    RENDERER_VERSION,
    REPORT_TYPES,
    RULES_VERSION,
    SCHEMA_VERSION,
    validate_session_brief_manifest,
)
from ..llm.client import _strict_loads
from ..ops.backup import _linked

__all__ = ["render_session_brief", "verify_session_brief", "replay_session_brief"]

_REPORT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

_TYPE_LABELS = {
    "pre_market": "盘前简报",
    "post_market": "盘后简报",
}

_CATEGORY_LABELS = {
    "macro": "宏观经济 (macro)",
    "policy": "政策监管 (policy)",
    "company": "公司事件 (company)",
    "fund_flow": "资金动向 (fund_flow)",
    "geopolitics": "地缘政治 (geopolitics)",
    "sentiment": "市场情绪 (sentiment)",
    "calendar": "财经日历 (calendar)",
    "other": "其他 (other)",
}

_SOURCE_LABELS = {
    "fed_press_all": "美联储 · 官方来源链接",
    "nbs_releases": "国家统计局 · 官方来源链接",
}

_WATCH_MESSAGES = {
    "synthetic_fixture": "当前输入为合成测试样本（synthetic_fixture），仅用于离线开发验证，不可作为真实市场依据。",
    "retrospective": "当前简报属于回溯/离线重放口径（retrospective），非实盘准时发布。",
    "source_metadata_only": "当前真实来源仅覆盖标题、时间与链接元数据（source_metadata_only），未留存或核验正文全文。",
    "content_support_not_reviewed": "尚未执行事实与正文支撑度的人工或模型复核（content_support_not_reviewed）。",
    "model_unavailable": "模型推理客户端未启用（model_unavailable），模型解读栏保持空白，不生成替代观点。",
    "market_data_unavailable": "授权行情与交易会话源未接入（market_data_unavailable），行情时点为空，评价模块保持关闭。",
    "mixed_test_data": "警告：当前截点内同时包含合成与非合成记录（mixed_test_data），严禁用于真实市场研究。",
    "supplement_revision": "本版为补版修订（supplement_revision），独立归档且未覆盖被替代旧版。",
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(text_value):
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def _safe_dir(path):
    raw_path = Path(path).absolute()
    if raw_path.drive.startswith("\\\\"):
        raise ValueError("report_path_unsupported")
    if any(_linked(item) for item in (raw_path, *raw_path.parents)):
        raise ValueError("report_symlink_not_allowed")
    return raw_path.resolve()


def _safe_file(root, relative):
    base = _safe_dir(root)
    candidate = base / relative
    if any(_linked(item) for item in (candidate, *candidate.parents) if item != base and base in item.parents):
        raise ValueError("report_symlink_not_allowed")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("report_file_outside_workspace")
    current = candidate
    while current != base:
        if _linked(current):
            raise ValueError("report_symlink_not_allowed")
        current = current.parent
    if not candidate.is_file():
        raise ValueError("report_file_missing")
    return candidate


def _payload(db, table, key):
    row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise ValueError("report_input_missing")
    return json.loads(row[0])


_MD_ORDERED_LIST_RE = re.compile(r"^(\d+)([.)])(\s|$)")


def _escape_md_text(value):
    # Escape backslashes first so user input cannot neutralize subsequent escapes,
    # then neutralize raw HTML tags, autolinks, Markdown links/images, and code spans.
    escaped = str(value).replace("\\", "\\\\")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    escaped = escaped.replace("[", "\\[").replace("]", "\\]").replace("`", "\\`")
    return escaped


def _escape_md_block_start(text_val):
    if not text_val:
        return text_val
    if text_val[0] in {"#", "-", "*", "+", "=", "~"}:
        return "\\" + text_val
    ordered = _MD_ORDERED_LIST_RE.match(text_val)
    if ordered:
        return f"{ordered.group(1)}\\{ordered.group(2)}{text_val[ordered.end(2):]}"
    return text_val


def _clean_md_inline(value):
    collapsed = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return _escape_md_text(collapsed)


def _clean_md_paragraph(value):
    return _escape_md_block_start(_clean_md_inline(value))


def _format_md_quote(value):
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    formatted = []
    for line in lines:
        if not line:
            formatted.append(">")
        else:
            formatted.append(f"> {_escape_md_block_start(_escape_md_text(line))}")
    return "\n".join(formatted)


def _validate_render_params(*, report_id, run_id, report_type, market_session_date, display_timezone, cutoff, supersedes_report_id):
    if type(report_id) is not str or not _REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("invalid_report_id")
    if type(run_id) is not str or not _REPORT_ID_RE.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    if report_type not in REPORT_TYPES:
        raise ValueError("invalid_report_type")
    if type(market_session_date) is not str or not _DATE_RE.fullmatch(market_session_date):
        raise ValueError("invalid_market_session_date")
    try:
        date.fromisoformat(market_session_date)
    except ValueError as exc:
        raise ValueError("invalid_market_session_date") from exc
    if (
        type(display_timezone) is not str
        or not display_timezone.strip()
        or display_timezone != display_timezone.strip()
        or any(ch.isspace() for ch in display_timezone)
        or "\\" in display_timezone
        or ".." in display_timezone
        or display_timezone.startswith("/")
        or display_timezone.endswith(("/", "."))
    ):
        raise ValueError("unknown_display_timezone")
    try:
        ZoneInfo(display_timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("unknown_display_timezone") from exc
    limit = instant(cutoff, "session_brief.information_cutoff")
    if supersedes_report_id is not None:
        if type(supersedes_report_id) is not str or not _REPORT_ID_RE.fullmatch(supersedes_report_id):
            raise ValueError("invalid_supersedes_report_id")
        if supersedes_report_id == report_id:
            raise ValueError("supplement_self_reference")
    return limit


def _source_label(source):
    if source["is_synthetic"]:
        return "合成来源"
    return _SOURCE_LABELS.get(source["source_id"], "原始来源链接")


def _build_documents(
    *,
    report_id,
    run_id,
    report_type,
    market_session_date,
    display_timezone,
    cutoff,
    supersedes_report_id,
    synthetic,
    mixed,
    reason_codes,
    selected,
    raw_map,
    evidence_map,
):
    type_label = _TYPE_LABELS[report_type]
    if synthetic:
        banner = f"离线合成样本 · {type_label}"
        notice = "仅用于离线开发验证；未执行真实采集解读、模型推理或行情评价。"
    elif mixed:
        banner = f"混合测试数据 · {type_label}（不可用于市场研究）"
        notice = "包含合成与非合成混合数据；严禁用于真实市场研究。"
    else:
        banner = f"官方信息降级版 · {type_label}"
        notice = "仅展示已核验的来源标题/摘要摘录；模型解读与授权行情未接入（降级版）。"

    grouped = defaultdict(list)
    for event in selected:
        grouped[event["category"]].append(event)
    ordered_categories = sorted(grouped.keys())
    watch_items = [_WATCH_MESSAGES[code] for code in reason_codes]

    # --- Markdown document ---
    md_lines = [
        f"# {banner}",
        "",
        f"> **状态声明**：{notice}",
        "",
        "## 元数据",
        "",
        f"- **报告编号 (`report_id`)**：`{report_id}`",
        f"- **运行编号 (`run_id`)**：`{run_id}`",
        f"- **报告类型 (`report_type`)**：`{report_type}`（{type_label}）",
        f"- **交易日 (`market_session_date`)**：`{market_session_date}`",
        f"- **展示时区 (`display_timezone`)**：`{display_timezone}`",
        f"- **严格信息截点 (`information_cutoff`)**：`{cutoff}`",
        "- **行情时点 (`market_data_as_of`)**：未接入（`null`，已降级）",
        "- **发布状态 (`status`)**：`degraded`",
        f"- **降级/状态原因码 (`reason_codes`)**：{', '.join(f'`{code}`' for code in reason_codes)}",
        f"- **替代旧版 (`supersedes_report_id`)**：{f'`{supersedes_report_id}`' if supersedes_report_id else '无'}",
        f"- **合成样本标记 (`is_synthetic`)**：`{str(synthetic).lower()}`",
        "",
        "## 一、已核验事实（Facts）",
        "",
    ]
    if not selected:
        md_lines.append("截点前无可用事件，不强行填充主题。")
        md_lines.append("")
    else:
        for cat in ordered_categories:
            md_lines.append(f"### {_CATEGORY_LABELS.get(cat, cat)}")
            md_lines.append("")
            for event in grouped[cat]:
                md_lines.append(f"#### {_clean_md_inline(event['title'])} (`{event['event_version_id']}`)")
                md_lines.append("")
                md_lines.append(_clean_md_paragraph(event["fact_summary"]))
                md_lines.append("")
                for ev_id in event["evidence_ids"]:
                    ev = evidence_map[ev_id]
                    src = raw_map[ev["raw_item_id"]]
                    label = _source_label(src)
                    md_lines.append(_format_md_quote(ev["quote"]))
                    md_lines.append("")
                    md_lines.append(
                        f"- 证据：`{ev['evidence_id']}` | 关系：`{ev['relation']}` | 留存：`{src['storage_policy']}`"
                    )
                    md_lines.append(
                        f"- 来源：[{_clean_md_inline(label)}](<{src['original_url']}>) | "
                        f"来源发布时间：{_clean_md_inline(src['source_time_text'] or '未知')} | "
                        f"系统获取：`{src['fetched_at']}`"
                    )
                    md_lines.append("")

    md_lines.extend([
        "## 二、模型解读（Interpretations）",
        "",
        "模型解读未启用（`model_unavailable`），本栏保持空白，不生成替代解读。",
        "",
        "## 三、观察事项与缺口（Watch Items）",
        "",
    ])
    for item in watch_items:
        md_lines.append(f"- {item}")
    md_lines.append("")
    md_doc = "\n".join(md_lines)

    # --- HTML document ---
    meta_rows = [
        ("报告编号 (report_id)", report_id),
        ("运行编号 (run_id)", run_id),
        ("报告类型 (report_type)", f"{report_type}（{type_label}）"),
        ("交易日 (market_session_date)", market_session_date),
        ("展示时区 (display_timezone)", display_timezone),
        ("严格信息截点 (information_cutoff)", cutoff),
        ("行情时点 (market_data_as_of)", "未接入（null，已降级）"),
        ("发布状态 (status)", "degraded"),
        ("降级/状态原因码 (reason_codes)", ", ".join(reason_codes)),
        ("替代旧版 (supersedes_report_id)", supersedes_report_id or "无"),
        ("合成样本标记 (is_synthetic)", str(synthetic).lower()),
    ]
    meta_html = "".join(
        f"<tr><th>{html.escape(k)}</th><td><code>{html.escape(v)}</code></td></tr>"
        for k, v in meta_rows
    )

    if not selected:
        facts_html = "<p>截点前无可用事件，不强行填充主题。</p>"
    else:
        cat_blocks = []
        for cat in ordered_categories:
            articles = []
            for event in grouped[cat]:
                quote_blocks = []
                for ev_id in event["evidence_ids"]:
                    ev = evidence_map[ev_id]
                    src = raw_map[ev["raw_item_id"]]
                    label = _source_label(src)
                    quote_blocks.append(
                        f'<blockquote><p>{html.escape(ev["quote"])}</p>'
                        f'<footer><a href="{html.escape(src["original_url"], quote=True)}">{html.escape(label)}</a>'
                        f' · <code>{html.escape(ev["evidence_id"])}</code>'
                        f' · {html.escape(ev["relation"])}'
                        f' · {html.escape(src["storage_policy"])}<br>'
                        f'来源发布时间：{html.escape(src["source_time_text"] or "未知")}；'
                        f'系统获取：<code>{html.escape(src["fetched_at"])}</code></footer></blockquote>'
                    )
                articles.append(
                    f'<article><h4>{html.escape(event["title"])} '
                    f'<small><code>{html.escape(event["event_version_id"])}</code></small></h4>'
                    f'<p>{html.escape(event["fact_summary"])}</p>{"".join(quote_blocks)}</article>'
                )
            cat_blocks.append(
                f'<section class="category"><h3>{html.escape(_CATEGORY_LABELS.get(cat, cat))}</h3>'
                f'{"".join(articles)}</section>'
            )
        facts_html = "".join(cat_blocks)

    watch_html = "".join(f"<li>{html.escape(item)}</li>" for item in watch_items)
    html_doc = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(banner)}</title>"
        '<style>body{max-width:920px;margin:32px auto;padding:20px;font:16px/1.75 "Microsoft YaHei",sans-serif;color:#183048}'
        'aside{background:#fff0ce;border-left:4px solid #c98a00;padding:14px 18px;margin:16px 0}'
        'table{width:100%;border-collapse:collapse;margin:16px 0}th,td{border:1px solid #d5e0ea;padding:8px 12px;text-align:left}'
        'th{background:#f4f8fc;width:34%}section.block{border-top:2px solid #ccd8e4;margin-top:24px;padding-top:12px}'
        'article{border-top:1px solid #e2ebf3;margin-top:16px;padding-top:12px}'
        'blockquote{background:#f0f5fa;border-left:3px solid #175b91;padding:12px 16px;margin:12px 0}'
        'blockquote footer{font-size:0.9em;color:#415b76;margin-top:8px}a{color:#175b91}</style></head><body>'
        f"<h1>{html.escape(banner)}</h1>"
        f"<aside>{html.escape(notice)}</aside>"
        f'<section class="block"><h2>元数据</h2><table>{meta_html}</table></section>'
        f'<section class="block"><h2>一、已核验事实（Facts）</h2>{facts_html}</section>'
        '<section class="block"><h2>二、模型解读（Interpretations）</h2>'
        "<p>模型解读未启用（<code>model_unavailable</code>），本栏保持空白，不生成替代解读。</p></section>"
        f'<section class="block"><h2>三、观察事项与缺口（Watch Items）</h2><ul>{watch_html}</ul></section>'
        "</body></html>"
    )
    return html_doc, md_doc, len(watch_items)


def render_session_brief(
    db,
    workspace,
    *,
    cutoff,
    report_id,
    report_type,
    market_session_date,
    run_id=None,
    display_timezone="Asia/Shanghai",
    supersedes_report_id=None,
    default_synthetic=False,
    frozen_manifest=None,
    output_root=None,
):
    """Render and atomically archive a dual-template (HTML + Markdown) session brief."""
    if type(default_synthetic) is not bool:
        raise ValueError("default_synthetic_boolean_required")
    if frozen_manifest is not None:
        validate_session_brief_manifest(frozen_manifest, expected_report_id=report_id)
        report_type = frozen_manifest["report_type"]
        market_session_date = frozen_manifest["market_session_date"]
        display_timezone = frozen_manifest["display_timezone"]
        run_id = frozen_manifest["run_id"]
        supersedes_report_id = frozen_manifest["supersedes_report_id"]
        cutoff = frozen_manifest["information_cutoff"]
        default_synthetic = frozen_manifest["is_synthetic"]

    effective_run_id = report_id if run_id is None else run_id
    limit = _validate_render_params(
        report_id=report_id,
        run_id=effective_run_id,
        report_type=report_type,
        market_session_date=market_session_date,
        display_timezone=display_timezone,
        cutoff=cutoff,
        supersedes_report_id=supersedes_report_id,
    )

    workspace_root = _safe_dir(workspace)
    reports_root = _safe_dir(output_root) if output_root is not None else _safe_dir(workspace_root / "reports")

    if supersedes_report_id is not None and frozen_manifest is None:
        superseded_verify = verify_session_brief(
            db, workspace_root, supersedes_report_id, reports_root=reports_root
        )
        if (
            superseded_verify["report_type"] != report_type
            or superseded_verify["market_session_date"] != market_session_date
        ):
            raise ValueError("supplement_scope_mismatch")

    # Single read statement guarantees one SQLite read snapshot across all tables.
    rows = db.execute(
        "SELECT 'raw',id,payload FROM raw_items "
        "UNION ALL SELECT 'events',id,payload FROM event_versions "
        "UNION ALL SELECT 'evidence',id,payload FROM evidence "
        "UNION ALL SELECT 'receipts',event_version_id,json_object('committed_at',committed_at) FROM availability_receipts"
    ).fetchall()
    loaded = {kind: {} for kind in ("raw", "events", "evidence", "receipts")}
    for kind, key, payload in rows:
        loaded[kind][key] = json.loads(payload)
    raw_map, events_map, evidence_map, receipts_map = (
        loaded["raw"], loaded["events"], loaded["evidence"], loaded["receipts"]
    )

    eligible = {}
    frozen_event_ids = (
        set(frozen_manifest["input_manifest"]["event_version_ids"])
        if frozen_manifest is not None
        else None
    )
    for event in events_map.values():
        if frozen_event_ids is not None and event["event_version_id"] not in frozen_event_ids:
            continue
        if (
            type(event) is not dict
            or type(event.get("input_raw_item_ids")) is not list
            or type(event.get("evidence_ids")) is not list
            or len(event["input_raw_item_ids"]) != 1
            or len(event["evidence_ids"]) != 1
        ):
            raise ValueError("unsupported_report_bundle_shape")
        raw_id = event["input_raw_item_ids"][0]
        ev_id = event["evidence_ids"][0]
        if raw_id not in raw_map or ev_id not in evidence_map:
            raise ValueError("report_input_missing")
        raw_obj = raw_map[raw_id]
        ev_obj = evidence_map[ev_id]
        if any(instant(x["available_at"], "available_at") > limit for x in (event, ev_obj, raw_obj)):
            continue
        if not event["is_synthetic"]:
            receipt = receipts_map.get(event["event_version_id"])
            if receipt is None or instant(receipt["committed_at"], "receipt.committed_at") > limit:
                continue
        old = eligible.get(event["event_id"])
        if old is None or event["version"] > old["version"]:
            eligible[event["event_id"]] = event

    selected = sorted(eligible.values(), key=lambda item: item["event_version_id"])
    for event in selected:
        raw_obj = raw_map[event["input_raw_item_ids"][0]]
        ev_obj = evidence_map[event["evidence_ids"][0]]
        try:
            validate_bundle({"raw": raw_obj, "event": event, "evidence": ev_obj})
        except ContractError as exc:
            raise ValueError("report_citation_invalid") from exc
        content_path = _safe_file(workspace_root, raw_obj["content_ref"])
        if _digest(content_path.read_bytes().decode("utf-8")) != raw_obj["content_sha256"]:
            raise ValueError("report_evidence_corrupt")

    inputs = {
        "event_version_ids": [x["event_version_id"] for x in selected],
        "evidence_ids": sorted({k for x in selected for k in x["evidence_ids"]}),
        "raw_item_ids": sorted({k for x in selected for k in x["input_raw_item_ids"]}),
        "prediction_ids": [],
        "market_snapshot_id": None,
    }
    input_hash = _digest(_canonical(inputs))

    if frozen_manifest is not None:
        if inputs != frozen_manifest["input_manifest"] or input_hash != frozen_manifest["input_manifest_sha256"]:
            raise ValueError("frozen_input_mismatch")

    if selected:
        synthetic = all(raw_map[k]["is_synthetic"] for k in inputs["raw_item_ids"])
        mixed = (not synthetic) and any(raw_map[k]["is_synthetic"] for k in inputs["raw_item_ids"])
    else:
        synthetic = default_synthetic
        mixed = False

    if synthetic:
        reason_codes = ["synthetic_fixture", "retrospective", "model_unavailable", "market_data_unavailable"]
    else:
        reason_codes = [
            "source_metadata_only",
            "content_support_not_reviewed",
            "model_unavailable",
            "market_data_unavailable",
        ]
        if mixed:
            reason_codes.append("mixed_test_data")
    if supersedes_report_id is not None:
        reason_codes.append("supplement_revision")

    html_doc, md_doc, watch_count = _build_documents(
        report_id=report_id,
        run_id=effective_run_id,
        report_type=report_type,
        market_session_date=market_session_date,
        display_timezone=display_timezone,
        cutoff=cutoff,
        supersedes_report_id=supersedes_report_id,
        synthetic=synthetic,
        mixed=mixed,
        reason_codes=reason_codes,
        selected=selected,
        raw_map=raw_map,
        evidence_map=evidence_map,
    )
    artifact_hashes = {
        "brief.html": _digest(html_doc),
        "brief.md": _digest(md_doc),
    }

    if frozen_manifest is not None and artifact_hashes != frozen_manifest["artifact_sha256"]:
        raise ValueError("replay_artifact_mismatch")

    source_config_version = ",".join(sorted({raw_map[k]["source_config_version"] for k in inputs["raw_item_ids"]}))
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "run_id": effective_run_id,
        "report_type": report_type,
        "market_session_date": market_session_date,
        "display_timezone": display_timezone,
        "information_cutoff": cutoff,
        "generated_at": generated_at,
        "status": "degraded",
        "reason_codes": reason_codes,
        "input_manifest": inputs,
        "input_manifest_sha256": input_hash,
        "canonical_json_version": CANONICAL_JSON_VERSION,
        "source_config_version": source_config_version,
        "rules_version": RULES_VERSION,
        "template_version": RENDERER_VERSION,
        "renderer_version": RENDERER_VERSION,
        "market_data_as_of": None,
        "citation_check": "passed",
        "content_support_check": "not_performed",
        "sections": {
            "facts_count": len(selected),
            "interpretations_count": 0,
            "watch_items_count": watch_count,
        },
        "artifact_refs": list(ARTIFACT_REFS),
        "artifact_sha256": artifact_hashes,
        "supersedes_report_id": supersedes_report_id,
        "is_synthetic": synthetic,
    }
    validate_session_brief_manifest(manifest, expected_report_id=report_id)

    reports_root.mkdir(parents=True, exist_ok=True)
    target = reports_root / report_id
    if _linked(target):
        raise ValueError("report_symlink_not_allowed")
    if target.exists():
        if not target.is_dir():
            raise ValueError("published_report_conflict")
        try:
            prev_manifest = _strict_loads(_safe_file(reports_root, f"{report_id}/manifest.json").read_text(encoding="utf-8"))
            validate_session_brief_manifest(prev_manifest, expected_report_id=report_id)
            prev_html = _safe_file(reports_root, f"{report_id}/brief.html").read_bytes().decode("utf-8")
            prev_md = _safe_file(reports_root, f"{report_id}/brief.md").read_bytes().decode("utf-8")
        except Exception as exc:
            raise ValueError("published_report_conflict") from exc
        same_manifest = all(prev_manifest[k] == manifest[k] for k in manifest if k != "generated_at")
        same_artifacts = (
            _digest(prev_html) == artifact_hashes["brief.html"]
            and _digest(prev_md) == artifact_hashes["brief.md"]
        )
        if not (same_manifest and same_artifacts):
            raise ValueError("published_report_conflict")
        return target

    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=reports_root))
    try:
        (staging / "brief.html").write_text(html_doc, encoding="utf-8", newline="")
        (staging / "brief.md").write_text(md_doc, encoding="utf-8", newline="")
        (staging / "manifest.json").write_text(_canonical(manifest), encoding="utf-8", newline="")
        os.rename(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def verify_session_brief(db, workspace, report_id, *, reports_root=None):
    """Read-only verification of a dual-template session brief against persisted evidence."""
    if type(report_id) is not str or not _REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("invalid_report_id")
    if db.in_transaction:
        raise ValueError("report_verification_requires_clean_transaction")

    workspace_root = _safe_dir(workspace)
    base_reports = _safe_dir(reports_root) if reports_root is not None else _safe_dir(workspace_root / "reports")

    try:
        manifest = _strict_loads(_safe_file(base_reports, f"{report_id}/manifest.json").read_text(encoding="utf-8"))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("invalid_report_manifest") from exc

    validate_session_brief_manifest(manifest, expected_report_id=report_id)

    for ref in ARTIFACT_REFS:
        artifact_bytes = _safe_file(base_reports, f"{report_id}/{ref}").read_bytes()
        if hashlib.sha256(artifact_bytes).hexdigest() != manifest["artifact_sha256"][ref]:
            raise ValueError("published_artifact_corrupt")

    # Verify supplement chain (if any) without mutating anything or looping.
    seen = {report_id}
    superseded_id = manifest["supersedes_report_id"]
    while superseded_id is not None:
        if superseded_id in seen:
            raise ValueError("supplement_cycle_detected")
        seen.add(superseded_id)
        try:
            prev_manifest = _strict_loads(
                _safe_file(base_reports, f"{superseded_id}/manifest.json").read_text(encoding="utf-8")
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("invalid_superseded_manifest") from exc
        validate_session_brief_manifest(prev_manifest, expected_report_id=superseded_id)
        if (
            prev_manifest["report_type"] != manifest["report_type"]
            or prev_manifest["market_session_date"] != manifest["market_session_date"]
        ):
            raise ValueError("supplement_scope_mismatch")
        for ref in ARTIFACT_REFS:
            prev_bytes = _safe_file(base_reports, f"{superseded_id}/{ref}").read_bytes()
            if hashlib.sha256(prev_bytes).hexdigest() != prev_manifest["artifact_sha256"][ref]:
                raise ValueError("superseded_artifact_corrupt")
        superseded_id = prev_manifest["supersedes_report_id"]

    cutoff = instant(manifest["information_cutoff"], "session_brief.information_cutoff")
    raw_ids, evidence_ids = set(), set()
    synthetic_flags = []
    source_configs = set()
    selected_events = []
    raw_map = {}
    evidence_map = {}

    db.execute("BEGIN")
    try:
        for version_id in manifest["input_manifest"]["event_version_ids"]:
            event = _payload(db, "event_versions", version_id)
            if (
                type(event) is not dict
                or type(event.get("input_raw_item_ids")) is not list
                or type(event.get("evidence_ids")) is not list
                or len(event["input_raw_item_ids"]) != 1
                or len(event["evidence_ids"]) != 1
            ):
                raise ValueError("unsupported_report_bundle_shape")
            raw_id = event["input_raw_item_ids"][0]
            evidence_id = event["evidence_ids"][0]
            raw_obj = _payload(db, "raw_items", raw_id)
            evidence_obj = _payload(db, "evidence", evidence_id)
            validate_bundle({"raw": raw_obj, "event": event, "evidence": evidence_obj})
            if (
                event["event_version_id"] != version_id
                or raw_obj["raw_item_id"] != raw_id
                or evidence_obj["evidence_id"] != evidence_id
            ):
                raise ValueError("report_input_identity_mismatch")
            for rec in (raw_obj, event, evidence_obj):
                if instant(rec["available_at"], "available_at") > cutoff:
                    raise ValueError("report_input_after_cutoff")
            if not event["is_synthetic"]:
                receipt = db.execute(
                    "SELECT committed_at FROM availability_receipts WHERE event_version_id=?",
                    (version_id,),
                ).fetchone()
                if receipt is None or instant(receipt[0], "receipt.committed_at") > cutoff:
                    raise ValueError("report_receipt_missing_or_after_cutoff")
            content = _safe_file(workspace_root, raw_obj["content_ref"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != raw_obj["content_sha256"]:
                raise ValueError("report_evidence_corrupt")
            raw_ids.add(raw_id)
            evidence_ids.add(evidence_id)
            synthetic_flags.append(event["is_synthetic"])
            source_configs.add(raw_obj["source_config_version"])
            selected_events.append(event)
            raw_map[raw_id] = raw_obj
            evidence_map[evidence_id] = evidence_obj

        if (
            raw_ids != set(manifest["input_manifest"]["raw_item_ids"])
            or evidence_ids != set(manifest["input_manifest"]["evidence_ids"])
        ):
            raise ValueError("report_input_closure_mismatch")
        if synthetic_flags and manifest["is_synthetic"] != all(synthetic_flags):
            raise ValueError("report_synthetic_status_mismatch")
        if synthetic_flags and (
            ("mixed_test_data" in manifest["reason_codes"])
            != (any(synthetic_flags) and not all(synthetic_flags))
        ):
            raise ValueError("report_mixed_data_status_mismatch")
        if manifest["source_config_version"] != ",".join(sorted(source_configs)):
            raise ValueError("report_source_config_mismatch")
    finally:
        db.rollback()

    selected = sorted(selected_events, key=lambda item: item["event_version_id"])
    if [x["event_version_id"] for x in selected] != manifest["input_manifest"]["event_version_ids"]:
        raise ValueError("report_input_order_mismatch")

    expected_html, expected_md, expected_watch_count = _build_documents(
        report_id=manifest["report_id"],
        run_id=manifest["run_id"],
        report_type=manifest["report_type"],
        market_session_date=manifest["market_session_date"],
        display_timezone=manifest["display_timezone"],
        cutoff=manifest["information_cutoff"],
        supersedes_report_id=manifest["supersedes_report_id"],
        synthetic=manifest["is_synthetic"],
        mixed=("mixed_test_data" in manifest["reason_codes"]),
        reason_codes=manifest["reason_codes"],
        selected=selected,
        raw_map=raw_map,
        evidence_map=evidence_map,
    )
    if expected_watch_count != manifest["sections"]["watch_items_count"]:
        raise ValueError("report_watch_items_count_mismatch")
    expected_hashes = {
        "brief.html": _digest(expected_html),
        "brief.md": _digest(expected_md),
    }
    if expected_hashes != manifest["artifact_sha256"]:
        raise ValueError("published_artifact_manifest_mismatch")

    return {
        "status": "verified",
        "report_id": report_id,
        "report_type": manifest["report_type"],
        "market_session_date": manifest["market_session_date"],
        "events": len(synthetic_flags),
        "artifact_sha256": manifest["artifact_sha256"],
        "supersedes_report_id": manifest["supersedes_report_id"],
        "is_synthetic": manifest["is_synthetic"],
    }


def replay_session_brief(db, workspace, report_id, destination):
    """Deterministically reproduce a verified session brief into an isolated destination."""
    if type(report_id) is not str or not _REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("invalid_report_id")
    try:
        verify_session_brief(db, workspace, report_id)
    except ContractError as exc:
        raise ValueError("invalid_report_manifest") from exc
    reports_root = _safe_dir(Path(workspace) / "reports")
    manifest = _strict_loads(_safe_file(reports_root, f"{report_id}/manifest.json").read_text(encoding="utf-8"))
    return render_session_brief(
        db,
        workspace,
        cutoff=manifest["information_cutoff"],
        report_id=report_id,
        report_type=manifest["report_type"],
        market_session_date=manifest["market_session_date"],
        frozen_manifest=manifest,
        output_root=destination,
    )
