# Batch40 开发交接（待独立 QA 验收与发布）

- **主导/实现方**：Antigravity (`antigravity_lead`)
- **独立 QA 与发布配合方**：ChatGPT / Codex (`codex_qa`，线程 `codex://threads/01a1b664-fa93-7883-996c-ca231196a9c2`)
- **当前状态**：`B40-SESSION-BRIEF` 与 `QA-B40` 均已完成并通过独立验收（`done`）。独立 QA 首轮发现 3 项缺陷（Markdown/HTML 注入绕过、`verify_session_brief` 语义清单篡改及 `watch_items_count` 失配、Windows NTFS 尾部空格时区放行），主控全部修复后独立 QA 复测全部通过（定向 30 项 29 通过 1 跳过，全量 `./scripts/dev.ps1 test` 679 项 675 通过 4 项 Windows 符号链接权限跳过，退出码 0）。验收记录见 [batch-40-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-40-review.md)。待后续统一交由 Codex 通道推送 GitHub `main`。

## 本批交付内容（`B40-SESSION-BRIEF`）

面向 `RPT-01` / `RPT-02` 的离线降级原型，新增盘前/盘后双模板简报契约 `session-brief-manifest/0.1` 与渲染/校验/重放流水线 `session-brief/0.1`（不影响既有 `evidence-brief/0.2`、`0.3` 及全部历史测试）：

- [session_brief.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/contracts/session_brief.py)：定义 `validate_session_brief_manifest`，强制校验 `pre_market`/`post_market`、`market_session_date`、`display_timezone`、`information_cutoff <= generated_at`、`status == "degraded"`、`market_data_as_of == null`、`interpretations_count == 0`、`watch_items_count >= 1`、严格原因码集合与双产物（`brief.html` + `brief.md`）SHA-256 映射。
- [session_brief.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/report/session_brief.py)：实现 `render_session_brief`、`verify_session_brief`、`replay_session_brief`，包含单次 SQLite 快照防前视、`availability_receipts.committed_at <= cutoff` 校验、引用与原文内容哈希闭包检查、三栏分离（已核验事实 / 空白模型解读 / 观察事项与缺口）、无主题不强填、原子临时目录重命名与失败清理、同 ID 冲突保护不覆盖旧版，以及 `supersedes_report_id` 补版链只读校验。
- [cli.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/cli.py)：新增 `session-brief`、`verify-session-brief`（只读数据库模式）、`replay-session-brief` 三个命令。
- [session-brief-v0.1.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/contracts/session-brief-v0.1.md)：契约与 CLI 使用文档。
- [test_session_brief.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/tests/test_session_brief.py)：12 项开发者单元与 CLI 回归测试。

## 开发者自测真实结果（2026-11-23）

- 定向测试：`& $py -X utf8 -m unittest test_session_brief -v` → **12 项运行、12 项通过**（耗时 2.475s，退出码 0）。
- 全量离线回归：`powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test`（指定 `MARKET_INTEL_PYTHON` 为本机 `OpenAI.CodexPrimaryRuntime.v26-1119-907-0` Python 3.12.14）→ **661 项运行、658 项通过、3 项因 Windows 符号链接权限跳过**（耗时 78.208s，退出码 0，日志见 `out/batch40-tests.log`）。
- CLI 端到端冒烟：`demo` → `session-brief` v1 → `verify-session-brief` v1 → `session-brief` v2 (`--supersedes`) → `verify-session-brief` v2 → `replay-session-brief` v2，全部退出码 0。

## 未验证项与主任务板边界

- 主任务统计维持不变：**10 项已完成 / 2 项进行中（`MKT-01`、`NLP-01`）/ 13 项待开发 / 1 项已取消**。
- 本批仅覆盖离线降级双模板原型，真实模型解读、真实授权行情时点、独立人工标注与宽窄屏人工抽检（`WB-03`）仍待验收。
- **待 Codex 执行**：独立审查与黑盒测试（`QA-B40`），确认无误后落盘 `docs/verification/batch-40-review.md`，将 `B40-SESSION-BRIEF` 与 `QA-B40` 更新为 `done`，刷新 `docs/ACTIVE_CONTEXT.md`，并发布本批变更到 GitHub `main`。
