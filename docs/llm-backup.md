# 模型预算账本的一致备份与隔离恢复

日期：2026-11-08；任务 NLP-01-RECOVERY。支持模型账本 schema 1（历史 USD）和 schema 2（day 显式 USD/CNY），不修改证据库 schema 4，也不把模型账本合并进原证据 backup。

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

备份目录只能包含 `ledger.db` 和 `ledger-backup-manifest.json`。manifest 版本为 `llm-ledger-backup/0.1`，保存备份ID、UTC创建时间、实际数据库schema版本、行数、pending数、文件大小及 SHA-256；不保存源机器绝对路径。

## 一致性与校验

源文件必须已存在，不会通过连接自动建立空账本。源以 SQLite read-only URI 打开，backup API取得已提交的一致快照；WAL中已提交状态纳入，未提交写排除。新快照转为 DELETE journal，不依赖源 WAL/SHM 文件。仅复制这一个数据库，不复制 API 密钥、配置、日志、证据库或任意旁支文件。读源不更新 schema、额度或调用状态。

验证不仅检查清单hash，还校验以下业务闭包：

- schema版本、固定表/列与主键、SQLite完整性和外键。
- day日期、额度、币种；调用UTC开始/结束与所属日一致，未知费用的pending/failed不能变成零占用。
- 预留与已占用均为非负整数，已占用不能超过预留；输入上界与输出上限能复算预留；每日合计不超过冻结额度。
- schema1沿用历史USD整数每token费率；schema2新元数据按各分项 `ceil(tokens × micro_units_per_million_tokens / 1,000,000)` 相加，不换汇、不向下取整。调用元数据币种须等于该日币种。
- 成功usage不能超各自预留，费用按调用当时元数据费率复算。金额只是配置费率估算，不是供应商账单。
- 成功原始输出哈希、严格JSON及输出schema保持一致；失败与pending没有成功输出。cache必须指向同请求key的成功调用，不能指向其他真实但不相关的结果。
- 带本轮新通用费率/币种元数据的成功记录，无可信usage时另按UTF-8字节数保守复核输出token上界。真正历史schema1记录（或迁移后的旧记录）缺少这些新标记，旧客户端曾接受零usage、存为NULL并保留全额预留，其输出可能超过当前保守上界；备份按旧规则保留这些历史字节和费用，不回写、不释放，**不声称旧记录已通过当前token上界验证**。历史异常须另行核查，新版记录不能利用旧兼容路径绕过校验。

更改库内容后重新计算文件hash，也不能绕过业务闭包。hash不是数字签名；有权限重写全部历史、费用与清单的本机文件所有者仍能伪造记录，不宣称具备恶意管理员防篡改能力。

## 目标路径与恢复边界

备份和恢复目标都必须尚不存在，拒绝源/目标包含、路径逃逸和符号链接/junction祖先。先写独占staging，验证后rename至新目录；错误时不发布正式目标。失败staging会保留，不能当成功备份；不会递归删除未知目录。

恢复仅建立新目录中的隔离副本，保留全部days、calls、pending、费用占用及缓存关系，**不自动释放任何额度、不覆盖当前账本、不执行生产切换**。旧快照只能证明保存时点的状态，不能反映备份后的新调用或费用。因此禁止把旧快照替换现用账本，或者换文件以规避日预算；生产恢复需要冻结当前调用、核对最新账单/日志、固定账本身份和显式切换流程，仍属后续验收范围。

隔离副本可用于只读核对和mock恢复演练。以同一原额度重新打开副本时，pending仍占预算，超限仍被拒。真正启用供应商前还须独立验收人工对账、身份绑定、旧快照回退防护和真实usage规则；本模块不提供这些额外权限或功能。

## 实际定向验证

```powershell
$env:PYTHONPATH = 'src'
$env:TEMP = (Resolve-Path out/test-temp).Path
$env:TMP = $env:TEMP
& .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_llm_backup.py -v
```

实现者首轮运行26项定向测试全部通过。独立QA随后指出无可信usage的成功输出还需复核保守token字节上界，已补新版记录重算所有hash仍拒绝的负向回归，并按主控兼容裁定另测真正旧schema1零usage记录的原字节/全额占用保留。最新测试数与执行结果随交接报告给主控。测试包含源数据库字节不变、只读验证、pending恢复后仍被额度拒绝、失败/零usage预留、WAL已提交与未提交区分、schema1历史USD、schema2 CNY分项向上取整、重算清单后的释放费用/缓存错配/坏输出/低日额度拒绝、未来schema、目标冲突与路径/链接拒绝。币种schema2样本按主控冻结契约构造；最终主控客户端迁移与独立QA集成结果另见批次验收记录，不把样本构造视为真实供应商调用。
