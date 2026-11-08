# 一致备份与恢复到新副本

范围：本地证据库、其全部内容寻址证据，以及受支持的已发布报告。接口位于`market_intel.ops.backup`；CLI由主控统一接入。本模块不安装调度、不联网、不推送备份，不读取或复制任意环境文件。

## 接口

```python
create_backup(workspace, destination) -> dict
verify_backup(backup) -> dict
restore_backup(backup, destination) -> dict
```

输入使用Path或可转换为Path的路径。所有目标目录必须不存在，且不能与源workspace/备份目录相互包含；已有目录或生产库不被覆盖。目标父目录中的符号链接/Windows reparse point拒绝；源内部引用同样拒绝链接或越界。

## 备份步骤

1. 以`mode=ro`打开来源`market.db`，通过SQLite backup API产生独立数据库快照。不会复制运行中的数据库文件来冒充一致备份。
2. 只对新快照设置`journal_mode=DELETE`，使从WAL源得到的备份自包含；不修改来源journal模式。快照通过integrity_check和foreign_key_check。
3. 从快照全部raw_items提取`raw/<SHA256>.txt`，检查记录文本哈希、路径及磁盘文件字节。历史版本同样保存；相同字节只复制一次。
4. 仅复制`reports/<规范report_id>/manifest.json`与`brief.html`。隐藏staging目录排除；每个报告检查ID、输入清单hash、HTML hash及快照引用存在，然后调用公共`verify_report`核验输入闭包、bundle、截点、receipt与真实性标记。
5. 生成`backup-manifest.json`，版本`workspace-backup/0.1`，包含创建UTC、独立ID、数据库schema、raw数、报告ID及每个文件字节SHA256/size。再次验证完整包后，才将同父目录staging整体rename为目标。

仅复制上述白名单。未引用raw、运行日志、其他用户文件、凭证、缓存、虚拟环境和不完整报告不会进入备份。清单不记录来源绝对路径。目录发布对正常Windows读者是整体可见的；不声称具备硬件掉电恢复保证或多进程发布租约。

失败不发布正式目标，已创建的特定staging保留供检查，不递归清理未知目录。不要把失败staging当作成功备份。

## 验证与恢复

verify_backup只读验证：清单结构、相对路径、逐文件hash/size、SQLite完整性/FK、应用支持的schema范围、数据库实际raw引用集合、报告集合及文件全集完全匹配。即使删掉清单中的某个raw条目，数据库实际引用集合也会使验证失败。报告原始输入必须在快照中存在，不允许用之后的事件补齐旧备份。未知未来或负schema版本明确拒绝，不把应用无法读取的数据库称为可恢复。

restore_backup先验证备份，再复制到新staging，再验证副本，最后发布到新的目标目录。恢复仅复制已经关闭的快照及匹配证据，不覆盖现有工作库。恢复副本保留backup-manifest作为来源清单；开始新的业务写入后，该清单只是初始恢复来源，不再代表更新后的工作区全量状态。

文件hash用于发现缺失/损坏和输入不一致，**不是数字签名或来源认证**；能够重写备份全部文件及清单的文件所有者仍可伪造内容，不作防篡改安全承诺。

## 一致性与并发边界

SQLite backup API可在来源WAL存在时保存已提交状态，未提交写不进入快照。本产品目前按单写入者使用。证据和已发布报告按项目规则不可变；若备份期间有新报告发布且依赖快照外新事件，验证会失败，应在当前写入结束后重试。不会静默漏掉该报告或把不一致组合宣称成功。

新报告清单模型或渲染器必须先被公共验证器支持，否则备份将明确拒绝。备份不是对未知schema/任意目录的通用归档工具。

模型预算节点使用独立 `llm-state.db`，不属于本命令的证据库备份范围。恢复证据工作区不能作为重置、释放或重新计算已预留模型额度的依据；也不能删除预算库来解除限额。批次06新增独立ledger-backup/verify-ledger-backup/restore-ledger，支持模型账本schema1/2及新目录隔离副本，见 `llm-backup.md`；供应商账单对账、生产身份绑定及恢复切换尚未验收。DeepSeek只提供显式单次合成smoke入口，不自动接入报告或调度。

## 本轮定向验证

命令：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_backup.py -v
```

覆盖：恢复副本可查询与冻结重放、WAL已提交而未提交写排除、源与备份证据缺失/损坏、报告损坏、目标冲突、嵌套路径拒绝、清单路径逃逸、未列文件、遗漏引用文件、staging/环境文件排除、源文件不改写及链接拒绝。合成fixture不代表实际生产恢复演练，真实库备份/恢复由主控另做。

Windows本账户不能实际创建符号链接，因此真实OS symlink用例跳过；另有mock分支用例验证拒绝逻辑。初次定向测试因沙箱拒绝检查AppData父路径失败，获批在沙箱外执行后进一步发现并修复WAL副本sidecar问题；失败轮未记为通过。最新实际测试结果随交接记录报告。
