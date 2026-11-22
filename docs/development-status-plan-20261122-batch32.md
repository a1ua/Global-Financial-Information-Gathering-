# Batch32 开发交接

`B32-RESPONSE-HASH` 在 `src/market_intel/cli.py` 增加 `hash-provider-response-id`。它从重定向的标准输入读取单个响应标识，复用账本的 SHA-256 口径，输出可填入 `provider-receipt-claim/0.1` 的字段。 [输入与输出契约](contracts/provider-receipt-v0.1.md)

`QA-B32` 独立验收的 30 项定向测试全部通过。完整 `./scripts/dev.ps1 test` 运行 623 项，620 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-32-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。NLP-01 的真实用量、供应商收据与账户扣款仍待验证。MKT-01 仍待授权样本与实际会话证据。
