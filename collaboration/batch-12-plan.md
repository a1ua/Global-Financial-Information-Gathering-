# Batch12：供应商验证证据预检

2026-11-17。依Batch11下一项，仅只读整理本地成功/失败调用与外部凭证缺口。不得认证人工声明、调用模型、结算或释放预算。

- B12-CONTRACT/INTEGRATION：主控，独占本计划、任务板、契约、CLI及集成测试和最终验收文档。
- B12-PREFLIGHT：preflight12，依赖设计QA，仅写 ops/provider_preflight.py、tests/test_provider_preflight.py、docs/provider-preflight.md。
- QA-B12：qa12，独立设计和实测，仅写 docs/verification/batch-12-review.md。

输入：绑定schema3账本、精确call_id，复用model-call-info/0.2单只读事务。输出：安全摘要、原UTC预算日、证据缺口及供应商凭证字段清单，所有认证/结算/切换/模型调用权限false。无外部凭证输入。预算日口径设计复核后冻结。

验收：关键成功/失败/旧记录/缺库/损坏/重试边界；确认不改账本；全套 ./scripts/dev.ps1 test。WorkBuddy本轮工具入口不可用，未派发，不冒认完成；既有WB-06不停止、WB-04不重启。
