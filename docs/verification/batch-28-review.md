# Batch28 合成周报命令独立验收

2026-11-22 离线验收通过。命令读取 Batch26 合成评估数组，调用 Batch27 周度汇总并输出 `synthetic-weekly-review/0.1` JSON。

- `python -X utf8 -m market_intel summarize-synthetic-week --input config/weekly-review.synthetic.example.json --week-monday 2026-11-09` 退出码为 0。样例报告含 2 条合成评估，其中已计算 1 条、待定 1 条，组内 CAR 均值为 `0.15000000`。
- `python -X utf8 -m unittest test_batch28_cli test_weekly_review test_market_sample_audit test_szse_index_audit test_batch21_cli test_batch24_cli -v` 运行 17 项，全部通过，0.606 秒，退出码为 0。覆盖合成周报、沪深样本审计及市场样本离线回放。
- 独立内联检查使用 Batch26 评估函数生成已计算、待定和不可用三种状态。命令输出与纯函数结果一致，源文件字节和目录内容保持原样，并在数据库和网络调用设为失败时成功运行。
- 独立边界检查确认恰好 1 MiB 的合法输入可读取，超出 1 字节即拒绝。重复键、NaN、错误 UTF-8、截断或嵌套过深的 JSON、错误根类型、非周一日期、缺失文件和模拟链接均返回固定错误。模拟 UNC 路径在检查文件系统链接前被拒绝。

验收使用本地合成输入，UNC 路径和链接检查采用模拟。真实来源、模型调用与计划调度仍待各自启用及验证。
