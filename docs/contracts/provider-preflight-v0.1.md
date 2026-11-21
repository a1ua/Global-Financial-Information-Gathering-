# 供应商验证证据预检 v0.1

2026-11-17，设计经 QA-B12 复核。API preflight_provider_evidence(workspace, call_id)，CLI provider-evidence-preflight --workspace PATH --call-id ID。

仅调用一次 inspect_model_call，复用绑定schema3账本单只读事务与完整校验，call_summary原样包含model-call-info/0.2的26字段。budget_day_utc取已验证started_at前10字符；_ledger保证该UTC日期等于原账本call.day，不使用今天费率或日期。

输出schema_version=provider-evidence-preflight/0.1，status=evidence_incomplete，read_only=true；model_called/invoice_verified/settlement_allowed/switch_allowed均false。evidence_gaps按顺序：hash为null时response_hash_missing；任一usage为null时usage_missing（0仍为存在）；永远supplier_receipt_missing。supplier_receipt_requirements固定列出response_id_hash/provider/model/utc_day/currency/input_tokens/output_tokens/billed_amount/provenance。

仅整理本地观察和原费率估算，清单不是完整账单认证协议。无外部文件/声明输入，不能证明供应商来源、扣费、账户全局限额或释放pending。失败保持全额占用。错误沿用固定model_call_*；缺库不创建。SQLite只读可能维护WAL协调文件，非跨绑定/数据库原子或抗特权回退。
