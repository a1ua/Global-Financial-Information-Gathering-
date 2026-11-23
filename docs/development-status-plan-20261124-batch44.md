# Batch44 开发交接

`B44-TITLE-REVIEW-COVERAGE` 增加 `--include-title-review`，单独统计同标题待核对队列覆盖的已标注漏报和异事件对。默认汇总保持兼容。 [评测契约](contracts/synthetic-event-cluster-v0.1.md#同标题候选覆盖)

`QA-B44` 的 36 项独立定向测试全部通过。合成样例命令实际回报覆盖 1 个漏报，并列入 1 个异事件对，另有 1 个漏报仍未覆盖。完整 `./scripts/dev.ps1 test` 共 714 项，710 项通过，4 项因 Windows 符号链接权限跳过，退出码为 0。 [验收记录](verification/batch-44-review.md)

生产 NLP-03 仍待真实抽取和独立标注验证。
