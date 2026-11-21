# Batch14：离线供应商凭证声明比对

2026-11-17，用户保持先离线准备。真实模型和可信账单仍等待显式启用；本批推进其离线取证协议，不重复制作只读缺口清单。

B14-CONTRACT/INTEGRATION：主控，独占本计划、契约、任务板及验收/最新计划。B14-RECEIPT：receipt14独占ops/provider_receipt.py、tests/test_provider_receipt.py、docs/provider-receipt.md。QA-B14：qa14独占verification/batch-14-review.md，设计前置+独立验收。

API接受严格内存声明对象，不读取外部文件；复用一次已绑定账本只读快照，逐字段报告一致/差异/本地缺失。手工声明始终不可信、金额仅比较原费率估算。绝不认证/结算/释放占用/切换或调用模型。无新依赖/schema，默认不扩展CLI，契约经QA冻结。

验收：严格类型/边界/脱敏、成功/失败/pending/旧记录、单次读取、原UTC日/原费率、不改账本；完整scripts/dev.ps1 test。无真实凭证、来源刷新或WorkBuddy派发。本批不提交无关output/tmp或覆盖Batch12/13。
