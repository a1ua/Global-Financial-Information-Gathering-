# 供应商响应关联 v0.1

日期2026-11-10，Batch10。DeepSeek官方文档 https://api-docs.deepseek.com/api/create-chat-completion/ 当日读取：非流式200响应有字符串id，标识chat completion，不是已核实的HTTP request_id或账单ID。这里只存原始id UTF8 SHA256，不持久化/输出原ID或响应头。hash是关联线索，不是签名、认证或可信外部锚点；真实API/账单未验证。

独立QA设计复核无阻断后冻结。DeepSeek须把纯hash函数ValueError映射既有deepseek_invalid_response；只在实际接受正整数usage后同成功事务添加metadata；查询须bound/schema3并在单BEGIN核对_ledger的ledger_id。补充共享`validate_response_hash(value)`：仅允许null或64小写hex，否则同固定ValueError。

## 共享纯契约

新增llm/correlation.py（不导入client避免循环）：`response_id_sha256(value)`，仅接受非空ASCII `[A-Za-z0-9_.-]{1,256}` 字符串，返回其原字节SHA256；错误固定ValueError，不回显内容。该字符/长度上限是本地受限契约，不声称官方只可能返回此格式。缺失id由transport给None；存在但null/非法类型/超长/Unicode/空白则拒绝。兼容既有无id模拟/旧适配器，不宣称通过官方完整响应schema校验。

`validate_provider_response(value)`纯校验合法返回None，否则固定ValueError。严格对象仅schema_version='provider-response-correlation/0.1'、response_id_sha256（null或64小写hex）、input_tokens、output_tokens；tokens严格正int非bool且<=10^12。None hash代表标识不可用；不能补造ID。`validate_call_correlation(metadata,call)`检查metadata可选provider_response；缺失为legacy/未关联，存在则必须有效、call status恰succeeded、input/output tokens与call列精确相等，不允许bool冒充数值。该函数只验证可选字段及关联，不代替完整ledger验证。共享函数错误固定provider_correlation_invalid。

ModelResponse末尾添加`response_id_sha256: str | None = None`，既有三位置参数兼容。CallResult不变。DeepSeek仅在现有_parse成功返回处读取id并hash，返回新字段；不读取HTTP头、不更改传输版本/cache-key（同请求的输出/费用语义不变）。现有模型/endpoint/错误处理不扩展。

ModelClient成功响应必须先验证response hash为null/64小写hex及正整数usage/预留限制，再在现有_finish同一事务把provider_response对象加入既有calls.request_metadata；只有input/output正数且可在预留内结算的成功行添加。mock与DeepSeek均可合法附带hash，provider字段仍只是既有本地标记，不认证来源。无usage通用mock成功不添加关联；既有元数据其余键不改，不重新写input/prompt/缓存key。非法hash导致固定invalid_provider_response错误、失败保留全额预留，且不缓存/保存响应正文或原ID。失败、超时、输出schema错误即使已收到响应，也不保存关联/usage，本轮范围明确限成功完成；每次retry仍独立call_id/attempt和预留。

缓存命中不调用transport、不新增行/费用或补写关联；原call_id保留其旧metadata，旧成功缓存缺关联仍可命中，不伪装新关联；CallResult接口不变。不强求不同calls的response hash唯一，重复哈希只是线索，不作为幂等扣费依据或账单证据。

## 备份/查询

模型schema3和原表列不变，备份/恢复/对账逐行比较自然包含原metadata字符串。llm_backup._ledger在既有严格业务验证中调用validate_call_correlation，拒绝额外字段、坏hash、tokens不符、失败/pending带关联等。历史schema1/2/3无字段全部保持兼容；不为旧行自动补字段。隔离恢复不提供生产切换授权。

ops/model_calls.py提供`inspect_model_call(workspace,call_id)`，call_id必须`call_[0-9a-f]{32}`。先复用check_workspace_ledger固定身份/路径，再对绑定schema3账本mode=ro/query_only单BEGIN内复用_llm_backup._ledger进行完整业务校验并核对绑定ledger_id，取精确call_id；不新建库/绑定，不用ModelClient，不查询环境/密钥，不网络。

返回严格摘要：schema_version='model-call-info/0.1'、status='observed'、read_only=true、model_called=false、invoice_verified=false、settlement_allowed=false、ledger_id、call_id、call_status、attempt、provider、model、started_at、finished_at、currency、accounting_basis='configured_rate_estimate'、reserved_tokens、charged_tokens、reserved_cost_micro_units、charged_cost_micro_units、input_tokens、output_tokens、input_rate_micro_units_per_million、output_rate_micro_units_per_million、correlation_status（absent/id_unavailable/recorded）、response_id_sha256。无字段=absent，合法对象nullhash=id_unavailable，否则recorded。不返回output_text/输入/提示词/原ID/headers/全文metadata/路径。金额仍原日费率估算，id哈希不等于外部账单可信匹配。pending/failed所有关联合理为空。空/缺失call拒绝固定错误。所有公开错误固定ValueError，不泄底层路径/正文；SQLite/WAL可能维护协调文件，主库业务只读不保证零文件变化。

CLI `model-call-info --workspace data/live --call-id call_HEX`只读返回摘要，成功0/错误1；不带live/force/settle/provider选择，不输出CallResult正文，也不修改deepseek-smoke输出。完整ledger验证可能因无关坏行拒绝，不能承诺只验一行/局部故障无影响。

## 验收与边界

纯schema/hash/类型/超长/重复键经现有strictJSON拒绝；模拟HTTP idhash/缺失兼容/非法存在拒绝；成功事务/cache原call/legacycache/retry/超时与错误输出保留预留；备份/恢复/对账包含关联且非法字段拒绝；只读CLI缺库不建/错ID/绑定身份/路径link/错误脱敏。验证无真实key读取/网络/model调用（模拟HTTP仅显式离线注入）。不接真实候选到模型、不自动结算或释放pending。NLP-01/G3仍未完整通过。
