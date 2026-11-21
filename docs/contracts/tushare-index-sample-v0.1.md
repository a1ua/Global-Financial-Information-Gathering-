# 指数日线样本离线解析

Batch20。parse_index_daily_sample(raw, *, expected_symbol) 接收 1 至 262144 字节的 UTF-8 JSON。输入采用 Tushare 文档的 HTTP 响应结构，明确请求六列 ts_code、trade_date、open、high、low、close。调用方提供单个期待代码，格式为六位 ASCII 数字加 .SH、.SZ 或 .CSI。

顶层对象精确包含 code、msg、data。code 为整数，msg 为字符串或 null。有效非零返回码抛 tushare_sample_provider_error。成功 data 精确包含 fields、items。fields 是上述六列的任意无重复排列，items 是至多 366 行等宽数组。禁止重复 JSON 键和非标准数字。

每行的 ts_code 必须精确匹配期待代码。trade_date 为真实公历 YYYYMMDD，转成 YYYY-MM-DD。价格必须为 JSON 十进制数字字面量，限 ASCII 整数 1 至 12 位和可选 1 至 8 位小数。使用原数值词法保留小数位，拒绝指数记法、字符串价格、零和负数。开盘与收盘须在最低、最高价之间。

返回日线 dict 列表，键为 session_date、open、high、low、close。保留原行顺序与重复日期以供下一层 audit_daily_ohlc 检查，空响应保留空列表。其他格式、标的、数据错误统一抛 ValueError("tushare_sample_invalid")，错误里不接收供应商正文作为提示。

本契约仅验收文档形状的离线样本。授权、实际响应外层元数据、日期范围、标的与市场映射、时点及留存另行核对。

- [Tushare HTTP 响应文档](https://tushare.pro/document/1?doc_id=40)
- [指数日线字段文档](https://tushare.pro/document/2?doc_id=95)
