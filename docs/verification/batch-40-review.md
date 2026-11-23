# Batch40 独立验收记录（QA-B40）

- **审查任务**：`QA-B40`（独立验收 `B40-SESSION-BRIEF`）
- **审查日期**：2026-11-23（复验完成于 2026-11-24）
- **契约版本**：`session-brief-manifest/0.1` / `session-brief/0.1`（`docs/contracts/session-brief-v0.1.md`）
- **最终验收结论**：**PASS（两轮独立 QA 完成：首轮发现 3 项缺陷退回，实现方修复后二轮复验全量通过）**
- **独立 QA 测试文件**：`tests/test_batch40_session_brief_qa.py`（18 项对抗与边界测试；审查全程未修改 `src/market_intel/**` 或 `tests/test_session_brief.py`）

## 一、两轮实测命令与真实结果

使用本机经验证的 Python 解释器：
`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe`

### 第一轮（初审 — FAIL，发现 3 项真实缺陷）

1. **定向回归**：`& $py -X utf8 -m unittest test_batch40_session_brief_qa test_session_brief -v`
   - 结果：共运行 **30** 项，耗时 **6.649s**，退出码 **1**（`failures=12, skipped=1`；开发者 12/12 通过，独立 QA 14 通过、1 跳过、3 个测试方法共 12 个 subTest 失败）。
2. **全量离线回归**：`$env:MARKET_INTEL_PYTHON=$py; powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test`
   - 结果：共运行 **679** 项，耗时 **79.611s**，退出码 **1**（`failures=12, skipped=4`；既有 661 项 0 回归失败）。

### 第二轮（修复后复验 — PASS）

1. **定向回归（独立 QA + 开发者测试）**：
   ```powershell
   $py = "C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe"
   $env:PYTHONPATH="src;tests"; $env:TEMP="$PWD\out\test-temp"; $env:TMP="$PWD\out\test-temp"
   & $py -X utf8 -m unittest test_batch40_session_brief_qa test_session_brief -v
   ```
   - **结果**：共运行 **30** 项，**29 项通过、1 项跳过**（Windows 账户无 `SeCreateSymbolicLinkPrivilege` / WinError 1314；同组 NTFS 目录连接点 `mklink /J` 测试实测通过），耗时 **6.658s**，退出码 **0**。

2. **全量离线回归**：
   ```powershell
   $env:MARKET_INTEL_PYTHON = $py
   powershell -ExecutionPolicy Bypass -File ./scripts/dev.ps1 test
   ```
   - **结果**：共运行 **679** 项，**675 项通过、4 项跳过**（均为 Windows 符号链接权限受限跳过），耗时 **77.932s**，退出码 **0**。

## 二、首轮发现缺陷与修复复核闭环

1. **缺陷 1（高危 — 已修复并复验通过）：`brief.md` Markdown 与原始 HTML 注入绕过**
   - 原问题：`src/market_intel/report/session_brief.py` 中 `_clean_md_inline` 未先转义 `\` 导致 `\[bypass\](...)` 绕过、未转义 `<`/`>` 导致原始 `<script>` 透传、`_format_md_quote` 未转义引文内 Markdown 链接/图片/HTML、`fact_summary` 置于行首可伪造 `## 二、模型解读（Interpretations）` 二级标题。
   - 修复核查：已新增 `_escape_md_text`（先转义 `\`，再转义 `<`、`>`、`[`、`]`、`` ` ``）与 `_escape_md_block_start`（转义行首 `#`、`-`、`*`、`+`、`=`、`~` 及有序列表前缀），统一覆盖 `_clean_md_inline`、`_clean_md_paragraph`（`fact_summary`）与 `_format_md_quote` 每一行。
   - 复验：`test_markdown_injection_protection_in_title_summary_and_quote` 全部 4 个对抗向量通过。

2. **缺陷 2（高危 — 已修复并复验通过）：`verify_session_brief` 未检出 `manifest.json` 1 字节语义篡改与 `watch_items_count` 失配**
   - 原问题：篡改 `manifest.json` 的 `sections.watch_items_count`、`market_session_date`、`run_id`、`report_type`、`information_cutoff`、`display_timezone` 或伪造产物并同步改写 `artifact_sha256` 均曾静默通过 `verify_session_brief`。
   - 修复核查：`validate_session_brief_manifest` 已新增 `sections["watch_items_count"] == len(reasons)` 校验（`watch_items_count_mismatch`）；`verify_session_brief` 在只读事务结束后于内存中执行 `_build_documents(...)`（零写盘），严格校验 `event_version_ids` 顺序、`watch_items_count` 及 `brief.html`/`brief.md` 双产物 SHA-256 与 `manifest["artifact_sha256"]` 一致（失配报 `published_artifact_manifest_mismatch`）。
   - 复验：二轮同步补充了“伪造 `brief.html` + 同步改写 `artifact_sha256`”与 `watch_mismatch_high` 对抗断言，`test_verify_detects_one_byte_semantic_manifest_tampering` 全部通过，且 `test_verify_is_strictly_read_only_api_and_cli` 确认 `verify_session_brief` 仍全程严格只读。

3. **缺陷 3（低危 — 已修复并复验通过）：Windows NTFS 下尾部空格/点 `display_timezone` 放行**
   - 原问题：Windows NTFS 自动裁剪尾部空格导致 `ZoneInfo("UTC ")`、`ZoneInfo("Asia/Shanghai ")` 被放行，破坏 POSIX 跨平台重放确定性。
   - 修复核查：`contracts/session_brief.py` 与 `report/session_brief.py` 均在调用 `ZoneInfo` 前拒绝首尾空白、任意空白字符、`\`、`..`、前导 `/` 及尾部 `/` 或 `.`。
   - 复验：二轮扩展覆盖 `"UTC "`、`" UTC"`、`"Asia/Shanghai "`、`"UTC."`、`"Asia/Shanghai."`、`"Asia\\Shanghai"`，`test_validate_manifest_rejects_whitespace_padded_timezone` 全部拒绝通过。

（注：首轮 `test_supplement_chain_v3_v2_v1_scope_mismatch_and_cycle_detection` 中手工构造循环补版夹具时仅向 `v1` 追加了 `"supplement_revision"` 而未同步递增 `v1["sections"]["watch_items_count"]`，二轮已按新契约补齐该夹具计数以准确触达 `supplement_cycle_detected` 检测，未弱化任何断言。）

## 三、四大独立审查域验收摘要

1. **防前视与截点边界（通过）**：
   - `raw`/`event`/`evidence` 任一 `available_at` 晚于截点 1 微秒严格排除；精确等于截点纳入；同 `event_id` 高版本晚 1 微秒不泄漏。
   - 非合成记录缺 `availability_receipts` 或 `committed_at` 晚于截点 1 微秒严格排除；`committed_at == cutoff` 纳入。
   - 空截点不回看截点后记录决定 `is_synthetic`，亦不受截点后损坏内容文件影响，明确声明无可用事件、不强行填充主题。
2. **契约防伪造与双模板转义（通过）**：
   - `validate_session_brief_manifest` 严格拒绝非 `degraded`、非零 `interpretations_count`、失配 `watch_items_count`、非空 `market_data_as_of`、多/缺字段、非法时区（含空白/尾部点/反斜杠）、非法日历日期（含非闰年 `2026-02-29`）、`generated_at < information_cutoff`、自引用补版及非法 `artifact_refs`/`artifact_sha256`，且不修改输入字典。
   - `verify_session_brief` 与 `replay_session_brief` 拒绝重复键 JSON（`duplicate_json_key`）及 `NaN`/`Infinity`/`-Infinity`（`nonfinite_json`）。
   - `brief.html` 与 `brief.md` 均对 `<script>`、换行、方括号、反斜杠绕过、引文链接/远程图片及行首块级标题伪造完成防护。
3. **原子归档、冲突保护、补版链与只读校验（通过）**：
   - 同 `report_id` 内容冲突或目标为常规文件时均拒绝覆盖且不残留 `.staging-*`。
   - `v3 → v2 → v1` 补版链校验通过且旧版只读不被覆盖；跨 `report_type`/`market_session_date` 被拒；循环补版（`v1 ↔ v2` 及 `v3 → v2 → v1 → v2`）触发 `supplement_cycle_detected`。
   - `verify_session_brief`（API 与 CLI）全程只读（`market.db` 与报告目录字节及 `mtime_ns` 零变更，无 `-wal`/`-shm` 残留），且对 `brief.html`、`brief.md`、`manifest.json`（语法与语义字段）、伪造产物+同步改写哈希及旧版产物 1 字节篡改均失败。
4. **确定性重放与路径安全（通过，1 项环境权限跳过）**：
   - 后续补录同事件更高版本及补版后，`replay_session_brief` 在独立目录重放的 `brief.html` 与 `brief.md` 字节哈希 100% 一致。
   - 路径穿越、非法 `report_id`、UNC 路径及 Windows NTFS 目录连接点（`mklink /J`）均被拒绝；原生符号链接测试因 Windows 无 `SeCreateSymbolicLinkPrivilege` 干净跳过。

## 四、未验证项与边界说明

- 本次为离线合成及受限元数据单元测试验收；真实模型推理、真实授权行情、`WB-03` 宽窄屏人工抽检，以及具备符号链接权限环境下的原生文件符号链接用例仍待对应条件具备后验证。
- 本批已满足独立 QA 验收要求，可由主控更新任务板与活跃上下文并按发布清单推送 GitHub `main`。
