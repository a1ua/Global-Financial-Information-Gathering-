# 模型账本恢复候选的只读预检

只读指不执行SQL业务写、不改schema/调用/预算/绑定，不代表零文件系统副作用。SQLite读取WAL模式可能创建/更新`-wal`、`-shm`协调侧文件；不能承诺目录文件集完全不变，也不采用忽略WAL的immutable模式。静态非WAL fixture与WAL场景分别检查文件/业务状态。

输入契约：`docs/contracts/reconciliation-v0.1.md`。API为`market_intel.ops.recovery_preflight.preflight_ledger_recovery(workspace, backup)`；CLI为`ledger-recovery-preflight --workspace ... --backup ...`。

本入口比较当前固定绑定工作区与候选备份的观察状态，始终返回`switch_allowed=false`、`trusted_high_water=false`。它不恢复、切换、覆盖文件或修改预算、pending、缓存，不建立活动绑定，也不读取密钥或调用模型。旧`restore-ledger`仍仅产生隔离副本。

## 检查与输出

1. 当前工作区必须已绑定，且不含隔离恢复清单；只读检查身份与固定路径，不自动初始化或采用。
2. 候选须通过既有严格备份清单、文件哈希及业务闭包验证，必须是schema3且身份与当前账本相同。schema1/2仍可用原命令隔离恢复，但本入口拒绝，不迁移。
3. 在两个独立的`mode=ro`、`query_only`读事务中再次校验schema、身份与完整业务闭包，然后按主键比较`days`、`calls`、`cache`全部列。调用输出和元数据参与内部比较，但只返回计数，不返回原文。

完全相同时status为`equivalent_observation`；有缺失、新增或更改行时为`not_equivalent`。计数分别列出当前/候选调用数、候选缺失/新增调用、修改调用，以及day/cache缺失、新增、更改条数。即使调用数和金额总和相同，行内容或缓存指向不同也算不等价。

blockers始终包含`trusted_high_water_unavailable`、`reconciliation_not_verified`、`production_switch_not_implemented`；不等价时另有`snapshot_not_equivalent`。合法结果即使不等价也由CLI以exit0输出JSON；输入/绑定/身份/哈希/业务闭包错误exit1。不得只检查退出码判断恢复可执行。

## 明确限制

两库各自是稳定读快照，不是跨库原子快照；预检结果也不是稍后操作的锁或租约。先验备份验证到实际打开存在TOCTOU，重验身份和业务闭包不能证明路径未被恶意替换、供应商证据真实或快照最新。

比较能够显示当前观察中候选缺失调用等差异，但不能保证同身份回退检测。如果当前库本身已回退，旧候选恰与它相同仍可能返回等价。外部可信单调高水位、真实逐调用对账、不可变审计和受控生产切换尚未实现，不把本入口描述为生产可恢复。

新错误码包括`ledger_recovery_binding_required`、`ledger_recovery_schema3_required`、`ledger_recovery_identity_mismatch`、`ledger_recovery_io_error`、`ledger_recovery_database_error`；既有绑定及备份验证错误码保持。底层I/O/SQLite异常映射为固定码，不附加路径或异常原文。

## 验证

使用工作区`.venv`、`PYTHONPATH=src`和工作区内`TEMP/TMP`，运行：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_recovery_preflight.py -v
```

针对合成账本验证重复调用字节/文件集不变、pending保留、空库等价仍禁止切换、旧候选缺行、候选多行、同数同额改行、day限额和合法缓存指向变化、legacy/错误身份/链接/哈希拒绝、实际事务再次校验身份和业务闭包及错误脱敏。真实账单、账户、外部高水位与真实生产切换均未验证。
