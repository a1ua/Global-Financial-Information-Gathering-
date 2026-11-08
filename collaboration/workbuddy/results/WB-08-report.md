# WB-08：对账与恢复契约同步设计审查 — 结果定稿

## 执行记录（父端）

- task_id：WB-08
- 依据文件：任务单 `collaboration/workbuddy/WB-08-task.md`；唯一固定契约 `docs/contracts/reconciliation-v0.1.md`。未读代码/配置/凭证/账户/环境。
- 执行模式：普通同步阻塞子任务，`run_in_background=false`，未设 team/name，尝试恰 1 次。
- 子任务：固定契约全文内嵌；只读、不写文件；最多三点检查；只给可引用正文并区分设计意见与测试。
- 父端：未运行命令/测试/网络，未改任何旧 WB 文件，未扩大范围；tests_run = 0。
- 结果：完整正文已实际回传（非仅派发/完成状态），状态 completed，finalized = true。
- 定稿后不再覆盖；额外消息只报主控。

## 实际回执

- 工具：Agent，subagent_type = general-purpose；调用参数 `run_in_background=false`、未设 team/name、尝试次数 1。
- 工具返回的原始回执行：`[Agent ID: agent-746341f1-26bf-4d60-911f-b5e6b697f777]`
- 未编造时间或日志；除上述实际回执外，无其他时间/日志信息。

## 完整返回正文（逐字保留，末行为工具回执行）

```
设计意见（本任务为只读设计审查，仅依据内嵌冻结契约原文，不读取代码/配置/凭证/账户/环境，不运行命令/测试/网络，不写文件；以下结论均为设计意见）

一、检查点1：声明金额相同（matched_estimates / delta=0）能否被误当作供应商账单认证或结算许可，契约是否明确否定

【契约可引用原句】
- 「用户提供文件、完整JSON、SHA-256和金额相等都不能认证供应商账单真实性；本批只将声明金额与本地配置费率估算比对。没有供应商证据时不猜测零费用。合成证据只能验证代码，不算真实账单。」
- 「本地调用call_id尚未与供应商逐调用凭证建立可靠绑定。」
- 「金额字段只在本日单币种计算，delta=声明总额减本地全部选定调用估算总额；缺项时该delta只是覆盖不完整的差额，不是已核对净支出。」
- 「status：有缺项或pending为incomplete；无缺项/pending但金额差异为differences；其余matched_estimates。matched_estimates只说明数值相同，不认证账单、不结算；零调用覆盖也不得宣称真实对账完成。相同输入重复预检无写入、结果一致，不产生对账审计记录。」
- 「返回严格公开字段：schema_version=`ledger-reconciliation-preview/0.1`、status、ledger_id、utc_day、currency、provider、evidence_kind、read_only=true、evidence_authenticated=false、settlement_allowed=false、local_calls、statement_records、missing_records、pending_calls、difference_records、local_estimated_micro_units、statement_micro_units、delta_micro_units。」
- 「不新增结算写入口、不改调用状态、不释放pending、不切换生产文件。」

【结论（设计意见）】契约明确否定，不存在把金额相同误当作账单认证或结算许可的语义空间。其一，证据层面已否定：「金额相等都不能认证供应商账单真实性」，且本批仅将声明金额与「本地配置费率估算」比对，不含供应商真实计费口径；「合成证据只能验证代码，不算真实账单」。其二，status 语义已否定：「matched_estimates只说明数值相同，不认证账单、不结算」，且「零调用覆盖也不得宣称真实对账完成」。其三，delta 语义已否定：delta 仅为「声明总额减本地全部选定调用估算总额」，缺项时「只是覆盖不完整的差额，不是已核对净支出」，故 delta=0 亦不构成已核对净支出或结算依据。其四，返回字段固定 evidence_authenticated=false、settlement_allowed=false、read_only=true，并在前言固定「不新增结算写入口、不改调用状态、不释放pending、不切换生产文件」，且「相同输入重复预检无写入、结果一致，不产生对账审计记录」。四个层面一致且互相印证，设计为明确否定。

二、检查点2：恢复预检等价（equivalent_observation）是否被误当作新鲜性证明或生产切换许可，blockers 是否标清

【契约可引用原句】
- 「绑定/候选/实际读事务身份均重新核对；业务验证和读取处于各自单一只读事务。两库不是跨库原子快照，预检不能作为稍后切换许可。」
- 「备份先验验证不能消除之后打开时的TOCTOU，实际读事务仍需重验业务闭包和身份；不声称跨库原子或抵抗恶意并发换库。」
- 「按days/calls/cache主键比较全部列，包含pending、费用、缓存指向与调用元数据；不按总金额推断新旧。」
- 「返回字段：schema_version=`ledger-recovery-preflight/0.1`、status=`equivalent_observation|not_equivalent`、ledger_id、read_only=true、switch_allowed=false、trusted_high_water=false、current_calls、candidate_calls、candidate_missing_calls、candidate_extra_calls、changed_calls、missing_days、extra_days、changed_days、missing_cache、extra_cache、changed_cache、blockers。」
- 「blockers始终包含trusted_high_water_unavailable、reconciliation_not_verified、production_switch_not_implemented；不等价另加snapshot_not_equivalent。相同文件行不证明最新、费用真实或可安全切换；旧候选若恰等于已回退的当前库仍可能等价，不能称完整防回退。」
- 「不写生产库、不删除/复制/覆盖文件、不创建活动绑定或恢复目录、不读取密钥/联网。」
- 「合法结果即使incomplete/differences/not_equivalent也exit0并显式展示禁止结算/切换。」

【结论（设计意见）】契约明确否定，blockers 已标清。新鲜性方面：「相同文件行不证明最新、费用真实或可安全切换；旧候选若恰等于已回退的当前库仍可能等价，不能称完整防回退」，且前言明确「备份先验验证不能消除之后打开时的TOCTOU……不声称跨库原子或抵抗恶意并发换库」，「两库不是跨库原子快照」。切换许可方面：「预检不能作为稍后切换许可」，返回字段固定 switch_allowed=false、trusted_high_water=false、read_only=true，并配合「不写生产库、不删除/复制/覆盖文件、不创建活动绑定或恢复目录」及 CLI「显式展示禁止结算/切换」。blockers 标清且结构完备：三项「始终包含」的 trusted_high_water_unavailable、reconciliation_not_verified、production_switch_not_implemented 不因等价而清空，不等价时「另加snapshot_not_equivalent」；等价仅表示按 days/calls/cache 主键「比较全部列」的只读观察一致，且「不按总金额推断新旧」。因此 equivalent_observation 既非新鲜性证明，也非生产切换许可，设计上已封闭误用路径。

三、检查点3：未来外部可信高水位与不可变审计（第3节）本批未实现，是否清楚标注未实现/方案未选定/生产切换保持禁止

【契约可引用原句】
- 「## 3. 后续结算状态与不可变审计设计（本批不实现）」
- 「对账工作流拟为submitted→needs_evidence/discrepant→verified→applied；rejected为审查拒绝，不等于供应商拒绝计费。每次转移新增审计事件，包含event_id、前序哈希、ledger_id、call_id、UTC recorded_at、证据哈希、验证方式、原估算与账单金额及币种、原因枚举和版本。禁止UPDATE/DELETE覆盖历史；错误用新事件纠正，重复证据幂等且冲突拒绝。」
- 「只有真实来源证据及可信调用关联通过、金额/币种/账期均一致、独立审批和事务性预算核对满足时才可设计applied；不能单凭手输零、状态failed或供应商总账单释放未知预留。pending调用仍保留原预算占用。」
- 「外部可信高水位必须独立于可恢复账本与同目录文件，且具有已验收的持久、单调和访问控制边界，至少关联ledger_id、连续审计序列/链摘要和未决占用。普通同目录JSON或备份manifest不可信，不能提供回退检测保证。具体存储方案和部署尚未选定；缺失/冲突/不可访问时生产恢复切换保持禁止。」
- 「blockers始终包含trusted_high_water_unavailable、reconciliation_not_verified、production_switch_not_implemented」
- 「read_only=true、switch_allowed=false、trusted_high_water=false」
- 「不新增结算写入口、不改调用状态、不释放pending、不切换生产文件。」

【结论（设计意见）】契约清楚标注，三者均可逐字定位。未实现：第3节标题直接写明「（本批不实现）」，工作流用「拟为」表述为设计态，applied 亦为「才可设计applied」，且前言固定「不新增结算写入口、不改调用状态、不释放pending、不切换生产文件」。方案未选定：「具体存储方案和部署尚未选定」，并以「外部可信高水位必须独立于可恢复账本与同目录文件」「普通同目录JSON或备份manifest不可信，不能提供回退检测保证」明确不得以本批同目录文件替代实现。生产切换保持禁止：「缺失/冲突/不可访问时生产恢复切换保持禁止」；该禁止在本批接口中被固化为返回字段 trusted_high_water=false、switch_allowed=false 及 blockers 中「始终包含」的 trusted_high_water_unavailable 与 production_switch_not_implemented，另有 reconciliation_not_verified 与「不认证账单、不结算」呼应。审计设计部分（「每次转移新增审计事件」「禁止UPDATE/DELETE覆盖历史」「错误用新事件纠正」）明确归属后续设计，本批「不产生对账审计记录」。因此第3节作为未来设计已被清楚隔离，未实现状态、方案未选定状态与生产切换禁止状态在契约内一致且无歧义。

测试/验收（本任务不执行，仅指出归属）

【契约可引用原句】
- 「QA-B08设计审查通过后冻结。」
- 「实际代码验收另行完成。」
- 「独立QA验证，不以合成HTTP代替真实账单。」
- 「必须验证：声明重复/额外字段、bool/负值/非有限金额、大小上限、错日/币种/provider/身份、缺项/未知调用、pending不释放、同输入无写入；schema/绑定错误不建库；旧备份缺当前调用、同数同额但行变化、缓存/日限额差异、相同快照仍switch_allowed=false；CLI不读key/发网络。文件字节和业务行前后不变；WAL读写并发无法提供切换保证，明确限制。」

上述三点仅为依据冻结契约原文作出的设计审查意见，不构成实现符合性证明。契约所列「必须验证」各项、CLI exit1/exit0 行为、「文件字节和业务行前后不变」、WAL 读写并发限制、以及真实账单相关验证，均由独立QA与实际代码验收另行完成；本任务不执行任何测试、不读取代码、不访问环境、不替代验收、不出具验收结论，亦不以合成HTTP代替真实账单。

[Agent ID: agent-746341f1-26bf-4d60-911f-b5e6b697f777]
```

## 状态

status = completed；raw_result_recovered = true；tests_run = 0；finalized = true。本文件与 `WB-08-results.json` 为定稿，不再覆盖。

WB-08 FINALIZED
