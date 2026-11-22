# Batch34 开发交接

`B34-SYNTH-EXTRACT` 完成合成抽取提案的证据绑定原型。实现位于 `src/market_intel/contracts/synthetic_extraction.py`，输入沿用证据 bundle 及 `synthetic-extraction-proposal/0.1`，输出为 `synthetic-extraction-validation/0.1`。 [契约](contracts/synthetic-extraction-v0.1.md)

`QA-B34` 独立验收 51 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 632 项，629 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-34-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。NLP-02 正式开发仍依赖 NLP-01 的真实模型验收，后续类别评测需独立标注数据。MKT-01 仍待授权行情和实际会话证据。
