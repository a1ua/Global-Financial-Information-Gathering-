# Batch 05：预算模型节点与行情来源能力验证

基线：68e4702fdbe60581ca0e0bb4d01919178684cecf；输入契约：docs/contracts-v0.1.md、现有证据 schema 4。执行结果见 `docs/verification/batch-05.md`；NLP-01 离线子集已独立验收，MKT-01 为部分能力验证，完整原任务继续进行中。产品仍采用确定性流水线。

| 工作包 | 负责人 | 依赖 | 独占可写路径 | 验收 |
| --- | --- | --- | --- | --- |
| NLP-01 | 模型实现 Agent | ENG-03 已验收子集 | src/market_intel/llm/、tests/test_llm.py、docs/llm-client.md、config/llm.example.json | 离线预算、超时、无效 JSON、重试、版本缓存、并发预留和重启恢复测试；独立审查 |
| MKT-01 | 数据验证 Agent | ENG-03 | docs/market/、config/instruments.example.json、config/calendars.example.json | 官方原始资料、真实访问结果、代码/币种/OHLC/复权/日历差异和缺口；不合格评价保持关闭 |
| WB-05 | WorkBuddy，要求委派其子 Agent | 本任务单 | collaboration/workbuddy/results/WB-05-report.md、WB-05-results.json | 独立预算失败案例审查与子 Agent 执行证据；不改产品代码 |
| QA-B05 | 独立审查 Agent | NLP-01 实现交付 | docs/verification/batch-05-review.md（代码只读） | 检查预算绕过、缓存污染、崩溃/重试计费与测试结果 |
| 集成与发布 | 主控 | 上述产物 | CLI/公共契约必要调整、README、任务板、批次验收和上下文 | 全量离线回归、必要安装验证；提交与远程文件树一致 |

本轮不自动调用付费模型、不安装调度、不启用行情评价。来源访问失败如实保留，不以设计或 mock 标记真实接口通过。WorkBuddy 原有用户任务不打断，WB-04 不重启。共享目录不切换分支。
