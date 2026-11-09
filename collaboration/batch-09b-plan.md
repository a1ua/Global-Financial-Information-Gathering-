# Batch09-B：证据库只读候选输入清单

2026-11-09，基线本地cca420a、GitHub7f2f96b。先冻结契约、独立设计审查，再派发实现。读已有证据库，不联网采集、不做模型抽取、不将输出送入mock或DeepSeek，不改schema和报告。

| ID | 负责人 | 独占可写范围 | 依赖/验收 |
| --- | --- | --- | --- |
| B09B-CONTRACT | 主控 | docs/contracts/evidence-candidates-v0.1.md、共享计划/任务板 | 单读快照、receipt、最新可用版本、闭包哈希及历史稳定性先设计QA |
| B09B-SELECT | 证据Agent | src/market_intel/pipeline/evidence_candidates.py、tests/test_evidence_candidates.py、docs/evidence-candidates.md | 只读schema4，严格现有bundle/身份/文件，固定版本与计数，错误脱敏，历史追加/WAL边界 |
| QA-B09B | 独立QA | docs/verification/batch-09b-review.md | 设计及稳定实现的独立负例/时点/版本/只读/CLI验证 |
| WB-09B | WorkBuddy | collaboration/workbuddy/results/WB-09B-report.md、WB-09B-results.json | 固定契约一次普通同步子任务，完整正文或如实blocked，tests_run0 |
| B09B-INTEGRATION | 主控 | cli.py、tests/test_batch09b_cli.py、共享文档与发布 | 只读候选命令、安装/完整测试、现有真实元数据库只读验证（不刷新）、GitHub上传 |

每文件单写者；主控独占schema/CLI/依赖，产品确定性流水线。原证据库4/模型3不变。合成故障样本不等于真实来源验收；真实验证只说明此前已归档标题元数据能形成候选清单。
