# 合成评价周度汇总

summarize_synthetic_week(results, *, week_monday) 接收至多 1000 个 Batch26 结果。week_monday 为规范 YYYY-MM-DD 的周一，周区间按 Asia/Shanghai 的回执日期定义，首尾为周一含、下一周一不含。每条结果必须在该周，重复 prediction_id 统一拒绝，由调用方明确选择要汇总的评价版本。输入支持空列表。

接收 Batch26 的精确字段集合、版本 synthetic-abnormal-return/0.1 和 is_synthetic=true。ID 按项目 identifier 检查；内容、计划日历和协议哈希为规范 SHA-256；UTC 回执及 as_of 使用项目 instant，且 as_of 不早于回执。状态与原因匹配：calculated / null，pending / window_incomplete 或 window_not_closed，unavailable / missing_prices。calculated 的价格快照哈希有效，缺失列表为空，segments 1 至 5 项，car 为规范 8 位小数字符串；pending 的价格哈希为 null，缺失列表和 segments 均为空，car 为 null；unavailable 的价格快照哈希有效，至少一条腿缺价，segments 为空且 car 为 null。每个分段精确键 session_date、target_return、benchmark_return、abnormal_return，规范日期严格递增，比例同样为 8 位小数。缺价日期数组各自为 0 至 5 个规范日期且严格递增。比例限制为可选负号、1 至 24 位整数和 8 位小数，禁止前导零与负零。这里只校验已计算结果结构，Batch26 在上游核算。

返回精确键 schema_version=synthetic-weekly-review/0.1、is_synthetic=true、week_monday、counts、protocols。counts 含 total、calculated、pending、unavailable 四项。protocols 按 evaluation_protocol_sha256 升序，每项含该哈希、同样的 counts、mean_car。每组只按 calculated 样本已有的 CAR 精确求算术平均，保留 8 位小数并以 ties-to-even 舍入。没有已计算结果时 mean_car 为 null。输入顺序不影响输出。验证失败抛 ValueError("synthetic_weekly_review_invalid")。

该报告用于合成联验。判断数量不代表统计独立样本数。状态按每条传入结果各自的 as_of 记录，周归属由回执决定。结果保留各状态的分母，按固定协议哈希分组，不汇成跨协议的平均值。
