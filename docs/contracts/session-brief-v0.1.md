# 盘前/盘后双模板简报契约（v0.1）

本文定义 `session-brief-manifest/0.1` 及其配套渲染器 `session-brief/0.1`（对应任务板 `RPT-01` / `RPT-02` 的离线降级原型）。本版本不执行真实模型推理，也不接入授权行情，发布状态固定为 `degraded`。

## 1. 范围与边界

- 支持的报告类型：`pre_market`（盘前简报）、`post_market`（盘后简报）。
- 产物固定为双模板及单一清单：`brief.html`、`brief.md`、`manifest.json`。
- 严格信息截点：仅纳入 `available_at <= information_cutoff` 的事件、证据与原始条目；非合成记录额外要求 `availability_receipts.committed_at <= information_cutoff`。同一 `event_id` 仅取截点前最高版本。
- 证据与引用闭包：渲染前逐条校验 `validate_bundle(...)` 与 `content_ref` 文件 SHA-256；任一引用缺失、越界、符号链接或篡改均拒绝发布。
- 三栏严格区分：
  1. **一、已核验事实（Facts）**：按事件类别排序展示通过截点与引用校验的事件及证据引文；无可用事件时明确说明“截点前无可用事件，不强行填充主题”。
  2. **二、模型解读（Interpretations）**：v0.1 未接入已验收模型，固定保留空白说明（`interpretations_count == 0`），禁止臆造解读。
  3. **三、观察事项与缺口（Watch Items）**：逐条对应当前降级/状态原因码，至少 1 条。

## 2. 清单契约（`session-brief-manifest/0.1`）

`validate_session_brief_manifest(manifest, *, expected_report_id=None)` 位于 `src/market_intel/contracts/session_brief.py`，校验以下精确字段：

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 固定为 `session-brief-manifest/0.1` |
| `report_id`、`run_id` | 1~128 位 `[A-Za-z0-9_-]` |
| `report_type` | `pre_market` 或 `post_market` |
| `market_session_date` | 有效日历日期 `YYYY-MM-DD` |
| `display_timezone` | 有效 IANA 时区（默认 `Asia/Shanghai`） |
| `information_cutoff`、`generated_at` | UTC `Z` 时间戳，且 `generated_at >= information_cutoff` |
| `market_data_as_of` | v0.1 固定为 `null` |
| `status` | v0.1 固定为 `degraded` |
| `citation_check` / `content_support_check` | 固定为 `passed` / `not_performed` |
| `renderer_version` / `template_version` / `rules_version` | `session-brief/0.1` / `session-brief/0.1` / `strict-cutoff-session/0.1` |
| `canonical_json_version` | `python-json-sorted-utf8/0.1` |
| `input_manifest` 与 `input_manifest_sha256` | 与 `report-manifest/0.1` 一致，`prediction_ids=[]`、`market_snapshot_id=null` |
| `sections` | 精确包含 `facts_count`（等于 `len(event_version_ids)`）、`interpretations_count`（固定 `0`）、`watch_items_count`（`>= 1`） |
| `reason_codes` | 去重枚举数组。合成模式固定含 `synthetic_fixture`、`retrospective`、`model_unavailable`、`market_data_unavailable`；非合成模式固定含 `source_metadata_only`、`content_support_not_reviewed`、`model_unavailable`、`market_data_unavailable`（混合数据时附 `mixed_test_data`）；补版必须附 `supplement_revision` |
| `artifact_refs` | 固定为 `["brief.html", "brief.md"]` |
| `artifact_sha256` | 精确映射 `{"brief.html": <64hex>, "brief.md": <64hex>}` |
| `supersedes_report_id` | 可为空；非空时不得等于 `report_id` |
| `is_synthetic` | 布尔值 |

## 3. 补版、原子归档与重放

- **原子归档**：先写入 `reports/.staging-*` 临时目录，写齐 `brief.html`、`brief.md`、`manifest.json` 后 `os.rename` 到目标目录 `reports/<report_id>`；中途失败自动清理临时目录。
- **幂等与冲突保护**：若目标目录已存在，仅当清单（忽略 `generated_at`）及双产物哈希完全一致时幂等返回；否则抛出 `published_report_conflict`，绝不覆盖旧版。
- **补版修订（`supersedes_report_id`）**：生成补版前先对被替代旧版执行只读 `verify_session_brief(...)`，并校验 `report_type` 与 `market_session_date` 一致；旧版目录保持只读不被覆盖。校验时沿补版链检查防环、范围一致及旧版产物完整性。
- **离线重放**：`replay_session_brief(db, workspace, report_id, destination)` 在验证旧版后，以 `frozen_manifest` 在独立目录重放并逐字节核对 `brief.html` 与 `brief.md` 的 SHA-256。

## 4. 本地命令

```powershell
# 生成盘前降级双模板简报
python -m market_intel session-brief --workspace out/demo --report-type pre_market --session-date 2026-11-06 --cutoff 2026-11-06T00:30:00Z --report-id pre_20261106_v1 --run-id run_20261106_01

# 只读验收（不修改数据库与文件）
python -m market_intel verify-session-brief --workspace out/demo --report-id pre_20261106_v1

# 生成独立补版（不覆盖 v1）
python -m market_intel session-brief --workspace out/demo --report-type pre_market --session-date 2026-11-06 --cutoff 2026-11-06T01:00:00Z --report-id pre_20261106_v2 --supersedes pre_20261106_v1

# 独立目录确定性重放
python -m market_intel replay-session-brief --workspace out/demo --report-id pre_20261106_v2 --destination out/replay-session
```

## 5. 未验证与边界说明

- 本契约覆盖离线合成及已有受限来源元数据的双模板简报、降级、补版与重放。
- 真实模型解读（依赖 `NLP-01` / `NLP-02`）、真实授权行情与交易会话时点（依赖 `MKT-01` / `MKT-02`）以及宽窄屏人工抽检（`WB-03`）尚未验收。
