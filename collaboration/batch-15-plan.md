# Batch15：ENG-04判断存储契约设计

2026-11-17。依完整开发任务流计划推进判断持久化。当前模型/行情/评价协议尚未验收；本轮先完成可实现、可独立审查的存储设计，禁止直接上schema迁移。

B15-DESIGN：judgment_design15，独占docs/prediction-storage-design.md，读取现有证据库/备份及判断基线，产出字段、引用、事务/回执、幂等和迁移方案。
B15-CONTRACT：主控，独占docs/contracts/prediction-storage-v0.1.md、本计划、任务板、最终验收及最新计划。
QA-B15：qa15，独占docs/verification/batch-15-review.md，独立核对当前实现与新契约可实现性，不把设计检查算代码测试。

完成条件：冻结精确引用/UTC提交回执/追加更正/模型跨库引用/未就绪协议拒绝/备份迁移边界；明确下一批独占文件与测试矩阵。仅改设计文档，不改schema/源码/运行库/CLI/deps，无live/来源刷新/WorkBuddy派发。ENG-04仍in_progress。
