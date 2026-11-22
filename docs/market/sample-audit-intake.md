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

## 核对两次行情取样

将同一供应商、同一接口、同一标的和同一区间的两次取样分别留存原始响应及抓取 UTC 时间。用对应市场的同一份计划日历核对。以下命令以深交所为例，上交所使用 `--exchange SSE`、对应日历和 `.SH` 标的。

```powershell
python -m market_intel compare-index-samples --exchange SZSE --calendar config/szse-2026-scheduled-days.example.json --before out/before.json --after out/after.json --symbol 399300.SZ --start-date 2026-10-07 --end-date 2026-10-09
```

三个输入文件均限 256 KiB。JSON 输出版本为 `index-sample-comparison/0.1`，保留计划日历快照和两份响应的 SHA-256，以及两次分别计算的覆盖结果。

- 两次覆盖都完整时，按精确十进制比较 OHLC。行序和小数末尾零的差异不影响结果。状态为 `unchanged` 或 `changed`，退出码均为 0。变化列表按交易日期排序，只列变化字段。
- 任何一份存在缺失、重复或意外日期时，状态为 `coverage_incomplete`，差异列表为 `null`，退出码为 2。
- 文件、参数、日历或响应格式有误时，退出码为 1。

比对可以定位两次取样的数值差异。供应商是否发布修订、修订何时生效、行情何时可供项目使用，仍需使用供应商记录和采集证据验收。
