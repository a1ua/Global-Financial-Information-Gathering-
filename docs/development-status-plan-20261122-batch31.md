# Batch31 开发交接

`B31-RECEIPT-CLI` 在 `src/market_intel/cli.py` 增加 `compare-provider-receipt`。它按 `provider-receipt-claim/0.1` 读取本地声明，并复用只读账本接口输出 `provider-receipt-comparison/0.1`。结果列出本地缺项、字段差异和金额比较口径。 [使用契约](contracts/provider-receipt-v0.1.md)

`QA-B31` 独立验收 31 项定向测试，全部通过。覆盖命令与 Python API 一致性、账本和声明文件不变、文件上限和输入错误。 [验收记录](verification/batch-31-review.md)

完整 `./scripts/dev.ps1 test` 运行 619 项，616 项通过，3 项因 Windows 符号链接权限跳过。

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。NLP-01 仍待明确启用后的真实模型用量、供应商收据及账户扣款验证。MKT-01 仍待授权样本与实际会话证据。
