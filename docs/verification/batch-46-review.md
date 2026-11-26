# Batch46 独立验收记录（QA-B46）

- **审查任务**：`QA-B46`（独立对抗审查 `B46-OPS-GUARDED-BRIEF`：受锁离线双模板简报执行器 `ops-run-session-brief` 及 `ops/backup.py` 双模板兼容加固）
- **审查日期**：2026-11-26
- **契约版本**：`ops-guarded-run-result/0.1`（`docs/contracts/ops-guarded-session-brief-v0.1.md`）、`session-brief-manifest/0.1`、`ops-lock/0.1`、`ops-run-record/0.1`、`ops-missed-run-plan/0.1`
- **最终验收结论**：**PASS（两轮独立 QA 闭环完成：第一轮检出 2 项高危并发/锁释放阻断缺陷与 1 项中危 Windows NTFS 并发路径缺陷退回修复；第二轮定向 41 项、三组无 Mock 真并发压力探针及全量 741 项离线回归全部通过）**
- **独立 QA 测试文件**：`tests/test_batch46_ops_session_runner_qa.py`（17 项独立对抗测试；两轮全程严格遵守写入边界，未修改 `src/market_intel/**`、`tests/test_ops_session_runner.py`、`collaboration/task-board.json` 或 `docs/ACTIVE_CONTEXT.md`）

## 一、两轮实测命令与真实结果

使用本机经验证的 Python 解释器：
`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1123-915-0_26.1123.915.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe`

### 第一轮（初审 — FAIL，检出 3 项真实并发缺陷）

1. **定向回归（独立 QA 17 项 + 作者 6 项 + 备份 18 项）**：
   - 命令：`& $py -X utf8 -m unittest test_batch46_ops_session_runner_qa test_ops_session_runner test_backup -v`
   - **真实结果**：共运行 **41** 项，耗时 **26.712s**，退出码 **1**（`failures=1, errors=1, skipped=1`；独立 QA 15 通过、1 失败、1 报错；作者 6/6 通过；`test_backup` 17 通过、1 跳过）。
2. **全量离线回归**：
   - 命令：`$env:MARKET_INTEL_PYTHON=$py; powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test`
   - **真实结果**：共运行 **741** 项，耗时 **116.526s**，退出码 **1**（`failures=1, errors=1, skipped=4`；既有 724 项 0 回归失败）。
3. **并发根因诊断探针**：
   - 15 轮 × 8 线程无预锁变长 `run_id` 探针复现 **2/15 轮**永久破坏 `ops/runs.jsonl`（残行 `26-11-06T00:30:05Z"}`）；10 轮 × 8 线程等长 `run_id` 探针复现 **2/10 轮**静默丢记录（8 返回 `recorded_run=True` 但台账仅 7 条）。
   - 100–150 轮锁释放 + 4 线程并发读探针无 Mock 复现 `release_run_lock` 抛出 `PermissionError [WinError 32]` 及 Windows NTFS delete-pending 态 `Path.resolve()` 返回 `C:\$Extend\$Deleted\<file_id>` 导致 `_safe_child_no_symlink` 误报 `ops_path_outside_workspace`。

### 第二轮（终验 — PASS，全部缺陷修复闭环且全绿通过）

1. **定向回归（独立 QA 17 项 + 作者 6 项 + 备份 18 项）**：
   ```powershell
   $py = "C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1123-915-0_26.1123.915.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe"
   $env:PYTHONPATH="src;tests"; $env:TEMP="$PWD\out\test-temp"; $env:TMP="$PWD\out\test-temp"
   & $py -X utf8 -m unittest test_batch46_ops_session_runner_qa test_ops_session_runner test_backup -v
   ```
   - **真实结果**：共运行 **41** 项，**40 项通过、1 项跳过**（既有 Windows `SeCreateSymbolicLinkPrivilege` 符号链接权限跳过）、**0 失败、0 错误**，耗时 **34.999s**，退出码 **0**。

2. **三组无 Mock Windows 多线程高并发压力探针**：
   - **探针 A（20 轮 × 8 并发受锁执行器 = 160 次变长 `run_id` 争用）**：`probe_a_errs=0`（0 异常、0 丢记录、0 台账损坏、`ops/` 仅余 `['runs.jsonl']`）。
   - **探针 B（15 轮 × 12 并发 `skipped_locked` 爆发 = 180 次同时写台账）**：`probe_b_errs=0`（每轮精确 12/12 记录、0 异常、释放持锁后 `ops/` 仅余 `['runs.jsonl']`）。
   - **探针 C（200 次 `acquire_run_lock`/`release_run_lock` 循环 + 4 线程持续 `inspect_run_lock`/`read_ops_status` 并发读）**：`probe_c_errs=0`（0 `PermissionError [WinError 32]`、0 `ops_path_outside_workspace`、0 异常）。
   - **总耗时**：**33.541s**，退出码 **0**。

3. **全量离线回归**：
   ```powershell
   $env:MARKET_INTEL_PYTHON = $py
   powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test
   ```
   - **真实结果**：共运行 **741** 项，**737 项通过、4 项跳过**（均为既有 Windows `SeCreateSymbolicLinkPrivilege` 符号链接权限受限跳过）、**0 失败、0 错误**，耗时 **133.531s**，退出码 **0**。

## 二、第一轮缺陷修复与复验闭环核查

1. **缺陷 1（高危 — 已修复并复验通过）：并发 `ops/runs.jsonl` 非原子追加丢记录与台账损坏**
   - **修复核查**：`src/market_intel/ops/scheduler.py` 在 `record_ops_run`（548–590 行）通过 `_atomic_create_file` 创建独占守卫 `ops/.runs-journal.lock`（最多 200 × 5ms 退避重试，超时报 `ops_run_journal_busy`，`finally` 通过 `_unlink_with_retry` 保证清理）串行化 `_load_run_journal(..., under_guard=True)` + 幂等/冲突检查 + `append/fsync` 全流程；`_read_bounded_bytes` 增加瞬时 `PermissionError` 重试；`_load_run_journal` 对无守卫并发读者在 `.runs-journal.lock` 瞬态存在时提供最多 6 次无撕裂重读，同时对真正损坏台账（无守卫或 `under_guard=True`）立即故障关闭。
   - **复验结果**：`test_concurrent_skipped_locked_burst_preserves_every_journal_record_without_corruption`、`test_concurrent_guarded_runs_zero_exceptions_zero_orphans_exact_journal_and_reports` 及探针 A（160 次）/ 探针 B（180 次）全部 **0 异常、0 丢记录、0 残留 `.runs-journal.lock`/`.lock-staging-*`**。
2. **缺陷 2（高危 — 已修复并复验通过）：`release_run_lock` 遇 Windows WinError 32 泄漏孤儿 `ops/run.lock`**
   - **修复核查**：`src/market_intel/ops/scheduler.py` 新增 `_unlink_with_retry(path, attempts=20, delay=0.005)`（87–97 行），并在 `release_run_lock`（477–497 行）中先对 `"busy"` 瞬态重读确认所有者 `lock_id`，再经 `_unlink_with_retry(lock_path)` 释放；同时统一用于 `.stale-recovery.lock` 与 `.runs-journal.lock` 清理。
   - **复验结果**：`test_guarded_run_release_lock_survives_transient_windows_sharing_violation` 与无 Mock 探针 C（200 次并发读写释放）全部通过，**0 孤儿锁泄漏**。
3. **缺陷 3（中危 — 已修复并复验通过）：Windows NTFS `$Extend\$Deleted` 瞬态导致 `_safe_child_no_symlink` 误报 `ops_path_outside_workspace`**
   - **修复核查**：`_safe_child_no_symlink`（100–126 行）逐段拒绝 `.`/`..`/`/`/`\`/`:` 与 `_linked(current)`，当 Windows `Path.resolve()` 瞬态返回 `$Extend\$Deleted\` 时最多退避重试 5 × 5ms 并核验父目录仍严格位于 `base_dir` 内。
   - **复验结果**：无 Mock 探针 C（4 并发读线程 + 200 次锁释放）与全部 UNC / NTFS 连接点安全用例均 **0 误报、0 绕过**。

## 三、五大独立审查域终验摘要

| 审查域 | 状态 | 实测覆盖与结果摘要 |
| --- | --- | --- |
| 1. 前置校验与零副作用 | **通过** | 缺失 `market.db`（空目录/不存在工作区/目录占位）、损坏 `ops/runs.jsonl`（断行/无尾换行/重复 JSON 键/目录占位）、已存在 `run_id`（无锁与持活跃锁两种场景）、非法 `report_type`、`2026-02-29`/全角日期、非规范时区（`"Asia/shanghai"`、`"UTC "` 等）、布尔/越界 `ttl_seconds`、非法 `cutoff`/`scheduled_for`/`now_utc`、`supersedes == report_id`（显式与自动生成）、UNC 路径（`\\server\share\ws`、`//server/share/ws`）及真实 Windows NTFS 目录连接点（工作区、祖先目录、`market.db`、`ops/`）全部在获锁前拒绝，工作区目录树字节与 `mtime_ns` 零变化。 |
| 2. 并发与锁生命周期 | **通过** | 真实多线程受锁执行争用、高并发 `skipped_locked` 爆发、WinError 32 瞬时共享冲突与并发读锁释放均做到 0 异常、0 丢记录、0 损坏台账、0 孤儿锁/守卫/临时文件残留；`--no-recover-expired` 对过期锁返回 CLI 退出码 `2`（`skipped_locked`、`lock_status="expired_lock_present"`）并原样保留过期锁；损坏锁（断 JSON/重复键/跨工作区 `workspace_sha256`/目录占位）返回 CLI 退出码 `1`（`blocked_corrupt_lock`）且零改写锁与台账。 |
| 3. 运行时失败、补版链与合成口径对齐 | **通过** | 冲突 `report_id` 失败为 `failed_runtime`（`published_report_conflict`）、保留旧版字节、无 `.staging-*`、释放锁并记台账（`report_id=None`）；未来 `cutoff` 触发 `generated_before_cutoff`（含过期锁恢复后失败正确携带 `stale_lock_recovered`）并干净释放锁；补版链 `--supersedes v1` 发布并只读验真 v1/v2、保留 v1 原样、跨类型补版拒为 `supplement_scope_mismatch`；纯非合成（`metadata_only`）与混合（`mixed_test_data`）工作区正确输出 `is_synthetic=False` 且不含 `"synthetic_fixture"`；空截点按 `--synthetic-empty` 精确对齐 `is_synthetic` 与原因码。 |
| 4. `ops/backup.py` 双模板兼容与防篡改 | **通过** | 同时含旧版 `report-manifest/0.1` 与新版 `session-brief-manifest/0.1` 补版链（v1+v2）的工作区备份、验真、隔离恢复与三份报告只读复验全部通过；`brief.md` 源端与备份端 1 字节篡改（含同步伪造 `backup-manifest.json` 甚至同步伪造报告 `manifest.json` 哈希）均被 `create_backup` / `verify_backup`（经 `verify_session_brief` 重算）拦截；语义篡改（`generated_at < cutoff`、改 `display_timezone`、改 `citation_check`、注入重复 JSON 键、删除被替代旧版 v1 并同步修改 `backup-manifest.json`）均被拦截；缺失 `brief.md` 在源端与备份端均被拒绝。 |
| 5. 端到端 CLI 退出码与 `ops-plan-recovery` 联动 | **通过** | CLI 退出码严格满足 `degraded=0`、`skipped_locked=2`、`blocked_corrupt_lock/failed_runtime/无效参数=1`；`ops-plan-recovery` 精确流转 `offline_or_missed` -> `previous_lock_conflict` -> `previous_runtime_failure` -> `completed_slots`，1 微秒防前视与未到点 `post_market` 防前视均准确。 |

## 四、未验证项与边界说明

- 本次独立验收覆盖离线受锁双模板简报执行器、高并发锁/台账一致性、故障锁释放、漏跑规划联动以及混合双模板备份/验真/恢复防篡改闭环。
- 真实 Windows 计划任务注册与定时唤醒、真实模型调用、授权行情接入与多日实盘连续运行仍待后续对应阶段外部前置解锁后单独验收。
- `B46-OPS-GUARDED-BRIEF` 已满足独立 QA 验收要求（**PASS**），可由主控更新任务板与活跃上下文并归档发布。
