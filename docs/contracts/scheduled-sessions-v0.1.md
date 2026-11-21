# 上交所与深交所计划交易日快照

2026-11-18。compile_scheduled_sessions(value) 为纯函数。调用方提供已固定的对应交易所自然年休市区间和来源网址，并用输出的 scheduled_sessions 核对同市场、同区间的日线。日期均为 Asia/Shanghai 本地日。

输入为普通 dict，精确键为 schema_version、calendar_id、exchange、year、closure_ranges、source_urls。版本 scheduled-session-source/0.1，exchange 为 SSE 或 SZSE，calendar_id 使用项目 ID 规则，year 为 1900 至 9998 的整数。closure_ranges 是 0 至 32 个普通对象，每项精确键为 start 和 end，采用规范 YYYY-MM-DD，包含首尾，同年，按开始日期递增且互不重叠。source_urls 是 1 至 8 个按字典序排列且不重复的对应交易所 HTTPS 网址（SSE 限 www.sse.com.cn，SZSE 限 www.szse.cn 和 docs.static.szse.cn），每项最多 512 个字符。

输出版本 scheduled-session-snapshot/0.1，含 calendar_id、exchange、timezone、year、source_sha256、scheduled_sessions、snapshot_sha256。日期由周一至周五扣除已提供休市区间生成，并严格递增。有效快照至少含一个计划交易日。原输入和输出均使用项目规范 JSON 对象哈希，输出哈希计算时排除自身字段。输入失效统一返回 ValueError("scheduled_sessions_invalid")。

上交所 2026 示例的七个区间来自年度通知，后续中秋与国庆公告印证相关日期。年度内先后适用的 2023 和 2026 修订规则第 2.4.1 节均采用周一至周五的常规口径。另列的调休周末自然排除。快照表示根据所列资料推导的计划日期，使用时需核对其他适用的临时公告、标的停牌、实际会话和供应商入库证据。接入评价仍需完成这些前置检查。

- [上交所年度通知](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)
- [上交所中秋和国庆公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml)
- [上交所 2023 年规则存档](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml)
- [上交所 2026 年规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)

深交所样例另以自身公告和规则固定来源。两所使用各自的 exchange 和来源列表计算哈希。详见 [深交所样本验收](szse-index-sample-audit-v0.1.md)。
