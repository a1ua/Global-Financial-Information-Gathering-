# Batch08：人工对账与受控恢复前置

日期2026-11-09；基线本地2817ba2，远程8c5e23a。已有未提交`docs/development-status-plan-20261109.md`保留。先核验本地对话归档manifest与当前状态；旧对话不授予新增权限。

本轮先完成08-A契约独立审查，再实现08-B只读对账/恢复预检。未获得供应商可信逐调用账单及外部可信高水位前，不实现费用释放、修改调用状态、生产库切换或“防回退已完成”声明。不可变审计记录/终态结算属于后续工作包。

| ID | 负责人 | 独占可写范围 | 依赖、验收 |
| --- | --- | --- | --- |
| B08-CONTRACT | 主控 | docs/contracts/reconciliation-v0.1.md、共享计划/任务板 | 明确证据字段、状态、不可释放条件、高水位边界及负例；设计QA通过再派发实现 |
| QA-B08 | 独立QA | docs/verification/batch-08-review.md | 先只读审契约；实现稳定后独立测试，不自行实现产品 |
| B08-RECONCILE | 对账Agent | src/market_intel/ops/reconciliation.py、tests/test_reconciliation.py、docs/reconciliation.md | 只读独立外部声明与账本比对，不认证凭证，不写审计/预算；缺项/差异明确阻断 |
| B08-RECOVERY | 恢复Agent | src/market_intel/ops/recovery_preflight.py、tests/test_recovery_preflight.py、docs/recovery-preflight.md | 严格快照验证、固定绑定核对、闭包差异、默认禁止切换；非可信高水位不伪称可切换 |
| WB-08 | WorkBuddy | collaboration/workbuddy/results/WB-08-report.md、WB-08-results.json | 仅固定契约普通同步子任务设计审查，回收正文或如实blocked，tests_run0 |
| B08-INTEGRATION | 主控 | CLI、tests/test_batch08_cli.py、交接文档、Git发布 | 只读命令、脱敏错误、全量/安装验收、独立审查后发布；不读真实key/发真实API |

同文件单写入者；产品确定性流水线、不加依赖。对账/预检输出不是不可变审计或可信账单；同身份回退检测、生产切换、pending终态仍未完成，NLP-01保持in_progress。
