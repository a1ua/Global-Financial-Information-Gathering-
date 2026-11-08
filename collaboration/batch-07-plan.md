# Batch 07：固定工作区账本身份与路径绑定

基线本地199d8ec、远程84fbcac。开工仅WB-06两份结果被WorkBuddy后续续写；保留并核对，不覆盖。父任务NLP-01仍in_progress；本批只完成身份/路径绑定子集，不自动调用DeepSeek或重启旧WorkBuddy任务。

| 工作包 | 负责人 | 独占可写路径 | 依赖与验收 |
| --- | --- | --- | --- |
| NLP-01-BINDING | 绑定实现Agent | src/market_intel/llm/binding.py、tests/test_ledger_binding.py、docs/ledger-binding.md | 依赖下述schema3契约；固定路径、只读预检、缺失/替换/移动拒绝、显式接管未绑定旧库、错误码与崩溃失败关闭 |
| NLP-01-BACKUP3 | 恢复实现Agent | src/market_intel/ops/llm_backup.py、tests/test_llm_backup.py、docs/llm-backup.md | 支持schema1/2/3；身份随快照保留、清单和库身份一致、历史兼容、只新目录恢复 |
| QA-B07 | 独立QA Agent | docs/verification/batch-07-review.md，代码只读 | 独立验证绑定/迁移/pending/费用与恢复边界；不可用自身实现作为唯一验收 |
| WB-07 | WorkBuddy同步子任务 | collaboration/workbuddy/results/WB-07-report.md、WB-07-results.json | 只读固定契约；尝试一个同步、非团队、非后台子任务；没有完整返回即如实blocked，不循环等待，不代写 |
| 主控 | 集成者 | llm/client.py、cli.py、tests/test_llm_cny.py、tests/test_batch06_cli.py、tests/test_identity_migration.py、共享契约/文档/任务板 | schema3迁移、CLI接入、全量与安装验证、Git/GitHub发布；不启用真实调用 |

共享契约：docs/contracts/ledger-binding-v0.1.md。同文件仅一个写入者；不切换共享分支，不改依赖。schema迁移与CLI由主控串行处理。

不在本批：同身份旧备份的回退检测、跨工作区/账户全局额度、人工账单结算、生产恢复切换、真实API验证、NLP-02。身份绑定不能被写成上述能力已完成。
