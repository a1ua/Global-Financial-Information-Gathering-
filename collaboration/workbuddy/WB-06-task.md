# WB-06：固定契约的独立子Agent设计审查

项目C:/Users/user/Documents/ChatGPT/市场信息抓取；基线79cafc2。新任务，与已取消WB-04无关；不再改写WB-05任何文件。

只读以下固定文档：collaboration/batch-06-plan.md、docs/contracts/deepseek-budget-v0.2.md、docs/contracts-v0.1.md第10节。本任务只做固定契约设计审查，不追踪正在开发的代码，不运行测试/命令，不自行扩大读取/写入范围。用户已指定DeepSeek每日人民币10元，不能混用USD。

真实委派一个或两个只读子Agent，分别检查（1）旧账本恢复导致预算回退的边界、币种及pending保留，（2）人民币每日10元、向上取整、未知费用、HTTP密钥/时限/响应与显式启用边界。每个子任务必须明确输入文档、预期返回、无代码写权限。没有实际回执不得声明派发，没有真实完整回传不得编写或代替子Agent摘要；不能把自述当运行证据。

只允许写collaboration/workbuddy/results/WB-06-report.md与WB-06-results.json。子Agent也不得写其他文件。不得读凭证、配置、账户、环境变量，不调用付费API、不修改产品/测试/Git/系统、不外发、不上传。若不支持实际子Agent，如实写blocked。

JSON必须有task_id,status,subagent_used,subagent_evidence（实际agent/task ID、回执、完整结果是否回收）、checks_run（本任务tests_run=0）、findings、limitations、finalized=true。时间仅在能实际核实时写，不编造。等所有子Agent完整回传后再一次写入最终两文件，明确分开子Agent原始发现、主端推断和未验证项。正文末尾写WB-06 FINALIZED；完成后停止修改，不响应旧WB-05队列续写。若需勘误另报告主控，不覆盖本次定稿。
