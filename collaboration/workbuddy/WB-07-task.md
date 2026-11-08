# WB-07：同步子任务的固定契约审查

项目C:/Users/user/Documents/ChatGPT/市场信息抓取。只读docs/contracts/ledger-binding-v0.1.md，原文作为固定设计输入。不读代码、配置、凭证、环境、账户，不运行命令/测试/网络，不改WB-05/WB-06。

尝试调用一个普通同步、阻塞返回完整结果的只读子任务（如工具支持run_in_background=false且不设置team/name）。不要使用此前异步团队成员的消息回收模式；不通过反复TaskOutput或SendMessage等待输出。若当前工具不支持该模式，或仅返回派发/完成状态而无结果正文，即一次如实blocked并结束，不重试/扩审/代写摘要。

子任务目标：最多3点指出身份绑定是否被误写为旧快照回退防护、单边文件崩溃如何失败关闭、显式接管与隔离恢复的边界。不得写文件。必须将实际返回正文原样或准确摘录留在父端交接；不得把父端推断标作子任务结论。

父端只写collaboration/workbuddy/results/WB-07-report.md与WB-07-results.json。JSON含task_id、status、execution_mode、subagent_used、raw_result_recovered、actual_tool_receipt、subagent_result（无正文则null）、tests_run=0、finalized=true。正文末尾WB-07 FINALIZED。总报告尽量简洁；不编造时间或回执。定稿后不再覆盖，后续只向主控发送说明。
