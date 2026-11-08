# WB-05：模型预算节点独立失败案例与设计审查报告（终版）

| 项 | 值 |
|---|---|
| task_id | `WB-05` |
| status | `partial` |
| 项目目录 | `C:/Users/user/Documents/ChatGPT/市场信息抓取` |
| 基线 | `68e4702` |
| started_at_utc | `2026-11-08T06:03:05Z`（首个实测命令；会话上下文时间 06:01:10Z） |
| 初版写入 UTC | `2026-11-08T06:13:13Z` |
| 终版 finished_at_utc | `2026-11-08T07:59:34Z`（主控补充并入） |
| 子 Agent 真实调用 | **是（2 个，均完成并回传带签名的完整结论）** |
| 唯一写入文件 | `collaboration/workbuddy/results/WB-05-report.md`、`WB-05-results.json` |
| 本包运行测试数 | **0** |

> `partial` 的含义：7 项检查点审查、真实子 Agent 委派证据、两份交付文件均已完整产出；标记 partial 是因为本包按边界**未运行任何测试**，且审查对象在执行期间被其他执行者多次改写、多项发现已被修复，最终状态须由主控与 QA-B05 回收验收后决定（任务单第 15 行）。无工具不可用或额度不足，**不是 blocked**。

---

## 0. 本版修订说明（如实披露本包自身差错）

1. **初版 06:13:13Z 写入时，两个子 Agent 的完整回传尚未送达**，其 §2「子 Agent 关键结论摘要」为在等待期间写入的**未经核实的转述**，其中若干用例数值与子 Agent 实际结论不符。本版已删除该摘要，全部替换为真实回传内容（§2.2、§2.3）。这是本包自身差错，不隐去、不改写为「一直正确」。
2. 初版称「实现只读复核仅由主 Agent 追加、子 Agent 按边界未读代码」——**不准确**。两个子 Agent 均依据后续授权与 `WB-05-task.md:9` 追加了实现静态只读复核，并各自回传。本版已更正。
3. **实现文件在审查期间被并行改写多次**，初版基于 06:09Z 快照（client.py 425 行 / test_llm.py 324 行 / llm-client.md 89 行 / 30 项测试），终版基于 07:46:29Z 快照（458 / 460 / 92 行 / 38 项测试）。多项初版发现已被实现方修复并补回归测试，**本版逐条撤回**（§4）。
4. 两处事实错误已订正：① 北京时间 08:30 = **UTC 00:30**（30 分钟错位，不是与 UTC 日切重合）；② `docs/contracts-v0.1.md:22`「不把 null 转 0」约束的是输入/输出字段，`charged_cost` 恒为正的预留额，**不违反**该条，初版与子 Agent 初始报告对此有误引。
5. **两个子 Agent 均提交勘误 v2 并最终对齐、结论无矛盾**：A 撤回「SQLite 锁超时未映射稳定码」、把 C2 改为「已标注估算依据并在汇总层分列、缺行级状态字段」、C4 改为「文档已书面承认待办、实现未落地」；B 撤回「ISO 字符串比较违反契约 :17」、修正估算/结算口径、撤回对 :22 的误引。终版已全部纳入（§4、§6）。
6. **快照已冻结**：代码与文档在本次执行中至少迭代三次（30 → 31 → 38 项测试），继续追更会使 WB-05 证据持续漂移、不利于主控定稿。本包以 `07:46:29Z` 复核快照为最终依据，之后的实现变更不在本包结论范围内，须由主控/QA-B05 重新核对。
7. **主控 15:58 GMT+8 进度补充**已并入 §1、§2.1、§8：代码与 docs 已稳定、测试与独立 QA 复核已完成、`_strict_loads` 问题已交实现者最小修复。该等信息为**主控陈述、本包未实测**，按「静态发现 / 待核实」记录；不改动 `tests_run=0`、不改 `status`、不改产品、不新增审查任务。主控所述「30 项定向」与本包快照「38 项」口径不同，如实并列、不调和、不推断原因。

---

## 1. 结论摘要

1. **子 Agent 能力实测可用**：本版本 WorkBuddy 确实提供子 Agent 并行委派与消息回传。`docs/charter-v3.md:93`「不假定存在跨 Agent 消息接口」的待实测假设可据此更新（不据此推定存在 CLI 或后台常驻协作）。
2. **两个子 Agent 均真实执行**：`Explore` 类型、并行派发、各返回 `Spawned successfully` 与 agent_id/task_id，各自回传含 `SUBAGENT_SIGNATURE` 的完整结论，且都追加了实现静态只读复核。
3. **7 项检查点全覆盖**，每项给出离线可构造输入、预期断言、发现位置与建议断言（均标注「建议，未运行」）。
4. **审查产生了可核验的实际效果**：`docs/llm-client.md:90` 记载「WorkBuddy 后续审查发现解析器将具体错误码折叠成通用错误，已修复为保留 `duplicate_json_key` 和 `nonfinite_json`」，与本报告 06:07Z 的纯内存语义核验结论一致。本包**不主张因果归属**（无法证明是本次审查触发），仅记录时间线与同向修复事实。
5. **终版仍成立的高风险项**：换 `state_path` 即可重置当日额度（F-01）；崩溃遗留 `pending` 预留无释放/结算终态（F-02）。二者均属 QA-B05 关注的预算绕过/崩溃计费。
6. 全程未读凭证/环境变量/账户文件，**故意未读** `config/llm.example.json` 与 `docs/verification/batch-05-review.md`（保持独立性）；未用付费 API、未联网、未外发、未上传；未改产品/测试/Git/依赖/系统；未写入工作区记忆。
7. **主控进度补充（15:58 GMT+8，按陈述记录、本包未实测）**：代码与 docs 已稳定；30 项定向与 188 项全量测试已通过；独立 QA 已完成双进程 / 跨日 / 缓存污染复核；本包 06:07Z 发现的 `_strict_loads` 专用错误码被 `ValueError` 吞并问题已交实现者最小修复（与 07:46:29Z 快照 `client.py:51-52` 的 `except ModelError: raise` 及 `docs/llm-client.md:90` 修复记载同向）。上述均为**待核实的静态记录**：本包未运行测试、未读取 `docs/verification/batch-05-review.md` / `batch-05.md`、未验证 QA 复核结论，`tests_run` 仍为 0，`status` 仍为 `partial`。主控所述「30 项定向」与本包快照「38 项定向」口径不同，如实并列、不推断原因。

---

## 2. 真实子 Agent 委派证据（核心验收项）

### 2.1 派发与回执

| 项 | 子 Agent A | 子 Agent B |
|---|---|---|
| 名称 | `wb05-budget-auditor` | `wb05-state-auditor` |
| 类型 | `Explore`（只读） | `Explore`（只读） |
| 派发 UTC | `2026-11-08T06:04:45Z` | 同左（同一消息内并行派发） |
| 回执 | `Spawned successfully` | `Spawned successfully` |
| agent_id | `wb05-budget-auditor@_auto_5ee6109e-42eb-46eb-90e8-c88a23d3ca25` | `wb05-state-auditor@_auto_5ee6109e-42eb-46eb-90e8-c88a23d3ca25` |
| task_id | `agent-5fd5bdd1-95f8-4c67-a797-71da8d8c3c71` | `agent-9b5fdeb2-edc6-4358-895e-5ee3eff46678` |
| 检查点 | C1–C4 | C5–C7 + 契约一致性核对 |
| 结论 | 已回传（设计审查 + 实现静态只读复核） | 已回传（设计审查 + 实现静态只读复核 + 勘误 v2） |
| 签名 | `SUBAGENT_SIGNATURE: wb05-budget-auditor` | `SUBAGENT_SIGNATURE: wb05-state-auditor` |

派发后 `SendMessage` 共 5 条，均收到 `{"success":true,"message":"Message sent to ... inbox"}` 回执（要求回传证据 ×2、告知代码已生成并纳入只读复核 ×2、催促 B 立即回传 ×1）。`TaskOutput` 多次返回 `Status: running / This is a team member task; Inbox notifies when they finish`；框架自动通知显示两个子 Agent 均 `completed successfully`：`wb05-state-auditor` 多次任务 `Duration: 13m 4s` / `5m 17s` / `3m 13s` / `1m 3s`，`wb05-budget-auditor` `Duration: 85m 15s`。`07:59:34Z` 复查两个 task_id 均返回 `No task found / There are no running background tasks`，与框架 `completed` 通知一致；两个子 Agent 的真实结果（完整结论 + 勘误 v2 + 最终对齐）**已全部收取，无待收项**。**均为真实工具调用与真实返回，非主 Agent 自述代写。** 消息未附 UTC 时间戳，不编造精确回传时刻；可核验区间为 06:04:45Z 派发至 07:48:17Z 交付。

### 2.2 子 Agent A 真实回传要点（C1–C4）

- **C1**：`docs/contracts-v0.1.md:219` 是 R08 唯一定义；`:180` 把「预算预留状态」列为可变运行状态。离线用例：合成时钟 `2026-11-09T00:00:00Z`、cap 10000 token、已结算 9000，A/B 用 `threading.Barrier` 同时各 `reserve(800)`，期望 `granted` 恰 1、另一 `rejected`/`degraded`，`SUM(committed)+SUM(reserved)<=10000`。指出 `task-board.json` 把并发 worker/持久租约列为延后，与 R08 存在张力。
- **C2**：V2:139 要求「费用无法即时确定时显示估算值及依据，不伪装为结算值」；契约 `:22-23` 禁止把 null 当 0、未知枚举须显式。最危险路径是 catch 里 `cost=0` 且把 reserved 直接 commit 为 0。
- **C3**：`max_retries` 与每日上限并列（V2:139），V3:156「不自动无限重试」只约束次数；重试必须同样先过预留 gate，否则 C1 的原子预留被架空。
- **C4**：契约 `:180` 要求失败重跑幂等且不能靠回退整库恢复，但未要求重启 reconciliation；`batch-05-plan.md:7` 要求「重启恢复测试」而任务板验收清单未列重启/pending。崩溃用例：reserve 后 `os._exit`，重启后可用额度应为 200 而非 1000。
- **实现静态复核（其快照 client.py 427 行 / test_llm.py 339 行 / llm-client.md 89 行）**：确认 `BEGIN IMMEDIATE` + `SUM(charged_tokens)` + pending 全额计入 used（:283/:291/:294-297）规避 check-then-act 竞态；确认 `daily_budget_policy_changed`、每次 attempt 重新 `_reserve`、失败保留全额 charged、UTC 日按 reserve 时点归属不结转。指出当时 `sqlite3` 锁超时未映射稳定码、无 `cost_status/cost_basis` 字段、pending 无终态、重试 N 次扣 N×预留、账本无对象级 schema_version。
- **给主控 6 问**：账本落地是否走了后置契约升级；`ledger_lock_timeout` 是否需要；「保守按预留额当结算值」是否满足 V2:139；失败 attempt 是 release 还是 commit；pending 人工结算 SOP 与幂等键；Phase 0 限额数值与 `llm_calls/report_runs/job_runs` 三表结构未冻结、账本备份/对账归属工作包。

### 2.3 子 Agent B 真实回传要点（C5–C7 + 勘误）

- **C5**：契约 `:17` 要求比较前解析为时间；给出 23:59:58Z / 00:00:01Z / 整点 / 本地串 / 不同小数秒 / 时钟回拨的离线用例。指出「每日」边界（UTC 日 / Asia-Shanghai 交易日 / 滚动 24h）未在契约定义。
- **C6**：发现 V2:137 五类缓存键版本、任务板四类、batch-05 仅「版本缓存」三处不一致；实现静态复核确认 `sha256(b"model-request/0.1\0" + canonical_json(request))` 已把 `output_schema` + `schema_version` 纳入键，**实现层已覆盖输出模式版本、缓解验收文字遗漏**；但无独立 `output_mode_version` / `canonical_json_version` 字段，前缀硬编码。
- **C7**：契约 `:23` 未知枚举须显式 unknown/null；`:91` 要求保存原始输出与校验结果。实现复核指出：失败不写缓存（✓），但 `_finish(..., "failed")` 不传 output 导致**失败原始输出未留档**，与 `:91` 冲突；状态集仅 `{pending,succeeded,failed}`、无 degraded/待处理队列；错误码命名与 `contracts-implementation.md:85` 稳定码不一致；缓存命中不产生账本记录、无 `cache_hit` 审计列。
- **契约一致性三项**：R08 阶段口径属层次差异而非矛盾，但不得把 mock 并发写成 R08 通过；缓存键验收文字须补齐并同步契约 `:178`；本包须按任务单 `:13` 标注未运行测试、status 建议 partial。
- **勘误 v2（重要）**：撤回「ISO 字符串比较违反契约 :17」（新版用 `date.fromisoformat` / `instant()` 解析后比较）、修正「未区分估算值/结算值」（新增 `accounting_basis="configured_rate_estimate"` 与分列）、撤回对契约 `:22` 的误引、纠正北京 08:30 = UTC 00:30。并指出文档已书面化跨日归属、已承认并发同 key 双计费、提示注入评测属 NLP-02。

### 2.4 子 Agent 与快照差异（如实保留，不调和）

| 事实 | 子 Agent A 快照 | 子 Agent B 快照 | 主 Agent 快照 |
|---|---|---|---|
| `docs/llm-client.md` | 已生成（89 行） | 一度报告未出现，勘误后确认已生成 | 06:09Z 读到 89 行，07:46Z 读到 92 行 |
| `client.py` / `test_llm.py` | 427 / 339 行 | 427 / 339 行 | 425 / 324 行 → 458 / 460 行 |
| 定向测试数 | 31 项（文档自述） | 31 项 | 30 项 → 38 项 |

差异源于其他执行者并行写入的不同时点，非任何一方错误。本包不把任一快照冒充为唯一事实。

补充计数口径：终版 `wc -l` 实测 `458 / 460 / 92`，而两个子 Agent 与 Read 工具按编辑器行号记为 `459 / 461 / 93`。这是「末行无换行符时 `wc -l` 统计换行数比编辑器行号少 1」的**计数方式差异**，不是又一次版本迭代，不应误判为新的漂移。

---

## 3. 实际命令与时间（全部只读）

| UTC | 命令 | 输出/用途 |
|---|---|---|
| `06:03:05Z` | `date -u ... && date +"%Y-%m-%dT%H:%M:%S%z"` | `2026-11-08T06:03:05Z` / `14:03:05+0800` |
| `06:04:45Z` | `date -u ...` | 子 Agent 派发时刻 |
| 约 `06:07Z` | `python -B - <<'PY' ... PY` | 纯内存语言级语义核验，3 行 `-> raised=invalid_output_json` |
| `06:09:14Z` | `date -u ...` | 只读复核阶段 |
| `06:10:54Z` | `date -u ... && ls -1 ".../results/"` | 仅 `WB-01-report.md`、`WB-01-results.json` |
| `06:13:13Z` | `date -u ...` | 初版写入 |
| `07:46:29Z` | `date -u ... && wc -l client.py test_llm.py llm-client.md` | `2026-11-08T07:46:29Z`；`458 / 460 / 92`，合计 1010 行 |
| `07:48:17Z` | `date -u ...` | 终版交付 |

语义核验脚本仅用标准库 `json` 复现 `_strict_loads` 的异常继承关系，**未导入 `market_intel`、未运行 `tests/test_llm.py`、未写盘**（`-B` + stdin）。真实输出：

```
input='{"category":"macro","category":"other"}' -> raised=invalid_output_json
input='{"category":NaN}' -> raised=invalid_output_json
input='not-json' -> raised=invalid_output_json
```

其余为只读工具调用：Glob、Grep、Read。**未执行任何测试、构建、安装、Git、网络或上传命令。**

---

## 4. 版本漂移与撤回清单（终版核实于 07:46:29Z）

| 初版编号 | 初版结论 | 终版判定 | 修复证据 |
|---|---|---|---|
| F-04 | `duplicate_json_key`/`nonfinite_json` 被 `except ValueError` 吞并 | **撤回：已修复** | `client.py:51-52` 新增 `except ModelError: raise`；`test_llm.py:178` `test_specific_json_errors_preserve_reason_and_reservation`；`docs/llm-client.md:90` 明确记载该发现与修复 |
| F-06 | SQLite 锁超时未映射稳定码 | **撤回：已修复** | `client.py:269-278` → `ledger_busy`/`ledger_error` 且关闭连接；`test_llm.py:281`；`docs/llm-client.md:63` |
| F-07 | ISO 字符串比较与契约 `:17` 字面不符 | **撤回：已修复** | `client.py:296-301` `date.fromisoformat`、`:322-328` 公共 `instant()`；`test_llm.py:351` 不同小数秒精度回归；`docs/llm-client.md:63` |
| F-08 | 并发测试未真正竞争临界区 | **撤回：已补测** | `test_llm.py:259` `test_barrier_clients_compete_for_one_reservation` 用 `threading.Barrier(3)` |
| F-09 | `task-board.json` 验收清单漏输出模式版本 | **撤回：已补齐** | `task-board.json:323` 现含「输出模式及 schema 版本、schema 内容、参数和输出限制」 |
| F-11 | 估算占位与真实结算混在 `charged_*` 一列 | **大幅收窄** | `client.py:384` `accounting_basis`、`:455-458` `reserved_or_unknown_*` / `usage_reported_*` 分列；`docs/llm-client.md:61`；`test_llm.py:339`。仅保留「`charged_*` 列名仍易误读、且 `calls` 表缺行级 `cost_status` / `settled_cost` 状态字段」的低风险提示（子 Agent A 勘误 v2 同口径） |
| F-03 | 无效输出也重试且测试未覆盖 | **降级为观察项** | 设计已明示（`docs/llm-client.md:56`），并补 `test_llm.py:328` `test_repeated_invalid_schema_reserves_every_attempt_without_cache`；重试仍消耗全额预算，属待裁定的设计取舍而非隐藏缺口 |
| F-10 | UTC 日桶规则未书面化 | **降级** | `docs/llm-client.md:58` 已书面化；剩余问题仅是「未写入共享契约 `contracts-v0.1.md`」 |

> 说明：上述修复由其他执行者完成，本包**不主张因果归属**；`docs/llm-client.md:90` 提及「WorkBuddy 后续审查」与本报告 06:07Z 的核验同向，但无法证明是同一次传递。本包如实记录时间线。

---

## 5. 七个检查点：输入 / 预期 / 发现位置

> 均为离线 mock / 合成 fixture，「建议断言」**全部未运行**。

| ID | 检查点 | 可操作输入 | 预期结果 | 发现位置（终版行号） |
|---|---|---|---|---|
| C1 | 预算原子预留（R08） | 两线程 `Barrier` 同时各请求超出剩余额度 | 仅一笔预留成功，另一笔 `budget_exceeded` 且不调用 transport | `contracts-v0.1.md:219`、`:180`；`client.py:293-313`；`test_llm.py:229`、`:259`；`llm-client.md:50-59` |
| C2 | 超时后不确定费用 | transport 抛 `TimeoutError`，`max_retries=1`，无 usage | `failed`、`charged == reserved`，按 `configured_rate_estimate` 标注估算依据，不记 0、不伪装结算值 | V2:139；`client.py:403-404`、`:435`、`:455-458`；`test_llm.py:134`、`:339` |
| C3 | 失败重试上限 | `max_retries=5` + 恒定超时，`daily_tokens=1800` | 每次重新预留、有界；`budget_exceeded` 终止；失败 attempt 仍全额占预算 | V3:156；`client.py:396-438`；`test_llm.py:223`、`:328`；`llm-client.md:53-56` |
| C4 | 重启后的保留额度 | transport 抛 `KeyboardInterrupt` → 新建 client → `usage(day)` | `pending_calls=1`、后续被拒；且 R08「失败可释放或结算」应有终态入口 | `contracts-v0.1.md:180`、`:219`；`client.py:309-312`、`:315-344`、`:440-458`；`test_llm.py:371`；`llm-client.md:57`、`:77`、`:92` |
| C5 | UTC 跨日 | 23:59:58Z 预留、00:00:02Z 结算；naive / 非零偏移 / 不同小数秒 / 时钟回拨 | 按开始 UTC 日归属、跨午夜不结转；解析为时间后比较；回拨 `clock_regression` | `contracts-v0.1.md:17`、`:21`；`client.py:280-284`、`:296-301`、`:322-328`；`test_llm.py:351`、`:387`、`:397`；`llm-client.md:58`、`:63` |
| C6 | 缓存键版本覆盖 | 逐一改提示词/版本/规则/schema/参数/model/输出限制后重放 | 每次变更均 `cache_miss`；旧缓存不复用；命中不预留但可追溯 | V2:137；`task-board.json:323`；`client.py:363-394`；`test_llm.py:90` |
| C7 | 输出无效 JSON | `not-json`、顶层数组、非法枚举、额外字段、重复键、`NaN`、布尔 | 稳定错误码、`failed`、不写缓存、不静默升级枚举、保留预留 | `contracts-v0.1.md:23`、`:91`、`:229`；`client.py:40-54`、`:424-435`；`test_llm.py:169`、`:178` |

---

## 6. 终版仍成立的发现（静态只读复核，未运行测试）

| ID | 级别 | 发现 | 位置 | 输入 → 预期 |
|---|---|---|---|---|
| F-01 | **高** | 预算账本以 `state_path` 为边界，`ModelClient` 接受任意路径且仅 `mkdir`，换一个新账本文件即可获得全新当日额度；文档「改变配置不应换一个空账本规避累计预算」只是声明，代码无绑定，账本须放 `out/`/`data/` 亦未校验 | `client.py:231-238`、`:302`；`llm-client.md:59`、`:77` | 同日 `out/a.db` 耗尽后 `out/b.db` 成功 → 预期应有单一账本绑定或跨账本对账。关联 QA-B05 预算绕过 |
| F-02 | **高** | 崩溃遗留 `pending` 行无终态、无 reconcile/TTL/release/结算入口；`calls` 表与 `usage()` 仅能查询。文档 `:57/:77/:92` 已书面承认待办、实现未落地，故属**已知缺口而非隐藏缺陷**，人工结算 SOP 与幂等键仍缺；R08「失败可释放或结算」在崩溃场景仍未闭环，单次崩溃锁死当日剩余额度至 UTC 日切 | `client.py:246-253`、`:309-312`、`:315-344`、`:440-458`；`llm-client.md:57`、`:77`、`:92`；`contracts-v0.1.md:219` | 崩溃 → 重启 → `pending_calls=1` → 后续 `budget_exceeded`；建议补人工结算 SOP 与幂等键 |
| F-05 | 中 | 模型账本不在现有备份/恢复范围，文档自述「不能随证据快照回滚，否则预算会被重置」，且一致备份/异地恢复/真实账单对账仍列待完成；R10 与 G5 恢复演练口径需澄清 | `llm-client.md:77`、`:92`；`contracts-v0.1.md:221`、`:176`；`docs/backup-restore.md:37` | `backup → verify-backup → restore` 后比对 `usage(day)`；应纳入一致性范围或显式排除且禁止宣称整体可恢复 |
| F-14 | 中 | 失败原始输出未留档：`_finish(..., "failed", error=...)` 不传 `output` → `output_text=None`，与 `contracts-v0.1.md:91`「保存原始输出与校验结果」存在张力。文档 `:73` 明示「失败不保存原始响应或异常内容」为设计选择 | `client.py:435`；`llm-client.md:73`；`contracts-v0.1.md:91` | 构造无效输出后查 `calls.output_text` → 需主控裁定改实现、上层留档或显式写入契约例外 |
| F-15 | 中低 | `calls` 表无 `cache_hit` 审计列，缓存命中在 `_reserve` 前直接返回、不写账本，无法从账本追溯命中次数或核验「应否计费」；并发同 key 双未命中会各预留各计费（文档 `:65` 已书面承认） | `client.py:246-256`、`:385-394`；`llm-client.md:46`、`:65` | 命中后 `usage(day)` 不增但亦无记录 → 建议 `cache_hits` 计数或独立审计表 |
| F-16 | 中低 | 跨模块稳定错误码命名未统一：llm 用 `invalid_output_json`/`output_schema_mismatch`/`ledger_busy` 等，`contracts-implementation.md:85` 列 `invalid_enum`/`missing_or_unknown_fields` 等 | `client.py:40-54`、`:269-278`；`docs/contracts-implementation.md:83-87` | 建议主控裁定是否需统一码表或明确分域命名空间 |
| F-17 | 中低 | 交付路径口径仍不一致：`task-board.json:306-310` 写 `tests/llm/` + `config/llm.example.yaml`，`batch-05-plan.md:7` 写 `tests/test_llm.py` + `config/llm.example.json`；实际生成后者。且 NLP-01 `status: in_progress` 与 `accepted_scope`「independent review accepted this subset」并存 | `task-board.json:306-311`、`:317-319`；`batch-05-plan.md:7` | 建议主控统一路径与状态表述，避免验收清单错位 |
| F-19 | 中低 | Phase 0 实际限额数值与 V2:117 的 `llm_calls/report_runs/job_runs` 三表结构未冻结；实现用独立 SQLite 账本 `days/calls/cache` + `user_version=1`，无对象级 `schema_version`；契约 `:9` 把「真实预算预留账本」列为后置契约，落地是否走了契约升级/主控单点整合未知 | `client.py:239-258`；`task-board.json:318`；`contracts-v0.1.md:9`、`:225-229`；V2:117、:139 | 建议主控裁定账本字段集的版本归属与契约升级流程 |
| F-18 | 信息 | 状态集仅 `{pending,succeeded,failed}`，无 `degraded`/待处理队列/简报降级事件清单（V2:64、:72）；提示注入评测明确归 NLP-02（`llm-client.md:71`） | `client.py:309`、`:435`；`llm-client.md:71` | 属上层职责划分，记录以便 QA-B05 确认边界 |
| F-12 | 信息 | 实现文档 `:3`、`:90` 自述 38 项定向测试通过、独立审查与主控安装回归已验收；**本包未复跑、未采信为自身结果** | `docs/llm-client.md:3`、`:90`；`test_llm.py`（38 个 test 方法） | 由 QA-B05/主控留证；本包 `tests_run=0` |
| F-13 | 信息 | WorkBuddy 子 Agent / 跨 Agent 消息能力实测可用，charter 待实测假设可更新 | `docs/charter-v3.md:93`；`task-board.json` WB-05 条目 | 仅证明本版本具备并行委派与消息回传，不推定 CLI/后台协作 |

---

## 7. 契约一致性结论

1. **R08 阶段口径**：`contracts-v0.1.md:219`「并发真实调用前」+ `:208` MVP 先 R01–R03/R09–R10；`batch-05-plan.md:7` 要求离线并发预留测试、`:13` 不自动调用付费模型。属**层次差异而非矛盾**；`test_llm.py:259` 的 Barrier 双客户端为离线 mock，不得据此宣称 R08 真实并发门槛通过（`AGENTS.md:10`、`protocol.md:45`）。
2. **缓存键清单**：V2:137 五类 / `task-board.json:323` 已补齐 / 实现 `client.py:363-375` 已覆盖。**该不一致已闭环**；剩余仅为无独立 `output_mode_version`/`canonical_json_version` 字段、前缀 `"model-request/0.1"` 硬编码，键算法升级需改代码。
3. **UTC 日桶**：`llm-client.md:58` 已书面化「按开始 UTC 日归属、跨午夜结算原日、新尝试新日」，但**未写入共享契约**；按契约第 9 节由主控单点整合。注意北京 08:30 = UTC 00:30，盘前时点与日切相隔 30 分钟，跨日归属规则仍应明确。
4. **交付标注**：契约 `:229` 要求列运行命令、实际结果与已知缺口，且「未执行测试不得写成通过」。本包 `tests_run=0`，已显式标注；定向命令见 `llm-client.md:83-88`，由 QA-B05 复跑。
5. **后置契约落地**：`:9` 的「真实预算预留账本」已以独立账本落地，但字段集、估算口径、日桶规则尚未回写共享契约（F-19）。

---

## 8. 未验证项、限制与阻塞

1. 本包**未运行任何测试、构建、安装或 CI 命令**（`tests_run=0`）；`docs/llm-client.md:90` 的 38 项通过为实现者/主控自述，未经本包独立复跑。
2. 所有实现级结论均为**静态只读复核推断**；唯一实测为 06:07Z 的纯内存语言级语义核验，且该问题现已被修复（F-04 撤回）。
3. R08 真实并发门槛、真实供应商 HTTP 超时、usage/费用核实、模型抽取质量、G3 均未验收；`llm-client.md:92` 亦列供应商传输、真实 smoke、候选数上限、账本备份与人工对账为待完成。
4. **版本漂移**：审查对象由其他执行者并行改写，快照见 §0/§2.4。终版核实于 07:46:29Z，之后若有提交需重新核对。
5. 未读 `config/llm.example.json`（凭证规避），以及 `docs/verification/batch-05-review.md`、`docs/verification/batch-05.md`、`docs/verification/batch-05-workbuddy-triage.md`（保持独立性）。子 Agent 的 Glob 确认这三份验收文档存在，即 `docs/llm-client.md:3` 所称「已通过独立 38 项定向及主控最终安装回归验收」的引用对象；**本包与两个子 Agent 均未读取其内容**，是否构成独立验收由 QA-B05 与主控核验，本包不判断、不采信为通过结论。文档 `:3` 在本次执行中亦经历多次改写（离线实现已交付待独立验收 → 已通过独立 38 项定向及主控最终安装回归验收），进一步说明快照必须冻结。
6. 未验证 Git 状态、依赖清单、CI 与多进程锁在 Windows 文件系统下的实际行为；F-01 为静态推断，未做换账本实测。
7. 消息通道未附 UTC 时间戳，精确回传时刻未编造；初版曾含未经核实的转述，已在 §0 披露并于本版订正。
8. 仅写入两个结果文件；未修改产品/测试/Git/依赖/系统设置/其他任务文件，未写入工作区记忆。未读/输出凭证，未用付费 API、未联网、未外发、未上传。
9. 主控 15:58 GMT+8 补充的「30 项定向 + 188 项全量测试通过」「独立 QA 双进程/跨日/缓存污染复核」「`_strict_loads` 最小修复已交付」均为**主控陈述**，本包未运行测试、未读取验收文档、未验证 QA 结论，按「静态发现 / 待核实」记录；不改写 `tests_run=0`、不据此把 `status` 改为 `completed`。相应地，报告中 C1 并发、C5 跨日、C6 缓存污染相关的建议断言仍标注「建议，未运行」，即便主控称 QA 已复核，本包仍不将其写成自身实测结果。
10. **阻塞**：无硬性阻塞。`partial` 源于上述未验证项与验收权归属，非工具不可用或额度不足。

---

## 9. 交主控 / QA-B05 的待决问题

1. **F-01**：是否强制单账本绑定或跨账本对账，以关闭「换文件重置额度」这一预算绕过。
2. **F-02**：`pending` 预留的人工结算/释放终态归哪个工作包？R08「失败可释放或结算」在崩溃场景何时闭环、幂等键如何定义？
3. **F-14 / F-16 / F-19**：失败原始输出是否须留档（契约 `:91`）或写入契约例外；跨模块错误码是否统一；账本字段集与 UTC 日桶规则是否回写共享契约并升版本。
4. **F-05**：恢复演练（R10 / G5）是否把模型账本纳入一致性范围，或显式排除且禁止宣称整体可恢复。
5. **F-15 / F-17**：缓存命中是否需账本审计；统一任务板 `write_paths` 与 `status/accepted_scope` 表述。
6. **验收口径**：明确「离线 Barrier 并发验证」与 R08「并发真实调用前」门槛的区别；由主控确认 `docs/charter-v3.md:93` 的 WorkBuddy 跨 Agent 能力待实测假设可依本包证据更新。

---

## 10. 交付与自检

- 交付文件（仅此两项）：
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-05-report.md`
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-05-results.json`
- JSON 必需字段自检：`task_id`、`status`、`started_at_utc`、`finished_at_utc`、`subagent_used`（真实布尔 `true`）、`subagent_evidence`、`files_read`、`findings`、`checks_run`、`limitations` 均已填写。
- 未写入凭证或敏感环境变量；未包含任何未实际执行的命令输出或虚构的测试通过结论；已撤回的发现均列入 §4 并给出修复证据。
