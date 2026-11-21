# 上交所指数日线离线核对

明确指定两个本地 JSON 文件、六位 .SH 指数代码及同年起止日期。日期包含首尾，并选出快照内的计划交易日。跨年、无计划日期、其他市场后缀均拒绝。供应商返回的区间外行照常纳入意外日期，重复日线保留供核对。

命令示例：

```powershell
python -m market_intel sse-index-sample-audit --calendar config/sse-2026-scheduled-days.example.json --response out/sample.json --symbol 000300.SH --start-date 2026-10-07 --end-date 2026-10-09
```

response 使用上一批的六列响应契约。两个文件分别限 256 KiB。命令向标准输出写入 JSON，包含原响应字节 SHA-256、计划日历快照 SHA-256、标的、区间和覆盖结果。退出码 0 表示覆盖完整，2 表示存在缺失、意外或重复日期，1 表示文件、输入或供应商响应错误。

.SH 仅限定本命令适用范围。标的映射、实际交易日期、授权与使用范围须凭供应商及交易场所证据验收。合成样本可以验证程序行为，生产接入另需有据可查的真实样本。
