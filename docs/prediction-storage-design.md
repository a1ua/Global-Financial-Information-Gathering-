# ENG-04 判断持久化设计与实施分批

日期：2026-11-17，Batch15。共享语义契约以docs/contracts/prediction-storage-v0.1.md为准；本文概念分组不是另一个可直接实施JSON键集。精确键集/容量及合成快照结构留P16冻结。本文是设计交付，不表示schema5、判断存储API或评价已实现。现有证据库schema4、模型账本schema3和审计库schema1保持不变。共享正式契约由主控单点维护，本文说明现有实现约束和后续落地顺序。

## 1. 当前实现审查

- store/__init__.py仅有raw_items、event_versions、evidence、availability_receipts及可变采集表。insert_immutable仅允许三种证据对象；不能直接把判断混入该通用入口。
- record_visibility要求主内容事务已提交后再采样并另事务追加receipt。这是保守可用时间栅栏，不是SQLite精确提交瞬间，也不是外部可信时钟。
- pipeline/evidence_candidates.py:_plan和pipeline/candidate_snapshot.py:_load均硬拒绝非schema4。只把store.SCHEMA_VERSION改5会使既有候选/重放入口失效。
- ops/backup.py导入SCHEMA_VERSION接受范围内数据库，但仅验证raw文件/报告语义引用；新增判断表虽能被SQLite备份复制，却不代表判断闭包已经验证。必须同步扩展语义校验。
- cli.py status只列raw/event/evidence数量，不能据此证明判断可用。模型账本schema3、audit_journal schema1不属于本次证据迁移。

## 2. 内容、引用与读模型

建议将不可变内容、精确引用关联和可用receipt分开持久化。提交输入使用prediction-draft/0.1，存储内容使用prediction-content/0.1，已可用读结果使用prediction-record/0.1。最终精确字段集合及界限由主控正式契约冻结，实施不得依据本文猜测未冻结字段。

### 内容字段建议

| 字段 | 语义与约束 |
|---|---|
| prediction_id | 不含标题/URL的稳定版本ID，同ID同内容可幂等，异内容拒绝 |
| prediction_family_id | 同一判断及其更正的固定逻辑家族，禁止通过更正改变家族；target/benchmark/basis/协议/日历上下文保持一致，改变则另建家族 |
| schema_version | 内容schema，不等于数据库版本 |
| event_version_ids、evidence_ids | 非空、排序去重的精确版本引用；不能引用event逻辑ID或查询latest |
| cluster_version_id | 初始实现必须null；聚类快照未落地前不能接受不透明字符串冒充冻结成员 |
| model_call_ref | 概念分组；正式契约用model_ledger_id、model_call_id、model_call_manifest_sha256三个字段表达，不是单独call_id即可证明归属 |
| created_at | 创建记录的UTC时间，不作为评价起点；不能晚于receipt时间 |
| target_instrument_id、benchmark_instrument_id | 必须属于固定证券主数据版本，不能仅凭可解析字符串认定可评价 |
| direction | positive/negative/neutral/mixed/uncertain |
| direction_basis | absolute_return/benchmark_relative；不隐式切换口径 |
| judgment_confidence | low/medium/high，仅模型自评，不是校准概率 |
| reasoning | 有界UTF8文本，只解释已绑定输入，避免存凭证或日志 |
| counter_evidence | 精确反证evidence_id集合；须属于固定输入闭包，不另存可漂移引用 |
| abstention_reason | uncertain必须非空，其他方向初始可固定null；缺失信息不能补造 |
| evaluation_protocol_ref | 概念分组；正式字段evaluation_protocol_id、evaluation_protocol_sha256；协议内容须有可验证持久版本 |
| calendar_snapshot_ref | 概念分组；正式字段calendar_snapshot_id、calendar_snapshot_sha256；必须包含会话版本，不得查最新日历 |
| rules_version | 不可变规则版本 |
| input_manifest_sha256 | 精确输入manifest的规范JSON哈希，不能只哈希ID列表而漏掉外部快照 |
| supersedes_prediction_id | 初始null；更正只追加，指向同家族当前链末节点 |
| is_synthetic | 初始实现true；生产模式另经前置完整验收 |

输入manifest应包含精确证据bundle描述符（沿用candidate-snapshot/0.1）、模型调用证据快照、协议payload/哈希、日历manifest及证券主数据版本。集合字段规范排序、拒绝重复；有顺序语义的内容不得静默排序。规范化使用既有python-json-sorted-utf8/0.1：UTF8、sort_keys、紧凑分隔符、ensure_ascii=false、allow_nan=false；不做Unicode规范化、时区猜测或浮点容差。存储前只接受严格字段、类型、大小和UTF8可编码值；整体容量与文本上界须在正式契约冻结。

### 关联完整性

同market.db内通过关联表为event/evidence/父判断设置真实外键；payload ID须与列一致，关联表精确等于payload集合。每份evidence必须指向本判断输入的event/raw，validate_bundle与现有精确加载器复核内容哈希/可用回执。输入manifest必须冻结全部闭包，不能只验证单独ID存在。

模型账本是独立SQLite数据库，不能伪装为同库FK或跨库原子提交。先读取并固定已绑定、已校验模型调用证据快照，再在判断证据库保存快照manifest及其哈希；生产启用前明确快照字段（包含调用输入哈希/提示词/规则/输出schema版本与成功输出哈希，安全摘要26字段不足以证明输入输出归属）与留存规则。当前手工声明不能替代这个桥接证明。

协议、日历、证券主数据须具有可验证不可变registry或完整自包含快照，否则生产提交拒绝。不能把尚未创建的protocol/calendar ID填进合成例子后当生产引用成立。

## 3. 提交时序与committed_at

1. 在单写者约束下，验证请求、固定全部输入和版本；获取BEGIN IMMEDIATE，重验同库引用与更正链末端。
2. 以一个事务追加内容及引用关联。失败整体回滚，不写receipt，也不返回已提交判断。
3. 内容事务明确commit成功后，重新读取UTC时钟，检查不早于created_at、全部输入有效可用时刻及同家族已记录receipt；回退时拒绝封存，不回填更早时间。
4. 另一个事务追加prediction_availability_receipts(prediction_id, content_sha256, committed_at)，该表也不可UPDATE/DELETE/REPLACE。对外已提交读模型把内容与receipt组合，committed_at仅来自该receipt。
5. receipt事务commit成功后才返回可用判断。它是内容已经提交之后的保守栅栏；不能声称等于第二事务精确持久化瞬间。未来评价只能选择开盘严格晚于此栅栏的会话，且不得凭此声称跨文件系统/外部时钟原子性。

若在步骤2后崩溃，内容保留但无receipt，状态为unreceipted，不可进入报告/评价。恢复必须由显式幂等resume执行：重新验证相同内容/闭包和更正前置，重新采样当前时间插入新receipt，不使用客户端原时间或根据历史创建时间补写。若已有receipt则返回原值而不重采样/改写。

## 4. 不可变、更正与幂等

- 内容、关联表和receipt均须有UPDATE/DELETE拒绝trigger；另设BEFORE INSERT冲突guard拒绝INSERT OR REPLACE，包括recursive_triggers=OFF场景。
- 同prediction_id同规范内容：内容阶段幂等；有receipt直接返回，缺receipt仅显式resume补保守栅栏。相同ID不同内容或manifest一律固定冲突错误。
- 一个家族只有一个根判断，每个父判断最多一个后继；以根唯一约束、supersedes唯一约束、同家族检查、外键及事务共同避免分叉。父必须已取得receipt，新内容不得先于父可用。同家族target/benchmark/direction_basis/协议与日历快照保持一致，改变上下文另建家族。
- 更正只能追加新ID/内容，不覆盖原判断、原输入manifest或原receipt。历史报告固定prediction_id，后续更正不能悄悄改变旧报告。链末端视图只用于新请求，不用于重放。
- 非同家族、自指、跳过当前末端或循环均拒绝。数据库触发器与应用校验互补，不能把应用层检查当作所有SQL写入都不可变。

## 5. 合成首包与生产边界

首次持久化实现仅开放显式synthetic模式，新独立测试副本中所有证据、模型调用、协议、日历和证券主数据均是完整fixture，is_synthetic一致。API必须拒绝非合成请求和合成/真实混用；不能把不存在的外部ID当合法引用。没有真实模型/行情/评价协议前，不新增“生产提交”CLI，不安装调度，不生成评价成绩。

合成fixture可验证引用、事务、幂等及不可变，并不证明协议经济含义、供应商字段、开盘时间或研究收益有效。完整生产入口须等待NLP-01/02/03、MKT-01/02与REV-01相应条件；ENG-04的存储基础完成也不自动升级这些任务。

## 6. schema5迁移与兼容实施顺序

| 子包 | 写入者与范围 | 必须先满足 | 验收 |
|---|---|---|---|
| S1契约冻结 | 主控正式契约；设计Agent本说明；独立QA审查 | 精确字段/容量/哈希/receipt时序/合成边界 | 设计无阻断，未执行代码不记测试通过 |
| S2纯校验及合成fixture | 契约实现者独占新validator/tests | S1 | 合法/非法方向、UTC、哈希、引用、自指、弃权、类型及容量测试 |
| S3副本schema迁移与存储 | 主控共享store；独占存储实现/测试 | S2，迁移及所有读取兼容已设计 | 0→5/4→5副本、事务回滚、内容/关联/receipt不可变、REPLACE拒绝及恢复 |
| S4读取与备份兼容 | 主控串行协调候选、报告、backup模块 | S3与新schema验证器 | 明确支持4/5证据读取，不能简单改为任意>=4；旧manifest重放不变；新判断闭包/receipt在备份验证中覆盖 |
| S5独立集成与普通安装 | QA+主控 | S2至S4 | 原完整回归、新迁移/存储故障场景、普通安装；更新能力和限制后才决定ENG-04状态 |
| S6生产开启 | 独立后续工作包 | 真实版本registry/模型输入输出桥接/协议与行情验收 | 非合成集成、前视隔离、生产操作与恢复证据；不在Batch15冒认完成 |

禁止在S4未完成时修改全局SCHEMA_VERSION并发布，因为connect会迁移既有工作库而使当前schema4-only入口停止工作。先在隔离副本演练，正式集成同轮发布全部兼容修改；不覆盖真实数据或删除旧证据。

备份兼容必须验证predictions/关联/receipt表的ID、payload哈希和精确证据闭包，以及协议/日历/模型证据快照文件，确定manifest新增字段/版本与旧备份0.1的明确支持策略。即使无receipt内容仍属于存储数据，备份不能丢弃，但恢复后仍不可评价。workspace backup不自动包含独立模型预算账本；其单独备份/身份/生产切换规则继续有效，不宣称跨库一致恢复。

## 7. 首次代码验收矩阵（计划，未运行）

1. 同一合成输入重试同ID无重复；更改任一绑定版本/哈希产生冲突，不查询latest。
2. 内容、关联、receipt分别UPDATE/DELETE/REPLACE均拒绝，包含关闭recursive_triggers的直接SQL。
3. 未存在证据、evidence跨event、旧输入补新版本、模型调用输入归属不匹配、协议/日历opaque ID全部拒绝。
4. 内容事务异常整体回滚；内容commit后receipt前崩溃保留unreceipted，不参与报告/评价。
5. 显式resume使用恢复时保守新fence；已有receipt幂等返回，UTC回退拒绝，不回填过去。
6. 双任务同时更正同父最多一条成功，旧父/不同家族/循环拒绝，历史固定ID读取不变。
7. 输入available_at晚于请求或父receipt/created_at异常进入明确错误，不自动修时间；09:31封存不得以09:30开盘评分（实际会话选择留REV-01）。
8. schema4副本迁移到5保留原证据/报告hash；旧候选清单/重放仍按精确ID验证，旧备份按明确版本支持。
9. 判断或关联/receipt/自包含快照损坏导致backup verify失败；仅重新算文件hash不等于业务引用合法。
10. 合成fixture与所有真实模式入口隔离，拒绝生产标志及mixed输入，无模型网络、无实际行情/收益评价。

本文未运行上述任何代码验收；只完成现有源码阅读与设计。完成设计不能将ENG-04、G1或任何评价闸门标记done。
