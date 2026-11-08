# Batch08 独立设计与实现审查

任务ID：QA-B08。日期：2026-11-09。审查者只读契约、实现和测试，独占维护本文件；不实现产品、不改共享契约、CLI或任务板，不读取真实凭证或联网。

## 设计审查结论

输入：`collaboration/batch-08-plan.md`、`docs/contracts/reconciliation-v0.1.md`设计审查稿，以及项目AGENTS规则。**设计可冻结并进入只读预检实现；未发现阻止本轮范围实现的重大设计缺陷。** 这仅是设计审查通过，产品尚未独立运行验收，不能写成代码或生产通过。

已确认的关键约束：

- 外部JSON、声明哈希、人工金额及数值相等均不认证账单；`evidence_authenticated=false`与`settlement_allowed=false`无成功分支。
- 不实施pending释放、调用终态修改或费用结算；不能从金额倒推token。真实费用超过预留的处置仍为后续设计，当前不截断声明金额。
- 声明限定UTC日、provider和单币种；缺覆盖优先返回incomplete。delta在缺覆盖时仅是声明合计减所选本地估算，不是已核对净支出。
- 当前固定绑定、schema3闭包和读事务内身份均要核对；不迁移、不建库、不读key、不联网，结构错误和未知调用拒绝。
- 恢复预检比较全部days/calls/cache列，而非仅合计费用；即使相等，也始终`switch_allowed=false`和`trusted_high_water=false`。
- 高水位必须独立于可回退的同目录状态；存储/部署未验收时维持禁止。相同身份、当前库也被回退或两库非原子观察均不提供完整回退保证。
- 独立审计链和终态结算仅定义后续方向，本轮只读重复结果不冒充不可变审计记录。

## 实现时需保留的解释边界

1. 备份校验、随后打开候选以及两库读取之间可能存在TOCTOU。对每次实际读取重新验证schema/身份/业务闭包，不把先前校验结果当本次连接证明；观察到文件变化应拒绝或明确本次观察无切换许可。不得将只读事务描述为跨库原子快照，也不承诺抵抗有文件写权限者的恶意替换。
2. 金额差异计数必须逐调用比较；一正一负抵消、合计相等仍应为differences。pending即使声明金额等于预留仍为incomplete，不自动释放。
3. 既有schema1/2隔离恢复能力保持；本次拒绝其生产预检不是移除旧备份兼容。绑定缺失或错误须失败，不能通过ensure或ModelClient初始化补齐。
4. 结构合法且status不佳时CLI按契约exit0，但必须保留明确状态和禁止操作标志；调用者不得只凭退出码推断可结算/可恢复。
5. synthetic/manual_statement均未认证；空范围的matched_estimates只可理解为零行数值相等。不可宣称真实核对完成。

## 独立实现验收

最终结论：**Batch08-A契约与Batch08-B只读预检子集通过独立验收，WAL只读语义缺口已由主控修正文档后复核关闭；无待修实质代码缺陷。** 仅验收不执行SQL业务写、不改schema/调用/预算/绑定的只读语义，不承诺SQLite不创建协调侧文件。NLP-01整体、真实对账、不可变审计、高水位及生产恢复切换仍未完成。

稳定实现交接后，在真实工作区使用`.venv/Scripts/python.exe`，设置`PYTHONPATH=src;tests`及工作区内`TEMP/TMP=out/qa-batch08-temp`，实际运行：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest test_reconciliation test_recovery_preflight test_batch08_cli test_ledger_binding test_llm_backup test_identity_migration test_batch06_cli -v
```

退出码0，110项：109通过、1项Windows符号链接权限跳过，用时22.188秒；实际junction分支通过。日志`out/qa-batch08-tests.log`。包含Batch08新功能44项及相关旧绑定/备份/CLI/身份回归，不与主控全套数量累加。

另行运行独立stdin验证脚本，5组场景全部通过、退出码0：

1. 同时有pending及两条一增一减的声明差异，合计差为0仍计2项difference，status优先incomplete；预算调用行和文件哈希前后不变，不认证或结算。
2. 实际只读账本验证阶段抛出含合成敏感标记的SQLite异常，返回固定`ledger_backup_database_error`，不包含原文，文件不变。
3. 恢复两次实际业务验证均处于BEGIN读事务及query_only，尝试UPDATE被SQLite拒绝；等价结果仍禁止切换，非WAL静态文件集及哈希不变。
4. 初始备份校验后，同身份候选被改为业务仍合法的day.cost_cap；实际读观察为changed_days=1/not_equivalent且switch_allowed=false。该场景不证明抵抗全部TOCTOU，尤其不能保证读取仍对应先验manifest。
5. WAL模式中，在对账读事务已验证后，由独立写入者新增合成调用；结果仍读取固定旧快照local_calls=1，而提交后的当前库为2，matched_estimates仍不允许结算。业务变化来自测试主动并发写入者，不是只读预检。

### 发现及处置：SQLite WAL侧文件

**事实复现：** 合成账本切为WAL并关闭所有连接；调用前目录仅有`llm-state.db`与`llm-binding.json`。执行`preview_reconciliation`返回matched_estimates后，SQLite生成`llm-state.db-wal`及`llm-state.db-shm`。因此“所有文件集和字节前后不变”或完全“零文件写”的绝对表述不成立；mode=ro/query_only只限制数据库逻辑写入，不保证SQLite不维护WAL侧文件。

已向主控报告并完成处置复核：冻结契约、README、两项API说明及批次验收记录均增加明确限定：只读为不执行SQL状态/预算/绑定/schema业务写，SQLite可能创建/维护WAL侧文件；静态非WAL fixture才验证全文件集和哈希不变。没有采用immutable=1忽略有效WAL，也未改变产品代码。复核时三个产品文件SHA-256与已测试版本完全一致，因此此次仅文档修正，不重复完整代码测试。若未来要求严格零文件写，需另行设计拒绝WAL或安全快照读取方案；本次不声称该能力。

### 已审查实现版本

| 路径 | SHA-256 |
| --- | --- |
| `src/market_intel/ops/reconciliation.py` | `A7130EF5C8C59AA37860B1B4A12E9B2F62724FCD62642D3064B6150FE03F2C69` |
| `src/market_intel/ops/recovery_preflight.py` | `84F7EC2C11ABFB8BA582D25D80D0344F6C004466966EE4A6A7EC78648E8E0F19` |
| `src/market_intel/cli.py` | `A8928E756041550176B888BA2D363284031B103F58B25F0FA4E4CEF7E23825E4` |

未改实现或测试文件；所有请求、金额和证据为合成，未调用真实API、读取真实凭证或核对真实账单。主控的安装/全套结果另记，QA不替未亲自运行的验证出具通过证明。

## WB-08 静态交接复核

已读取`collaboration/workbuddy/results/WB-08-report.md`及可解析JSON。两文件含三点完整设计意见；JSON为completed、raw_result_recovered=true、tests_run=0、finalized=true，并列出一次同步Agent调用、run_in_background=false及Agent ID的父端自述。QA未独立看到底层Agent工具日志，故能确认文件正文和所载回执，不能独立认证执行方式、来源或回执真实性；不计为代码测试。

三点分别讨论金额相等不认证或结算、等价快照不证明新鲜性/许可切换，以及外部高水位/不可变审计为未来未实现设计，与本批范围基本一致。“设计上已封闭误用路径”等措辞仅能理解为契约返回标志明确禁止操作，不证明调用者不能忽略标志、生产切换已受完整强制约束或同身份回退已被防护。

该静态审查引用的是WAL补充前契约，其中“文件字节和业务行前后不变”“不删除/复制/覆盖文件”等原句不能作为所有文件系统零副作用的现行保证。原始报告保留不改；现行解释由本报告WAL实测发现及冻结契约实现验收补充覆盖。WB设计正文不替代110项定向联验、独立场景或主控安装验收。
