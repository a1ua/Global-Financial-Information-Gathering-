# WB-08：对账与恢复契约同步设计审查

项目C:/Users/user/Documents/ChatGPT/市场信息抓取。只读本任务单和docs/contracts/reconciliation-v0.1.md一份固定契约；不读代码/配置/凭证/账户/环境、不运行命令/测试/网络，不改旧WB文件。

尝试恰一次普通同步阻塞子任务，run_in_background=false、不设team/name。将固定契约内嵌给子任务，子任务不写文件。最多三点检查：声明金额相同能否误当认证/结算；恢复等价是否被误当新鲜性/切换许可；未来高水位/不可变审计未实现是否标清。只给可引用的正文，区分设计意见与测试。

若不支持同步模式或只有派发/完成状态而无完整正文，一次如实blocked定稿；不轮询/重试/代写。父端只写collaboration/workbuddy/results/WB-08-report.md和WB-08-results.json，JSON含task_id/status/execution_mode/subagent_used/raw_result_recovered/actual_tool_receipt/subagent_result/tests_run=0/finalized=true；无正文则null。准确保留完整返回正文及实际回执，不编造时间/日志。末尾WB-08 FINALIZED。定稿不再覆盖，额外消息只报主控。
