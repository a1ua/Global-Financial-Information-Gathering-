# Batch08-C 独立设计与实现审查

任务ID：QA-B08C。日期2026-11-09。审查者仅维护本文件，产品、契约、CLI、任务板均只读；不联网、不读取真实key、不执行真实供应商请求。

## 设计审查

输入：AGENTS、charter-v3、contracts-v0.1、development-backlog-v3、`collaboration/batch-08c-plan.md`、`docs/contracts/audit-journal-v0.1.md`设计稿、`docs/audit-trust-decision.md`及现有对账预检字段语义。

本地追加审计与外部可信高水位分离正确：仅保存未认证声明的预检观察；哈希/触发器不证明账单真实，不阻止完整旧链整体回退或持文件权限者重算全链。`trusted_high_water=false`、`settlement_allowed=false`和`switch_allowed=false`无解锁分支，未伪称未来verified/applied、预算释放或生产切换已实现。

冻结前已向主控提出两点需明确的实现约束：

1. 审计输入限定计数至10^7、金额合计至10^19，现有预检对本地调用总数/本地费用合计并无对应相同上限，因此不能同时声称“不拒绝现有预检合法合计”。可明确这些是审计入口容量限制并固定错误拒绝，或采用覆盖实际合法合计的规则；不得静默截断金额/计数。声明最多10000项不代表本地调用数最多10000。
2. `INSERT OR REPLACE`/`REPLACE`可能在`recursive_triggers=OFF`时通过UNIQUE冲突隐式删除旧行，单靠UPDATE/DELETE触发器及新seq/prev链尾检查不足。INSERT保护还需拒绝已存在event_id、observation_key和event_sha256；应有真实SQL负例覆盖，不能只测试普通UPDATE/DELETE。即使应用随后全链校验能发现损坏，也不能把已发生历史删除说成追加保护成功。

其余设计适合本轮最小局部实现：新文件独占创建、既存库mode=rw、BEGIN IMMEDIATE内先全链校验再去重/追加、幂等键覆盖完整观察、多账本全局序号、真实UTC时钟回退拒绝、单次解析声明、严格公共字段及错误脱敏。WAL协调侧文件限制沿用Batch08；只读校验不等于文件系统零写入。工作区外路径仅是角色分离，不提升信任。

主控已修订：总额/计数明确为审计入口容量限制，超限固定错误、原预检无限量语义不变；INSERT在插入前拒绝已有seq、event_id、observation_key与event_sha256，覆盖recursive_triggers=OFF的REPLACE隐式删行。已实际复读相应契约段落，**设计可冻结并派发本轮局部实现，无剩余阻断性设计问题**。此阶段tests_run=0，设计审查不构成代码运行通过。

定向负例建议：分别对四种唯一字段进行`INSERT OR REPLACE`及`REPLACE`冲突，显式关闭recursive_triggers并核对旧行全列/链长不变；测试容量边界10^19、10^19+1与bool，计数关系及总额抵消但逐调用difference_records仍大于0；已有坏链后相同观察重试必须先失败，不能靠幂等命中返回成功；将完整旧库副本替换为当前库后校验仍可能通过时，输出必须继续保持无高水位/结算/切换许可。

## 实现独立验收

稳定交接后，使用真实工作区`.venv/Scripts/python.exe`，设置`PYTHONPATH=src;tests`，`TEMP/TMP=工作区out/qa-batch08c-temp`，实际执行：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest test_audit_journal test_batch08c_cli test_reconciliation test_batch08_cli test_recovery_preflight test_ledger_binding test_llm_backup -v
```

退出0，**120项：119通过、1因Windows符号链接权限跳过，31.048秒**；实际junction分支通过。日志`out/qa-batch08c-tests.log`。这些目标测试覆盖已验收的依赖模块，和主控全套有重叠，不能相加计算。

实际检查了SQL UPDATE/DELETE拒绝、`recursive_triggers=OFF`下两种REPLACE逐个唯一键冲突、缺失/替换保护触发器、坏链先校验再幂等、错payload/canonical/身份/哈希/UTC、容量上界与bool、并发追加、只读缺库不创建、旧链回退限制，以及CLI声明仅解析一次且摘要/凭证哈希/预检使用同一值、角色路径和原账本业务不变。源码/密钥目录避让现明确为操作者约定，CLI只强制工作区树外、角色不同路径或文件及链接拒绝，不声称识别任意秘密目录。

另通过stdin运行5组独立场景，最终退出0，未写产品或测试文件：

1. 6线程Barrier同时首次创建同一新审计文件，实际1成功、5个安全错误；最终合法链1行且连续序号，无被覆盖或丢失的成功记录。首次并发创建允许安全失败，不能将失败者计入成功追加。
2. 4线程Barrier重试相同新观察，恰1个recorded，所有响应event_id相同；最终事件数仅增加1。
3. 完整旧链字节替换较新库后，本地verify仍通过且events回到1；所有高水位/结算/切换许可保持false，符合已明确限制，不被写成防回退成功。
4. 持SQL权限者移除UPDATE触发器、改payload并重算observation_key和event_sha256后恢复精确触发器，合法自洽改写仍可verified_local_chain，trusted_high_water=false。该实测支持“本地链不具备抵抗特权重算的保证”，不是实现防篡改能力证明。
5. 注入包含私密文本的sqlite3.OperationalError，仅返回audit_journal_database_error，原审计文件字节不变。

**最终结论：本轮本地追加审计、严格链校验与CLI局部范围通过独立离线验收，未发现待修复实质代码缺陷。** 模型schema3与证据schema4未变；不认证供应商账单、不实现可信外部高水位、预算结算、pending释放或生产切换。NLP-01及整体运维闸门不能因本轮通过自动升级。

### 实现版本

| 路径 | SHA-256 |
| --- | --- |
| src/market_intel/ops/audit_journal.py | 534CEBCA6592B3A0B4EC89808C3DB54A6151473189BE932F1682D4F5E03D8D3B |
| src/market_intel/ops/reconciliation.py | 2D18B6C3107B551B5FFFC165B295774FAE38FB3E1F390AA42F503AEA26F920AC |
| src/market_intel/cli.py | 5D62BD8976EE887992CD01D80FAD1147AACC2F080F830F09B185B977851BBB53 |

QA没有修改实现或测试，没有调用真实模型、访问账户、读取真实key或核对真实账单。未执行Git/GitHub写操作、普通安装或主控全项目回归；这些结果由主控另记。

## WB-08C 静态交接复核

已读取`WB-08C-report.md`及可解析`WB-08C-results.json`：含三点完整设计正文，JSON为completed、subagent_used=true、raw_result_recovered=true、tests_run=0、finalized=true；父端载有一次Explore同步调用、run_in_background=false及Agent ID agent-39045a17-1bc1-4ccc-a4f0-8a5aebb2bfb1的自述。QA未独立看到底层Agent工具日志，因此确认的是可见文件正文及其所载回执，不能独立认证执行方式、来源或回执真实性，不计代码测试。

三点主要讨论本地链非外部高水位/不可回退保证，幂等先全链验证与触发器拒绝，以及未认证输入、false许可及未来能力明确未实现；与本轮契约边界基本一致。WB文字中的“无文档级契约缺口”是固定设计输入的静态意见，不能替代实际实现检查，也不能证明特权者无法重算链、提供真实账单或已接通外部服务。原文件保留，局部实现通过依据仍为上述独立测试和场景。
