# 授权行情样本的离线核对

取得适用授权后，将原始日线响应保存到本地工作区内的非版本管理目录。按供应商请求记录标的、起止日期和抓取 UTC 时间，另行确认允许的留存及展示范围。供应商原始响应和凭证留在本地。

在已安装环境或设置 `PYTHONPATH=src` 后，按样本所属市场选择命令。下例的标的和日期用于说明参数。

```powershell
python -m market_intel sse-index-sample-audit --calendar config/sse-2026-scheduled-days.example.json --response out/sse-sample.json --symbol 000300.SH --start-date 2026-10-07 --end-date 2026-10-09 --explain-scope
python -m market_intel szse-index-sample-audit --calendar config/szse-2026-scheduled-days.example.json --response out/szse-sample.json --symbol 399300.SZ --start-date 2026-10-07 --end-date 2026-10-09 --explain-scope
```

启用 `--explain-scope` 后，顶层添加 `scope_diagnostics`。该选项也可通过 Python API 的 `explain_scope=True` 启用。两个列表中的日期去重后按升序排列，合起来覆盖 `audit.unexpected_sessions`。

| 字段 | 含义 | 核对方向 |
| --- | --- | --- |
| `outside_requested_range` | 日期早于起始日或晚于结束日 | 核对请求参数及样本导出边界 |
| `inside_range_not_scheduled` | 日期在含首尾的请求区间内，但未列入所选计划日历 | 核对适用日历、日期口径及实际会话证据 |

未启用选项时，原有 JSON 字段保持一致。退出码 0 表示覆盖完整，2 表示覆盖有差异，1 表示输入错误。两类诊断都只依据给定的样本、区间和计划日历。实际会话、开盘形成与行情入库时点、来源权限仍需另行验收。核对结果可用报告中的响应和日历 SHA-256 追溯。

参见 [上交所样本契约](../contracts/sse-index-sample-audit-v0.1.md) 与 [深交所样本契约](../contracts/szse-index-sample-audit-v0.1.md)。
