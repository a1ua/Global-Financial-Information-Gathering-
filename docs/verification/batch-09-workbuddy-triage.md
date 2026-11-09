# WB-09正文回收与主控处置

2026-11-09。两份结果已回收，JSON可解析，completed、raw_result_recovered=true、tests_run=0、finalized=true，报告有WB-09 FINALIZED及三点完整正文。父端列Agent ID agent-38c9bcb4-10ec-4cb3-bc82-b7d19da47a2c并声称单次同步回传。主控观察到固定文档读取、一次子任务条目和结果写入；未独立取得底层完整Agent日志，任务保持review，不计作产品测试。

| 设计意见 | 主控处置 |
| --- | --- |
| 候选集合上限与尝试次数/缓存预留口径易混 | 在冻结契约补充：仅限制候选ID集合，计数按候选，重试尝试看账本calls；缓存命中无新预留/transport但仍占名额。无需为本轮新加尝试计数输出字段。 |
| 首次ModelError与内部重试/账本拒绝的状态关系 | 明确为generate内部有界重试后对外抛错或预留拒绝；budget_exceeded等本来就是ModelError，当前failed、剩余not_attempted、整体stopped。已有测试验证，不属于新实现缺陷。 |
| 合成与真实验证、设计通过与代码通过边界 | 契约已标明独立阶段，保留其审慎意见。本批mock人工usage不证明真实token、来源或供应商账单；设计文档不替代代码验收。 |

原WB报告保持原文，不覆盖为后见结论；澄清仅文档，无产品更改。代码依据为384项完整/安装回归和独立112项联验及5组补充场景，详见batch-09.md及batch-09-review.md。不停止旧WB-06，不重启用户取消WB-04。
