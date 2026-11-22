# Batch35 开发交接

`B35-SYNTH-SCORE` 在 `src/market_intel/contracts/synthetic_extraction.py` 增加合成分类批量评测。结果保留完整样本分母，并区分正确、错误、证据绑定无效和缺失的提案。 [评测契约](contracts/synthetic-extraction-v0.1.md#合成分类批量评测)

`QA-B35` 独立验收 56 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 637 项，634 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-35-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。NLP-02 正式开发仍依赖真实模型验收和独立标注集。MKT-01 仍待授权行情和实际会话证据。
