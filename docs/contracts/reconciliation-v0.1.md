# 人工对账与受控恢复契约 v0.1（已冻结）

日期2026-11-09。Batch08-A先冻结设计，再开发Batch08-B只读预检。模型账本保持schema3，证据库保持schema4；不新增结算写入口、不改调用状态、不释放pending、不切换生产文件。

QA-B08设计审查通过后冻结。备份先验验证不能消除之后打开时的TOCTOU，实际读事务仍需重验业务闭包和身份；不声称跨库原子或抵抗恶意并发换库。实际代码验收另行完成。

实现验收补充：本契约read_only指mode=ro/query_only、不执行SQL业务写入，不更改预算/调用/绑定或迁移schema。SQLite读取WAL模式可能创建或更新-wal/-shm协调侧文件，不能承诺整个文件集和所有字节零变化；这不代表对账审计或预算写入。不得使用immutable=1绕过WAL读取。非WAL静态fixture验证文件字节不变，WAL场景验证业务行/预算不变及正确可见性，并披露可能的侧文件变化。下文“文件不写入/不变”均依此解释。

## 1. 证据与信任

本地调用call_id尚未与供应商逐调用凭证建立可靠绑定。用户提供文件、完整JSON、SHA-256和金额相等都不能认证供应商账单真实性；本批只将声明金额与本地配置费率估算比对。没有供应商证据时不猜测零费用。合成证据只能验证代码，不算真实账单。

可信对账证据至少需要供应商/账户范围、请求关联、币种、实际计费口径、账期、凭证原件哈希、取得时间和验证人/验证方式；不得存API密钥、账户秘密或任意响应正文。供应商当前API/账单是否足够支持这些字段尚未验证，本批不联网调查或访问账户。

## 2. 只读声明格式

API `preview_reconciliation(workspace, statement_path)`；输入文件上限1MiB，禁止文件/祖先symlink及junction。JSON拒绝重复键、非有限值、额外字段和无效类型。严格顶层字段：

- schema_version=`ledger-reconciliation-statement/0.1`。
- ledger_id：ledger_加32位小写十六进制，必须等于当前固定绑定与schema3账本身份。
- utc_day：有效YYYY-MM-DD；currency为CNY/USD，必须等于该day.currency。
- provider：mock/deepseek，仅比较该UTC日该provider的全部本地调用，不能将部分覆盖说成全账本核对。
- evidence_kind：synthetic/manual_statement；evidence_sha256：64位小写十六进制，作为外部凭证声明引用，不读取或认证其原件。
- records：最多10000项，每项严格为call_id、charged_micro_units。call_id为call_加32位小写十六进制；金额整数0至10^15，bool拒绝；call_id不得重复。

先只读验证固定工作区bound且不是隔离恢复目录。以mode=ro/query_only和单一读事务验证schema3业务闭包，重新核对绑定身份，再读取同一快照中的day和calls。不创建目录/账本/绑定，不迁移，不读取密钥，不联网。day不存在、声明出现非该day/provider调用、身份/币种不符等拒绝固定错误码，不回显输入或底层异常。

返回严格公开字段：schema_version=`ledger-reconciliation-preview/0.1`、status、ledger_id、utc_day、currency、provider、evidence_kind、read_only=true、evidence_authenticated=false、settlement_allowed=false、local_calls、statement_records、missing_records、pending_calls、difference_records、local_estimated_micro_units、statement_micro_units、delta_micro_units。金额字段只在本日单币种计算，delta=声明总额减本地全部选定调用估算总额；缺项时该delta只是覆盖不完整的差额，不是已核对净支出。difference_records为已声明调用金额与对应本地charged_cost不同的条数。

status：有缺项或pending为incomplete；无缺项/pending但金额差异为differences；其余matched_estimates。matched_estimates只说明数值相同，不认证账单、不结算；零调用覆盖也不得宣称真实对账完成。相同输入重复预检无写入、结果一致，不产生对账审计记录。

## 3. 后续结算状态与不可变审计设计（本批不实现）

对账工作流拟为submitted→needs_evidence/discrepant→verified→applied；rejected为审查拒绝，不等于供应商拒绝计费。每次转移新增审计事件，包含event_id、前序哈希、ledger_id、call_id、UTC recorded_at、证据哈希、验证方式、原估算与账单金额及币种、原因枚举和版本。禁止UPDATE/DELETE覆盖历史；错误用新事件纠正，重复证据幂等且冲突拒绝。

只有真实来源证据及可信调用关联通过、金额/币种/账期均一致、独立审批和事务性预算核对满足时才可设计applied；不能单凭手输零、状态failed或供应商总账单释放未知预留。pending调用仍保留原预算占用。真实费用超预留需记录差异并阻断新增调用，不能截断账单冒充满足限额；跨日按原调用预算日及外部账期分别留痕。实际收费与token占用是不同维度，不从金额推算token。

外部可信高水位必须独立于可恢复账本与同目录文件，且具有已验收的持久、单调和访问控制边界，至少关联ledger_id、连续审计序列/链摘要和未决占用。普通同目录JSON或备份manifest不可信，不能提供回退检测保证。具体存储方案和部署尚未选定；缺失/冲突/不可访问时生产恢复切换保持禁止。

## 4. 恢复只读预检

API `preflight_ledger_recovery(workspace, backup)`：使用既有严格备份验证，候选必须schema3且身份与当前bound工作区一致；旧schema1/2仍可隔离恢复，但不得进入本预检。绑定/候选/实际读事务身份均重新核对；业务验证和读取处于各自单一只读事务。两库不是跨库原子快照，预检不能作为稍后切换许可。

按days/calls/cache主键比较全部列，包含pending、费用、缓存指向与调用元数据；不按总金额推断新旧。候选缺少当前调用、调用/日限额/币种/缓存被改写都记录不等价。返回不包含原始输出或元数据。

返回字段：schema_version=`ledger-recovery-preflight/0.1`、status=`equivalent_observation|not_equivalent`、ledger_id、read_only=true、switch_allowed=false、trusted_high_water=false、current_calls、candidate_calls、candidate_missing_calls、candidate_extra_calls、changed_calls、missing_days、extra_days、changed_days、missing_cache、extra_cache、changed_cache、blockers。

blockers始终包含trusted_high_water_unavailable、reconciliation_not_verified、production_switch_not_implemented；不等价另加snapshot_not_equivalent。相同文件行不证明最新、费用真实或可安全切换；旧候选若恰等于已回退的当前库仍可能等价，不能称完整防回退。

不写生产库、不删除/复制/覆盖文件、不创建活动绑定或恢复目录、不读取密钥/联网。错误固定ValueError码，缺库/损坏/链接/错误身份/legacy候选等明确拒绝，不回显原始错误。

## 5. CLI与验收

`ledger-reconcile-preview --workspace ... --statement ...`和`ledger-recovery-preflight --workspace ... --backup ...`只读输出JSON；格式/身份/闭包错误exit1，合法结果即使incomplete/differences/not_equivalent也exit0并显式展示禁止结算/切换。不增加--apply/--force/--release参数。

必须验证：声明重复/额外字段、bool/负值/非有限金额、大小上限、错日/币种/provider/身份、缺项/未知调用、pending不释放、同输入无SQL业务写入；schema/绑定错误不建业务库；旧备份缺当前调用、同数同额但行变化、缓存/日限额差异、相同快照仍switch_allowed=false；CLI不读key/发网络。非WAL静态fixture文件字节和业务行前后不变；WAL业务行/预算不变，允许SQLite协调侧文件出现/更新，且读写并发无法提供切换保证。独立QA验证，不以合成HTTP代替真实账单。
