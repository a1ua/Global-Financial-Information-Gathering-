# 合成行情版本快照

Batch23 为 MKT-02 的离线实现准备。适用前提是调用方已固定同交易所的一份计划日历和一份合成行情版本列表。

- `freeze_market_snapshot(calendar_source, instrument_id, bars, *, cutoff, start_date, end_date)` 创建快照。
- `load_market_snapshot(calendar_source, bars, snapshot)` 按快照中的哈希读取原始版本，成功返回按日期排列的版本对象列表。

输入日历复用 scheduled-session-source/0.1。instrument_id 使用项目 identifier。日期是规范 YYYY-MM-DD，起始日不晚于结束日，首尾均含，均须属于日历年，并选中至少一个计划日。cutoff 和 available_at 使用项目 instant 的 UTC Z 语法。cutoff 时刻本身包括在内。

bars 为 0 至 1464 项普通 list。每项精确键 instrument_id、is_synthetic、available_at、bar。instrument_id 必须等于指定 ID，is_synthetic 必须为 true。bar 复用现有已规范化 OHLC 验证，日期须在该日历的计划日期内。available_at 转到 Asia/Shanghai 后的日期不得早于 bar.session_date。所有版本输入均校验结构。重放使用快照的 instrument_id 作为指定 ID。可用时间表示合成的系统可用时点。

创建时，同一日期有效版本按 UTC 瞬时比较，选出 cutoff 之前或等于 cutoff 的最近版本。若同一日期同一 UTC 瞬时出现多条版本，则拒绝创建。区间内未选中任何可用版本的日期列为缺失。返回精确键 schema_version=synthetic-market-snapshot/0.1、instrument_id、is_synthetic=true、calendar_snapshot_sha256、start_date、end_date、cutoff、selected、missing_sessions、snapshot_sha256。selected 按日期严格升序，每项精确键 session_date、bar_version_sha256。版本哈希覆盖完整版本对象。snapshot_sha256 覆盖其他九键，统一沿用项目规范 JSON。

重放校验快照精确字段、规范 SHA、日历内容哈希、区间、selected 格式与计划日期范围、缺失日期恰为未选中的区间计划日。按条目哈希定位版本，并复核日期与可用时点。全程使用列出的哈希，新增历史回填或修订不替换已选版本，也不自动补全既有缺失日。相同版本字节可重复出现在读取输入中。找不到选定版本即失败。返回与调用方输入无共享可变对象的结果。错误统一 ValueError("synthetic_market_snapshot_invalid")。

本切片只验证合成时间语义及固定版本读取。快照描述自身一致性，哈希可重算，无法证明所选行情是原供应商记录或快照创建者当时见到的全集。日历版本由调用方固定，日期数据不含实际会话或已公开时点。本轮的工作项独立于 MKT-01，MKT-02 正式同步依赖来源验收。
