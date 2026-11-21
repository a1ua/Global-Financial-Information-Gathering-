# P16 判断输入契约

2026-11-18。合成输入支持现有单 raw/event/evidence bundle 格式。公开函数 validate_prediction_input(value) 成功返回 None。load_prediction_inputs(workspace, value) 成功返回现有精确读取器的 verification/bundles。只有后者读取文件及 schema4 证据库。二者均使用 ValueError("prediction_input_invalid") 表示输入失效。读取器的 ValueError/OSError 统一映射 prediction_inputs_unavailable，保留输入校验错误。无数据库迁移、回执或估值。

所有下列对象都是精确普通 dict，数组是普通 list。值只允许普通 JSON 类型中的 dict/list/str/int/bool/None，整数必须在有符号 64 位范围内，禁止浮点；深度最多 16、总节点最多 32768（含键和值）、单字符串最多 65536 UTF-8 字节、所有键和值字符串的 UTF-8 字节合计最多 1 MiB，规范序列化整体也最多 1 MiB。先进行边界检查再执行下列业务校验。时间使用项目 instant() 的 UTC Z 规则，ID 使用 identifier()，非空文本去空白后长度至少 1。所有哈希使用既有 candidate_snapshot.payload_sha256。

根键为 content、inputs。content 的精确键如下：
schema_version prediction_id prediction_family_id event_version_ids evidence_ids cluster_version_id model_call_id model_ledger_id model_call_manifest_sha256 created_at target_instrument_id benchmark_instrument_id direction direction_basis judgment_confidence reasoning counter_evidence abstention_reason evaluation_protocol_id evaluation_protocol_sha256 calendar_snapshot_id calendar_snapshot_sha256 rules_version input_manifest_sha256 supersedes_prediction_id is_synthetic

schema_version 为 prediction-content/0.1。is_synthetic 必须 true，cluster_version_id 必须 null。supersedes_prediction_id 可空且不能等于自身，实际前驱验证留给存储。方向 positive/negative/neutral/mixed/uncertain，basis absolute_return/benchmark_relative，置信度 low/medium/high。reasoning 非空且最多 4096 UTF-8 字节。uncertain 的 abstention_reason 非空且最多 1024 UTF-8 字节，其他方向必须 null。counter_evidence 是排序无重复的 evidence_ids 子集。各 ID 和 rules_version 使用 identifier()。

inputs 的精确键为 schema_version、evidence_snapshot、model_call、protocol、calendar、rules_version。版本 prediction-input-manifest/0.1。evidence_snapshot 复用 validate_candidate_snapshot，至少一个候选且全为合成，cutoff 不晚于 created_at。content 的 event_version_ids 和 evidence_ids 必须精确等于描述符对应 ID 的排序列表。

其余三对象均含 schema_version、is_synthetic、available_at，标记必须 true、可用时间不晚于 created_at。model_call 额外键 ledger_id、call_id、evidence_manifest_sha256、output_sha256，版本 prediction-fixture-call/0.1。两个 ID 对应 content；evidence_manifest_sha256 等于 evidence_snapshot.input_manifest_sha256；output_sha256 等于对 content 中 direction、direction_basis、judgment_confidence、reasoning、counter_evidence、abstention_reason 六键投影的哈希。model_call.available_at 不早于证据快照 cutoff。该快照为合成 fixture，无实际模型账本查询。

protocol 额外键 protocol_id、target_instrument_id、benchmark_instrument_id、direction_basis、calendar_snapshot_id、horizon_sessions，版本 prediction-fixture-protocol/0.1。前五键与 content 一致（protocol_id 对应 evaluation_protocol_id），horizon_sessions 为整数 1..5 且不多于日历会话数。calendar 额外键 calendar_snapshot_id、sessions，版本 prediction-fixture-calendar/0.1。ID 与 content 一致，会话数组 1..32 个，每个精确键 opens_at、closes_at，均为 UTC，开盘严格早于收盘，且相邻会话的前收盘严格早于后开盘。日历可预先发布，未来会话发生时间允许晚于 created_at。

content 的四个 *_sha256 分别绑定 inputs 全体、model_call、protocol、calendar。rules_version 必须相同。纯校验验证结构和自洽，读取器复核固定 ID 对应的实际证据库内容和原文文件，复用现有只读单事务入口。自洽哈希可重算，它的用途是验证固定输入的一致性。家族更正链、可用回执和真实模型/行情引用由后续工作包处理。
