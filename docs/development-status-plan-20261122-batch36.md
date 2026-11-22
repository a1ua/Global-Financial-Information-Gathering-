# Batch36 开发交接

`B36-SCORE-CLI` 新增 `evaluate-synthetic-extraction`，从有大小上限的本地 JSON 读取合成批次并输出 `synthetic-extraction-evaluation/0.1`。 [使用契约](contracts/synthetic-extraction-v0.1.md#本地命令)

`QA-B36` 独立运行 39 项定向测试，全部通过。完整 `./scripts/dev.ps1 test` 运行 641 项，638 项通过，3 项因 Windows 符号链接权限跳过。 [验收记录](verification/batch-36-review.md)

`AG-B36` 由 Antigravity 在未关联项目的对话中审查合成命令契约，提出字节上限、批次级退出码、错误脱敏和分母的验证建议。主控补跑四个实际命令用例并通过，覆盖含多字节正文的 1 MiB 输入且全无有效提案、超过一字节、UTF-8 BOM 和深层数组。初次补查把可解析的深层数组预期写成 JSON 语法错误，核实它在评测结构校验阶段安全退出后，按实际契约复跑成功。

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。真实模型输出、独立标注集和授权行情仍待验收。
