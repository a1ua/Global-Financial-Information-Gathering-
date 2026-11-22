# Batch33 独立验收

`QA-B33` 于 2026-11-22 验收 `compare-index-samples`。新增用例位于 `tests/test_batch33_index_compare.py`，输入由合成日线及 `scheduled-session-source/0.1` 合成日历组成。

使用可用的 Codex Python 解释器，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的完整路径。

```powershell
& $qaPy -X utf8 -m unittest test_batch33_index_compare test_batch30_market_scope test_batch21_cli test_batch22_cli test_market_sample_audit test_market_sample test_scheduled_sessions test_tushare_sample -v
```

33 项定向测试全部通过，耗时 1.876 秒，退出码 0。

- 沪深两市命令输出与 Python API 完全一致。数字拼写及响应行顺序不同而价格等值时，结果为 `unchanged`。两份响应哈希匹配原始字节，日历哈希匹配编译快照。运行前后的响应文件字节一致。
- 实际模块入口 `python -m market_intel` 返回 `changed`。测试确认了小数第八位变化、日期排序及开高低收的固定字段顺序。
- 缺失与重复日期产生 `coverage_incomplete`，退出码 2，变化列表为 null。供应商错误及日历市场不一致均退出 1，标准输出为空，错误仅包含固定原因码。
- 直接命令用例在数据库和网络连接入口设置了失败断言，未触发连接。

本轮验证覆盖本地样本处理。授权行情、实际开市证据及价格变化的来源仍待 MKT-01 验收。
