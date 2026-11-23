# Codex 独立 QA 审查与发布任务单（QA-B40）

- **任务 ID**：`QA-B40`（独立验收 `B40-SESSION-BRIEF`，并发布 Batch40 到 GitHub `main`）
- **主导方**：Antigravity（已完成实现与自测，当前 `B40-SESSION-BRIEF` 状态为 `review`）
- **配合方**：Codex（`codex://threads/01a1b664-fa93-7883-996c-ca231196a9c2`），担任独立审查者与 GitHub 发布通道
- **基线版本**：Batch39（GitHub `main` `5d94369`）

## 允许读取路径

- `AGENTS.md`
- `docs/ACTIVE_CONTEXT.md`
- `docs/development-status-plan-20261123-batch40.md`
- `docs/contracts/session-brief-v0.1.md`
- `src/market_intel/contracts/session_brief.py`
- `src/market_intel/report/session_brief.py`
- `src/market_intel/cli.py`
- `tests/test_session_brief.py`
- `collaboration/task-board.json`

## 允许写入路径（严格独占，不修改实现源码）

- `tests/test_batch40_session_brief_qa.py`（独立 QA 定向与对抗测试用例）
- `docs/verification/batch-40-review.md`（独立验收记录）
- 仅在 QA 全部通过后更新：
  - `collaboration/task-board.json`（将 `B40-SESSION-BRIEF` 与 `QA-B40` 状态更新为 `done`，补充 `evidence`）
  - `docs/ACTIVE_CONTEXT.md`（运行 `scripts/build-active-context.py` 重新生成）
  - `docs/development-status-plan-20261123-batch40.md`（补充 QA-B40 实测结论）

## 禁止修改路径

- `src/market_intel/**`（若发现缺陷，请记录复现用例并退回给 Antigravity 修复，勿直接改实现源码）
- `tests/test_session_brief.py`

## 重点独立审查项

1. **防前视与截点边界**：
   - 事件/证据/原始记录任一 `available_at` 晚于 `cutoff` 1 微秒是否严格被排除；
   - 非合成记录缺 `availability_receipts` 或 `committed_at` 晚于 `cutoff` 1 微秒是否严格被排除；
   - 空截点报告是否绝不回看截点后记录决定 `is_synthetic`，且明确声明无可用事件、不强行填充主题。
2. **双模板与契约防伪造**：
   - `validate_session_brief_manifest` 是否严格拒绝 `status != "degraded"`、`interpretations_count != 0`、`market_data_as_of != None`、缺失/多余字段、非法时区、非法日期（如闰年边界）、重复键 JSON、非标准 JSON 数字；
   - HTML 转义与 Markdown 注入防护（含 `<script>`、换行、方括号等不可信标题/引文字符）。
3. **原子归档、冲突保护与补版链**：
   - 同 `report_id` 内容冲突时绝不覆盖旧版 `brief.html`/`brief.md`/`manifest.json`；
   - 补版（`supersedes_report_id`）是否校验旧版完整性及 `report_type`/`market_session_date` 一致性，是否支持多级补版链（v3 → v2 → v1）与防环检测（v1 ↔ v2）；
   - `verify-session-brief` 全程只读（不修改数据库与产物目录），且篡改 `brief.html`、`brief.md`、`manifest.json` 或旧版产物任一字节均失败。
4. **重放与路径安全**：
   - `replay-session-brief` 在独立目录重放后的 `brief.html` 与 `brief.md` 字节哈希与原发布完全一致；
   - 符号链接、路径穿越、UNC 路径拒绝（视 Windows 权限条件验证）。

## 验收命令与发布清单

1. 运行独立 QA 定向测试与开发者测试：
   ```powershell
   & $py -X utf8 -m unittest test_batch40_session_brief_qa test_session_brief -v
   ```
2. 运行全量回归：
   ```powershell
   ./scripts/dev.ps1 test
   ```
3. **若发现阻断或缺陷**：不推送 GitHub，输出清晰问题清单与复现用例交回 Antigravity 修复。
4. **若全部通过**：
   - 写入 `docs/verification/batch-40-review.md`；
   - 更新 `collaboration/task-board.json` 与 `docs/ACTIVE_CONTEXT.md`；
   - 仅将 Batch40 明确清单文件提交并推送到 GitHub `a1ua/Global-Financial-Information-Gathering-` 的 `main` 分支（排除 `out/`、`tmp/`、凭证与无关文件）：
     - `src/market_intel/contracts/session_brief.py`
     - `src/market_intel/report/session_brief.py`
     - `src/market_intel/cli.py`
     - `docs/contracts/session-brief-v0.1.md`
     - `docs/development-status-plan-20261123-batch40.md`
     - `docs/verification/batch-40-review.md`
     - `docs/ACTIVE_CONTEXT.md`
     - `collaboration/task-board.json`
     - `collaboration/codex/QA-B40-task.md`
     - `tests/test_session_brief.py`
     - `tests/test_batch40_session_brief_qa.py`
   - 返回 GitHub `main` 新提交 SHA、QA 实测结果摘要及是否发现需下一批跟进的改进建议。
