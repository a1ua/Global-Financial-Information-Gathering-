# WB-06｜固定契约的独立子Agent设计审查（主控收敛范围后定稿）

状态：**partial** —— 主控收敛本轮交付范围，仅以真实回传的 `wb06-recovery` 一份完整结论定稿；`wb06-budget` 为 **pending/not_received**，不编造、不声称完成、不作为发布前置。
任务单：`collaboration/workbuddy/WB-06-task.md`（基线 79cafc2）。

只读范围（严格三份）：`collaboration/batch-06-plan.md`、`docs/contracts/deepseek-budget-v0.2.md`、`docs/contracts-v0.1.md` 第10节（231–244行）。未扩展读取，未读代码/凭证/配置/账户/环境变量，未运行测试或命令（`tests_run=0`），未改 WB-05，未实网/外发/上传。币种口径全程为人民币每日10元；USD 仅为 schema1 旧记录向后兼容语义，不换汇、不混用、不作账单或账户全局限额。

## 1. 子Agent与真实回执

| 子任务 | agent_id / task_id | 回执 | 完整结论回收 | 本轮状态 |
| --- | --- | --- | --- | --- |
| 账本恢复回退边界 / 币种 / pending 保留 | `wb06-recovery@_auto_511dde95-43de-49f4-883a-00639fd4b9dd` / `agent-fc13a5e8-150d-4dd4-a697-c7a99ad96c9e` | Spawned successfully；框架完成通知 `completed`（10m10s） | **已回收**：完整四段（审查依据17条 / 关键发现3项 / 未验证项10条 / 边界声明），经收件箱消息真实回传 | 纳入本轮交付 |
| CNY每日10元 / 向上取整 / 未知费用 / HTTP密钥·时限·响应 / 显式启用 | `wb06-budget@_auto_511dde95-43de-49f4-883a-00639fd4b9dd` / `agent-b758cc7c-650f-4b8e-8b7f-f1f5003363bb` | Spawned successfully；框架完成通知 `completed` | 未纳入 | `pending/not_received`；不纳入 findings、不声称完成、不再等待其作为发布前置 |

框架完成通知与子Agent自述均不等同于结论正文；本稿仅使用已真实回收的 wb06-recovery 结论。

## 2. 子Agent原始发现（wb06-recovery，3项，≤5）

- **F-A1（性质：推断）** 恢复"隔离"只落在目录层、未落到账本身份/state_path 绑定层；"仅新目录恢复、不把旧备份当最新额度"与文档3"禁止切换或回滚账本规避额度"之间缺少可执行衔接约束，而能补位的"固定生产账本绑定"被三份文档一致列为未完成的独立前置，前置完成前无运行时兜底。依据：文档1"范围"段、文档2第8条、文档3第10节。风险：保留旧 pending 与旧费用占用的时点快照若日后被指向为活动 state_path，即回滚到占用更低的账本，正落入所禁的"以回滚规避额度"；且"NLP-01-RECOVERY 工作包可验收"与"恢复切换仍为前置"并列表述，易被误读为恢复能力已闭环。
- **F-A2（性质：文档明示）** 文档2第1/2/4条明示了币种边界（DEFAULT 'USD'、同 UTC 日不可混合币种/静默变更限额、CNY 不得使用 USD 默认值、金额按 day.currency 的 micro 单位且 CNY 不得标为 USD），但没有任何一条规定 CNY 日建行必须显式写入 `currency='CNY'`，也未规定 `day.currency` 与 `request_metadata.budget_currency` 冲突时的判定/拒绝规则，明示约束之间缺少写入期衔接规则。风险：CNY 日依赖列默认值会静默落为 USD，误套"仅 USD 用旧 micro_usd_per_token 等价公式"、把 CNY 金额按 USD 口径记入 reserved_cost/charged_cost；schema1→schema2 切换当日旧 USD 与新 CNY 同日的归账、既有 daycaps/占用是否按 microCNY 重解读亦未定义；文档2第4条称旧公式为"等价公式"，但文档3未固定旧公式取整方式。
- **F-A3（性质：推断）** pending 作为"不能写成零的未知支出"被要求在恢复副本中原样保留，但三份文档未定义副本内 pending 的终态处理与快照时点闭包（"引用和时点闭包"仅见 QA-B06 验收项、未进入恢复契约），且"人工对账/终态修复"整体为未通过前置，副本 pending 既不能自动释放、也无已定义的人工结算路径，与当前账本 pending 的时点/占用对应关系无约束。风险：副本若被激活（呼应 F-A1），旧时点冻结占用会带入且与当前账本不等，形成"旧备份当额度基准"的绕过面；尽管文档2第8条有"不因隔离恢复演练而宣称完成"兜底，仍有被读成"生产可恢复"的歧义。

## 3. 主端推断（非子Agent结论）

1. 本轮交付范围由主控收敛为 wb06-recovery 一份；wb06-budget 按 `pending/not_received` 处理，其审查焦点（人民币每日10元、向上取整、未知费用、HTTP 密钥/时限/响应、显式启用）本轮无子Agent结论纳入，故不列为已验证发现。
2. 上述3项均为固定契约的静态设计缺口，不等同于实现缺陷；本任务未读代码、未跑测试，实现是否落地未验证。F-A1/F-A3 为子Agent标注的推断，F-A2 为文档明示。

## 4. 未验证项（子Agent原列10条，按简洁要求合并为5条）

1. 恢复副本是否会被同一应用当作 state_path 激活、是否存在"副本只读/禁止激活"的运行时约束 —— 须查实现与运行态。
2. CNY 日是否显式写入 `currency='CNY'`、`day.currency` 与 `request_metadata.budget_currency` 冲突是否被拒绝、schema1→2 迁移对既有 daycaps/费用金额的单位处理，及同一 UTC 日跨 schema 切换的归账分支 —— 须查写入/迁移代码与单测。
3. "一致快照"是否包含全部 pending 及其占用、恢复后与当前账本 pending 的时点/占用对应关系 —— 须查 SQLite 快照与恢复测试。
4. 计费是否按输入/输出分别 ceil 后相加、成功 usage 减记是否封顶于各自预留、超时/非法 usage 是否保留全额 —— 须查计费实现与单测。
5. 真实供应商费率与账单/账户支出、固定生产账本绑定/人工对账/恢复切换三项前置是否通过、传输强制与密钥来源、证据库 schema4 及已发布报告是否未改动 —— 须查验收记录、代码与版本基线（本任务禁止外网/账户访问，均未验证）。

## 5. 定稿说明

本稿替代前序 blocked 稿：`status=partial`、`finalized=true`，仅1份子Agent完整结论纳入，不声称 WB-06 整体审查完成。本次仅写 `WB-06-report.md` 与 `WB-06-results.json` 两份；results 目录内既有 WB-01/WB-05 文件未改动。定稿后不再覆盖；后续收到 wb06-budget 或其他额外结论只以消息报主控，不改本定稿。如需勘误另报告主控，不覆盖本次定稿；不响应旧 WB-05 队列续写。

WB-06 FINALIZED
