# 日线样本检查契约

2026-11-18。公开 Python 函数 audit_daily_ohlc(expected_sessions, bars) 接受一组明确选定的交易会话日期与已规范化的单标的 OHLC 行。调用方负责固定供应商及标的、交易日期口径、价格类型和会话快照。

- expected_sessions 为普通 list，1–366 个严格递增的规范 YYYY-MM-DD 字符串，按真实公历验证。
- bars 为普通 list，0–366 行。每行是普通 dict，精确键为 session_date、open、high、low、close。session_date 同样使用规范日期。价格为正的 ASCII 十进制字符串，整数部分 1–12 位，可带 1–8 位小数，允许位数上限内的前导零。开盘与收盘都须落在最低到最高的闭区间。
- 任意一行结构或价格失效时抛出 ValueError("market_sample_invalid")。重复及意外日期也适用同样的行校验。
- 有效输入返回 status、expected_count、bar_count、missing_sessions、unexpected_sessions、duplicate_sessions。三类日期分别列出去重排序的结果，可重叠。bar_count 为原始行数，包括重复。三类结果皆为空时 status=complete，其余为 incomplete。

检查仅反映样本对给定会话集合的覆盖及结构。来源准入、原始字段语义、价格可用时点及数据许可由 MKT-01 另行验证。
