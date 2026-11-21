# Batch28 周度汇总命令验收

2026-11-22。新增 summarize-synthetic-week。命令从显式本地 JSON 读取已计算、等待和缺价结果，以指定的上海自然周汇总。返回协议分组、状态计数和已计算样本的平均 CAR。沿用 1 MiB 输入限制与严格 JSON 解析。

- 示例通过实际 python -m market_intel 命令执行。返回 2 条，其中 1 条已计算、1 条等待，协议组均值为 0.15000000。日志 out/batch28-weekly-review.json。
- 2 项新增测试通过，验证报告、输入原样保留、错误脱敏，并禁止访问数据库和网络。独立检查见 batch-28-review.md。
- scripts/dev.ps1 test 共运行 608 项，605 项通过，3 项因符号链接权限跳过，59.286 秒，退出码 0。日志 out/batch28-tests.log。

范围为合成结果的本地汇总。正式行情与模型来源验收依然分别由 MKT-01 和 NLP-01 推进，REV-03 保留为待开发。
