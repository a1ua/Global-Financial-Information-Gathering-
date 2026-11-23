# Batch41 开发交接（含 Batch40 QA 闭环）

- **主控与实现方**：Antigravity (`antigravity_lead`)
- **独立 QA 审查方**：独立只读 QA 子 Agent（`QA-B40` / `QA-B41`，严格隔离源码写入权限）
- **GitHub 发布配合方**：ChatGPT / Codex（发布任务单见 `collaboration/codex/PUBLISH-B40-B41-task.md`）
- **当前状态**：`B40-SESSION-BRIEF`、`QA-B40`、`B41-OPS-RUNLOCK`、`QA-B41` 均已通过多轮对抗审查与全量离线回归并标为 `done`。

## 1. 本轮交付内容

### Batch40 独立 QA 闭环（`QA-B40`）
- 独立 QA 发现并复现 3 项缺陷，主控全部修复并经独立复测通过（[batch-40-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-40-review.md)）：
  1. `brief.md` Markdown 与原始 HTML 注入防护（先转义 `\`，再转义 `<`、`>`、`[`、`]`、`` ` ``，并防止行首块级标题/列表伪造）；
  2. `validate_session_brief_manifest` 增加 `watch_items_count == len(reasons)`，`verify_session_brief` 增加内存中 `_build_documents(...)` 交叉核验防止 `manifest.json` 1 字节语义篡改；
  3. 跨平台 `display_timezone` 校验，拦截 Windows NTFS 尾部空格/点放行。

### Batch41 离线调度内核交付（`B41-OPS-RUNLOCK`，面向 `OPS-01`）
- [ops_schedule.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/contracts/ops_schedule.py)：定义纯确定性契约校验器 `validate_ops_lock`（`ops-lock/0.1`）、`validate_ops_run_record`（`ops-run-record/0.1`）、`validate_ops_recovery_plan`（`ops-missed-run-plan/0.1`），强制严格 ASCII 日期/`HH:MM`、大小写敏感规范 IANA 时区、`ttl_seconds` 与 `expires_at` 精确一致及跨字段语义一致性。
- [scheduler.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/ops/scheduler.py)：
  - 原子单实例锁（`ops/run.lock`，`fsync` + `os.link` 原子创建、`.stale-recovery.lock` 独占保护过期锁归档防 TOCTOU、Windows `\\?\` 路径规范化与 `WinError 32` 共享冲突退避、跨工作区哈希校验、损坏锁故障关闭、所有者校验释放）；
  - 只追加运行台账（`ops/runs.jsonl` 幂等/冲突拒绝）与严格只读 `read_ops_status`；
  - 严格只读防前视漏跑规划器（`plan_missed_runs`，过滤未来排班槽与 `finished_at > evaluated_at` 记录，区分 4 类漏跑原因，支持 `scheduled-session-snapshot/0.1` 与 DST 校验）；
  - 纯 dry-run Windows Task Scheduler 1.2 XML 模板渲染器（`render_windows_task_template`，`<Enabled>false</Enabled>`、零凭证、不调用 `schtasks`）。
- [cli.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/src/market_intel/cli.py)：新增 `ops-status`、`ops-lock-acquire`、`ops-lock-release`、`ops-record-run`、`ops-plan-recovery`、`ops-render-task-template` 六个命令。
- [ops-schedule-v0.1.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/contracts/ops-schedule-v0.1.md)、[test_ops_scheduler.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/tests/test_ops_scheduler.py)、[test_batch41_ops_scheduler_qa.py](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/tests/test_batch41_ops_scheduler_qa.py)。

## 2. 真实测试与独立 QA 证据（2026-11-24）

使用本机已验证 Python 3.12.14（`OpenAI.CodexPrimaryRuntime.v26-1119-907-0`）：

- **Batch40 独立 QA 定向回归**：`test_batch40_session_brief_qa` + `test_session_brief` → **30 项运行、29 通过、1 项 Windows 符号链接权限跳过**（6.658s，退出码 0）。
- **Batch41 独立 QA 3 轮对抗验收**（共发现并闭环 4 项缺陷 + Windows `WinError 32` 共享冲突 + 3 项安全加固）：
  - 定向回归：`test_batch41_ops_scheduler_qa` + `test_ops_scheduler` → **22 项运行、22 通过**（6.644s，退出码 0）；
  - 额外并发压测：30 轮 × 12 线程（360 次并发过期锁争抢）→ **0 异常、0 误报损坏、0 双重获锁、0 临时文件残留**（退出码 0）；
  - 详细记录见 [batch-41-review.md](file:///C:/Users/user/Documents/ChatGPT/市场信息抓取/docs/verification/batch-41-review.md)。
- **全量离线回归**：`powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test` → **701 项运行、697 通过、4 项 Windows 符号链接权限跳过、0 失败**（85.418s，退出码 0）。

## 3. 主任务板边界、未验证项与下一步

- **主任务统计维持诚实不变**：`10` 已完成 / `2` 进行中（`MKT-01`、`NLP-01`）/ `13` 待开发 / `1` 已取消。
- **未验证项**：
  - `OPS-01` 真实 Windows 计划任务注册、真实断网与多日连续运行（`QA-02` 七交易日运行观察）；
  - `NLP-01`/`NLP-02` 真实 DeepSeek API 调用、真实账单与人工标注；
  - `MKT-01`/`MKT-02` 授权真实行情与真实交易会话；
  - `WB-03` 宽窄屏人工抽检与具符号链接权限环境下的原生符号链接用例。
- **下一批次建议（Batch42）**：`B42-NLP-CLUSTER`（面向 `NLP-03` 的确定性规则事件聚类、去重候选与 `contradicts` 冲突证据保留契约及流水线），纯离线可推进且与 Batch40/41 解耦。
