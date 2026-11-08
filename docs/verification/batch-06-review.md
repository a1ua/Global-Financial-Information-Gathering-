# Batch 06 独立审查与验收

任务：QA-B06；审查者：独立 QA Agent。输入基线：本地79cafc2、证据schema 4、原模型账本schema 1；本轮目标按用户指定DeepSeek和每日人民币10元调整为供应商传输、人民币预算及独立账本恢复。审查者仅写本文，产品/测试/Git由各文件负责人处理。

## 当前状态

结论：**本轮人民币预算、受限DeepSeek传输及隔离账本恢复的代码/离线子集通过独立验收**。发现的一处新版无usage输出备份业务校验缺口已修复并独立复现拒绝；无未解决的本轮阻断。没有读取任何凭证，也没有运行真实付费API。结果只覆盖代码与合成HTTP验证，不能冒充DeepSeek实网、tokenizer、账单或生产恢复切换验收。

## WB-05 终版勘误核对

已读取WB-05终版Markdown、JSON及原主控处置文档。终版披露：初版在两个子Agent完整结果返回前提前写入了未经核实摘要，部分用例数值与真实回传不符；并修正了“子Agent未读代码、实现复核仅由主端完成”的旧表述，现称两位子Agent均追加了实现静态只读复核。终版还更正北京时间08:30对应UTC00:30，并撤回部分因代码快照迭代而失效的发现。

这些结论是WorkBuddy终版的自述及其回执/消息摘录。QA能检查文件可解析、修订披露和内部口径，不能由文档内容独立证明原始子Agent消息、精确返回时刻或“签名”真实性；`SUBAGENT_SIGNATURE`只是文本标记，不是密码学签名。主控曾观察到实际派发工具和团队成员，但该观察不自动证明初版摘要已经真实回收。原Batch05由QA和主控实际运行的代码测试证据独立成立，不应与WB的tests_run=0混为一谈。

本轮WB-06要求固定文档快照、真实完整子Agent结果回收后才一次定稿、不把建议或静态发现写成运行通过；这一流程修正必要。旧WB-05文件保留其执行端的终版，不由本审查者改写。

## 待验收范围

- 人民币10元对应10,000,000 microCNY；日币种隔离、schema1旧USD数据迁移不换汇/不重置、输入与输出费用各自向上取整、调用时费率留档。
- DeepSeek固定官方host、默认TLS验证、无重定向/环境代理、密钥不入请求元数据或异常、总deadline和响应字节限额、模型/usage/完成状态严格校验、有界重试。
- 账本SQLite一致快照，schema1/2、WAL已提交/未提交、pending和预算占用保留、文件hash及业务闭包、改坏业务后重算清单仍拒绝、只恢复新目录。
- 显式真实调用入口及预检、无密钥不发请求；默认测试和安装验证只用注入的合成HTTP响应。

## 最终验证

审查者已从工作区源码执行以下命令，`PYTHONPATH=src`，`TEMP/TMP`置于独占的`out/qa-batch06-temp/`，使用`.venv/Scripts/python.exe -X utf8`：

```text
python -m unittest discover -s tests -p test_llm_backup.py -v
python -m unittest discover -s tests -p test_deepseek.py -v
```

实际结果：初轮备份26项全部通过（4.385s），DeepSeek传输19项全部通过（0.027s），退出0。发现下述校验缺口后补2项回归，审查者重新独立运行最终备份28项全部通过（4.633s），退出0。包括WAL已提交/未提交、pending占用、损坏与闭包、币种/费用、旧schema、字节限额、HTTP错误、TLS固定host、禁参数覆盖和deadline等用例。没有真实HTTP请求。

随后对主控源码运行`test_llm_cny.py`与`test_batch06_cli.py`：分别10项（0.550s）、6项（0.471s）全部通过，退出0。最终独立定向为**63项全部通过**（28+19+10+6，按最终唯一用例计，未重复累加重跑），覆盖币种/ceil迁移、DeepSeek组合路径、只读预检、显式live标记、缺key前拒绝和隔离恢复副本拒绝live。主控确认稳定后，client/CLI及这两份测试哈希与本次验证时相同，没有无依据重复运行。

另执行独立内联Python脚本，全部运行产物仅位于上述目录下的`TemporaryDirectory(prefix='independent-')`，三个场景组全部通过、退出0：

1. **人民币分项取整与篡改检测**：配置输入333333、输出111111 microCNY/百万token，成功usage为1+1 token，金额为2 microCNY，证明按两个方向分别ceil而不是合计ceil；usage无USD金额键。备份恢复后usage和缓存一致。随后将备份days.currency改为USD并重算manifest文件SHA/size，验证仍以`ledger_backup_currency_invalid`拒绝，不能用正确文件hash掩盖币种业务损坏。
2. **旧USD迁移不重置**：构造schema1旧USD记录，去除新版generic币种/费率元数据；初始化新客户端迁移至schema2后，原calls所有列逐项不变、usage不变、day.currency为USD。再用相同数值cap的CNY策略请求同一日，得到`daily_budget_policy_changed`，没有进入transport；不是靠cap数值变化才拒绝。
3. **集成401与密钥边界**：注入合成401响应，走真实`DeepSeekTransport`和`ModelClient`组合（max_retries=2）。只发生一次opener调用，响应关闭，返回固定`deepseek_authentication_failed`；failed行仍占全部预留，合成假key标记未出现在账本字节中。没有读取或使用真实key。

## 独立发现与处置

新增负向实证：当前schema2客户端生成合法无usage成功记录，`max_output_tokens=64`、`max_output_bytes=1024`；备份后把输出替成schema仍合法的109字节字符串，同时更新输出SHA与manifest文件SHA/size，修复前`verify_ledger_backup`仍返回verified。当前客户端对无可信usage使用UTF-8字节保守上界，不可能新建这种成功记录，因此备份业务校验须复核该限制。已交账本负责人和主控，现已修复。

兼容裁定：早期schema1曾允许零usage成功后保留全部预留并将usage存None，其输出可能大于token上限，不能任意按新版规则拒绝历史账本。实现者对带新版`budget_currency`元数据的记录补此上界，旧无generic元数据记录保持原始内容和费用，不隐式改写；两条回归均独立通过。审查者随后重跑原内联篡改场景，现以`ledger_backup_output_invalid`拒绝109字节结果，退出0。旧格式兼容范围已在文档披露；这不是对完整重写全部账本和哈希的恶意管理员提供防伪承诺。

## 传输审查说明

已检查固定官方host、默认TLS校验、无环境代理/重定向、有限HTTP响应、原始message.content和严格usage/模型/完成状态。初审要求optional reasoning_tokens严格拒绝False/0.0，实现者已修并纳入定向回归。标准库同步DNS和多地址TCP/TLS连接不受Python逻辑deadline严格强制中断，文档已明确；当前deadline保护发送、headers和body并在连接返回后检查超时，不宣称硬墙钟终止任意底层阻塞。

## 最终审查快照

下列为工作区文件SHA-256（非Git换行规范化后的blob hash）：

| 文件 | SHA-256 |
| --- | --- |
| src/market_intel/llm/client.py | 000d28dbac3d002cab7e1132009ab27b5e136a1ca9b5e6d99f9c8ca1be7d034b |
| src/market_intel/llm/deepseek.py | 436d9ef9550ff25b8c545ba26af154de7ece87fd70696ae9cf340093da6f16aa |
| src/market_intel/ops/llm_backup.py | b706ad762d3382a633eb71805371c49b1a96f82ca2cf2da2669f3a6f2e1f5f7a |
| src/market_intel/cli.py | 800770d368ff9a01fbc92eb143e2d454234f8429a0a1f9a59dbc3f734dc67acb |
| tests/test_llm_cny.py | 2632f2b29f410b4572292247be86a15297c611b6e7007d7ab2a244b39043b94d |
| tests/test_batch06_cli.py | 2d5c8cd0169229d7a4723ff648014e09fdb8b0f7e1304f02d045f7ba474829bb |
| tests/test_llm_backup.py | c1fcd0eb3c65a64b9764b315ef065d84f79682974f845b8233240cc015ae0acc |

## 未验证与交付限制

- 未真实调用DeepSeek、未验证当前运行机证书链、DNS、真实tokenizer上界、服务端模型版本或账单；官方文档核实与注入HTTP不等于实网通过。
- 10元是同一受控账本、UTC自然日、配置费率估算上限，非DeepSeek账户的全局硬限额；其他应用、换账本、备份回退和供应商价格变动仍是边界。
- 仅新目录隔离恢复；不自动接管生产账本、不释放未知pending、不提供未经账单核对的人工结算。固定账本绑定、恢复切换、对账和真实usage核对仍待完成。
- WB-06固定文档审查尚未由QA回收，本报告不宣称其子Agent结果已返回或已通过；后续若发现影响代码的事项，须交文件负责人处理并复核。
- NLP-02语义抽取、正式报告、行情评价和运行观察仍未交付。本报告不替代主控全量回归、安装验证或最终GitHub发布核对。
