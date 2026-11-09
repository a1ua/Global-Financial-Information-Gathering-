# Batch09-A：离线候选限量与预算联验

2026-11-09；基线本地84ca192、GitHub73cf935。本批只消费明确合成的候选文件，不查询真实来源/证据库，不接入NLP-02或正式报告。模型仍用现有账本/缓存/重试，CLI固定mock，拒绝DeepSeek策略；不读key或联网。

| ID | 负责人 | 独占可写范围 | 依赖与验收 |
| --- | --- | --- | --- |
| B09-CONTRACT | 主控 | docs/contracts/candidate-batch-v0.1.md、共享计划/任务板 | 限量、UTC顺序、去重冲突、预算停机及输出口径先设计审查 |
| B09-SELECT | 候选Agent | src/market_intel/pipeline/candidates.py、tests/test_candidates.py、docs/candidate-selection.md | 严格合成输入、无效整批拒绝、去重/截点/稳定顺序、0/上限边界；纯函数不写文件 |
| B09-BATCH | 主控 | src/market_intel/llm/batch.py、cli.py、tests/test_candidate_batch.py、tests/test_batch09_cli.py、config/candidates.synthetic.example.json、共享交接 | mock策略校验先于建库，限定候选、预算/错误即停、缓存与预留、只读plan及显式mock-run |
| QA-B09 | 独立QA | docs/verification/batch-09-review.md | 先设计复核；稳定后独立候选/预算/CLI负例及信任边界 |
| WB-09 | WorkBuddy | collaboration/workbuddy/results/WB-09-report.md、WB-09-results.json | 固定契约一次普通同步子任务审查，完整正文/真实阻塞，tests_run0 |

同文件单写入者；不增加依赖/schema/自主调度框架。单次候选上限不等于全局调用次数上限；重试由现有Policy限额且每次预留。真实候选选择须以后接证据可用时间/版本，不把本批合成测试说成真实新闻分类或供应商验收。
