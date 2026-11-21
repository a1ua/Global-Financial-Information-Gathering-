# 深交所指数日线离线核对

命令 szse-index-sample-audit 使用深交所计划交易日快照。输入日历必须声明 SZSE，来源网址限深交所公告及规则的官方主机。代码采用六位数字加 .SZ，区间须在快照同一自然年内。已有上交所命令继续接受 SSE 快照与 .SH，即使两所的计划日期相同，命令也会拒绝错配。

```powershell
python -m market_intel szse-index-sample-audit --calendar config/szse-2026-scheduled-days.example.json --response out/sample.json --symbol 399300.SZ --start-date 2026-10-07 --end-date 2026-10-09
```

响应须符合指数日线样本契约。报告的版本为 szse-index-sample-audit/0.1，输出包含原始响应 SHA-256 和日历快照 SHA-256。退出码 0 表示覆盖完整，2 表示覆盖存在差异，1 表示输入错误。约束与上交所命令相同。

2026 示例依据深交所年度休市通知和中秋、国庆补充通知，并按 2023 与 2026 两版规则第 2.3.1 节的共同日期口径生成。该快照记录计划日期。标的代码只是文档候选，实际来源的授权、行情时点、供给和留存需单独验收。

- [深交所年度通知](https://www.szse.cn/disclosure/notice/general/t20251222_618087.html)
- [深交所中秋与国庆通知](https://www.szse.cn/www/disclosure/notice/general/t20260917_622911.html)
- [深交所 2023 年规则](https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020230217564423808793.pdf)
- [深交所 2026 年规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)
