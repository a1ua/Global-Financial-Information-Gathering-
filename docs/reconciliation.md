# 模型账本声明只读比对

这里“只读”指不执行SQL业务写、不改schema/调用/预算/绑定。SQLite读取WAL模式可能创建/更新`-wal`、`-shm`协调侧文件，不能承诺目录内所有文件和字节均不变；不会使用忽略WAL的immutable模式。静态非WAL fixture检查文件不变，WAL场景检查业务不变及正确读快照。

`preview_reconciliation(workspace, statement_path)`按照`docs/contracts/reconciliation-v0.1.md`比较绑定schema3账本中单一UTC日、单一provider的本地费用估算与手工声明金额。模型账本与证据库schema均不变。

输入JSON最大1MiB，最多10000个唯一call_id记录，严格字段与整数金额；重复键、无效类型、额外字段、符号链接和junction均拒绝。文件及祖先的链接预检不提供抵抗恶意并发替换的保证。工作区必须已绑定且不是隔离恢复目录。读取采用只读连接、query_only及单一读事务，事务内重验账本业务闭包和身份，不迁移、创建或修改账本、绑定、审计或预算；不读密钥、不联网。

结果状态：缺声明项或仍有pending为`incomplete`；覆盖完整、无pending但逐调用金额不同为`differences`；其他为`matched_estimates`。逐调用差异不会因金额正负抵消被掩盖。delta为声明总额减本地所选全部调用的估算总额；存在缺项时只代表覆盖不完整的数值差，不是净费用结论。未知call_id、错日、错币种、身份/闭包不符拒绝固定错误码，不回显输入文件或底层错误。

所有合法结果均`read_only=true`、`evidence_authenticated=false`、`settlement_allowed=false`，即使逐项金额相同、零调用或声明为manual_statement。声明中的证据哈希只作引用，不读取或认证其外部凭证。本地call_id尚无可信供应商请求映射，不能据此验收真实账单或释放未知费用；pending仍占原预留。重复预检无写入、结果相同，不产生不可变审计记录。

测试仅使用合成调用和声明，运行`PYTHONPATH=src`下的`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_reconciliation.py -v`。实际结果由本轮交接和独立验收记录，不能以此命令示例声称已执行。
