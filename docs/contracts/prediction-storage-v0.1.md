# 判断持久化契约 v0.1（设计冻结候选）

2026-11-17 / Batch15。本文规定后续ENG-04实现边界，当前无Prediction持久化代码、schema5迁移或评价开放。现有证据schema4、模型账本schema3保持不变。先独立QA后冻结。

## 1. 对象与字段

采用不可变判断内容+不可变提交回执组合，读取时组成Prediction envelope；不让调用方声明committed_at。以下为必须具备的字段与语义；精确JSON键集、字符串/数组上限和错误码在实现前的纯校验子包中冻结，不允许实现者自行扩展。

判断内容prediction-content/0.1包含：prediction_id、prediction_family_id、schema_version、event_version_ids、evidence_ids、cluster_version_id（可空）、model_call_id、model_ledger_id、model_call_manifest_sha256、created_at、target_instrument_id、benchmark_instrument_id、direction、direction_basis、judgment_confidence、reasoning、counter_evidence、abstention_reason、evaluation_protocol_id、evaluation_protocol_sha256、calendar_snapshot_id、calendar_snapshot_sha256、rules_version、input_manifest_sha256、supersedes_prediction_id、is_synthetic。内容不包含committed_at或可变评价状态。model_call_manifest_sha256是本地冻结调用摘要内容哈希，不是供应商认证。

提交回执prediction-receipt/0.1包含prediction_id、content_sha256、committed_at。其时间由存储层在判断内容事务成功提交后采样，不接收调用方时间；回执自身独立持久化，必须成功后API才返回已提交envelope。committed_at是保守的提交后可用边界，不声称精确SQLite物理提交时刻。评价模块不得使用created_at/模型开始时间代替。

created_at为带Z的UTC创建时间，不能晚于回执时间；所有引用对象的实际可用时刻不晚于内容校验截点。方向positive/negative/neutral/mixed/uncertain；basis absolute_return/benchmark_relative；置信度low/medium/high是模型自评类别不是概率；uncertain必须有弃权原因。其他方向的缺失理由不自动补造。

## 2. 固定引用与闭包

事件及证据数组非空、无重复，固定排序规则；Evidence必须属于列出的精确EventVersion，事件所需Raw/Evidence闭包完整。禁止查询latest悄悄替换引用，引用可用时刻要含真实来源availability_receipts。真实证据缺回执时拒绝。首次实现可仅支持cluster_version_id=null，非null必须先有固定成员快照验证，不允许只验证字符串存在。

input_manifest_sha256覆盖规范化固定事件/证据/raw闭包描述与内容哈希、协议/日历/调用摘要/规则版本；采用既有规范JSON约定并冻结明确版本。哈希不签名、不证明来源可信，也不替代内容读取校验。内容哈希另算，排除服务端回执，使重试不会因时间变化变成不同内容。

事件/证据/更正前驱在同一证据库可用真实外键和连接表表达；生产评价协议、日历、标的及基准须有版本化快照与闭包校验。当前这些注册表未实现，禁止把任意不为空ID当成真实引用有效。

模型账本独立数据库，不跨库伪造SQLite FK/联合原子提交。生产引用须验证固定绑定ledger_id+call_id，保存不可变且自包含的最小调用摘要快照/哈希；成功校验输出、输出哈希和精确输入必须能关联。预算状态和账单观察不能充当判断内容支持。后续账本不可用不允许回填其他call替代；本地调用快照不等于供应商账单认证。

## 3. 提交、幂等与更正

1. 完整验证内容/引用/时间/依赖，在写事务内读取同一证据快照并插入不可变内容及外键关系。提交前采样的时间仅用于校验，不标成committed_at。跨库调用摘要在事务前冻结验证并记录边界，不宣称联合原子。
2. 内容事务COMMIT成功后采样系统UTC，确保未回退到created_at、所需输入可用时间或更正前驱回执committed_at之前；异常时不伪造时间，保留无回执内容并返回未完成状态。
3. 独立事务排他追加prediction_receipts，内容哈希必须对应；已有回执返回原时间，不重复采样改历史。返回前确认回执事务提交成功。无回执判断不得用于报告/评价。
4. 相同prediction_id+相同规范内容幂等；ID相同内容不同固定冲突。内容已落但无回执的重试必须重新验证依赖/内容再补回执，补发时记录新的保守可用边界，不能补成旧时间。
5. supersedes_prediction_id=null代表家族首版本；每个family_id仅允许一个首版本（独立唯一约束），不能同家族多个根。更正用新ID、同family_id、引用唯一前驱，拒绝自引用/跨家族/分叉/缺前驱。前驱必须已取得回执；同家族保持target/benchmark/direction_basis/评价协议与日历快照一致，更正方向和理由可追加，改变上下文另建家族。严格单写者，事务唯一约束防止同前驱多后继。旧内容、回执和历史报告保持原样。
6. SQL禁止UPDATE/DELETE及冲突主键/逻辑键的INSERT OR REPLACE；不依赖recursive_triggers单独防替换。幂等在应用层先验证完全相同，不以REPLACE实现。

回执不是事务租约或外部可信时间戳，不抗特权DB改写/时钟欺骗。事务与回执不是跨事务整体原子，恢复路径必须显式处理孤立内容。

## 4. 未就绪依赖与初期实现门槛

后续存储首包仅合成模式：is_synthetic=true，事件/证据也全部合成，模型/协议/日历引用由明确合成fixture提供自包含快照，不能写成真实来源或研究判断。真实模式默认拒绝，直到NLP-01、MKT-01/02、REV-01所需契约及依赖经独立验收；未来生产开放需单独工作包，不受本契约自动授权。

实现前纯校验契约需冻结上述自包含快照的字段、引用类型和canonical格式，不能用虚构的生产注册表占位通过。这也是ENG-04下一实施子包的输入条件。当前设计只冻结语义边界，不宣称完整可执行schema已经完成。

## 5. schema迁移、备份及兼容

拟议证据schema5仅在新表/连接表/回执及不可变保护、消费者兼容、备份语义验证一并准备后实现。迁移应在副本先验证、事务内完成、失败回滚、保留已有字节。禁止本批只提升SCHEMA_VERSION。

pipeline/evidence_candidates.py:_plan与pipeline/candidate_snapshot.py:_load存在schema4严格检查，store/__init__.py定义SCHEMA_VERSION=4；ops/backup.py引用上限但缺判断语义校验。CLI status当前只计raw/event/evidence，需明确扩展判断就绪状态。模型schema3和审计schema1不随本次改变。候选快照读取存在schema4严格检查，迁移必须逐个查明证据规划/快照/重放/报告验证/备份/测试的版本假设。旧manifest保持原格式与重放语义；新库支持证据链路时仍忽略未被旧manifest引用的判断，不静默为历史报告添加判断。

备份现仅验证raw/report闭包，新增schema5须加入判断内容/回执/更正链/事件证据FK/冻结调用与协议日历快照校验，声明可恢复范围。内容已提交未回执行必须被一致保留并标记不可评价，不丢弃或伪造回执。外部模型账本不自动纳入证据备份：快照摘要仅支持引用回放，不代表可恢复预算或允许live。

旧schema0–4备份继续按原版本验证，schema5必须有专属清单/计数或明确兼容扩展，不让旧验证器仅凭数据库文件哈希通过。仅在新目录恢复，不覆盖生产库；任何snapshot/raw/协议/日历依赖缺失均拒绝整体可评价恢复。

## 6. 下一批实现分工与验收

- P16-CONTRACT：主控，精确JSON结构/上限/错误码/规范哈希、合成fixture闭包与协议快照子契约；独立QA前置。
- P16-VALIDATE：实现Agent，纯校验及固定引用加载；限定合成，不迁移主库。
- P17-STORE：主控或独占实现Agent，schema5事务迁移、判断表/关系/回执/更正链和幂等；共享schema主控整合。
- P17-COMPAT：独占备份/消费者Agent，在冻结schema5后适配快照及备份；不与store同文件写入。
- P17-QA：独立审查，既有全套+新行为+普通安装/副本迁移验收，通过后再判断ENG-04已完成范围。

必要矩阵：有效合成内容；非法/缺失/未来/错误类型引用；跨event证据；旧版本后新增事件不变；无回执不可读为可评价；COMMIT前外连接不可见、内容提交后回执前崩溃、回执失败/重试/时钟回退；同ID幂等及冲突；更正自环/分叉/跨家族；UPDATE/DELETE/REPLACE攻击；迁移回滚及旧报告重放；schema5备份缺对象/错误哈希/新目录恢复；真实模式拒绝；跨模型账本不一致拒绝。

本轮仅设计审查，tests_run=0，不运行无关代码回归、不提升ENG-04/G1/G4或宣称判断可评价。
