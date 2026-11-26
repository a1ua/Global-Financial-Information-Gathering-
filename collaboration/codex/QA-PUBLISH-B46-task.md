# Codex 复核、发布 Batch46 及协作推进 Batch47 任务单（QA-PUBLISH-B46）

- **基线版本**：Batch45（718 项测试，714 通过，4 项 Windows 符号链接跳过）
- **本批交付**：Batch46（`B46-OPS-GUARDED-BRIEF` + `QA-B46`），已完成 2 轮独立对抗 QA 与 3 项真实多线程 Windows 压测，全量 `./scripts/dev.ps1 test` **741 项运行、737 通过、4 项 Windows 符号链接跳过、退出码 0**（详见 [batch-46-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-46-review.md) 与 [development-status-plan-20261126-batch46.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/development-status-plan-20261126-batch46.md)）。

## 请 Codex 执行的步骤

1. **只读复核 Batch46 改动**：
   - 检查 `git status` 与改动差异，确认排除 `out/`、`tmp/`、本地凭证与无关文件；
   - 可复跑 `./scripts/dev.ps1 test` 进行二次抽检。
2. **仅按以下白名单提交并推送 Batch46 到 GitHub `main`**：
   - `src/market_intel/ops/session_runner.py`
   - `src/market_intel/ops/scheduler.py`
   - `src/market_intel/ops/backup.py`
   - `src/market_intel/cli.py`
   - `docs/contracts/ops-guarded-session-brief-v0.1.md`
   - `docs/development-status-plan-20261126-batch46.md`
   - `docs/verification/batch-46-review.md`
   - `docs/ACTIVE_CONTEXT.md`
   - `collaboration/task-board.json`
   - `collaboration/codex/QA-PUBLISH-B46-task.md`
   - `tests/test_ops_session_runner.py`
   - `tests/test_batch46_ops_session_runner_qa.py`
3. **可选继续协作（Batch47 草案，仅在 Batch46 推送完成后开展）**：
   - 若用户要求继续离线推进，可与主控衔接 **Batch47**：将 Batch42–45 的事件冲突保留（`contradicts`）与 Batch40/46 的受锁简报衔接（例如离线只读冲突摘要检查器 `check-session-brief-conflicts` 或 `session-brief` 冲突提醒，不破坏 `session-brief/0.1` 兼容性）。
4. 返回 GitHub `main` 最新提交 SHA、复核结论及是否发现需跟进的改进项。
