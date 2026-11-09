# 本地追加审计库

Batch08-C API：`append_observation(journal_path, observation)`显式写入独立SQLite审计库schema1；`verify_audit_journal(journal_path)`只读校验。输入及返回字段见`contracts/audit-journal-v0.1.md`。模型账本schema3与证据库schema4不变；本模块不接触两者，不读取凭证或联网。

每条事件包含全局连续序号、随机event_id、canonical观察payload及其去重哈希、ledger_id、实际UTC recorded_at、前序哈希和事件哈希。相同完整观察幂等返回原事件；同一声明的预检结果变化会新增事件。单库可记录多个ledger_id，序号和链始终全局连续。幂等命中前仍全量校验已有链，不能利用重试绕过损坏检查。

追加采用BEGIN IMMEDIATE，在同一事务校验schema/触发器/全链后追加；并发写序列化或明确busy失败。库不存在时仅显式append可独占创建文件与父目录，已有空文件、未知版本或损坏文件不覆盖、不自动修复。创建中断可能留下需人工检查的文件，不自动删除重建。verify缺库不创建任何目录或业务文件。文件及祖先symlink/junction拒绝；CLI另外限制审计路径不与声明/工作区混用。

UPDATE/DELETE触发器拒绝历史行修改，INSERT保护顺序、前序链及所有唯一键冲突，包括recursive_triggers=OFF时REPLACE隐式删行的路径。校验严格检查当前表与触发器定义、每条payload格式/canonical表示、计数/金额关系、身份、UTC顺序、去重哈希及完整事件链。错误转换为固定码，不输出payload、路径或底层私密异常。输入容量限额为计数最多10^7、合计金额最多10^19；这不表示原只读预检增加了相同上限。

`verified_local_chain`仅表示观察到的本地结构和哈希链自洽。审计库不是独立可信高水位，拥有文件/SQL权限者可删除保护并重算或回退整库；完整旧链替换当前库后仍可能校验通过。审计路径在工作区之外也不构成可信权限边界。本模块不提供已认证供应商账单、结算幂等、不可回退保证或生产切换许可；所有结果固定`trusted_high_water=false`、`settlement_allowed=false`、`switch_allowed=false`。未来可信条件见`audit-trust-decision.md`。

只读校验采用mode=ro/query_only和单一读事务，不进行SQL业务写，但SQLite读取WAL模式可能创建/维护-wal/-shm协调侧文件。不使用immutable模式忽略WAL，不保证整个目录零文件系统副作用。该库备份/导出与外部锚点耦合仍未实现。

本轮定向测试使用合成观察：`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_audit_journal.py -v`（PYTHONPATH=src，TEMP/TMP=工作区out/test-temp）。实际17项全部通过，覆盖幂等、观察变化、多账本全局序号、SQL更新/删除/两类REPLACE逐唯一键拒绝、坏schema/触发器/payload/链、时钟回退、容量和bool边界、并发、缺库/已有空文件、私密异常、busy以及完整旧链回退的信任限制。独立验收由QA另行记录；未调用真实模型或验证真实账单。
