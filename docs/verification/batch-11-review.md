# QA-B11：失败响应关联独立审查

日期2026-11-10。独立QA只写本文件，不修改产品、共享契约、任务板、依赖或实现者测试。

## 设计审查

结论：无阻断歧义，可冻结后派发实现。当前为静态设计复核，tests_run=0；不是模型、来源、账单、结算或生产验收。

已读AGENTS.md、charter-v3.md、contracts-v0.1.md、development-backlog-v3.md；collaboration/batch-11-plan.md、contracts/provider-failure-correlation-v0.1.md；现有llm/client.py、llm/correlation.py、llm/deepseek.py、ops/model_calls.py、ops/llm_backup.py。基线本地4458458、GitHub1a6d462，模型schema3/证据schema4。

确认的契约关系：

- 失败关联仅为收到completion标识后保存的hash观察。成功provider_response规则保留，新增provider_failure只含版本和非空hash，二者互斥。不是HTTP请求ID或账单认证，不把不完整usage写进已接受用量列。
- DeepSeek wrapper只包既有解析主体的安全ModelError白名单，并要求已解析dict、同model、合法id；缺失/坏id或不匹配model保留原错误优先级。HTTP错误体、头、网络超时、解析前响应超限等不扩展抓取，未产生响应时不能造关联。
- 正常ModelResponse只有hash先通过校验，后续usage/JSON/schema/输出长度失败才能记观察。ObservedTransportError只带安全code/hash，不能从普通异常同名属性采信。每次尝试重置观察，重试独立call_id与预留。
- _finish失败状态、finished_at、error及provider_failure同事务提交，失败计费不采用response usage；charged保留reserved，失败input/output/output_text/output_sha256保持null，不写cache。事务失败保留pending与原全额占用，不补写旧历史。
- 共享validate_call_correlation覆盖严格子对象、互斥、失败状态及null token列，兼容sqlite.Row；缺键/坏类型固定ValueError。既有_ledger继续完整验证失败列及全额占用，所以backup/隔离restore/预检能保留并校验metadata而不改schema。
- 只读摘要明确升级model-call-info/0.2，字段集合仍26个，failure_recorded区分失败观察；既有成功和absent/id_unavailable语义保留。无正文/元数据/原ID输出，固定invoice_verified/settlement_allowed/model_called=false；全库验证、绑定、事务、WAL限制不扩大。

给实现者的执行口径（既有设计细化，不新增功能）：

1. ObservedTransportError的hash在client except路径重新校验；若对象被突变成非法/null，丢弃观察，仍走原安全失败码/全额处理，不能让二次校验异常泄露或变成费用减记。
2. 正常ModelResponse必须在hash有效后再设置本尝试failure_hash；非法hash错误不得记录非法值；每attempt清空，成功分支不能沿用上次观察。
3. 失败路径不把response传入旧usage结算逻辑；_finish内部接收failure_hash只允许failed，provider_failure与provider_response不得并存。既有_ledger的失败空列/全额验证仍须保留。

## 实现稳定后的独立验收矩阵

| 范围 | 验收要点 |
| --- | --- |
| 纯schema/错误载体 | null/额外字段/坏hash/缺call/类型、互斥与状态、sqlite.Row兼容；code/hash构造固定错误、不回显秘密 |
| DeepSeek解析 | 同model合法id的finish/usage/content失败可观察；缺id/坏id/错误model/JSON/HTTP错误/头/超时/外层超限不造；原错误码优先级保留 |
| 客户端/预算 | 正常response输出错记hash、invalidhash不记；Observedhash重新校验、普通异常伪属性不采信；重试不继承；失败无usage减记/无cache |
| 事务/历史 | 提交前外连接仍见pending无观察；失败更新中断回滚pending/全额；旧缓存/失败行不回填 |
| 备份/预检 | provider_failure原字符串保存恢复；坏关联、错误状态、减少费用在重算文件hash后仍拒绝；关联变化不许可生产切换 |
| 查询/CLI | schema0.2/26字段/failed observation/旧absent；只读单事务绑定身份/WAL与实际junction；成功退出0、坏输入退出1、无正文/原ID/密钥 |

## 实际执行与限制

设计阶段仅通过只读文件审查，未运行测试、未联网或访问真实密钥/模型。环境常规exec启动通道异常由主控观察；本QA用node_repl的node:fs/promises读取指定文件，不借UI执行命令、不操作Git写入或无关output/tmp。实现稳定后再执行定向/独立场景并追加真实证据。

## 实现独立验收（2026-11-10）

结论：本轮失败/不完整响应hash观察范围通过独立验收，无发现的阻断缺陷。仅本审查文件为QA持久修改；未改产品、实现者测试或任务板。正常exec通道已可使用系统Windows PowerShell（明确shell=C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe，login=false）；原7版路径不可用不等于需要放宽审批。

### 实际执行

在项目工作目录运行（PYTHONPATH=src;tests，TEMP/TMP=工作区out/test-temp）：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest test_failure_correlation test_deepseek_failure_correlation test_failure_call_info test_failure_backup test_batch11_cli test_provider_correlation test_deepseek_correlation test_model_call_info test_correlation_backup test_batch10_cli test_llm test_llm_cny test_deepseek test_llm_backup test_ledger_binding -q
```

实测179项运行，178通过、1项Windows symlink创建权限跳过，17.254秒、exit0。真实Windows junction祖先拒绝项通过；不把权限跳过写作通过。包括旧154项及本轮25项，重复执行和主控结果不相加。

另以PowerShell here-string管道执行python stdin内联unittest，自行构造6场景，不调用实现者TestCase，仅复用REQUEST/NOW和注入HTTP的测试辅助类。最终6项全部通过，1.345秒、exit0：

1. 同model合法completion ID、usage为空、失败正文含秘密标记的模拟HTTP，经DeepSeek适配器到人民币client：仅1条failed（不因max_retries=2而改旧ModelError不重试规则），全额预留、失败usage/正文列null。只读摘要0.2/failure_recorded/CNY，hash等于原ID字节SHA256，metadata/摘要无原ID、失败正文或模拟key，invoice_verified/settlement_allowed=false。
2. 拦截_finish连接上下文，在失败更新已执行而事务尚未提交时，从另一连接查询仍为pending且无provider_failure；提交后才同时见failed/观察，且全额占用。验证真实事务可见性，不仅检查BEGIN字符串。
3. 修改隔离备份内provider_failure hash并重算备份文件hash：本地自洽验证通过，但恢复预检检测changed_calls=1且switch_allowed=false。再减1单位charged_cost并重新计算备份hash，仍以unknown_spend_released拒绝。这同时界定hash非真实性证明、观察不能释放费用。
4. 三次失败依次为带合法hash但单边缺usage的ModelResponse、无响应TimeoutError、ObservedTransportError：attempt严格1/2/3，观察hash分别为首hash/缺失/末hash；三行各自全额，input/output与正文列均null，不继承前次hash。
5. 合法构造的ObservedTransportError被删除hash属性并把args改为私密文本后，client仍以安全transport_error失败、无观察、全额保留；秘密文本没有进入账本。
6. 正常ModelResponse含非法Unicode代理字符正文且有合法hash：失败码固定invalid_output_json，仅保留hash，不存正文/usage或成功关联；共享校验直接接受数据库sqlite.Row表示的合法failed行。

独立场景首跑6项均在setUp因ledger_binding_link_forbidden失败：自写脚本将Get-Location返回的sandbox cwd接合点别名用于未resolve的临时目录。改为显式物理TEMP/TMP且Path.resolve后重跑通过，产品未因此修改；这是测试环境路径构造问题，不能把最初错误记为通过。有效覆盖为179定向加6独立场景，共185项，其中184通过、1权限跳过；6内联场景不加入长期项目测试数。

### 静态复核

ObservedTransportError构造器只保存安全code/hash，client在except重新验证hash，突变非法/null或丢失属性均不产生观察。普通ModelError的同名属性不被采信。正常ModelResponse先验hash后才暂存，失败hash在每次attempt清空；失败_finish不传response或output，因而不触发旧usage减记。失败metadata与状态同UPDATE事务、无cache插入；成功/旧缓存不回填。

DeepSeek wrapper只捕获原解析主体的ModelError白名单，要求dict/同model/合法id；缺或坏id保留原错误优先级，HTTP/网络/JSON解析前错误不从头或体提取。共享校验保持严格字段/互斥/状态/null usage，既有_ledger继续验证失败无正文及全额费用；没有以新增观察取代既有账本业务校验。摘要schema0.2保持26字段，仅增加failure_recorded语义，仍单只读BEGIN内全库验证和绑定身份检查。

### 验收文件SHA256边界

以下为独立验收结束时读取的实际文件字节hash，不是签名或外部可信锚点。后续产品改动需重新评估受影响检查。

| 文件 | SHA256 |
| --- | --- |
| src/market_intel/llm/client.py | 5B32BADE1475B58DE297E1283B25A39633253BD629626ED9A1361160FE3852CF |
| src/market_intel/llm/correlation.py | C77FAAF2A514A55D177EFE20ADE8A67C8FDBE956B36258FEF930AC9EE05B18AE |
| src/market_intel/llm/deepseek.py | E5FEA77FFF179C5B4F10BBF2242229C563AC464A72F2ED0FFBCB450E4B8625EB |
| src/market_intel/ops/model_calls.py | 5BA1169526AB807E7693087D2E3567AA6353DD13D771B7CEE6B4B2806C17C517 |
| src/market_intel/ops/llm_backup.py | F103619772C1A8B79C478F3D931A9C6689E60084E4788255A4BB9151078FAA85 |
| src/market_intel/cli.py | B4B36F56B334BF381B925C8EB1989F31E6B0D3A1BE3A8A683EE568A6682C8886 |
| tests/test_failure_correlation.py | DEB27513D1A4B209F18565450361232A928F952D06FCB24A0D6EC835324CBD0A |
| tests/test_deepseek_failure_correlation.py | 712B90598B8A10007FB2F49DCCBDFF679D4CC249AEAFBE9331B34DACF23A6A4B |
| tests/test_failure_call_info.py | 089603D16EF4EB013FE8BF7E8D345166873D0B0323DC98B3564023F49AE516C8 |
| tests/test_failure_backup.py | E73F4F7DE5092F68D3573649FD91564EC88CB7C22970EA67569B594F167BCC03 |
| tests/test_batch11_cli.py | 917E39A90BEEE3E920B2E0C4D788F39F32C616AAC74129BA2A26A903072F42E2 |
| tests/test_model_call_info.py | 523966655D4756853F7E6650CA5B181068D07F18A7FADD35512BC4A6FDC58825 |
| docs/contracts/provider-failure-correlation-v0.1.md | FA407D452E4441EAE644F80FC5157A318A045736730E73CBC1687F4B921A2EF2 |

本QA未亲测完整项目全套、普通安装、WorkBuddy底层工具执行或真实API/账单，不冒领主控证据。未联网或读取真实密钥，无模型费用；全部模型链路为合成输入及注入HTTP。SQLite/WAL侧文件、DB/绑定非跨文件原子、特权重写/回退及恶意换链等原限制保持；没有证明来源/事实/账单真实性、账户全局上限、结算、高水位或生产切换。NLP-01整体和完整生产闸门不因本轮通过升级。

## 最终静态文档复核

实现后未再运行测试。重新读取六个产品文件hash，均与上表独立验收边界一致；没有因WorkBuddy意见追加产品行为。本次只复核新交接文档和辅助结果，不增加185项覆盖计数。

WB-11 JSON可解析，subagent_result共1187字符，逐字包含于Markdown报告；tests_run=0、finalized=true和FINALIZED标记一致。其completed、同步调用次数和Agent回执仍是WorkBuddy父端结果声明，本QA没有独立取得底层工具日志；保持review而不计产品测试的处置合理。界面自然结束及父端目标存在性探测的观察由主控记录，本QA不冒称亲见UI或重验工具认证。

三点处置与既有实现/实测一致：HTTP非200/网络/JSON前置失败在_parse之外退出，代码并非仅文字约束；合法本地注入transport仍能伪造自洽hash，所以观察不认证来源。全部attempt各自charged求和，不按hash去重或免费重试，未知费用释放有意后置。摘要0.2新增failure_recorded语义而非纯版本号变化，旧行经当前查询也返回0.2/absent；旧外部消费方需识别版本。_ledger完整验证会整库阻断，不做逐行跳过或修复。这些澄清没有扩大权限、信任或兼容承诺。

| 最终静态文件 | SHA256 |
| --- | --- |
| docs/verification/batch-11-workbuddy-triage.md | 0A56E302C1F114608ACB74A5D62D8F8A3288369E7CD53DB89B1599851DA3A4FB |
| collaboration/workbuddy/results/WB-11-report.md | 3191E94C89F8476DA3571CFBD2BB5F01614DF9579DBABF6689C4C50674858E81 |
| collaboration/workbuddy/results/WB-11-results.json | 219DEE31B26F908523F86489D54FD616F26483A1373BF22697686A9349AA15FC |

主控batch-11.md记录完整510运行507通过3跳过（60.420秒）、普通安装同计数（63.610秒）及项目外已安装包注入HTTP到人民币失败摘要全额联验；本次仅核对这些声明与本QA179加6项和已知边界一致，不将读取文档视为独立执行或真实API/账单验收。未发现需修正文档事实的新阻断。
