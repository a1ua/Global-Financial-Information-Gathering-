# Batch38 开发交接

`B38-SCORE-PROVENANCE` 为合成抽取评测命令加入 `--include-provenance`。追溯信息绑定实际读入的原始 JSON 字节和已校验的 UTC 截点。开关未启用时，评测结果继续使用 `synthetic-extraction-evaluation/0.1` 的原有字段。 [使用说明](contracts/synthetic-extraction-v0.1.md#本地命令)

`QA-B38` 独立运行 17 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 644 项，641 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-38-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。真实模型输出、独立标注集和授权行情仍待验收。
