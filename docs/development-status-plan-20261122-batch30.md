# Batch30 开发交接

`B30-MKT-SCOPE` 为沪深两市指数日线核对增加可选的 `--explain-scope`。它把意外日期按请求区间划分，方便分别核对来源响应边界和计划日历。原有报告字段与退出码保持兼容。实现位于 `src/market_intel/cli.py` 和 `src/market_intel/pipeline/market_sample_audit.py`，沿用日线样本契约及 `scheduled-session-source/0.1`。 [使用说明](market/sample-audit-intake.md)

`QA-B30` 独立验收覆盖两个市场、区间首尾、空差异和输入错误。29 项定向测试全部通过。 [验收记录](verification/batch-30-review.md)

完整 `./scripts/dev.ps1 test` 在修正深交所合成样本的来源主机后重跑，615 项中 612 项通过，3 项因 Windows 符号链接权限跳过。

主任务仍为 10 项已完成、2 项进行中、13 项待开发、1 项已取消。MKT-01 的下一步是取得授权样本并核查实际会话、开盘形成和入库时点。NLP-01 仍待凭证配置和明确启用后的真实模型用量核验。
