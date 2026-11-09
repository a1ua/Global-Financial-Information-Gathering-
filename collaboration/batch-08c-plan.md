# Batch08-C：本地追加审计与高水位边界

日期2026-11-09；基线本地9e30027、远程115a141。沿用单文件单写者、多Agent开发与确定性产品流水线。先冻结契约并独立审查，再实现；不增加依赖、真实调用、结算或生产切换。

| ID | 负责人 | 独占可写路径 | 验收 |
| --- | --- | --- | --- |
| B08C-CONTRACT | 主控 | docs/contracts/audit-journal-v0.1.md、docs/audit-trust-decision.md、共享计划/任务板 | 固定事件字段、幂等/顺序、只读校验、故障、信任边界；设计QA后开工 |
| B08C-JOURNAL | 审计Agent | src/market_intel/ops/audit_journal.py、tests/test_audit_journal.py、docs/audit-journal.md | 本地独立SQLite追加审计、链/触发器校验、幂等、并发；不改模型账本 |
| QA-B08C | 独立QA | docs/verification/batch-08c-review.md | 先审设计；稳定后独立负例/集成/只读边界/不可伪称防回退 |
| WB-08C | WorkBuddy | collaboration/workbuddy/results/WB-08C-report.md、WB-08C-results.json | 一次普通同步子任务设计审查，完整正文回收或如实blocked，tests_run0 |
| B08C-INTEGRATION | 主控 | ops/reconciliation.py、cli.py、tests/test_batch08c_cli.py、共享文档与发布 | 单次解析声明复用同一比对结果生成审计；模型账本不改；全套/安装与上传 |

只交付本地追加/链校验，不称具有外部可信高水位。完整链被整体回退/替换/重算且无独立锚点时不能发现；不实现verified/applied和pending释放。审计记录的是未认证声明的预检观察，不是供应商账单证明。缺外部可信条件继续禁止生产切换。
