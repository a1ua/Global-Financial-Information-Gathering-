# Batch39 开发交接

`B39-SCORE-DIAGNOSTICS` 为合成评测提供可选的失分样本定位。报告按输入位置列出错误、无效和缺失样本，默认仍输出原有汇总。 [使用契约](contracts/synthetic-extraction-v0.1.md#本地命令)

`QA-B39` 独立运行 22 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 649 项，646 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-39-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。真实模型输出、独立标注集和授权行情仍待验收。
