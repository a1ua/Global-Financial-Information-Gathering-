# 合成判断评价窗口

plan_synthetic_evaluation_window(value, receipt) 接收经 P16 校验的合成判断内容与输入，以及 prediction-receipt/0.1 提交回执。回执的键为 schema_version、prediction_id、content_sha256、committed_at。检查判断 ID 与规范内容哈希，回执 UTC 时点须不早于创建时间。回执应由已提交的 P17 存储读取。纯函数验证引用一致性，无法自行证明回执来源。

从固定日历按顺序选取 opens_at 严格晚于 committed_at 的会话，精确开盘相等时跳过该会话。最多取协议 horizon_sessions 项。足额返回 planned，数量不足返回 pending，并保留已知会话前缀。输出版本 synthetic-evaluation-window/0.1，含状态、所选时间段、原回执时间、判断 ID、内容哈希、协议哈希、快照哈希与会话数量上限。合成标记为 true。验证失败固定返回 synthetic_evaluation_window_invalid。

planned 表示会话窗口已排定。评价成熟、真实开盘价与日线定义、市场数据完整性和收益核算由后续工作包验证。
