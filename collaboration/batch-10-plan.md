# Batch10：成功模型调用的供应商响应关联

2026-11-10，基线本地444dd2b、GitHub98eaec0。实现前先独立设计审查。本批只接成功且本地输出/usage通过验证的响应；失败/超时仍全额占用，不补写供应商关联，不认证账单/结算。无真实密钥/付费请求，不改证据schema4或模型schema3。

| 工作包 | 负责人 | 独占可写文件 | 依赖和验收 |
| --- | --- | --- | --- |
| B10-CONTRACT | 主控 | docs/contracts/provider-correlation-v0.1.md、src/market_intel/llm/client.py、src/market_intel/llm/correlation.py、tests/test_provider_correlation.py、共享文档/任务板 | 设计QA先通过；可选响应hash、成功事务存储、缓存原call关联、失败仍全额 |
| B10-TRANSPORT | 传输Agent（设计冻结后派发） | src/market_intel/llm/deepseek.py、tests/test_deepseek_correlation.py、docs/provider-response-correlation.md | 依赖共享ModelResponse字段；只提取documented completion id并hash，不造HTTP请求ID、不存原ID；模拟HTTP/缺失/恶意类型 |
| B10-INSPECT | 查询Agent（设计冻结后派发） | src/market_intel/ops/model_calls.py、tests/test_model_call_info.py | schema3绑定/单只读事务/固定callID，摘要无正文/凭证；不调用模型或修改预算 |
| QA-B10 | 独立QA | docs/verification/batch-10-review.md | 先设计后实现独立验收；success/cache/retry/backup/错误不泄密，不能把mock当live |
| WB-10 | WorkBuddy | collaboration/workbuddy/results/WB-10-report.md、WB-10-results.json | 固定契约一次普通同步只读子任务，完整正文或blocked，tests_run0 |
| B10-INTEGRATION | 主控 | src/market_intel/ops/llm_backup.py、src/market_intel/cli.py、tests/test_batch10_cli.py、tests/test_correlation_backup.py、README、验证/交接与发布 | 关联元数据备份严格验证、CLI无mutatingconnect；全套/普通安装、GitHub exact tree |

WorkBuddy任务单由主控写；实现者只写已派目录。文件单写者，无分支切换、无新依赖或自主产品Agent调度。无关output/tmp保留且不读取/提交。失败响应关联、外部账单终态、高水位部署与生产切换明确后续，不提前完成NLP-01。

集成连带登记：主控可修改tests/test_llm_backup.py中历史schema1 fixture的字段移除列表。新client自动写可选provider_response，人工降级为旧行时必须移除它；不放松产品校验。验收为既有历史用例、全套和独立QA扩展回归。
