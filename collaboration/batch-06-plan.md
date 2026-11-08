# Batch 06：DeepSeek人民币预算、受限传输与账本恢复

基线：本地79cafc22da177cb55558fc72af34c0374ab51407（远程518a534）；证据schema 4、模型账本schema 1。用户明确指定DeepSeek每日人民币10元，本轮因此优先供应商接入准备，抽取工作未派发并暂缓。账本升级schema2仅为每日预算新增币种，旧USD不换汇或清空。开工时仅WB-05两份结果被其执行端补发终版勘误；保留并复核，不回退，不视为产品代码改动。

| 工作包 | 负责人 | 依赖及独占可写路径 | 验收 |
| --- | --- | --- | --- |
| NLP-01-RECOVERY | 账本恢复Agent | 已验收mock账本；src/market_intel/ops/llm_backup.py、tests/test_llm_backup.py、docs/llm-backup.md | SQLite一致快照、schema1/2严格清单与业务校验、损坏拒绝、仅新目录恢复、pending及币种/费用占用保持；不修改client/schema |
| NLP-01-DEEPSEEK | 传输Agent | 官方文档；src/market_intel/llm/deepseek.py、tests/test_deepseek.py、docs/deepseek-provider.md、config/deepseek.example.json | 固定官方host、TLS、禁止重定向、密钥不留档、总时限、JSON/usage/模型校验；不自动实网 |
| QA-B06 | 独立QA Agent | 上述实现交付；只写docs/verification/batch-06-review.md | 独立故障/负向测试、恢复保留费用、输入不变、引用和时点闭包、WB勘误核对 |
| WB-06 | WorkBuddy及其实际子Agent | collaboration/workbuddy/WB-06-task.md；只写本任务两份results | 固定文档设计审查，真实工具回执；子Agent结果未回收前不写摘要或完成，结果一次定稿 |
| 主控 | 集成者 | 共享契约、llm/client.py及__init__、tests/test_llm_cny.py、CLI、tests/test_batch06_cli.py、README、任务板、上下文及本轮交接 | schema2迁移与CNY费用向上取整、CLI显式启用和账本命令、必要安装回归、提交与既有GitHub发布流程 |

范围：已确认DeepSeek和每日10元上限，默认选官方当前支持的deepseek-flash非思考模式。先通过离线传输模拟和预算测试；只有本地配置密钥并显式--live才可能发起合成smoke，不自动实网、不读取账户/凭证文件、不启用行情评价或调度。用户尚未提供密钥配置，未实测必须如实记录。NLP-01原始完整范围不得以局部完成标done。

恢复为新目录隔离副本，不能用旧备份覆盖当前账本、释放未知费用或绕过预算；固定生产账本绑定、人工结算、真实供应商与账单对账另列前置。

下一轮才进入NLP-02候选筛选和逐字证据提案，不写现有event/evidence，不改变已发布报告。
