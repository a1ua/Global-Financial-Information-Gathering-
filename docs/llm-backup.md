# 模型预算账本的一致备份与隔离恢复

日期：2026-11-08；任务 NLP-01-RECOVERY / NLP-01-BACKUP3。支持模型账本 schema 1（历史 USD）、schema 2（day 显式 USD/CNY）和 schema 3（追加固定账本身份），不修改证据库 schema 4，也不把模型账本合并进原证据 backup。

## API 与命令范围

```python
from market_intel.ops.llm_backup import (
    create_ledger_backup, verify_ledger_backup, restore_ledger_backup,
)

create_ledger_backup("out/llm-demo/llm-state.db", "out/ledger-backups/new-snapshot")
verify_ledger_backup("out/ledger-backups/new-snapshot")
restore_ledger_backup("out/ledger-backups/new-snapshot", "out/ledger-restored/new-copy")
```

CLI 由主控集成，具体参数以安装后 `market-intel --help` 为准。三个函数接受位置参数，返回 JSON 可序列化字典。创建返回 status=backed_up、backup 路径，验证返回 verified，恢复返回 restored、workspace 和 ledger 路径；共有 files=1、database_schema_version、days、calls、pending_calls，以及 `restore_mode="isolated_copy"`。

备份目录只能包含 `ledger.db` 和 `ledger-backup-manifest.json`。schema1/2 使用 manifest `llm-ledger-backup/0.1`，保存备份ID、UTC创建时间、实际数据库schema版本、行数、pending数、文件大小及 SHA-256；不保存源机器绝对路径。schema3 使用 `llm-ledger-backup/0.2`，严格新增 `ledger_id`，必须与库内唯一身份相同；创建、验证和恢复返回结果也新增该字段。旧schema1/2的清单与返回结构保持不变，不生成身份或迁移源账本。

## 一致性与校验

源文件必须已存在，不会通过连接自动建立空账本。源以 SQLite read-only URI 打开，backup API取得已提交的一致快照；WAL中已提交状态纳入，未提交写排除。新快照转为 DELETE journal，不依赖源 WAL/SHM 文件。仅复制这一个数据库，不复制 API 密钥、配置、日志、证据库或任意旁支文件。读源不更新 schema、额度或调用状态。

验证不仅检查清单hash，还校验以下业务闭包：

- schema版本、固定表/列与主键、SQLite完整性和外键。
- schema3 的 `ledger_identity` 恰有 singleton=1 的一行，身份为 `ledger_` 加32位小写十六进制，创建时间为有效UTC Z时点；缺表、空表、多行、非法身份或时间均拒绝。只重算文件hash不能掩盖清单与库身份不符。
- day日期、额度、币种；调用UTC开始/结束与所属日一致，未知费用的pending/failed不能变成零占用。
- 预留与已占用均为非负整数，已占用不能超过预留；输入上界与输出上限能复算预留；每日合计不超过冻结额度。
- schema1沿用历史USD整数每token费率；schema2/3新元数据按各分项 `ceil(tokens × micro_units_per_million_tokens / 1,000,000)` 相加，不换汇、不向下取整。调用元数据币种须等于该日币种。
- 成功usage不能超各自预留，费用按调用当时元数据费率复算。金额只是配置费率估算，不是供应商账单。
- 成功原始输出哈希、严格JSON及输出schema保持一致；失败与pending没有成功输出。cache必须指向同请求key的成功调用，不能指向其他真实但不相关的结果。
- 带本轮新通用费率/币种元数据的成功记录，无可信usage时另按UTF-8字节数保守复核输出token上界。真正历史schema1记录（或迁移后的旧记录）缺少这些新标记，旧客户端曾接受零usage、存为NULL并保留全额预留，其输出可能超过当前保守上界；备份按旧规则保留这些历史字节和费用，不回写、不释放，**不声称旧记录已通过当前token上界验证**。历史异常须另行核查，新版记录不能利用旧兼容路径绕过校验。

更改库内容后重新计算文件hash，也不能绕过业务闭包。hash不是数字签名；有权限重写全部历史、费用与清单的本机文件所有者仍能伪造记录，不宣称具备恶意管理员防篡改能力。

## 目标路径与恢复边界

备份和恢复目标都必须尚不存在，拒绝源/目标包含、路径逃逸和符号链接/junction祖先。先写独占staging，验证后rename至新目录；错误时不发布正式目标。失败staging会保留，不能当成功备份；不会递归删除未知目录。

恢复仅建立新目录中的隔离副本，保留全部days、calls、pending、费用占用、缓存关系及schema3原身份，目录中仍仅有数据库和清单，**不创建活动绑定、不自动释放任何额度、不覆盖当前账本、不执行生产切换**。旧快照只能证明保存时点的状态，不能反映备份后的新调用或费用；同一个ledger_id不能证明快照最新，不能检测同身份旧快照回退。因此禁止把旧快照替换现用账本，或者换文件以规避日预算；生产恢复需要冻结当前调用、核对最新账单/日志与显式切换流程，仍属后续验收范围。

隔离副本可用于只读核对和mock恢复演练。以同一原额度重新打开副本时，pending仍占预算，超限仍被拒。固定工作区身份和路径绑定见 `docs/ledger-binding.md`；备份恢复本身不建立或接管该绑定。真正启用供应商前还须独立验收人工对账、旧快照回退防护和真实usage规则；本模块不提供这些额外权限或功能。

## 实际定向验证

```powershell
$env:PYTHONPATH = 'src'
$env:TEMP = (Resolve-Path out/test-temp).Path
$env:TMP = $env:TEMP
& .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_llm_backup.py -v
```

本批实现者运行上述命令，34项定向测试全部通过。覆盖既有业务闭包、schema1历史USD、schema2 CNY分项向上取整、schema3同身份/费用/缓存恢复、身份缺表或缺行/多行/格式/UTC时间拒绝、清单身份错配和改库身份后重算hash仍拒绝，以及严格清单版本/字段检查。schema1/2 fixture移除身份表并恢复历史PRAGMA，验证旧清单和返回值不增加ledger_id。测试使用合成数据和mock，不代表真实供应商调用；独立QA及全量集成结果另见批次验收记录。
