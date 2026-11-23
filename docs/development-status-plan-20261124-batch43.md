# Batch43 开发交接

`B43-CLUSTER-SCORE` 新增 `evaluate-synthetic-event-clusters`，只对截点可用、明确标注的版本对评测精确去重规则。报告分别计数并列出规则误报与漏报。 [评测契约](contracts/synthetic-event-cluster-v0.1.md#按标注评测精确去重候选)

`QA-B43` 的 37 项独立定向测试全部通过。完整 `./scripts/dev.ps1 test` 共 710 项，706 项通过，4 项因 Windows 符号链接权限跳过，退出码为 0。 [验收记录](verification/batch-43-review.md)

生产 NLP-03 仍待真实抽取及独立标注验证。同标题候选仍供人工核对。
