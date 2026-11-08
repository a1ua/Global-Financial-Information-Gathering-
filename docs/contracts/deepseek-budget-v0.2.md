# DeepSeek预算与传输契约 v0.2

用户配置：DeepSeek，每日人民币10元。官方资料核验于2026-11-08：模型deepseek-flash，非思考模式；最高时段输入缓存未命中2元/百万tokens、输出8元/百万tokens。来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ 和 https://api-docs.deepseek.com/api/create-chat-completion/ 。采用峰值、未命中费率估算，不使用折扣压低预留，不进行汇率换算。价格可能变化，不把配置估算称作账单或账户全局限额。

1. 模型账本schema2：days新增currency TEXT NOT NULL DEFAULT 'USD'；schema1迁移不改变calls/cache/daycaps/占用，旧记录仍USD。证据库schema4不变。相同UTC日不可混合币种或静默变更限额。
2. CNY金额单位为microCNY，1元=1,000,000 microCNY；每日上限10,000,000。新增Policy budget_currency、daily_micro_units、input_micro_units_per_million_tokens、output_micro_units_per_million_tokens；USD旧字段只用于向后兼容。CNY不得使用USD默认值。DeepSeek的单工作区配置不得超过用户10元，默认每批单次smoke，不承诺账户其他程序累计支出也受控。
3. 预留/计费公式为分别向上取整后相加：ceil(input_tokens*input_rate/1e6)+ceil(output_tokens*output_rate/1e6)。DeepSeek配置最低上界费率为2,000,000和8,000,000 microCNY/百万tokens，版本写入调用元数据。成功usage仅能减少至预留内实际报告token的配置费率估算；超时/不明失败/非法usage继续保留全额。
4. request_metadata保存budget_currency、两项generic每百万token费率、accounting_basis=configured_rate_estimate及既有输入/版本/单次限额。旧记录无generic字段时仅在USD使用旧micro_usd_per_token等价公式。表内reserved_cost/charged_cost采用对应day.currency的micro单位，usage不得将CNY标为USD。
5. DeepSeek传输固定https://api.deepseek.com/chat/completions，禁止URL覆盖、代理继承、重定向、工具、stream与思考模式；仅允许温度参数，保留max_output_tokens限制。JSON Output仍须本地schema校验；空白、截断、工具调用、模型不符或usage不合法明确拒绝。
6. 真实输入预留上界使用精确HTTP JSON body的UTF8字节数加4096的消息格式余量；这属于保守工程假设，未经过实际tokenizer或账单验收，不声称数学保证。实际usage超预留时不自动减账，保留失败并阻断该输出。每次重试重新预留。
7. transport版本进入缓存键；密钥通过构造参数传入，只允许CLI显式--live时读取DEEPSEEK_API_KEY环境变量，不保存、打印或发送至其他host。未配置时先失败，不预留或请求。SDK/账户/任务计划不自动安装。
8. 一致备份保留所有pending、days币种、费率依据和费用占用，支持schema1/2；只恢复新隔离目录，不能覆盖当前账本或把旧备份当最新额度。固定生产账本绑定、人工对账及恢复切换仍为独立验收前置，不因隔离恢复演练而宣称完成。
