# Batch41 独立验收记录（QA-B41）

- **审查任务**：`QA-B41`（独立验收 `B41-OPS-RUNLOCK`，离线 `OPS-01` 调度、单实例锁与漏跑恢复内核）
- **审查日期**：2026-11-24
- **契约版本**：`ops-lock/0.1`、`ops-run-record/0.1`、`ops-missed-run-plan/0.1`、`ops-windows-task-template/0.1`（`docs/contracts/ops-schedule-v0.1.md`）
- **最终验收结论**：**PASS（三轮独立 QA 闭环完成：首轮发现 4 项缺陷退回，二轮验出残余 Windows WinError 32 共享冲突退回，三轮定向 + 压力探针 + 701 项全量离线回归全部通过）**
- **独立 QA 测试文件**：`tests/test_batch41_ops_scheduler_qa.py`（15 项独立对抗测试；审查全程未修改 `src/market_intel/**`、`tests/test_ops_scheduler.py`、`collaboration/task-board.json` 或 `docs/ACTIVE_CONTEXT.md`）

## 一、三轮实测命令与真实结果

使用本机经验证的 Python 解释器：
`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe`

### 第一轮（初审 — FAIL，发现 4 项真实缺陷）

1. **定向回归**：`& $py -X utf8 -m unittest test_batch41_ops_scheduler_qa test_ops_scheduler -v`
   - 真实结果：共运行 **21** 项，耗时 **4.020s**，退出码 **1**（`failures=8, errors=1`；开发者 7/7 通过，独立 QA 10 通过、3 方法共 8 子测试失败、1 方法报错）。
2. **全量离线回归**：`$env:MARKET_INTEL_PYTHON=$py; powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test`
   - 真实结果：共运行 **700** 项，耗时 **83.507s**，退出码 **1**（`failures=8, errors=1, skipped=4`；既有 686 项 0 回归失败）。

### 第二轮（复验 — FAIL，首轮主要缺陷与 3 项加固通过，检出残余 Windows 共享冲突）

1. **定向回归（独立 QA 15 项 + 开发者 7 项）**：
   - 真实结果：共运行 **22** 项，**20 项通过、2 项报错**（均为 `PermissionError [WinError 32]` 并发过期锁归档共享冲突），耗时 **6.028s**，退出码 **1**。
   - 本轮因定向回归稳定复现阻断错误，延后全量回归至第三轮。

### 第三轮（终验 — PASS）

1. **定向回归（独立 QA 15 项 + 开发者 7 项）**：
   ```powershell
   $py = "C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe"
   $env:PYTHONPATH="src;tests"; $env:TEMP="$PWD\out\test-temp"; $env:TMP="$PWD\out\test-temp"
   & $py -X utf8 -m unittest test_batch41_ops_scheduler_qa test_ops_scheduler -v
   ```
   - **真实结果**：共运行 **22** 项，**22 项全部通过（0 失败、0 错误、0 跳过）**，耗时 **6.644s**，退出码 **0**。

2. **附加高并发过期锁恢复压力探针**：
   - 30 轮 × 12 并发线程（累计 360 次并发过期锁争用），**0 异常、0 误报损坏、0 双获锁、0 临时/守卫文件残留**，退出码 **0**。

3. **全量离线回归**：
   ```powershell
   $env:MARKET_INTEL_PYTHON = $py
   powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test
   ```
   - **真实结果**：共运行 **701** 项，**697 项通过、4 项跳过**（均为既有的 Windows `SeCreateSymbolicLinkPrivilege` 符号链接权限受限跳过），耗时 **85.418s**，退出码 **0**。

## 二、缺陷与加固项闭环核查

1. **缺陷 1（高危 — 已修复并复验通过）：过期锁并发恢复 TOCTOU 双获锁与窃取活跃锁**
   - 修复核查：`acquire_run_lock` 新增原子独占守卫 `ops/.stale-recovery.lock`（`finally` 确保清理），在守卫内重读并复核过期状态、`stale_lock_id_collision`，完成归档并原子创建新 `run.lock`。
   - 复验：`test_concurrent_stale_lock_recovery_toctou_cannot_double_acquire_or_steal_active_lock` 通过，仅 1 线程获锁、旧锁仅归档 1 次、活跃锁不被窃取且无 `.stale-recovery.lock`/`.lock-staging-*` 残留。
2. **缺陷 2（高危 — 已修复并复验通过）：Windows 并发抢锁路径异常与 WinError 32 共享冲突**
   - 修复核查：新增 `_normalize_resolved` 剥离本地 `\\?\C:\...` 前缀（仍拒绝 `\\?\UNC\...`）；`_read_lock_file` 显式区分 `FileNotFoundError`（`missing`）、`IsADirectoryError`/目录占位（`corrupt`）与瞬时 `PermissionError`（5 次 5ms 退避重试，仍忙返回 `busy`）；`acquire_run_lock` 对 `missing`/`busy` 争用重试，并对 `os.rename(lock_path, archive_path)` 增加 8 次 Windows `PermissionError` 退避重试及外层回退重试。
   - 复验：`test_concurrent_acquire_fresh_workspace_has_single_winner_and_no_errors`、`test_concurrent_stale_lock_recovery_stress_never_false_corrupt`、`test_stale_lock_recovery_handles_transient_windows_sharing_violation` 及 30×12 压力探针全部通过。
3. **缺陷 3（中危 — 已修复并复验通过）：`validate_ops_run_record` 拒绝非 `succeeded` 携带 `normal_completion`**
   - 修复核查：`ops_schedule.py:259-260` 对 `outcome != "succeeded"` 统一拒绝 `"normal_completion"`。
   - 复验：`failed_network` / `failed_runtime` / `skipped_locked` / `degraded` 4 类对抗子测试全部抛出 `ContractError`。
4. **缺陷 4（中危 — 已修复并复验通过）：`validate_hhmm` / `validate_calendar_date` 严格 ASCII 数字**
   - 修复核查：`_DATE_RE` 与 `_HHMM_RE` 均改为显式 `[0-9]`。
   - 复验：全角 `"0８:3０"` 与阿拉伯-印度 `"0٨:30"` 均被拒绝。
5. **三项加固项（全部落地并纳入 QA 回归通过）**：
   - `validate_timezone_strict` 结合 `zoneinfo.available_timezones()` 拒绝 Windows NTFS 大小写不规范时区（`"Asia/shanghai"`、`"America/new_york"`、`"utc"`）。
   - `_read_lock_file` 校验 `workspace_sha256` 必须与当前工作区一致，跨工作区拷贝的 `run.lock` 故障关闭（`foreign_workspace_sha256` 用例通过）。
   - `_SAFE_REL_SEG_RE` 禁止 `workspace_rel` 段首 `-` 或 `.`（`"--now"`、`"-workspace"`、`".hidden"`、`"data/.hidden"`、`"data/-flag"` 均被拒）。

## 三、五大独立审查域验收摘要

1. **单实例锁、并发、损坏与过期锁安全（通过）**：
   - `expires_at - 1us` 严格保持 `active`（`locked`），`expires_at` 精确点为 `expired` 且 `recover_expired=True` 可原子归档恢复、`recover_expired=False` 原样保留。
   - 多线程新工作区抢锁、过期锁并发恢复 TOCTOU 与 Windows WinError 32 共享冲突均保持严格单胜者、零假损坏、零临时/守卫文件残留。
   - 非法 JSON、重复键、`NaN`、超 64KB、TTL 失配、布尔 `pid`、跨工作区哈希、非法 UTF-8 及目录占位均故障关闭且字节与 `mtime_ns` 零变更；`release_run_lock` 严格校验所有者；`run.lock` 不泄漏原始路径或用户名。
2. **只追加运行台账（`ops/runs.jsonl`）与只读 `ops-status`（通过）**：
   - `inspect_run_lock`、`read_ops_status`、`plan_missed_runs`（API 与 CLI）全程严格只读（空工作区不建 `ops/`，非空工作区文件字节与 `mtime_ns` 零变更）。
   - 残缺尾行、空行、重复 JSON 键、`NaN`、重复 `run_id`、同 `run_id` 载荷冲突均拒绝并保护原台账不被改写，支持精确幂等重放；跨字段与类型伪装契约校验全面通过。
3. **漏跑恢复规划器（`plan_missed_runs` / `ops-plan-recovery`）（通过）**：
   - `auto_execute=False` 且全程只读；排班槽与补跑 `finished_at` 均通过精确 1 微秒防前视校验。
   - 支持显式日期列表与 `scheduled-session-snapshot/0.1` 日历文件（拒绝错误 schema、空/重复日期及 `2026-02-29`，CLI 拒绝重复 JSON 键）；`America/New_York` 不存在夏令时 `2026-03-08 02:30` 被拒且 EST/EDT 转换精确；跨平台严格时区校验与 4 类漏跑原因（按时间序选取最新尝试）全部准确。
4. **Windows Task Scheduler XML 模板渲染（通过）**：
   - `auto_installed=False`、`dry_run_template_only=True`、触发器与设置均 `<Enabled>false</Enabled>`、`MultipleInstancesPolicy=IgnoreNew`、`StartWhenAvailable=true`、`Command=%MARKET_INTEL_PYTHON%`，零凭证/密钥，XML 1.2 可解析。
   - 拒绝 27 类危险 `workspace_rel`、13 类危险 `task_name` 及非交易日任务名；冲突 `--output` 拒绝覆盖、幂等写入通过、零 `.template-staging-*` 残留。
5. **路径安全（通过）**：
   - UNC 路径（`\\server\share\ws`、`//server/share/ws`）及 Windows NTFS 目录连接点（`mklink /J`，覆盖工作区、祖先目录、`ops/`、`ops/stale-locks/`、模板输出及 CLI `--input`/`--calendar-file`）全部拒绝。

## 四、未验证项与边界说明

- 本次验收覆盖离线单实例锁、运行台账、漏跑恢复规划与 dry-run XML 模板内核；真实 Windows 任务计划注册安装、多日真实连续运行与真实断网恢复观察仍待 `OPS-01` 全范围及 `QA-02` 阶段验收。
- 本批 `B41-OPS-RUNLOCK` 已满足独立 QA 验收要求（**PASS**），可由主控更新任务板与活跃上下文并归档发布。
