# 供应商凭证声明离线比对 v0.1

2026-11-17 定义 API `compare_provider_receipt(workspace, call_id, receipt)`。Batch31 提供离线 CLI，沿用相同的输入与结果契约。

输入必须是精确10字段普通dict：schema_version=provider-receipt-claim/0.1，call_id，response_id_sha256，provider，model，utc_day，currency，input_tokens，output_tokens，billed_micro_units。请求ID和声明ID必须同为call_+32小写hex且相同；响应哈希为64小写hex非null；provider为mock/deepseek；model为ASCII[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}；日期为规范YYYY-MM-DD；币种CNY/USD；token为非bool整数0..10^9，金额为非bool整数0..10^15。额外/缺失/非法字段均在读账本前固定ValueError(provider_receipt_claim_invalid)。

仅调用一次inspect_model_call复用完整schema3账本校验和单只读事务。不增加新的账本查询。预算日从已校验started_at前10字符取得，_ledger保证其等于账本原day。

输出schema_version=provider-receipt-comparison/0.1，status=unverified_comparison，call_summary保留model-call-info/0.2安全26字段，budget_day_utc，missing_local_fields按response_id_sha256/input_tokens/output_tokens顺序报告null，0是存在；mismatched_fields按provider/model/utc_day/currency/response_id_sha256/input_tokens/output_tokens/billed_micro_units顺序，仅比较本地存在字段。金额与call_summary.charged_cost_micro_units原费率估算比较，不使用当前费率。币种不同则跳过金额比较，amount_comparison=not_comparable_currency_mismatch；相同币种时configured_estimate_only。无金额delta，不输出任意声明原值。

read_only=true；evidence_authenticated/invoice_verified/settlement_allowed/switch_allowed/model_called全false。所有字段相同仍为unverified_comparison。手工声明不是外部可信凭证，哈希不是认证或供应商扣费证据；金额估算一致不是账单验证。失败/pending保留原占用、不结算、不缓存、不模型调用。

缺库/损坏/身份问题沿用model_call_*安全错误。SQLite可能维护WAL协调文件，非跨绑定文件/库原子，不抵抗特权改写。未承诺供应商真实字段或可取得逐调用账单；真实取证需另行实测。

## 本地命令

`compare-provider-receipt --workspace PATH --call-id ID --claim PATH` 接收最多 16 KiB 的本地 UTF-8 JSON 文件。拒绝链接、UNC 路径、重复键及非标准数字。有效比对以 JSON 输出至标准输出，退出码为 0，字段差异列在 `mismatched_fields` 中。文件、声明或账本错误返回 1，标准错误仅输出固定错误原因。命令不会发起模型调用。
