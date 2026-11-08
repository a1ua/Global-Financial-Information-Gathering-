# Batch08：对账与恢复只读前置验收

日期2026-11-09。基线本地2817ba2、GitHub8c5e23a。任务B08-CONTRACT、B08-RECONCILE、B08-RECOVERY、B08-INTEGRATION、QA-B08；分工见`collaboration/batch-08-plan.md`，输入契约`docs/contracts/reconciliation-v0.1.md`。

发布核验：本地代码提交`54616f66deed0a88537eb3351c34b8f207a8db3b`对应GitHub main快照`2003240183803eedf7ea009ac98ce48697fd0446`，Git tree均为`d01f4d55b4cfcb9834aa9301476e119cd4cb29c6`。随后另提交发布归档；不强推、不替换本地开发历史。

## 交付范围

先核验本地对话归档ZIP及其manifest逐文件SHA-256，20轮100条可见消息；确认DeepSeek每日人民币10元、保持未知占用、用户取消任务不重启和不停止WB-06等既有约定。对话/ZIP仍仅本地，不上传仓库。

QA-B08先独立设计审查通过，主控冻结契约后才派发两个实现者。新增`ops/reconciliation.py`、`ops/recovery_preflight.py`及对应定向测试/说明，主控接入CLI及7项测试，共享client、backup及schema不变。

- `ledger-reconcile-preview`：严格声明格式、1MiB/10000记录限制、单日单provider/单币种、逐调用差异/缺项/pending；身份和业务闭包在单个只读事务重验。始终evidence_authenticated=false、settlement_allowed=false，不写账本/审计，不改变预算。
- `ledger-recovery-preflight`：严格验证schema3候选，实际读事务重验身份/闭包，逐主键全列比days/calls/cache；始终switch_allowed=false。两库不是跨库原子快照，等价不证明最新，也不提供切换租约。
- 合法incomplete/differences/not_equivalent返回0并明确状态及禁止标志；格式/绑定/账本错误返回1，不添加apply/force/release入口。

## 实际测试与复核

1. 实现者对账19项、恢复18项定向测试通过；恢复首跑一项测试错误预期cost_invalid，按真实拒绝码usage_invalid修正后复验。主控CLI首跑过度拦截全部环境读取，影响标准库argparse/gettext；修改测试只拦截DEEPSEEK_API_KEY后7项通过。以上是测试脚本修正，无对应产品补丁。
2. `./scripts/dev.ps1 test`：335项，333通过、2项实际symlink权限跳过，exit0，实际Windows junction分支通过。日志`out/batch08-tests.log`。
3. `TEMP/TMP=工作区out/test-temp`下`./scripts/setup-env.ps1`：普通隔离安装、项目外CLI help、明确合成demo和隔离完整测试通过；335项，333通过、2跳过，exit0。证据`.venv/setup-runs/20261109-014628-adbcb34f/`，日志`out/batch08-install.log`。
4. 独立QA目标联验110项，109通过、1权限跳过；另5组独立场景验证pending+抵消差异、私密SQLite错误脱敏、读事务query_only拒绝写入、先验验证后同ID合法候选变化、WAL并发新增时保持读快照。详见`batch-08-review.md`中的实际命令、边界及实现SHA-256。目标测试是全套子集，不叠加计数。

未请求真实模型/账单/账户、未读取真实key、未产生本轮真实付费调用。均是合成账本、声明与本地文件；不能据此宣称真实账单核实。

独立QA另复现WAL模式侧文件：所有写连接关闭且尚无-wal/-shm时，只读预检可能由SQLite建立协调侧文件。已修正契约、API说明和README中零文件变化的绝对表述；只读限定为无SQL业务写、不改预算/绑定/schema，静态非WAL fixture才验证完整文件不变。未使用immutable=1或改变SQLite读取逻辑。此项属于验收发现及文档修正，不隐藏为全文件无变化。后续最终QA结论见独立报告。

## 剩余事项

08-A契约及08-B只读入口可局部验收；Batch08整体闭环、父任务NLP-01仍进行中。不可变对账审计、供应商可信逐调用关联、终态结算、外部单调高水位和生产切换未实现。下一项08-C先冻结可部署信任边界；不得把同目录JSON或manifest当可信高水位，不把费用/状态清零作为恢复办法。

WorkBuddy WB-08仅固定契约设计审查，实际结果另行归档；派发提示不等于结果或测试通过。已有WB-06未停止，WB-04未重启。发布采用已授权GitHub连接、非强制更新及文件树核验；不上传对话、凭证、data/out/venv。
