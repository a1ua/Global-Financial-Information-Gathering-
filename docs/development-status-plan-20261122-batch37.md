# Batch37 开发交接

`B37-SCORE-SAMPLE` 在 `config/synthetic-extraction-evaluation.example.json` 提供四条可直接运行的合成评测样例，覆盖 `synthetic-extraction-evaluation/0.1` 的全部计数结果。使用文档给出的 UTC 截点运行，样例的正确、错误、无效和缺失各为 1。 [运行命令](contracts/synthetic-extraction-v0.1.md#本地命令)

`QA-B37` 核对了内容哈希、引用位置、实跑结果及提前一微秒的截点拒绝。14 项定向回归全部通过。完整 `./scripts/dev.ps1 test` 运行 641 项，638 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-37-review.md)

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。NLP-02 的生产抽取仍需真实模型验收和独立标注集。MKT-01 仍待授权行情与实际会话证据。
