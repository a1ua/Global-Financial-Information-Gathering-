# WB-05：模型预算节点独立子 Agent 审查

用户明确要求 WorkBuddy 子 Agent 协助本轮开发。本任务与已取消的 WB-04 无关。

项目：C:/Users/user/Documents/ChatGPT/市场信息抓取；基线 68e4702；输入：docs/contracts-v0.1.md（尤其 R08）、collaboration/batch-05-plan.md，以及后续生成的 docs/llm-client.md、src/market_intel/llm/、tests/test_llm.py。

要求使用 WorkBuddy 实际提供的子 Agent/并行委派能力执行至少一个独立审查子任务；记录真实子 Agent 调用和结果。如果当前版本不支持或额度/工具不可用，写明失败，不以主 Agent 自述冒充子 Agent 执行。可以先检查设计与现有契约，代码尚未生成时不要编造代码审查结果。

范围：为 NLP-01 检查预算原子预留、超时后不确定费用、失败重试上限、UTC 跨日、缓存键版本覆盖、输出无效 JSON、进程重启后的保留额度。给出可操作的输入/预期结果和发现位置。若代码已出现，可只读复核；无需等待代码才能交付设计审查。

唯一允许写入：collaboration/workbuddy/results/WB-05-report.md、collaboration/workbuddy/results/WB-05-results.json。不得修改产品、测试、依赖、Git、系统设置或其他任务文件。不得读取/输出凭证、环境变量或账户文件，不使用付费 API，不外发消息，不自行上传 GitHub。

JSON 至少包含 task_id、status（completed/partial/blocked）、started_at_utc、finished_at_utc、subagent_used（真实布尔值）、subagent_evidence、files_read、findings、checks_run、limitations。记录实际时间与命令；未运行测试明确标注。

完成后在 WorkBuddy 回复中列明实际文件路径、子 Agent 是否执行、阻塞。主控和独立审查者回收验收后决定完成状态。
