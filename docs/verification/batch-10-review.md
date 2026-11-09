# QA-B10：供应商成功响应关联独立审查

日期2026-11-10。独立QA仅写本文件，不修改实现、任务板、共享契约或依赖。

## 设计审查

结论：无阻断歧义，可冻结设计并派发实现。当前仅静态设计复核，tests_run=0，不计产品、真实API、账单或生产验收。

输入：AGENTS.md、charter-v3.md、contracts-v0.1.md、development-backlog-v3.md；collaboration/batch-10-plan.md；contracts/provider-correlation-v0.1.md；现有llm/client.py、llm/deepseek.py、llm/binding.py和ops/llm_backup.py。基线本地444dd2b、GitHub98eaec0，模型schema3/证据schema4。官方字段核实由主控完成；本QA没有真实联网/模型调用，不将主控查阅结果写为自己实测。

已复核的设计关系：

- completion id哈希是可选关联线索，不是HTTP请求ID、账单ID、签名或可信高水位。缺失兼容旧模拟响应；存在但非法拒绝。只持久化hash，不保存原ID、头或完整响应；本地ASCII/长度限制不是对官方所有合法ID的声明。
- ModelResponse末尾默认字段保持三参数构造兼容；CallResult及传输版本/请求缓存键不变。纯correlation模块不导入client，故可被client、transport、backup复用而不引入循环依赖。
- 只在成功且最终可接受的正整数usage入账时，把严格provider_response加入既有request_metadata，并与status/输出hash/charged列/cache写入同一_finish事务。无usage或0usage的既有通用mock成功可保留旧行为，但不形成关联；非法hash经固定错误处理，失败不存正文/关联并保留全额预留。没有把成功用量响应误当外部账单。
- 错误输出、超时或失败即使曾收到响应，仍不保存关联，是本批有意边界；重试各自call_id/attempt/预留。不同调用hash允许重复，不把hash当幂等扣费键。缓存命中继续原call_id，不新增关联、记录或费用；历史缓存缺字段不伪造回填。
- request_metadata扩展不改schema3或列，备份/恢复/预检原始字符串比较自然保留字段；现有_metadata允许额外顶层字段，因此需在_ledger逐call专门验证可选关联。严格子对象、call状态与tokens列必须一致；历史无字段schema1/2/3继续兼容。
- 查询仅接受规范call ID；check_workspace_ledger先确认bound，再单只读事务完整_ledger验证、schema3和ledger_id匹配绑定。不能用会初始化/迁移的ModelClient或可写connect。摘要按白名单返回，金额是该call原日费率估算；不存在/错绑定/非法call拒绝固定码。全库坏行仍可能阻断，不宣称只验所列行。

实施交接细节：DeepSeek捕获共享纯hash函数ValueError并转为既有deepseek_invalid_response；客户端以最终被接受的incoming/outgoing决定是否存关联，不能对未结算usage补写关联；check返回uninitialized/unbound时直接拒绝，不创建目录或绑定。数据库关闭等底层错误也不得回显原文。绑定预检与新读事务不是跨文件联合原子，继续适用既有特权换链/历史回退及WAL协调侧文件限制。

## 实现稳定后的独立验收矩阵

| 范围 | 独立观察点 |
| --- | --- |
| 纯规则 | 合法256字节ID准确hash；0/257/Unicode/空白/null/bool拒绝；对象额外/缺字段、坏hash、bool tokens、上下界、call状态/tokens不符拒绝 |
| 模拟HTTP | documented completion id准确传递hash，不保留原ID；missing兼容、present-invalid拒绝固定码；无新HTTP头/request_id推断 |
| 事务/费用 | 成功metadata与usage/charged一致；缓存重用原call不补写；legacy/no-usage兼容；非法hash、错schema、超时/重试全额预留且失败无正文/关联 |
| 备份与恢复 | 新字段原样保留、非法字段拒绝；schema1/2/3旧行兼容；隔离恢复仍不能生产切换；恢复预检应把关联变化作为差异 |
| 只读查询 | bound/schema3/规范call_id、同事务身份/用量；missing不建、路径链接/junction拒绝；WAL并发仍同快照；全文metadata/原ID/正文/路径不输出 |
| CLI | exit0摘要/exit1固定码，无live/settle；模型/网络/密钥读取和可写库入口guard；失败/未初始化不创建 |

## 已执行与未验证

设计阶段只阅读指定文档和源码，tests_run=0。没有访问真实模型、凭证、运行库、来源、外部账单或生产资源。待实现稳定后另追加实际命令、计数、独立场景及文件SHA；不把设计结论计入测试通过。

## 实现独立验收

结论：本轮成功响应关联及只读查询范围通过，已发现的问题修复后没有剩余阻断。仅本文件为QA持久修改；未改产品、实现者测试、任务板、依赖或既有运行库。

### 发现与处置

1. 共享纯API曾对合法provider_response加缺字段call泄漏KeyError，对None泄漏TypeError，与固定ValueError契约不符。主控修为兼容dict/sqlite3.Row的三键读取并映射TypeError/KeyError/IndexError为provider_correlation_invalid，补入实现者测试；独立缺call场景修后通过。
2. 独立扩展回归首跑154项：152通过、1符号链接权限跳过、1错误。既有test_legacy_unknown_usage_byte_gap_preserved_without_rewrite先用当前client生成正usage行，再手工降schema1并把usage改NULL，却保留本批provider_response，构造出矛盾历史样本，产品正确以ledger_backup_correlation_invalid拒绝。主控最终在两处降schema1历史fixture移除provider_response，未放松产品校验；本QA以最终文件重跑154项全部非跳过通过。初始失败日志out/qa-b10-targeted.log保留，不将失败计为通过。
3. 独立fakeHTTP场景初次自写测试漏配DeepSeek要求的CNY策略，构造Policy时失败；仅修正临时测试策略后重跑该场景通过，非产品缺陷，产品未因此修改。

### 实际命令和结果

项目根、PowerShell7：

```powershell
$env:PYTHONPATH='src;tests'
$env:TEMP=(Join-Path (Get-Location) 'out/test-temp')
$env:TMP=$env:TEMP
./.venv/Scripts/python.exe -X utf8 -m unittest test_provider_correlation test_deepseek_correlation test_model_call_info test_correlation_backup test_batch10_cli test_llm test_llm_cny test_deepseek test_llm_backup test_ledger_binding -v
```

最终实际结果：154项运行，153通过、1 Windows symlink权限跳过，17.157秒，exit0；日志out/qa-b10-targeted-final.log。真实Windows junction祖先拒绝项通过，不把权限跳过当作通过。

另通过PowerShell here-string管道执行python stdin的临时unittest，6个独立构造场景最终全部通过；没有调用实现者TestCase。复用既有REQUEST/NOW常量，自己创建临时绑定/账本和模拟HTTP：

1. 精确256字节ASCII ID的SHA与hashlib一致；缺call/None/列表/缺tokens均固定ValueError，验证纯API修复。
2. 以自定义sqlite3.Connection在成功事务即将写cache时，用另一连接观察同库：外连接仍看到pending、无provider_response、无output；事务后成功关联及hash才共同可见。验证真实SQLite提交隔离，非仅检查BEGIN调用。
3. 先备份合法成功账本，再只把当前关联hash改为另一个合法hash；恢复预检由equivalent_observation变为not_equivalent、changed_calls=1，费用不变且switch_allowed始终false，证明metadata关联纳入逐行比较。
4. WAL下在_ledger验证后由另一连接提交新的合法响应hash；本次摘要仍是旧hash，后续查询才看到新hash。验证完整校验与精确行查询消费同一SQLite快照。
5. 自写BytesIO模拟200 DeepSeek响应，经实际DeepSeekTransport→ModelClient→inspect查询，原completion id hash准确、CNY配置费率估算80 microCNY；成功行及摘要均无原ID或合成key，摘要无output_text/request_metadata。网络连接guard开启。此项最终单独重跑1项0.222秒exit0。
6. 0/0usage通用mock保持全额预留且不添加关联；非法response hash在max_retries=2时产生3个失败尝试，每行全额占用、无正文/关联。没有把关联哈希用作重试去重或费用减记键。

前5个其他独立场景在首个临时套件中已通过（该次6运行因上述fakeHTTP测试策略缺项有1错误），修正fakeHTTP场景后补跑通过。当前有效覆盖统计为154个定向用例加6个独立场景：160项覆盖中159通过、1权限跳过；历史失败和后续复跑另列，不将重复执行数相加或计入项目长期测试数量。

### 静态交叉核对

纯correlation不依赖client，ModelResponse默认字段兼容既有三参数构造。DeepSeek仅取非流式响应id并hash，不读HTTP头；缺失兼容、存在非法映射既有固定码。客户端generate先验证hash，_finish仅给最终已接受正usage的succeeded行同事务写provider_response，失败保留预留；缓存验证可选关联且不补写旧行。backup在每行完整业务验证内复用纯关联规则。inspect先bound、随后schema3/身份匹配及完整_ledger验证和精确查询同BEGIN；只白名单摘要，不用ModelClient或写库入口。CLI在模型/预算执行入口前返回，不接live、settle或force参数。

### 已验收文件字节SHA256

| 文件 | SHA256 |
| --- | --- |
| src/market_intel/llm/correlation.py | 3148134B89450D3680B8B4179EFAD887EB69BD0CD3C42A2D5D15E3EB19F573E6 |
| src/market_intel/llm/client.py | 65149F039BEB84656B6523F8906067C945ACEFBAE73BBA8643E5288FE7A02050 |
| src/market_intel/llm/deepseek.py | 113706E2095D22429F0374B4C162299F9C693E98C800357B55A6B197CD13323B |
| src/market_intel/ops/model_calls.py | 3EAE2DA44C7895539D9B78FC81DB5CFE3BC3342FBDBEF5A7C4E840371B01D35A |
| src/market_intel/ops/llm_backup.py | F103619772C1A8B79C478F3D931A9C6689E60084E4788255A4BB9151078FAA85 |
| src/market_intel/cli.py | B4B36F56B334BF381B925C8EB1989F31E6B0D3A1BE3A8A683EE568A6682C8886 |
| tests/test_provider_correlation.py | AF170097FF91557A9AE854C581D4E39AE68CD2E91E55F9C1949662EAFADA5DBD |
| tests/test_deepseek_correlation.py | 818864049C1175290C5689B9D188AC0C9A2823861F85C64AB008DCBE4C8D8915 |
| tests/test_model_call_info.py | 81958896E2B6E30BD34243C9DC5F27A3AE360255FC51EE10B6BB828CA504E7EF |
| tests/test_correlation_backup.py | 1524A003F29C922036CE4FEF9F37467DA2217A6F596B0EE6B4F4DE7B7F0C4960 |
| tests/test_batch10_cli.py | F556128D7058DD9AF7D4A237680C9ED61865659057249463E627919BFE4DB3B8 |
| tests/test_llm_backup.py | FC085F45D8DF68A994A4B48AC45F7196866B6E9FD5496B900597E91429C9D40B |
| docs/contracts/provider-correlation-v0.1.md | C0AD3387141FC6CE9C3D81AAF96AA0D77FCC0BCD5A87A8BC6328C1A07D2EDBF9 |

这些hash标记本次验收边界，不是签名或可信高水位。未亲测主控的完整回归、普通安装及后续WorkBuddy回收；待主控分别记录。本QA未使用真实key/模型/账单，不证明真实供应商请求关联或来源事实。失败响应关联仍是范围缺口；哈希一致不认证账单、不允许结算/释放pending、不能切换生产。绑定/DB非跨文件联合原子，WAL可维护协调文件，特权替换与回退无新增防护；NLP-01和G3完整验收不因本子集通过而升级。

## 最终静态回收核对

2026-11-10。读取主控batch-10.md、batch-10-workbuddy-triage.md和WB-10两结果文件，重新计算6个产品文件SHA，全部与本报告上表验收边界一致。本次未重跑测试；仅核对新增交接材料，不冒领主控完整回归、普通安装或界面实际操作。

JSON可解析，其subagent_result为1460字符，完整逐字包含在Markdown报告内；tests_run=0、finalized=true且两端WB-10 FINALIZED一致。父端completed、单次同步调用和实际Agent回执仍只是WorkBuddy回收声明，没有独立底层日志认证；保持review、不计产品测试合理。

三点处置与冻结契约/代码及本QA实测相符：completion id hash不是HTTP请求或账单认证；只有接受正usage的成功事务写关联，缓存不补写，失败/超时仍全额；只读schema3绑定、完整业务校验、历史备份无字段兼容和非生产切换限制均已明确。未要求扩大权限、放松产品验证或提出新的阻断变更。

主控batch-10.md如实区分早期两次485项全套失败与最终485运行482通过3权限跳过、52.441秒的稳定成功；首修误中另一同形fixture列表、最终两处schema1历史fixture都移除关联，与本QA独立154项修后通过的事实不冲突。普通安装该文当时仍标进行中，未提前写成通过。本次只静态阅读这些主控执行记录，不将其计为本QA亲测或追加到160项覆盖数。

本次读取的交接材料字节SHA：

| 文件 | SHA256 |
| --- | --- |
| docs/verification/batch-10-workbuddy-triage.md | CDC4BD82514FBA37980F6ADD05E942C44E9836504511B4A3E910244F0697D03C |
| collaboration/workbuddy/results/WB-10-report.md | B1C9486432A618F1BFB17F4E397D710C7033A3D099C368DFA69517A7A49339BB |
| collaboration/workbuddy/results/WB-10-results.json | 4DF10FEFD83951916C7297AE48A7AFE3702B2C9232AA1A16F818DDB6E97B8BFE |

最终静态核对无新增阻断。真实API、实际账单、可信高水位、终态结算及生产恢复未验收的限制保持。
