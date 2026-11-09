# Batch09-C：固定候选清单验证与重放

2026-11-09，基线本地19ec620、GitHub28c2c28。已核验用户指定归档包：26轮143条、99文件，逐文件SHA一致。现有未跟踪开发计划文档保留并纳入本轮交接；output/tmp原样不动，不上传对话/运行数据。先冻结契约并设计QA，再派实现。

| ID | 负责人 | 独占可写目录/文件 | 验收 |
| --- | --- | --- | --- |
| B09C-CONTRACT | 主控 | docs/contracts/candidate-snapshot-v0.1.md、contracts/candidate_snapshot.py、共享计划/任务板 | 严格snapshot schema/hash、精确输入语义、发布/失败边界；先设计审查 |
| B09C-VERIFY | 快照Agent | pipeline/candidate_snapshot.py、tests/test_candidate_snapshot.py、docs/candidate-snapshot.md | 精确ID只读单事务复核和输入加载，不重新选择latest，不受无关回填影响 |
| B09C-ARTIFACT | 归档Agent | ops/candidate_snapshot.py、tests/test_candidate_snapshot_artifacts.py、docs/candidate-replay.md | freeze新目录、重放自包含输入及离线校验；独占创建不覆盖，角色/路径/容量拒绝 |
| QA-B09C | 独立QA | docs/verification/batch-09c-review.md | 先设计复核，稳定后独立schema/hash/回填/WAL/发布/CLI负例 |
| WB-09C | WorkBuddy | collaboration/workbuddy/results/WB-09C-report.md、WB-09C-results.json | 固定契约一次普通同步子任务，完整正文或如实blocked，不计测试 |
| B09C-INTEGRATION | 主控 | cli.py、tests/test_batch09c_cli.py、共享文档及发布 | CLI/全量/安装、现有归档元数据只读和out重放验证、GitHub同步 |

目录均相对src/market_intel（tests/docs/collaboration为根路径）。每文件单写者，主控独占共享schema/CLI/依赖。不改证据schema4/模型3，不联网或调用模型，不复制运行数据库或把清单当可信签名。
