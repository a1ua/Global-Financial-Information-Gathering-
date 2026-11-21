# Batch25 独立 QA

2026-11-21。合成评价窗口通过独立复核。实现要求回执精确匹配判断 ID 和规范内容哈希，且 committed_at 为不早于创建时间的 UTC 瞬时。只选择严格晚于回执的会话，剩余会话不足时保留已知前缀并返回 pending。接口从调用方收到回执，真实来源由存储调用方保证。

使用工作区虚拟环境 Python 3.12.14 和 PYTHONPATH=src;tests，运行 unittest 的 test_evaluation_window、test_batch25_integration、test_prediction_input、test_prediction_store。22 项全部通过，耗时 1.479 秒。集成用例覆盖实际写入并读取的 P17 回执。

另外运行 3 组独立烟测，全部通过。验证同日有间隔会话和跨日空档时的严格开盘边界、禁止 SQLite 和网络访问时仍可运行且输出与输入无可变对象共享、修改协议并重新计算内部哈希后旧回执仍被拒绝。异常回执返回固定错误码。
