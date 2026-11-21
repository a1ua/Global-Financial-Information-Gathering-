# Batch16 判断输入校验

2026-11-18。P16-CONTRACT 由主控冻结判断输入契约，QA-B16 先审设计再独立验收。P16-VALIDATE 由 prediction16 独占两个 prediction_input.py 模块及 tests/test_prediction_input.py。文件范围登记在任务板。

以合成判断数据验收精确字段、哈希、时间和引用关系，复用 schema4 精确取证读取器核对证据及原文。主控运行完整离线回归，独立QA核查主要反例。存储及迁移安排在 P17。
