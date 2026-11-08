# WB-05：模型预算节点独立失败案例与设计审查报告

| 项 | 值 |
|---|---|
| task_id | `WB-05` |
| status | `partial` |
| 项目目录 | `C:/Users/user/Documents/ChatGPT/市场信息抓取` |
| 基线 | `68e4702` |
| started_at_utc | `2026-11-08T06:03:05Z`（首个实测命令；会话上下文时间为 06:01:10Z） |
| finished_at_utc | `2026-11-08T06:13:13Z` |
| 子 Agent 真实调用 | **是（2 个，均已完成并回传结论）** |
| 唯一写入文件 | `collaboration/workbuddy/results/WB-05-report.md`、`WB-05-results.json` |
| 未运行测试 | **是，本包未运行任何测试、构建或安装命令** |

> `partial` 的含义：任务单要求的 7 项检查点设计审查、真实子 Agent 委派与执行证据、两份交付文件均已完整产出；标记 partial 是因为存在**未验证依赖项**——本包按边界未运行任何测试，实现者自述的 30 项定向测试未经独立复跑，R08 的「并发真实调用前」门槛未验收，且审查对象在本次执行期间由其他执行者并行生成、仍处于变动中。按 WB-05 任务单第 15 行，最终完成状态由主控与独立审查者（QA-B05）回收验收后决定，本包不自行标记 `completed`。

---

## 0. 结论摘要

1. **子 Agent 能力已实测可用，无需写 partial/blocked 冒充。** 本包通过 WorkBuddy 的 Agent 委派能力真实派发 2 个 `Explore` 子 Agent，均返回 `Spawned successfully` 回执与 agent_id/task_id，随后各自回传带签名的完整结构化结论。这直接回答了 `docs/charter-v3.md:93`「WorkBuddy 作为能力待实测的额外执行端……不假定存在……跨 Agent 消息接口」中的待实测假设：本版本**确实提供**子 Agent 并行委派与消息回传能力，建议主控更新该假设。
2. **代码在审查期间生成，本包按任务单「若代码已出现，可只读复核」追加了实现复核。** 首次 Glob 时 `src/market_intel/llm/`、`tests/test_llm.py`、`docs/llm-client.md` 均不存在；约 06:06–06:09Z 期间陆续出现 `client.py`、`__init__.py`、`tests/test_llm.py`、`config/llm.example.json`、`docs/llm-client.md`。所有代码结论均为**静态只读复核**，未运行测试、未修改任何文件。
3. **7 个检查点全部覆盖**（C1 原子预留 / C2 超时不确定费用 / C3 重试上限 / C4 重启保留额度 / C5 UTC 跨日 / C6 缓存键版本 / C7 无效 JSON），每项均给出可操作的离线输入、预期断言、发现位置与建议测试断言。
4. **最高风险发现**：预算账本以 `state_path` 为边界，换一个账本文件可重置当日额度（F-01）；崩溃遗留的 `pending` 预留无释放/结算终态入口，R08「失败可释放或结算」在崩溃场景未闭环（F-02）。两者均属 QA-B05 明确要查的「预算绕过」。
5. **唯一有实测支持的代码级发现**：`_strict_loads` 中 `duplicate_json_key` / `nonfinite_json` 两个专用错误码被 `except (ValueError, ...)` 吞并成 `invalid_output_json`（F-04）。该结论来自**纯内存语言级语义核验**（`python -B -`，不导入项目模块、不运行测试、不写盘），不是项目测试结果。
6. 全程未读取凭证/环境变量/账户文件，**故意未读** `config/llm.example.json`（避免触碰凭证字段）与 `docs/verification/batch-05-review.md`（避免锚定、保持独立性）；未使用付费 API、未外发消息、未上传、未改产品/测试/Git/依赖/系统设置，也未写入工作区记忆文件。

---

## 1. 边界与执行方式

- **先读边界文件**：`collaboration/workbuddy/WB-05-task.md`、`collaboration/batch-05-plan.md`，再读 `docs/contracts-v0.1.md`（尤其 R08）。
- **写入范围**：仅本目录下 `WB-05-report.md` 与 `WB-05-results.json`。写入前 `ls -1` 确认目录仅有 `WB-01-report.md`、`WB-01-results.json`，未覆盖他人文件。
- **只读方式**：Read / Glob / Grep 工具；shell 仅执行 4 类只读命令（见 §3），不含 `git`、`pip`、构建、测试或任何写操作。
- **未运行测试**：按任务单「记录实际时间与命令；未运行测试明确标注」，`tests_run = 0`。`docs/llm-client.md:86` 中「实现者实际运行 30 项定向测试通过」是**实现者自述**，本包不据此认定通过，也未复跑。
- **避免影响独立性**：`docs/verification/batch-05-review.md`（QA-B05 独占产物）在 06:09Z 已存在，本包**未读取**其内容。
- **凭证规避**：`config/llm.example.json` 已生成但**未读取**；未读取任何 `.env`、账户、令牌或环境变量文件；语义核验脚本中不含任何真实凭证。

---

## 2. 真实子 Agent 委派证据（本包核心验收项）

### 2.1 派发与回执

| 项 | 子 Agent A | 子 Agent B |
|---|---|---|
| 名称 | `wb05-budget-auditor` | `wb05-state-auditor` |
| 类型 | `Explore`（只读探索型） | `Explore`（只读探索型） |
| 派发 UTC | `2026-11-08T06:04:45Z` | `2026-11-08T06:04:45Z` |
| 派发方式 | 同一次并行调用，两个独立 Agent 任务 | 同左 |
| 工具回执 | `Spawned successfully` | `Spawned successfully` |
| agent_id | `wb05-budget-auditor@_auto_5ee6109e-42eb-46eb-90e8-c88a23d3ca25` | `wb05-state-auditor@_auto_5ee6109e-42eb-46eb-90e8-c88a23d3ca25` |
| task_id | `agent-5fd5bdd1-95f8-4c67-a797-71da8d8c3c71` | `agent-9b5fdeb2-edc6-4358-895e-5ee3eff46678` |
| 承担检查点 | C1–C4（预算/并发/计费/重启） | C5–C7 + 契约一致性核对 |
| 结论回传 | **已回传完整结构化结论** | **已回传完整结构化结论** |
| 签名行 | `SUBAGENT_SIGNATURE: wb05-budget-auditor` | `SUBAGENT_SIGNATURE: wb05-state-auditor` |

两个子 Agent 的 prompt 均为自包含任务书（含项目根、基线、必读文件、逐项输出格式、硬性只读边界、禁止读凭证/联网/付费 API/写文件）。派发后通过 `SendMessage` 共发出 5 条消息并全部收到 `{"success":true,"message":"Message sent to ... inbox"}` 回执：① 要求回传完整结论作为证据（2 条）；② 告知代码已生成、允许纳入只读复核（2 条）；③ 催促 B 立即回传当前结论（1 条）。`TaskOutput` 在派发后多次返回 `Status: running / This is a team member task; Inbox notifies when they finish`，随后两个子 Agent 的结论经消息通道实际送达。**以上均为真实工具调用与真实返回，非主 Agent 自述代写。**

> 时间说明：消息通道未在回传内容中附加 UTC 时间戳，故不编造精确回传时刻；可核验区间为 `06:04:45Z`（派发）至 `06:13:13Z`（交付）之间。

### 2.2 子 Agent A 关键结论（摘要，逐字保留要点）

- **C1/R08**：`docs/contracts-v0.1.md:219` 是唯一 R08 定义；`:180` 将「预算预留状态」列为可变运行状态；`:176` 将已发布 ReportManifest 列为不可变对象、失败不得删除账本重置。`market-intel-agent-dev-plan-v2-20261107.md:139` 定义 5 类预算字段、预留、降级与「估算值及依据」。给出离线并发用例：固定 UTC 时钟 23:59:58Z，剩余 100 token / 100 microUSD，A、B 各预估 60+40=100 token 与 100 microUSD，期望仅一笔预留成功、另一笔 `budget_exceeded`。
- **C2**：契约未强制「超时仍计费」，`charged_cost` 缺 `estimated / unknown / settled` 标记（`:22-23` 禁止把 null 当 0）；估算需带依据（`:229`）。
- **C3**：`max_retries` 与「每日金额/token 上限」并列（V2:139），但 V3:156「不自动无限重试」只约束次数、未定义每次重预留；重试必须同样先预留（`:139`、`:180`）。
- **C4**：`:180` 最早概括「失败重跑幂等、不能靠回退历史库恢复」，但未要求重启 reconciliation；`batch-05-plan.md:7`「重启恢复测试」与 `task-board.json:318` 验收清单均**未列重启/pending**。建议挂起预算按 `attempt_start_utc` 归属、跨日不得继承或静默清零（V2:83 盘前 08:30 北京 ≈ UTC 00:00）。
- **给主控 6 问**：R08 预算单位/取整与 `fixed precision decimal` 如何落地；`estimated/charged/settled` 单列三态还是 `charge_basis`；重预留是否计入当日上限；重启 reconciliation 归属包；R08 验收命令与证据格式；「并发真实调用前」与「离线并发预留测试」的验收口径。

### 2.3 子 Agent B 关键结论（摘要，逐字保留要点）

- **C5**：`docs/contracts-v0.1.md:17` 要求「比较前解析为时间，不能依靠任意格式字符串排序」；额度按「每日」隐含 UTC 自然日但 `:133`、`:190` 明确不使用模型开始时间作评价起点。给出 23:59:58Z / 00:00:02Z 跨日用例与 Asia/Shanghai 08:00 反例（V2:83）。
- **C6**：发现**缓存键版本清单口径不一致**——V2:137 为五类（内容/模型/提示词/规则/**输出模式版本**）、`task-board.json:318` 与 V3 中文列为四类（输入/模型/提示词/规则，**漏输出模式版本**）、`batch-05-plan.md:7` 仅写「版本缓存」。结论：以任务板为权威状态源会漏验收，须把「输出模式/schema 版本」补进验收清单并同步 `contracts-v0.1.md:178`。
- **C7**：`:23` 未知枚举需显式 `unknown/null` 或契约升级，不能静默创造新枚举；`:91`、`:229`、V2:129 要求保存原始输出与校验结果、原文没有的字段留空、无证据事实拒收。给出 7 种无效输出样例与「不写缓存 / 不自动升级枚举 / 保存原始输出与校验结果」断言。
- **契约一致性核对**：R08 在 `:219` 标「并发真实调用前」、`:208` 规定 MVP 先 R01–R03/R09–R10，而 batch-05 要求 NLP-01 离线并发预留测试；结论为**层次差异而非矛盾，但不得把 mock 并发写成 R08 通过**（`AGENTS.md:10`、`protocol.md:45`）。并建议本包按 `WB-05-task.md:13` 明确标注未运行测试、按 `docs/llm-client.md` 提供的定向命令由 QA-B05 复跑，status 建议 `partial`。

---

## 3. 实际执行的命令与时间（全部只读）

| UTC | 命令 | 真实用途/输出 |
|---|---|---|
| `06:03:05Z` | `date -u +"%Y-%m-%dT%H:%M:%SZ" && date +"%Y-%m-%dT%H:%M:%S%z"` | `2026-11-08T06:03:05Z` / `2026-11-08T14:03:05+0800` |
| `06:04:45Z` | `date -u +"%Y-%m-%dT%H:%M:%SZ"` | 子 Agent 派发时刻 |
| `06:09:14Z` | `date -u +"%Y-%m-%dT%H:%M:%SZ"` | 只读复核阶段 |
| `06:10:54Z` | `date -u ... && ls -1 ".../collaboration/workbuddy/results/"` | 输出仅 `WB-01-report.md`、`WB-01-results.json` |
| `06:13:13Z` | `date -u +"%Y-%m-%dT%H:%M:%SZ"` | 交付时刻 |
| 约 `06:07Z` | `python -B - <<'PY' ... PY`（纯内存语义核验，见 F-04） | 3 行 `-> raised=invalid_output_json` |

语义核验脚本仅用标准库 `json` 复现 `_strict_loads` 的异常继承关系，**未导入 `market_intel` 任何模块、未运行 `tests/test_llm.py`、未写盘**（`-B` 且脚本从 stdin 输入）。真实输出：

```
input='{"category":"macro","category":"other"}' -> raised=invalid_output_json
input='{"category":NaN}' -> raised=invalid_output_json
input='not-json' -> raised=invalid_output_json
```

另有只读工具调用：Glob（全项目 `**/*.{py,md,json,toml,yaml,yml}` 一次；llm 相关路径三次）、Grep（全项目预算关键词一次；`client.py` 函数/事务关键词一次）、Read（§4 所列文件）。**未执行任何测试、构建、安装、Git、网络或上传命令。**

---

## 4. 实际读取的文件（files_read）

`collaboration/workbuddy/WB-05-task.md`、`collaboration/batch-05-plan.md`、`docs/contracts-v0.1.md`、`collaboration/protocol.md`、`collaboration/workbuddy/results/WB-01-report.md`、`collaboration/workbuddy/results/WB-01-results.json`、`collaboration/task-board.json`（第 292–336、700–731 行）、`docs/PROJECT_CONTEXT.md`、`docs/charter-v3.md`（第 70–97 行）、`docs/development-backlog-v3.md`（经 Grep）、`docs/contracts-implementation.md`（第 95–104 行）、`docs/environment-baseline.md`、`AGENTS.md`、`market-intel-agent-dev-plan-v2-20261107.md`（第 122–145 行）、`market-intel-agent-dev-plan-v3-20261107.md`（经 Grep）、`docs/backup-restore.md`（经 Grep）、`README.md`（经 Grep）、`src/market_intel/llm/__init__.py`、`src/market_intel/llm/client.py`、`tests/test_llm.py`、`docs/llm-client.md`。

**明确未读**：`config/llm.example.json`（凭证规避）、`docs/verification/batch-05-review.md`（保持独立性）、任何凭证/账户/环境变量文件。

---

## 5. 七个检查点：可操作输入 / 预期结果 / 发现位置

> 所有测试均为**离线可构造**的 mock / 合成 fixture 建议，不依赖真实付费 API。以下「建议断言」**均未运行**。

| ID | 检查点 | 可操作输入 | 预期结果 | 主要发现位置 |
|---|---|---|---|---|
| C1 | 预算原子预留（R08） | 固定 UTC 时钟 23:59:58Z，剩余 100 token/100 microUSD，两线程同时各请求 60+40 | `BEGIN IMMEDIATE` 串行化，仅一笔成功，另一笔 `budget_exceeded` 且不调用 transport | `contracts-v0.1.md:219`、`:180`；`client.py:281-296`；`tests/test_llm.py:210-238`；`llm-client.md:50-59` |
| C2 | 超时后不确定费用 | transport 抛 `TimeoutError`，`max_retries=1`，返回无 usage | 每笔 `status=failed`、`charged_cost == reserved_cost`，标记 `estimated/unknown`，不得写成真实结算值、不记 0 | V2:139；`contracts-v0.1.md:22-23`、`:229`；`client.py:378-379`、`:409-410`；`tests/test_llm.py:130-140` |
| C3 | 失败重试上限 | `max_retries=5` + 恒定超时，`daily_tokens=1800` | 重试次数 ≤ 上限且每次重新预留；耗尽时 `budget_exceeded`；`error_code` 保留原始超时原因 | V3:156；`client.py:371-413`；`tests/test_llm.py:204-208`；`llm-client.md:53-56` |
| C4 | 进程重启后的保留额度 | transport 抛 `KeyboardInterrupt` 模拟崩溃 → 新建 `ModelClient` → `usage(day)` | `pending_calls=1`、后续调用被拒；且存在人工结算/释放终态（R08） | `contracts-v0.1.md:180`、`:219`；`client.py:296`、`:300-321`、`:417-426`；`tests/test_llm.py:240-249`；`llm-client.md:57`、`:88` |
| C5 | UTC 跨日 | 23:59:58Z 预留、00:00:02Z 结算；再测 `Asia/Shanghai` naive datetime | 按开始 UTC 日归属、跨午夜仍结算原日；naive/非零偏移时钟被拒；时钟回退 `clock_regression` | `contracts-v0.1.md:17`、`:21`；`client.py:267-271`、`:275`、`:283-284`、`:305`；`tests/test_llm.py:256-270`；`llm-client.md:58` |
| C6 | 缓存键版本覆盖 | 逐一改 `system_prompt`/`prompt_version`/`rules_version`/`schema_version`/`parameters`/`output_schema`/`model`/`max_output_*` | 每次变更均 `cache_hit=False`；旧版本缓存不得被复用；缓存命中不预留但不构成预算绕过 | V2:137；`task-board.json:318`；`client.py:341-369`；`tests/test_llm.py:86-99`；`llm-client.md:46` |
| C7 | 输出无效 JSON | `not-json`、`[]`、`{"category":"wrong"}`、额外字段、重复键、`NaN`、`true`、`{"a":1}\n{"a":2}` | 全部 `ModelError`、`status=failed`、`output_text IS NULL`、不写缓存、不静默升级枚举、不重试至无限 | `contracts-v0.1.md:23`、`:91`、`:229`；`client.py:38-50`、`:399-410`；`tests/test_llm.py:165-172` |

---

## 6. 实现只读复核发现（代码于审查期间生成，静态推断，未运行测试）

| ID | 级别 | 发现 | 位置 | 可操作输入 → 预期 |
|---|---|---|---|---|
| F-01 | **高** | 预算账本以 `state_path` 为边界：换一个新账本文件即可获得全新当日额度。文档「改变配置不应换一个空账本规避累计预算」是声明，代码无强制绑定；账本须放 `out/`/`data/` 也未校验 | `client.py:229-234`、`:285`；`llm-client.md:59`、`:73` | 同日用 `ModelClient("out/a.db")` 耗尽额度后 `ModelClient("out/b.db")` 成功 → 预期应有单一账本绑定/跨账本对账，不应重置。关联 QA-B05「预算绕过」 |
| F-02 | **高** | 崩溃遗留 `pending` 行无终态转换入口：Grep 确认 `client.py` 无 `release`/`reconcile`/`settle` 方法，`_finish` 只接受 `pending→终态` 但仅由 `generate` 内部调用；`usage()` 仅能查询。设计文档已明示为**待完成项**，故属已知缺口而非隐藏缺陷，但 R08「失败可释放或结算」在崩溃场景未闭环，单次崩溃锁死当日剩余额度至 UTC 日切 | `client.py:296`、`:300-321`、`:417-426`；`llm-client.md:57`、`:88`；`contracts-v0.1.md:219` | 崩溃 → 重启 → `pending_calls=1` → 后续 `budget_exceeded`；建议补人工结算入口与状态字段 |
| F-03 | 中 | 无效 JSON / schema 违规也走有界重试（`except ModelError` 后 `retryable` 仍为 True），每次重新预留并保留全额；对确定性结构失败重试无收益且放大预算消耗。现有 `test_invalid_json_schema_and_nonfinite_fail_without_cache` 用 `max_retries=0`，**未覆盖**重试路径 | `client.py:371-413`；`llm-client.md:56`（已明示该设计）；`tests/test_llm.py:165-172` | `max_retries=2` + 恒定 `'{"category":"wrong"}'` → 应有 3 笔 `failed` 且各扣全额，或应区分为「不可重试」；需明确取舍并补断言 |
| F-04 | 中 | **有实测支持**：`ModelError(ValueError)`，`_strict_loads` 内 `duplicate_json_key` / `nonfinite_json` 经 `except (ValueError, ...)` 被吞并成 `invalid_output_json`，专用失败原因丢失；测试仅断言 `assertRaises(ModelError)` 未断言错误码 | `client.py:14`、`:38-50`；`tests/test_llm.py:165-172`；`llm-client.md:67`；§3 语义核验输出 | 输入重复键 / `NaN` → 预期 `duplicate_json_key` / `nonfinite_json`，实际（语言级核验）均为 `invalid_output_json`。影响 `contracts-v0.1.md:229`「失败原因」留档粒度 |
| F-05 | 中 | 模型账本不在现有备份/恢复范围，文档自述「不能随证据快照回滚，否则预算会被重置」；R10 与 G5 恢复演练的验收口径需相应澄清——恢复后预算状态应与源一致，或明确列为不覆盖且不得宣称整体可恢复 | `llm-client.md:73`、`:88`；`contracts-v0.1.md:221`、`:176`；`docs/backup-restore.md:37`；`PROJECT_CONTEXT.md:48` | `backup → verify-backup → restore` 后比对 `usage(day)`；建议纳入一致性清单或显式排除 |
| F-06 | 中低 | 并发写锁竞争未映射为稳定错误码：`sqlite3.connect(..., timeout=10)` + `BEGIN IMMEDIATE`，`generate` 未捕获 `sqlite3.OperationalError`，可能以非 `ModelError` 冒泡、绕过降级并带出底层异常文本 | `client.py:258`、`:283`、`:14-23` | 持写锁 >10s 时第二个 `_reserve` → 预期稳定错误码（如 `ledger_busy`）并降级。静态推断，未做并发实测 |
| F-07 | 中低 | `_reserve` 的 `day < latest` 与 `_finish` 的 `stamp < started_at` 为字符串比较，格式由 `_now()` 固定为 ISO 微秒 + Z，字典序等价时间序、实用安全；但字面不符合 `contracts-v0.1.md:17`「比较前解析为时间」 | `client.py:270-271`、`:283-284`、`:305`；`contracts-v0.1.md:17` | 建议主控裁定：补注释说明受控格式，或改用 datetime 对象比较 |
| F-08 | 中 | 测试证据强度：`test_atomic_reservations_across_two_clients` 用 `Event` 使第二个 client 在第一个**已完成预留、进入 transport 后**才发起，验证的是「已预留额度阻止后续请求」，未让两个 `_reserve` 真正同时进入临界区竞争。且不得把该 mock 通过写成 R08「并发真实调用前」通过 | `tests/test_llm.py:210-238`；`contracts-v0.1.md:219`、`:208`；`batch-05-plan.md:7`、`:13`；`AGENTS.md:10` | 建议补真并发屏障用例（`Barrier` 同时进入 `_reserve`），并由主控明确 R08 验收口径 |
| F-09 | 中 | 验收清单漏项：`task-board.json:318` 缓存键只列「输入/模型/提示词/规则版本」，遗漏 V2:137 的「输出模式版本」。**实现实际更强**：`client.py:341-359` 把 `output_schema`、`schema_version`、`parameters`、`max_output_*` 全部纳入键，已缓解缓存污染风险；风险在于以任务板为权威状态源会漏验收 | V2:137；`task-board.json:318`；`llm-client.md:46`；`client.py:341-359`；`contracts-v0.1.md:178` | 建议把验收第 3 条补「输出模式/schema 版本」并同步公共契约 |
| F-10 | 中 | 「按开始 UTC 日归属、跨午夜结算原日」仅写在 `llm-client.md:58` 与实现中，未纳入公共契约；契约第 9 节要求跨模块规则由主控整合。未来模块若按交易日/Asia-Shanghai/滚动 24h 实现会错账 | `llm-client.md:58`；`client.py:275`、`:299`；`contracts-v0.1.md:9`、`:178`、`:225-229` | 建议主控新增预算账本契约小节，明确 UTC 日桶、跨日归属、时钟回退与费率/取整 |
| F-11 | 中低 | `charged_*` 字段名把「保守估算占位」与「真实结算」混在同一列，`usage()` 混合求和且不披露估算占比；文档已声明「不作为真实结算值」，但 V2:139 要求「显示估算值及依据」 | `client.py:249`、`:294-295`、`:310-319`、`:423-426`；`llm-client.md:54`；V2:139 | 建议增加 `settlement_state` / `charge_basis` 与估算占比披露 |
| F-12 | 信息 | 实现者自述 30 项定向测试通过、且首次因测试辅助连接未关闭出现 Windows 文件锁错误后修复；本包按边界**未复跑、未确认** | `llm-client.md:86`；`tests/test_llm.py`（约 30 个 test 方法） | 由 QA-B05 独立复跑定向命令 `llm-client.md:80-84` 并留证 |

---

## 7. 契约一致性核对结论（子 Agent B + 主 Agent 复核）

1. **R08 阶段口径**：`contracts-v0.1.md:219` 标「并发真实调用前」、`:208` 规定 MVP 只先做 R01–R03/R09–R10；`batch-05-plan.md:7` 要求 NLP-01 做「并发预留」离线测试，`:13` 明确本轮不自动调用付费模型。二者是**层次差异不是矛盾**：离线并发预留测试可作为设计验证，但**不得等价于 R08 通过**，真实并发验收仍属前置门槛。`protocol.md:45` 与 `AGENTS.md:10` 均禁止把未执行的检查写成通过。
2. **缓存键版本清单**：V2 五类 / 任务板四类 / batch-05 仅「版本缓存」，三处不一致（F-09）。实现已覆盖得更全，需同步验收文本而非改实现。
3. **交付标注**：`contracts-v0.1.md:229` 要求每工作包列「运行命令、实际测试结果、已知缺口」，并明确「未执行测试不得写成通过」。本包为设计/只读审查，`tests_run=0`，已在 §1、§6、§8 及 JSON 中显式标注；定向命令由 `llm-client.md:80-84` 提供，交 QA-B05 复跑。
4. ** charter 待实测假设**：`docs/charter-v3.md:93` 称不假定 WorkBuddy 存在跨 Agent 消息接口；本包实测存在并成功用于委派，建议主控更新该结论（但不据此推定存在 CLI/后台常驻协作）。

---

## 8. 未验证项、限制与阻塞

**未验证（不得写成通过）**

1. 本包**未运行任何测试**、构建、安装或 CI 命令；`tests_run = 0`。实现者自述的 30 项通过未经独立复跑。
2. 所有 `client.py` / `tests/test_llm.py` 结论均为**静态只读复核推断**，除 F-04 有纯内存语言级语义核验外，均无运行时验证。
3. R08 的真实并发门槛、真实供应商 HTTP 超时、usage/费用核实、模型抽取质量、G3 均未验收（`llm-client.md:88` 亦列为待完成）。
4. 审查对象在本次执行期间由其他执行者并行生成并持续变化：首次 Glob 无 llm 代码，约 06:06–06:09Z 陆续出现 `client.py`、`__init__.py`、`tests/test_llm.py`、`config/llm.example.json`、`docs/llm-client.md`。本包快照为 **06:09Z 左右**的文件内容，之后若有提交需重新核对。
5. 未读取 `config/llm.example.json`（凭证规避）与 `docs/verification/batch-05-review.md`（保持独立性），故未核对示例配置字段，也未参考 QA-B05 结论。
6. 未验证 Git 状态、依赖清单、CI、账本在 Windows 文件系统下的多进程锁行为（F-06 为静态推断）。
7. 两个子 Agent 的回传内容未附 UTC 时间戳；签名与 agent_id/task_id 可核验，精确回传时刻不做编造。

**遵守的边界**

- 仅写入 `WB-05-report.md`、`WB-05-results.json` 两个文件；未修改产品代码、测试、Git、依赖、系统设置、其他任务文件，也未写入工作区记忆。
- 未读取/输出凭证、环境变量或账户文件；未使用付费 API、未调用真实模型、未联网、未外发消息、未上传 GitHub。
- 未绕过任何访问限制；未把设计用例、mock 或合成 fixture 标记为真实接口/真实调用通过。

**阻塞**

- 无硬性阻塞（子 Agent 能力可用、两份文件均交付）。状态为 `partial` 源于上述未验证项与验收权归属，非工具不可用或额度不足。

---

## 9. 交主控 / QA-B05 的最高优先级待决问题

1. **F-01**：是否要求单账本绑定（固定 `state_path` / 跨账本对账），否则「换文件重置额度」是 QA-B05 要查的预算绕过。
2. **F-02**：`pending` 预留的人工结算/释放终态归哪个工作包？R08「失败可释放或结算」在崩溃场景何时闭环？
3. **F-04 / F-03**：专用错误码是否需保留？确定性无效输出是否应停止重试并要求补 `max_retries>0` 的无效输出断言？
4. **F-08**：R08 的正式验收口径（mock 并发 vs 真实并发）与「并发真实调用前」门槛由谁签核；是否补真并发屏障用例。
5. **F-09 / F-10**：把「输出模式/schema 版本」补进 `task-board.json:318` 验收清单；把 UTC 日桶、跨日归属、费率/取整、估算三态写入公共契约（契约第 9 节由主控单点整合）。
6. **F-05**：恢复演练（R10 / G5）是否把模型账本纳入一致性范围，或显式列为不覆盖并禁止宣称整体可恢复。
7. **流程**：`docs/charter-v3.md:93` 的「WorkBuddy 跨 Agent 能力待实测」假设可依据本包证据更新；最终 WB-05 完成状态由主控与 QA-B05 回收验收后决定。

---

## 10. 交付与自检

- 交付文件（仅此两项）：
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-05-report.md`
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-05-results.json`
- JSON 必需字段自检：`task_id`、`status`、`started_at_utc`、`finished_at_utc`、`subagent_used`（真实布尔 `true`）、`subagent_evidence`、`files_read`、`findings`、`checks_run`、`limitations` 均已填写。
- 未写入凭证或敏感环境变量；未包含任何未实际执行的命令/访问输出或虚构的测试通过结论。
