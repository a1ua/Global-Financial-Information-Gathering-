# WB-10：成功调用供应商响应关联审查 — 结果报告

- task_id: WB-10
- status: completed（非 blocked）
- execution_mode: 普通同步阻塞只读子任务；run_in_background=false；未设 team/name；subagent_type=general-purpose；契约全文内嵌；恰一次调用
- subagent_used: true
- raw_result_recovered: true（取得完整三点正文）
- tests_run: 0
- finalized: true
- 边界说明：只读本任务单与 docs/contracts/provider-correlation-v0.1.md；未读代码、凭证、配置、环境、账户、运行数据或聊天归档；未运行命令、网络或测试；未操作旧 WB 任务；未编造时间；定稿后不覆盖。

## 子任务完整正文（逐字保留）

1. 关于 completion id hash 与 HTTP 请求 ID / 账单认证的边界：已明确。契约把该 id 定性为"标识chat completion，不是已核实的HTTP request_id或账单ID"，存储侧"只存原始id UTF8 SHA256，不持久化/输出原ID或响应头"，语义侧"hash是关联线索，不是签名、认证或可信外部锚点；真实API/账单未验证"、"provider字段仍只是既有本地标记，不认证来源"，并进一步"重复哈希只是线索，不作为幂等扣费依据或账单证据"、"id哈希不等于外部账单可信匹配"。账单认证一侧由摘要固定字段"invoice_verified=false"、"settlement_allowed=false"收口。契约未把 hash 提升为认证或账单证据；其措辞"不是已核实的"把结论止于"未核实"，并以"真实API/账单未验证"标注该边界的终点，未出现跨层混用，已明确。

2. 关于「仅成功同事务添加关联 / 缓存命中不补写关联 / 失败与超时保留全额预留」：清晰，无自相矛盾，范围已明确。三条由同一前提贯通："只在实际接受正整数usage后同成功事务添加metadata"、"只有input/output正数且可在预留内结算的成功行添加"，且"无usage通用mock成功不添加关联"。缓存侧"缓存命中不调用transport、不新增行/费用或补写关联；原call_id保留其旧metadata，旧成功缓存缺关联仍可命中，不伪装新关联"；失败侧"失败、超时、输出schema错误即使已收到响应，也不保存关联/usage，本轮范围明确限成功完成；每次retry仍独立call_id/attempt和预留"，并由"非法hash导致固定invalid_provider_response错误、失败保留全额预留"、"不接真实候选到模型、不自动结算或释放pending"、"pending/failed所有关联合理为空"闭合；验收句"retry/超时与错误输出保留预留"覆盖超时与错误输出的预留保留。所引各句均把关联写入限定在成功路径，缓存命中段落明确"不补写关联"，未见成功路径之外写入关联或缓存命中补写关联的表述，三条彼此一致，未见矛盾或遗漏；契约以"本轮范围明确限成功完成"收口，已明确。

3. 关于只读查询（inspect_model_call / CLI model-call-info）与备份/恢复兼容性的表述：未见夸大，相关限定已明确。备份侧只写"模型schema3和原表列不变，备份/恢复/对账逐行比较自然包含原metadata字符串"，并限定"历史schema1/2/3无字段全部保持兼容；不为旧行自动补字段"、"隔离恢复不提供生产切换授权"，未把兼容表述为自动补字段或生产切换授权。只读查询侧"不新建库/绑定，不用ModelClient，不查询环境/密钥，不网络"，摘要固定"read_only=true、model_called=false、invoice_verified=false、settlement_allowed=false"；契约同时主动声明"主库业务只读不保证零文件变化"、"SQLite/WAL可能维护协调文件"、"完整ledger验证可能因无关坏行拒绝，不能承诺只验一行/局部故障无影响"，并标注"NLP-01/G3仍未完整通过"。这些均为收敛式、否定式自我限定，而非对"只读""兼容"的扩张性承诺，故夸大不成立，边界已明确。

## 实际回执（逐字）

[Agent ID: agent-85c1d6dd-e36e-4787-a89c-396a8870c8f1]

单次普通同步阻塞调用内联返回完整正文；返回内容为纯文本审查，未见工具调用或文件读写；无后台任务号、无轮询、无重试、无代写。实际回执不含时间信息，故本报告不写入任何时间字段。

WB-10 FINALIZED
