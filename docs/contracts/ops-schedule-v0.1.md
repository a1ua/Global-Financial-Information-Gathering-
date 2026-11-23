# 离线调度、单实例锁与漏跑恢复契约（v0.1）

本文定义面向任务板 `OPS-01` 的离线内核契约与命令（`ops-lock/0.1`、`ops-run-record/0.1`、`ops-missed-run-plan/0.1`、`ops-windows-task-template/0.1`）。本版本纯离线确定性运行，**不自动安装 Windows 计划任务、不自动触发联网抓取或模型调用、不落盘任何凭证**。

## 1. 范围与安全边界

- **单实例锁（`<workspace>/ops/run.lock`）**：使用临时文件落盘 `fsync` + `os.link` 原子创建，防止并发重复触发双写或读到半写锁文件。
  - 未过期有效锁存在时返回 `status="locked"`（`reason_code="lock_held_active"`），绝不覆盖。
  - 锁文件损坏或 JSON 非法时默认故障关闭（`status="blocked_corrupt_lock"`，`reason_code="lock_corrupt_manual_check_required"`），绝不静默覆盖。
  - 已过期锁（`now_utc >= expires_at`）在 `recover_expired=True` 时，先原子重命名归档到 `<workspace>/ops/stale-locks/<lock_id>-<timestamp>-<rand>.json` 保留取证痕迹，再创建新锁并记录 `recovered_stale_lock_id`。
  - 释放锁必须提供匹配的 `lock_id`，所有者不匹配时抛出 `lock_owner_mismatch` 且不删除当前锁。
- **只追加运行台账（`<workspace>/ops/runs.jsonl`）**：每行一条经 `validate_ops_run_record` 校验的规范 JSON；同 `run_id` 同内容幂等返回，同 `run_id` 不同内容拒绝（`ops_run_id_conflict`）；任意损坏行或重复 `run_id` 故障关闭。
- **只读状态（`ops-status`）**：全程只读，绝不创建 `ops/` 目录或修改任何文件。
- **漏跑恢复规划器（`ops-plan-recovery`）**：全程只读、`auto_execute=false`。严格以 `evaluated_at`（`now_utc`）为时间截点：
  - 晚于 `now_utc` 的未来排班槽不纳入统计（防前视）；
  - 仅采纳 `finished_at <= now_utc` 的历史运行记录（点位可复现）；
  - 区分 `offline_or_missed`、`previous_network_failure`、`previous_runtime_failure`、`previous_lock_conflict`。
- **Windows 任务计划模板（`ops-render-task-template`）**：纯确定性 XML 1.2 渲染（`<Enabled>false</Enabled>`、`MultipleInstancesPolicy=IgnoreNew`、`StartWhenAvailable=true`、`Command=%MARKET_INTEL_PYTHON%`），不调用 `schtasks`，不写入任何密钥或用户凭证。

## 2. 契约字段摘要

### 2.1 `ops-lock/0.1`
- 精确字段：`schema_version`、`lock_id`、`job_name`、`run_id`、`workspace_sha256`、`pid`、`acquired_at`、`expires_at`、`ttl_seconds`、`status`、`recovered_stale_lock_id`。
- 约束：`ttl_seconds` 为 `30..86400` 整数且 `acquired_at + ttl_seconds == expires_at`；`workspace_sha256` 仅存工作区规范路径 SHA-256，不存原始路径或用户名。

### 2.2 `ops-run-record/0.1`
- 精确字段：`schema_version`、`run_id`、`job_name`、`market_session_date`、`scheduled_for`、`started_at`、`finished_at`、`outcome`、`reason_codes`、`report_id`、`lock_id`、`stale_lock_recovered`、`is_synthetic`。
- 约束：`pre_market`/`post_market` 必须提供合法日历日期 `market_session_date`；`finished_at >= started_at`；`outcome` 与 `reason_codes`、`report_id`、`stale_lock_recovered`、`is_synthetic` 必须语义一致。

### 2.3 `ops-missed-run-plan/0.1`
- 精确字段：`schema_version`、`evaluated_at`、`display_timezone`、`pre_market_local`、`post_market_local`、`window_start_date`、`window_end_date`、`scheduled_slots_checked`、`completed_slots`、`missed_slots`、`pending_recovery_actions`、`auto_execute`、`reason_codes`。
- 约束：`auto_execute` 固定为 `false`；`scheduled_slots_checked == completed_slots + missed_slots`；所有 `pending_recovery_actions` 的 `scheduled_for <= evaluated_at`。

## 3. 本地命令

```powershell
# 只读查看工作区锁与运行态（不创建目录或写盘）
python -m market_intel ops-status --workspace out/demo

# 原子获取与释放单实例锁
python -m market_intel ops-lock-acquire --workspace out/demo --job pre_market --run-id run_20261124_01 --ttl-seconds 900 --now 2026-11-24T00:30:00Z
python -m market_intel ops-lock-release --workspace out/demo --lock-id <lock_id>

# 追加一条已校验运行记录
python -m market_intel ops-record-run --workspace out/demo --input run_record.json

# 只读检测漏跑并输出补跑规划（支持 --session-dates 或 --calendar-file）
python -m market_intel ops-plan-recovery --workspace out/demo --session-dates 2026-11-23,2026-11-24 --now 2026-11-24T09:00:00Z

# 仅生成可审阅的 Windows Task Scheduler XML 模板（不安装）
python -m market_intel ops-render-task-template --job pre_market --task-name market_intel_pre_market --trigger-time 08:30 --workspace-rel data/live
```

## 4. 未验证与边界说明

- 本契约验证离线单实例锁、过期锁归档、运行台账、漏跑规划与 dry-run XML 模板渲染。
- 真实 Windows 任务计划安装注册、真实多日连续运行与真实断网恢复观察仍待 `OPS-01` 全范围及 `QA-02` 七交易日运行验收。
