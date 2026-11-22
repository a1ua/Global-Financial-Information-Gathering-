# Batch30 独立验收

`QA-B30` 于 2026-11-22 验收上交所和深交所指数样本核对命令的 `--explain-scope` 选项。新增测试位于 `tests/test_batch30_market_scope.py`，使用 `scheduled-session-source/0.1` 合成日历和本地构造的供应商响应。

使用可用的 Codex Python 解释器，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP`、`TMP` 指向工作区中 `out/test-temp` 的完整路径。

```powershell
& $py30 -X utf8 -m unittest test_batch30_market_scope test_batch21_cli test_batch22_cli test_market_sample_audit test_market_sample test_scheduled_sessions test_tushare_sample -v
```

29 项通过，耗时 0.752 秒，退出码 0。两个市场均核对了以下结果。

- 选择 2026-10-07 至 2026-10-11 时，区间首日和末日的非计划日期归入 `inside_range_not_scheduled`。区间前日期和下一年度日期归入 `outside_requested_range`。两个列表按日期排序，合起来覆盖原有意外日期。重复与缺失日期仍独立报告。
- 命令行与 Python API 的 JSON 内容一致。移除新增字段后的详细报告与默认报告完全相等。完整样本、异常样本和无效响应的退出码分别为 0、2、1。未将供应商原始错误消息写入诊断。
- 样本文件和日历文件保持原样。测试在数据库连接和网络连接入口设置失败断言。

验证仅覆盖合成样本与计划日历。真实供应商样本、实际会话、获取和留存许可仍待 MKT-01 验收。
