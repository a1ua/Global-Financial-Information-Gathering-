# Batch13：离线环境恢复验收

2026-11-17。用户明确选择先完成离线准备。根进程仅检查DEEPSEEK_API_KEY存在性，结果false，不输出值；无真实模型请求/费用/来源刷新。

分工：env13独占dev.ps1/setup-env.ps1及环境恢复说明；qa13独立设计和验收；主控负责实际venv安装、集成记录与操作手册。产品模型schema3、证据schema4、CLI业务契约不变。

修复：优先验证显式解释器和已有候选，找不到才扫描可用WindowsApps；无ProgramFiles时仍可开发。同major.minor失效venv使用--upgrade恢复，保留site-packages和setup-runs，不清空目录；不完整/跨版本拒绝。PowerShell5.1固定Python多行helper转UTF8文件解决引号问题；捕获原生stderr时临时Continue并恢复，按退出码拒绝失败。

实际验证：
- 原venv引用旧runtime退出103；当前base Python3.12.14 v26-1112-737已验证；实际同版本恢复成功，直接venv -I打印版本及新base_prefix exit0。
- dev.ps1 demo：ProgramFiles为空且显式MARKET_INTEL_PYTHON配置，exit0，报告明确synthetic。
- 第一次setup恢复环境后因旧-c多行引号错误失败；第二次安装及项目外help/demo成功后，因PowerShell5正常unittest stderr被误当异常失败；均未算验收成功。
- 修复后普通setup-env.ps1完整exit0；项目外已安装help/demo、pip check、site-packages检查及518运行515通过3权限跳过，53.764秒。证据.venv/setup-runs/20261117-231122-f6bf2f5b/，日志out/batch13-install-accepted.log。无联网pip，使用既有纯Python本地轮包。
- 最终 ./scripts/dev.ps1 test：ProgramFiles为空，不再设置解释器覆盖，直接恢复后的venv；518运行515通过3权限跳过，51.324秒 exit0，日志out/batch13-dev-tests.log。两次全套覆盖重叠不相加。
- env13及独立QA分别实测不完整/跨版本拒绝且无setup-runs新建，详见各自报告。QA解释器候选选择和脚本AST通过，初始harness失败如实记录。

未完成：真实API/tokenizer/usage/账单验证，可信外部高水位、终态结算与生产恢复。WorkBuddy本轮工具不可用未派发。旧Batch12后台进程状态未进一步认证，未停止WB-06/WB-04未重启。没有本轮Git提交或GitHub上传，既有Batch12源码/文档保留待发布。output/tmp无关目录未触碰。

下一项需用户今后在本地安全配置凭证并明确启用，先复核供应商当日模型及费率再做最小合成smoke；10元/UTC日单账本估算。详见../deepseek-smoke-runbook.md。主任务9done/3in_progress/13planned/1cancelled，闸门维持Batch12状态。
