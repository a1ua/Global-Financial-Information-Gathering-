# Batch29 开发交接

- `B29-WEEKLY-MARKDOWN` 为 `summarize-synthetic-week` 增加 Markdown 输出，默认 JSON 输出保持兼容。报告沿用 `synthetic-weekly-review/0.1` 汇总，输入仍为 `synthetic-abnormal-return/0.1` 结果数组。修改命令行、周报渲染和周报契约文档。
- `QA-B29` 增加四项命令行回归。独立定向验证 11 项全部通过，样例实跑退出码 0。完整 `./scripts/dev.ps1 test` 运行 612 项，609 项通过，3 项因 Windows 符号链接权限跳过。详见 [独立验收记录](verification/batch-29-review.md)。

主任务状态为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。MKT-01 待补授权行情样本及实际交易会话证据。NLP-01 待本地配置凭证并明确启用后进行模型用量验证。正式周报 REV-03 仍依赖生产评价链路。当前 Markdown 和 JSON 均已使用合成样例验证。
