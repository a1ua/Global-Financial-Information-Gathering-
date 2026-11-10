# Batch11：失败/不完整响应关联

2026-11-10，基线本地4458458、远程1a6d462。先独立设计审查再实施；产品继续确定性流水线，无真实key/网络/模型费用。schema3/证据4不变。

| ID | 负责人 | 独占文件 | 依赖与验收 |
| --- | --- | --- | --- |
| B11-CONTRACT | 主控 | docs/contracts/provider-failure-correlation-v0.1.md、llm/client.py、llm/correlation.py、tests/test_failure_correlation.py、共享文档/任务板 | QA设计先通过；安全错误载体、失败事务/hash白名单、重试隔离、全额预留 |
| B11-TRANSPORT | 传输Agent（冻结后派发） | llm/deepseek.py、tests/test_deepseek_failure_correlation.py | 已解析同model响应的合法ID；只传hash、不读取头/失败正文不落档；旧错误优先级不变 |
| B11-INSPECT | 查询Agent（冻结后派发） | ops/model_calls.py、tests/test_failure_call_info.py、tests/test_model_call_info.py | 默认摘要升级0.2、失败hash状态、旧成功/absent/绑定只读不退化；旧测试仅版本断言适配 |
| QA-B11 | 独立QA | docs/verification/batch-11-review.md | 设计→实际独立回归/场景；不把模拟HTTP当真实账单 |
| WB-11 | WorkBuddy | collaboration/workbuddy/results/WB-11-report.md、WB-11-results.json | 固定契约普通同步子任务，完整正文或如实blocked，不计测试 |
| B11-INTEGRATION | 主控 | tests/test_failure_backup.py、tests/test_batch11_cli.py、README/交接/验收及GitHub发布 | existing backup调用共享严格validator自然继承；全套dev.ps1/普通安装/CLI、exact tree发布 |

llm/ops路径相对src/market_intel，其他相对项目根；每文件一个写入者，无分支切换，无新依赖。exec启动通道报CreateProcessWithLogonW失败，已确认node子进程可执行Python/Git只读，记录实际替代验收途径，不绕过Git写入审批。output/tmp原样不动。主任务NLP-01不提前done，生产切换/结算不开启。
