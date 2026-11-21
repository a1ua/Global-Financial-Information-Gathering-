# 合成异常收益核算

calculate_synthetic_abnormal_return(value, receipt, calendar_source, target, benchmark, *, as_of) 使用合成判断、P17 回执及 Batch23 固定价格版本。target 与 benchmark 各为精确对象 {snapshot, bars}，两者使用同一标明交易所的计划日历源。判断必须为 benchmark_relative 且目标与基准 ID 不同。该函数只接收合成行情。

用 Batch25 规划窗口。as_of 须为 UTC Z 且不早于回执时点。若窗口不足，返回 pending/window_incomplete。若最后一个会话收盘晚于 as_of，返回 pending/window_not_closed。处于这两种状态时价格参数不参与核算，可传 None。精确收盘时刻纳入成熟判定。

成熟后，逐一将 cohort 的开盘与收盘换算到 Asia/Shanghai。每对开收盘须同一当地日期，日期不得重复。对每条腿调用 load_market_snapshot，确认 instrument_id 等于判断指定 ID，cutoff 的解析时间等于 as_of。每条腿快照的 selected 和 missing_sessions 合集恰为窗口日期，且 start_date/end_date 必须等于首末会话日期。所选版本的 available_at 不得早于计划会话的收盘 UTC；只按快照固定哈希取版本，输入中新增修订不得替换。此桥接核对日期范围和同一计划日历源，交易所的实际开收盘另行验收。

若任一腿缺快照所需日期，返回 unavailable/missing_prices，分别列出两条腿缺失日期，数值留空。完整行情按分段计算。首段以当日收盘除以开盘减 1，其后以当日收盘除以上一会话收盘减 1。每段 AR 为目标收益减基准收益，CAR 为所有未舍入 AR 的和。以精确有理数计算，输出为 8 位小数、舍入为 ties-to-even，单位比例。0.01000000 表示 1%。不根据方向或置信度评分。

结果精确键 schema_version=synthetic-abnormal-return/0.1、is_synthetic=true、prediction_id、content_sha256、committed_at、calendar_snapshot_sha256、evaluation_protocol_sha256、as_of、status、reason、target_snapshot_sha256、benchmark_snapshot_sha256、missing_target_sessions、missing_benchmark_sessions、segments、car。判断绑定字段来自窗口计划，日历哈希指固定的判断日历。segments 每项精确键 session_date、target_return、benchmark_return、abnormal_return。未计算时 segments=[] 与 car=null，已计算时 status=calculated、reason=null；pending 的价格快照哈希为 null、缺失数组均为空。unavailable 与 calculated 绑定两条腿的价格快照哈希。

输入、回执、版本、时间或结构不符合契约时，抛 ValueError("synthetic_abnormal_return_invalid")。使用合成数值核算。本契约未涉及真实行情权限、实际会话或策略表现。
