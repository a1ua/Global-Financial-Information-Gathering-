# 离线供应商声明比较

2026-11-17，Batch14。API：

`compare_provider_receipt(workspace, call_id, receipt)`

仅接受内存中的普通dict，不读取外部文件/凭证，不联网或调用模型。外部声明始终未验证。字段恰为schema_version、call_id、response_id_sha256、provider、model、utc_day、currency、input_tokens、output_tokens、billed_micro_units这10项，schema_version固定provider-receipt-claim/0.1。

call_id为call_加32位小写hex且须等于指定调用；响应哈希为64位小写hex非null；provider为mock/deepseek；model为1–128位ASCII标识（首字符字母/数字，后续允许字母/数字/点/下划线/冒号/斜杠/短横线）；日期严格YYYY-MM-DD且有效；币种CNY/USD；token为0..10^9、金额为0..10^15整数且拒绝bool。未知/缺失字段及非法值先于任何账本读取以固定provider_receipt_claim_invalid拒绝，不回显传入值。

验证后只调用一次inspect_model_call，继承绑定schema3/完整账本/单只读事务校验。budget_day_utc取已验证started_at日期；_ledger保证它等于原账本day。不存在的工作区不创建；读取错误沿用既有model_call_*固定错误。SQLite可能维护WAL协调文件；绑定文件与数据库并非跨文件原子，仍非抗特权回退。

输出provider-receipt-comparison/0.1共13字段：schema_version、status、read_only、evidence_authenticated、invoice_verified、settlement_allowed、switch_allowed、model_called、call_summary、budget_day_utc、missing_local_fields、mismatched_fields、amount_comparison。status永远unverified_comparison，read_only=true，其余权限/认证布尔值false；call_summary保留model-call-info/0.2的安全26字段。

missing_local_fields按响应哈希/input_tokens/output_tokens顺序报告本地null；这些字段不能与声明判等，也不同时记不相等。其他mismatched_fields按provider/model/utc_day/currency/响应哈希/input_tokens/output_tokens/billed_micro_units顺序报告。本地0是存在，不使用truthiness判断。

币种相同时amount_comparison=configured_estimate_only，比较声明金额与原账本charged_cost（按原配置费率估算，失败/pending仍为全额占用）。币种不同时amount_comparison=not_comparable_currency_mismatch，不比较金额、不计算差额。不论金额是否一致，都不证明供应商计费口径相同或账单可信。声明本身、任意供应商字符串、原ID及正文不进入输出；只输出本地安全摘要和固定字段码。

本轮无CLI或外部输入文件解析功能。人工声明即使完全匹配也不是账单认证，不认证来源、完成度、逐调用扣费或权限；不替代供应商可信凭证、外部高水位、终态结算。失败和pending全额预算不释放，旧调用不补写，不缓存、不写账本。

## 实际验证

实现者命令：

`PYTHONPATH=src;tests TEMP/TMP=out/test-temp .venv/Scripts/python.exe -X utf8 -m unittest test_provider_receipt -v`

实际8项全部通过，1.491秒，exit0。覆盖匹配仍未认证、一次读取、字节/绑定不变、差异顺序与不回显声明、异币种不比较金额、失败/pending全额、零及上界、非法类型/字段/日期/Unicode/数值先拒绝、缺库不创建、坏库不部分输出。全部输入为合成或注入本地样本；不算真实API/账单/生产验收。全量回归与独立审查由主控/QA执行，未由实现者冒领。
