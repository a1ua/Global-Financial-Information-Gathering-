# Codex 复核与 GitHub `main` 发布任务单（Batch40 + Batch41）

- **基线提交**：Batch39（GitHub `main` `5d94369`）
- **当前本地状态**：
  - `B40-SESSION-BRIEF` + `QA-B40` 已通过独立多轮对抗验收（[batch-40-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-40-review.md)）
  - `B41-OPS-RUNLOCK` + `QA-B41` 已通过独立 3 轮对抗验收与 360 线程并发压测（[batch-41-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-41-review.md)）
  - 全量 `./scripts/dev.ps1 test`：**701 项运行、697 通过、4 项 Windows 符号链接权限跳过、退出码 0**

## 请 Codex 执行的步骤

1. 只读复核工作区 `git status` 与改动差异，确认不包含 `out/`、`tmp/`、本地凭证或无关文件。
2. 如需二次抽检，可复跑：
   ```powershell
   ./scripts/dev.ps1 test
   ```
3. 仅按以下白名单文件提交并推送到 GitHub `a1ua/Global-Financial-Information-Gathering-` 的 `main` 分支（建议按 Batch40、Batch41 分两笔或单笔清晰 commit）：
   - **Batch40 文件**：
     - `src/market_intel/contracts/session_brief.py`
     - `src/market_intel/report/session_brief.py`
     - `docs/contracts/session-brief-v0.1.md`
     - `docs/development-status-plan-20261123-batch40.md`
     - `docs/verification/batch-40-review.md`
     - `collaboration/codex/QA-B40-task.md`
     - `tests/test_session_brief.py`
     - `tests/test_batch40_session_brief_qa.py`
   - **Batch41 文件**：
     - `src/market_intel/contracts/ops_schedule.py`
     - `src/market_intel/ops/scheduler.py`
     - `docs/contracts/ops-schedule-v0.1.md`
     - `docs/development-status-plan-20261124-batch41.md`
     - `docs/verification/batch-41-review.md`
     - `collaboration/codex/PUBLISH-B40-B41-task.md`
     - `tests/test_ops_scheduler.py`
     - `tests/test_batch41_ops_scheduler_qa.py`
   - **共享集成文件**：
     - `src/market_intel/cli.py`
     - `collaboration/task-board.json`
     - `docs/ACTIVE_CONTEXT.md`
4. 推送完成后返回最新 GitHub `main` 提交 SHA 及是否发现需在 Batch42 跟进的意见。
