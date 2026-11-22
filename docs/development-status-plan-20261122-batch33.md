# Batch33 开发交接

`B33-INDEX-COMPARE` 新增 `compare-index-samples`。命令使用一份计划日历核对两次离线日线样本，在两份覆盖完整时逐日比较 OHLC。结果为 `index-sample-comparison/0.1`。实现位于 `src/market_intel/cli.py` 和 `src/market_intel/pipeline/market_sample_audit.py`。 [使用契约](market/sample-audit-intake.md)

`QA-B33` 独立验收 33 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 627 项，624 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-33-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。MKT-01 仍待授权样本、实际会话及供应商修订记录。NLP-01 仍待明确启用后的真实用量和账单验证。
