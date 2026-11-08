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

## 实现验收补充（WB-06主端静态疑问澄清）

- CLI配置timeout_seconds=30，Policy只允许1–300整数秒；HTTP发送/响应头/正文共享monotonic截止时点，连接返回后检查已消耗时间。同步DNS、多地址TCP与底层TLS不能强制硬墙钟终止，不宣称绝对总墙钟上限。
- 迁移默认USD仅用于schema1已有记录。预留事务对每个新日显式写入policy.budget_currency；同日currency、token_cap或cost_cap不同均返回daily_budget_policy_changed，不能进入transport或默默换汇。
- input_bound的单位为token：将精确HTTP body的UTF8字节数按每字节1 token的保守假设取数值，再加4096 token消息余量；不是把未经转换的字节费用当token结算。该上界尚未通过真实tokenizer认证。通用max_input_bytes限制内部固定请求JSON，实际HTTP体另有限制；DeepSeek token预留使用上述实际HTTP体上界。
- 完整usage的input_tokens不得大于记录的input_bound，output_tokens不得大于本次max_output_tokens；不可信或超界则拒绝输出、保留原预留，不据未知实际费用补零或自动释放。上述规则可在本地验证，实际供应商计费一致性仍未验证。
- 第10节旧mock约定为批次05历史范围；本v0.2新增的是显式、单次、合成smoke入口，未自动启用生产模型处理。人工对账和生产恢复前置保持未完成。
