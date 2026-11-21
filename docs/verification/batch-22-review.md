# Batch22 独立验收

2026-11-20。范围为上交所兼容、深交所计划交易日来源和离线指数日线核对。

- 深交所示例中的 7 个休市区间与年度通知逐一一致。中秋国庆后续通知与相应区间一致。2023 年及 2026 年规则第 2.3.1 节分别给出常规工作日安排。[年度通知](https://www.szse.cn/disclosure/notice/general/t20251222_618087.html) · [后续通知](https://www.szse.cn/www/disclosure/notice/general/t20260917_622911.html) · [2023 年规则](https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020230217564423808793.pdf) · [2026 年规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)
- 独立 Python 3.12.14 脚本退出码 0。上交所原输入和快照哈希保持稳定。两所示例均编译出 242 个相同计划交易日，来源和快照哈希各自区分。春节和国庆边界符合通知。
- 同一份合成日期行分别测试对应市场的 API 和 CLI。结果一致地报告缺失 10-08、意外 10-07 和重复 10-09，原始响应哈希准确，文件字节保持不变。CLI 对上述差异返回 2。两所即使计划日期一致，交换日历也分别返回限定错误并以 1 退出。异市场代码后缀及异市场来源域名同样拒绝。正常 CLI 调用测试显式拦截网络与数据库连接。
- 独立复跑 scheduled_sessions、market_sample_audit、szse_index_audit、batch21_cli、batch22_cli 五个定向测试模块。16 项全部通过，耗时 0.280 秒，退出码 0。

本轮通过的是计划日期、响应格式和覆盖核对。真实供应商样本、标的映射、实际交易会话、开盘价形成和数据留存仍待 MKT-01 验收。全部测试行情为合成数据，供应商调用为 0。
