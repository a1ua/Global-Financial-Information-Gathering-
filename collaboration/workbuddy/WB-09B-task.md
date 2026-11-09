# WB-09B：证据候选时间与版本设计审查

项目C:/Users/user/Documents/ChatGPT/市场信息抓取。只读本任务单及docs/contracts/evidence-candidates-v0.1.md一份固定契约。恰一次普通同步阻塞只读子任务，run_in_background=false，不设team/name，契约原文内嵌。最多三点：receipt/可用时间与发布时间混淆；最新可用版本和旧截点清单稳定性；真实标签/只读计划是否被误称来源或模型已验收。

子任务不读写文件。父端只写collaboration/workbuddy/results/WB-09B-report.md、WB-09B-results.json；不读实现/配置/凭证/环境/账户/对话，不运行命令/网络/测试，不改旧WB文件。无同步能力或实际完整正文则一次如实blocked结束，不轮询/重试/代写。JSON含task_id/status/execution_mode/subagent_used/raw_result_recovered/actual_tool_receipt/subagent_result/tests_run=0/finalized=true。保留完整正文/回执，不编造时间；末尾WB-09B FINALIZED，定稿不再覆盖。
