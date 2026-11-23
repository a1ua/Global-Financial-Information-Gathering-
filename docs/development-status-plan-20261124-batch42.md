# Batch42 开发交接

`B42-NLP-CLUSTER` 实现离线合成事件聚类候选计划。按固定 UTC 截点筛选输入，输出精确去重和同标题待核对候选，并保留历史版本与已标记的冲突证据。 [使用契约](contracts/synthetic-event-cluster-v0.1.md)

`QA-B42` 独立运行 50 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 共 706 项，702 项通过，4 项因 Windows 符号链接权限跳过，退出码为 0。 [验收记录](verification/batch-42-review.md)

生产 NLP-03 保持待开发。后续需要 NLP-02 的真实提案与独立标注，用于分别衡量误合并和漏合并。真实行情和真实模型用量的前置验收仍待完成。
