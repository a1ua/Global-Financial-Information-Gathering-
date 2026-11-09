# 本地追加审计契约 v0.1（已冻结）

日期2026-11-09。新增独立SQLite审计库schema1，不改模型账本schema3和证据库schema4。用于保留未认证账单声明的只读预检观察；外部可信高水位、结算与生产切换仍未实现。

QA-B08C独立设计审查通过，容量与REPLACE保护意见已纳入后冻结；实现测试单独验收。

## 1. API、事件与幂等

`append_observation(journal_path, observation)`：observation严格字段schema_version=`ledger-audit-observation/0.1`、statement_sha256（解析声明后canonical JSON的SHA-256）、evidence_sha256（声明中未认证凭证哈希）、preview（reconciliation-preview/0.1完整严格字段）。三个外部输入均未认证；只允许现有preview字段和枚举，整数/bool/计数关系、金额及delta按预检语义验证；不接受自由文本/凭证/任意元数据。

完整preview字段见reconciliation-v0.1及实现，schema_version/status/ledger_id/utc_day/currency/provider/evidence_kind/read_only/evidence_authenticated/settlement_allowed/local_calls/statement_records/missing_records/pending_calls/difference_records/local_estimated_micro_units/statement_micro_units/delta_micro_units。严格要求read_only=true、evidence_authenticated=false、settlement_allowed=false；utc_day、ID及hash严格格式；计数非负整数非bool，statement_records+missing_records=local_calls，pending_calls<=local_calls、difference_records<=statement_records；状态incomplete/differences/matched_estimates须与计数一致；delta=statement_micro_units-local_estimated_micro_units。金额非负整数，delta可负；总额范围0至10^19、delta绝对值<=10^19；计数<=10^7。这是审计输入容量限制，超限固定错误，不能声称接受现有预检的任意规模合法合计；原只读预检不因此增加限制。

canonical JSON：ensure_ascii=False、sort_keys=True、separators=(',',':')、allow_nan=False，UTF8编码。observation_key=SHA256(canonical observation)。唯一键为完整observation_key，同一声明但当前账本观察变化时记录新事件；相同观察重试返回原事件不新增。该语义不是按每次人类点击计数，也不是账单幂等结算。

数值一致性补充：local_calls=0时local_estimated_micro_units必须0；statement_records=0时statement_micro_units必须0；missing_records=0且difference_records=0时delta必须0，因此matched_estimates必delta0。逐调用差异可正负抵消，difference_records>0时不能仅凭delta0变为matched。

事件表`audit_events`严格列：seq INTEGER PRIMARY KEY（连续从1）、event_id TEXT UNIQUE NOT NULL（audit_加32位小写hex）、observation_key TEXT UNIQUE NOT NULL、ledger_id TEXT NOT NULL、recorded_at TEXT NOT NULL（真实UTC Z）、previous_sha256 TEXT NOT NULL、payload TEXT NOT NULL（canonical observation）、event_sha256 TEXT UNIQUE NOT NULL。

创世previous_sha256为64个0。event_sha256=SHA256(canonical {seq,event_id,observation_key,ledger_id,recorded_at,previous_sha256,payload})；其中payload为canonical JSON字符串。ledger_id必须等于preview.ledger_id。单库允许多个ledger_id，所有事件全局连续；不得按每个ledger单独重用序号。

相同观察的历史事件允许复用，幂等命中前必须验证全部现存链；篡改后不能利用去重跳过校验。新事件recorded_at为真实UTC，不能早于链尾时间，时钟回退拒绝；注入业务预算clock不参与。相同观察幂等返回不用创建新时间。

## 2. 库创建、追加与校验

显式append可以创建新审计文件及父目录；不能覆盖已存在空文件、错误schema或损坏库。既存文件只能mode=rw打开，禁止缺失时意外自动重建；首次创建使用独占文件声明后初始化，失败可留下人工检查状态，不自动删除/修复。不把运行库路径放源码/密钥目录；文件及全部祖先symlink/junction拒绝，不允许与工作区账本/绑定/声明文件同路径（CLI负责输入角色冲突拒绝）。

源码/密钥目录的避让是操作者路径选择约定，CLI不能识别任意目录用途；强制范围是工作区树外、声明/账本/绑定角色不同路径或文件，以及模块链接拒绝，不宣称自动秘密目录识别。

SQLite使用BEGIN IMMEDIATE单事务：新建表/触发器、或校验已有schema和全链，再幂等查询或追加并提交。busy/locked固定错误，不重试无限循环。持有同一DB的合法并发追加必须无丢失/重复、序号连续；可安全失败，不承诺多进程高吞吐。

UPDATE/DELETE触发器拒绝audit_events变更；INSERT触发器约束seq连续及previous_sha256等于末行event_sha256（初始0），并在插入前拒绝已有event_id/observation_key/event_sha256/seq，防止INSERT OR REPLACE或REPLACE在recursive_triggers=OFF时隐式删行绕过。verify要检查schema列、约束所依赖的保护触发器确实存在且定义匹配本实现，再按seq全量验证每行ID、UTC、payload严格schema/canonical、observation_key、ledger_id和完整哈希/前序/时间/唯一性。新增独立库schema1仅当前格式，不自动迁移未知版本。

`verify_audit_journal(journal_path)`：mode=ro/query_only和单一读事务，只读验证；缺文件时不创建目录/文件，不修复损坏。WAL协调侧文件可能创建/更新，不用immutable模式忽略WAL。不输出payload或原始文本，错误均固定ValueError码，OSError/SQLite/JSON/Unicode等异常脱敏，不回显路径或底层错误。

append返回严格字段schema_version=`ledger-audit-result/0.1`、status=`recorded|already_recorded`、event_id、seq、ledger_id、event_sha256、events（当前全链长度）、trusted_high_water=false、settlement_allowed=false、switch_allowed=false。verify返回schema_version=`ledger-audit-verification/0.1`、status=`verified_local_chain`、events、last_event_sha256（空库64个0）、trusted_high_water=false、settlement_allowed=false、switch_allowed=false。verified_local_chain只指本地结构/链一致，不能叫已认证账单或不可回退。

## 3. 集成与明确写入

CLI `ledger-audit-record --workspace ... --statement ... --journal ...`：明确写入审计库，读取声明恰一次后，将同一解析值送现有预检逻辑，生成canonical statement_sha256/evidence_sha256及preview，追加审计观察。不能再次读取声明生成不一致的证据哈希；不更改原声明/账本/绑定，不读key/联网。对账输入/绑定无效时不得创建审计文件。journal与workspace内任意文件/同目录账本，以及statement路径冲突应拒绝；本批CLI要求journal位于工作区目录树之外，避免混入证据/模型恢复；这只分离文件位置，不构成可信边界。

CLI `verify-ledger-audit --journal ...`只读校验。合法record/verify返回0，错误1；没有apply/settle/release/trust/force/production-switch参数。不自动为既有只读预检写审计，只有显式audit-record才追加。

## 4. 信任边界与退出条件

触发器与哈希链用于拒绝常规API改写并发现部分损坏，拥有文件/SQL权限者可删除触发器、改写并重算或回退整库；没有外部独立锚点时完整旧链仍可能verify成功，不能宣称恶意防篡改/同身份防回退。文件在工作区外、fsync或SQLite提交均不自动使其成为外部可信高水位。审计只记录所观察状态，不持有账本提交锁，也不保证观察与后来付费调用/恢复切换原子一致。

本轮部署模式明确为local_untrusted_audit、production_switch_disabled。独立持久单调服务/受控存储/外部签名锚点的选型、凭证、部署、故障闭环尚未验证，不虚构已接通服务或默许云支出。未来选定可信后端并通过丢失/倒退/并发/不可用等验收前，不撤销trusted_high_water_unavailable，不将事件标为verified/applied、不释放pending。

验收必须包含：重复幂等、观察变化追加、多账本全局序号、SQL UPDATE/DELETE拒绝、缺触发器/坏链/坏payload/错hash拒绝、幂等命中先验证、同一旧库整体回退仍可能verify成功的限制、只读缺文件不创建、并发竞争、错误脱敏、角色路径冲突、声明恰一次读取、原账本业务不变、所有输出始终无结算/切换许可。独立审查，不以合成数据冒充可信账单或外部高水位。
