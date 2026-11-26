# 受锁离线双模板简报执行器契约（v0.1）

本文定义 `ops-guarded-run-result/0.1` 及命令行入口 `ops-run-session-brief`，将 Batch41 单实例锁/运行台账/漏跑恢复规划与 Batch40 双模板降级简报渲染/只读验收集成为单步确定性离线执行器（面向 `OPS-01`、`RPT-02` 与 `QA-01` 纵贯回归）。本命令纯离线执行，不触发实网抓取、模型调用、行情访问或 OS 计划任务安装。

## 1. 执行顺序与安全边界

1. **前置校验（零写盘）**：在碰触任何锁或报告目录前，先校验全部参数（`report_type`、`market_session_date`、`cutoff`、严格规范 IANA `display_timezone`、`ttl_seconds`、布尔开关与 ID 格式）、工作区路径安全（拒绝 UNC 路径与符号链接/目录连接点）、`market.db` 存在性，以及现有 `ops/runs.jsonl` 完整性与 `run_id` 唯一性。
2. **原子单实例锁（`ops/run.lock`）**：
   - 若锁文件损坏：立即故障关闭（`status="blocked_corrupt_lock"`，`recorded_run=false`，CLI 退出码 `1`），绝不覆盖损坏锁；
   - 若存在未过期活跃锁（或存在过期锁且传入 `--no-recover-expired`）：不渲染报告、不覆盖锁，向 `ops/runs.jsonl` 追加 `outcome="skipped_locked"` 记录并返回 `status="skipped_locked"`（CLI 退出码 `2`）；
   - 若锁已过期且允许恢复：通过 `.stale-recovery.lock` 独占归档旧锁到 `ops/stale-locks/`，获锁并标记 `stale_lock_recovered=true`。
3. **受保护渲染与只读复验**：
   - 在 `try ... finally` 保护下执行 `render_session_brief(...)` 并立即以 `?mode=ro` 只读连接执行 `verify_session_brief(...)`；
   - 成功时向 `ops/runs.jsonl` 追加 `outcome="degraded"` 记录（带 `degraded_no_model`、`degraded_no_market_data`，按实附加 `synthetic_fixture`、`stale_lock_recovered`、`retrospective_catchup`），CLI 退出码 `0`；
   - 渲染或校验异常时（如证据损坏/缺失、同 ID 冲突、`generated_before_cutoff`）：不留 `.staging-*`，向 `ops/runs.jsonl` 追加 `outcome="failed_runtime"`（`report_id=null`）记录，返回 `status="failed_runtime"`（CLI 退出码 `1`）；
   - `finally` 块强制按本人 `lock_id` 调用 `release_run_lock`，保证正常与异常路径均不遗留孤儿锁。
4. **与漏跑规划及备份恢复联动**：
   - 正常发布并写入 `degraded` 后，`ops-plan-recovery` 自动将该 `(market_session_date, job_name)` 槽计为 `completed_slots`；
   - 失败写入 `failed_runtime` 或 `skipped_locked` 后，`ops-plan-recovery` 分别识别为 `previous_runtime_failure` 或 `previous_lock_conflict`；
   - `ops/backup.py`（`backup` / `verify-backup` / `restore`）兼容归档与校验 `session-brief-manifest/0.1`（同时校验并拷贝 `manifest.json`、`brief.html`、`brief.md`，调用 `verify_session_brief`），同时保持既有 `report-manifest/0.1` 备份行为 100% 兼容。

## 2. 本地命令

```powershell
# 受锁生成并只读验收盘前降级双模板简报
python -m market_intel ops-run-session-brief --workspace out/demo --report-type pre_market --session-date 2026-11-06 --cutoff 2026-11-06T00:30:00Z --run-id run_20261106_pre_1 --report-id pre_20261106_v1

# 补跑模式（附加 retrospective_catchup 原因码）
python -m market_intel ops-run-session-brief --workspace out/demo --report-type post_market --session-date 2026-11-06 --cutoff 2026-11-06T08:30:00Z --scheduled-for 2026-11-06T08:30:00Z --retrospective-catchup
```

## 3. 未验证与边界说明

- 本契约覆盖离线合成及既有受限来源元数据的受锁简报执行、故障锁释放、台账联动及备份/恢复/重放纵贯校验。
- 真实 Windows 计划任务注册、真实定时唤醒、真实模型调用与授权行情仍待对应外部前置解锁。
