# QA-B09C：固定候选快照与重放独立审查

日期：2026-11-09。负责人：独立 QA Agent。独占修改：本文件；未修改产品、共享契约、CLI、任务板或依赖。

## 设计审查

结论：设计可冻结，无阻断歧义；实现与验收尚未完成。本结论不是运行、来源事实、模型或生产验收。

输入：项目 AGENTS.md；charter-v3.md、contracts-v0.1.md、development-backlog-v3.md；collaboration/batch-09c-plan.md；contracts/candidate-snapshot-v0.1.md 设计稿；已冻结 evidence-candidates-v0.1.md；现有 pipeline/evidence_candidates.py。基线本地19ec620，证据 schema4、模型 schema3。

确认的约束：

- 精确清单验证只读取所列 event_version_id/raw_item_id/evidence_id 和对应真实回执，不调用 planner、不扫描全部业务 payload、不重查 latest。新版本、旧时刻回填和无关坏 payload 不应替换或污染已列闭包；全库 integrity/FK 校验仍可能阻断，不能宣传任意数据库变化都不影响验证。
- 顶层、manifest、16字段 descriptor 均严格字段/类型，拒绝 bool 冒充 int、无效 UTC、重复身份、顺序不符、容量/范围越界和不匹配哈希。排序按解析后的有效时刻和两个 ID；完整 manifest canonical JSON 参与 SHA256。真实回执原字符串精确匹配，规范 effective 取等值时刻；合成回执恰 null，effective 沿用09B三对象可用时刻最大值。
- 数据库 schema/integrity/FK、精确对象、真实回执在同一只读事务读取；返回已经验证的 bundles。重放只读取清单一次、加载闭包一次，不再另开查询替换输入。文件系统与 SQLite 非原子快照、WAL 协调侧文件以及恶意本机并发换文件的限制均已明确。
- 离线重放完全由两文件自包含闭包验证，不依赖原工作区/数据库/原 raw 文件；各 bundle 严格仅 raw/event/evidence/receipt_committed_at 四字段，按清单顺序核对所有 descriptor 和三个 payload 哈希，normalized_text 提供内容哈希输入。content_ref 是被验证数据，不是离线读取目标。
- 发布前完成数据/路径/序列化容量校验；新目标与工作区及来源清单目录树角色分离，祖先和文件均拒绝链接/接合点。只独占创建新目录，不覆盖/删除/自动修复；失败可能留下半成品并应被验证拒绝。不是多文件整体原子发布。1MiB/64MiB 是本批清单/重放读写限制。
- 自洽哈希不是签名、可信来源证明、完整选择证明或防回退锚点。real 仅表示数据标签；verified_inputs/verified_replay 不意味着事实支持审查、来源刷新、真实模型或 NLP-02 完成。来源正文及归档内容不得改变权限。

交接重点（属于既有设计的具体执行口径，不另增功能）：严格拒绝 replay bundle 额外字段；共享 describe 对合成数据使用三对象 available_at 最大值；真实 receipt 保留原字符串而 effective 使用规范 UTC 微秒。两实现者应直接复用主控冻结的纯 descriptor 函数。

## 实现稳定后的独立验收矩阵

| 范围 | 关键观察结果 |
| --- | --- |
| 纯 schema | 额外/缺失字段、bool/int、非法 Unicode/非有限数/重复键、cap0/100/101、重复身份/乱序/重算哈希仍不合法者均拒绝 |
| 固定输入 | 冻结旧版本后追加高版本和旧时刻回填；planner 可改变但旧清单仍加载原对象；无关坏 payload 不影响精确闭包 |
| 闭包完整性 | 所列 payload/身份/FK/回执字符串/时间/内容文件逐项破坏均拒绝；合成无视 receipt 表行；全局 FK 错误拒绝 |
| 一致性 | 读事务/WAL 新提交不混入当前闭包；replay 只消费一次加载所得 bundles，不重新规划/二次读取 |
| 自包含离线 | 移走源库和 raw 后仍能验证；两文件额外项/缺项、bundle 多字段/乱序/正文改写/manifest 不匹配拒绝 |
| 发布 | 既有目标、角色重叠、链接/接合点、容量超限、竞争和中断半成品拒绝；前置校验失败不创建目标或父目录 |
| CLI 与边界 | 成功/空集合 exit0，失败 exit1 且错误脱敏；stdout 无标题/quote/URL/正文；不调用模型/网络/凭证/预算写入口 |

## 实际执行与未验证项

设计阶段仅阅读文档和现有09B实现，tests_run=0；没有把设计结论计为测试通过。待两实现工作包和主控 schema/CLI 稳定后再独立执行并追加实际命令、结果和限制。未访问网络、密钥或模型，未将归档作为新授权，未操作其他运行中的 WorkBuddy 任务。

## 实现独立验收（2026-11-09）

结论：Batch09-C 本轮固定快照验证/自包含重放范围通过独立验收，无发现的阻断缺陷。共享 raw_item_id 必须同 raw_payload_sha256 的最终契约补充已纳入审查。仅本文件为 QA 持久修改，临时离线工作区由测试创建并清理；未修改实现或实现者测试。

实际命令（项目根目录，PowerShell 7）：

```powershell
$env:PYTHONPATH='src;tests'
$env:TEMP=(Join-Path (Get-Location) 'out')
$env:TMP=$env:TEMP
./.venv/Scripts/python.exe -m unittest test_candidate_snapshot_contract test_candidate_snapshot test_candidate_snapshot_artifacts test_batch09c_cli -v
```

结果：44项运行，43通过、1跳过，退出0；运行器报告8.024秒。跳过项是 Windows 不允许创建 symlink，不能计通过；独立复跑的实际 Windows junction 祖先拒绝项通过。套件实际涵盖严格 schema、共享 raw 身份哈希、固定旧输入、无关坏 payload、精确真实回执字符串、单只读事务、WAL、路径角色/容量/独占竞争/中断半成品和4个 CLI 成功/失败/脱敏场景。

另外通过 PowerShell here-string 管道执行 `./.venv/Scripts/python.exe -` 内联 `unittest`，6个独立构造场景全部通过（1.015秒、退出0），没有调用实现者 TestCase。仅复用既有 fixture 生成合法合成对象及 store 插入 API；快照由共享 describe/canonical hash 从明确对象手工构造，不通过 planner：

1. 两个事件/证据共享同 raw ID 和同 payload 可复核；改为同 raw ID 不同 raw hash，即使重新计算 manifest hash，纯校验仍拒绝。
2. 冻结后追加同逻辑事件高版本且可用时刻回填到旧截点，并把无关事件 payload 改为缺失字段对象；禁止 planner 和全部 bundle 扫描后仍精确返回旧 bundle。
3. WAL 模式下读完所列 event 后，由另一连接提交所列 evidence 的 claim_key 改写；本次事务仍返回旧 evidence，下一次加载明确拒绝。验证跨对象的同一读快照，不仅检查是否调用 BEGIN。
4. 重放后将源工作区整体改名，并让源路径访问/加载函数直接报错；离线验证仍通过，其 replay_sha256 等于 candidate-inputs.json 实际文件字节 SHA256。
5. 修改 raw 的 title、重新构造全部 descriptor/manifest hash 和自包含重放：离线验证通过而对原库精确验证拒绝。这是明确验证“哈希不是签名”：自洽本地重写可通过闭包一致性检查，不能据此认证来源、历史或事实。
6. 实际创建1MiB+1字节清单文件（非调低限制模拟），重放以 capacity_exceeded 拒绝；新目标及其父目录均未创建。

静态交叉审查：精确加载模块仅对所列 ID 使用 WHERE id=? 和真实回执键查询，未调用 planner/_bundles/latest；schema/integrity/FK 与闭包都处于只读单事务。重放读取清单一次并消费一次 loader 返回的已验证 bundles；离线代码不读取 content_ref 所指源文件。CLI 新命令在模型/账本入口前返回，正常结果不包含 bundles；错误经固定码处理。发布前完成两文件序列化及容量检查，文件独占写入并 fsync；不宣称目录整体原子提交。

### 已验收文件 SHA256 边界

下表为验收结束时读取到的文件字节 hash；后续若改动这些文件，应重新评估受影响检查。文档 hash 是当时设计稿文本，不代表签名或外部可信锚点。

| 文件 | SHA256 |
| --- | --- |
| src/market_intel/contracts/candidate_snapshot.py | 5C6A64F44E6362A1DD886F1EF9D33E9C8AC996F4FBA257AC5CC0CB37A45DAE6F |
| src/market_intel/pipeline/candidate_snapshot.py | 2B5D6391E4D2D48B99319596D1E913013E8933CB85C7D1E89D0C9F9988A7D94D |
| src/market_intel/ops/candidate_snapshot.py | 1BA038F319EAA05129E2A0A019D744497FBF5D1162797CF30A3D7DC05A547DB7 |
| src/market_intel/cli.py | 8AC273055CB84E9EFC8EAE8037CBA8A52C0E96C515349D439C0B90E10E5FFB71 |
| tests/test_candidate_snapshot_contract.py | 95224ED899A1517F9BA6B2C817B67BAD34C95AE2F087DCAEA5428C5E362BDCEC |
| tests/test_candidate_snapshot.py | 64B95C49AE9E7DB38FCEB0B226BC91C9F23D9551C04C7818E758B9692DDF0970 |
| tests/test_candidate_snapshot_artifacts.py | 68232E335733BA4A162F2496E4FE907B6B8561B970EFDD66C5C78635D813493B |
| tests/test_batch09c_cli.py | C8547952D1937AD6C67C47E19325FB1884EEE7BC03DAEE5E2DB46E42F7F124F8 |
| docs/contracts/candidate-snapshot-v0.1.md | F202E8397B7BAC68CF92C9DCDFA848D72D13746D6460A3EF80860DB413526BD1 |

本 QA 执行计数共50项：49通过、1跳过；6个内联独立场景不纳入项目长期测试数。全量回归、干净安装和既有35条真实标题元数据的冻结重放由主控另行记录，本报告不代为声称已运行。未实测恶意特权并发换链/断电持久性、无限大正文、真实来源刷新、API/模型/账单或七交易日运行；SQLite 与 raw 文件非联合原子、WAL侧文件可能维护等限制保持。未联网、读取密钥或调用模型，未验证事实支持、选择完整性或可信高水位。

## 最终文档静态复核

WorkBuddy自然完成后，独立QA核对了WB-09C报告/JSON、主控三点处置、candidate-replay.md阅读口径补充、契约冻结说明和主控batch-09c.md。本次只做静态复核，未重跑测试；前述QA实测计数保持50项，不新增或冒领主控全量/安装/35项元数据实测。

静态结论：三点处置与既有代码及独立实测吻合，无新增阻断。selection_version记录产生时的选择算法版本，与后续精确ID验证并不矛盾；全库integrity/FK阻断条件原契约已覆盖。复用的是同次loader已验证对象的逻辑内容，canonical输出不承诺原JSON排版；freeze仅保存描述而非正文，之后对象变化由payload/content hash拒绝。容量是UTF8编码字节限制，receipt/verified只表示输入一致性，不能提升为来源认证或签名；这些说明没有扩大产品能力或授权。

结果JSON解析成功，tests_run=0；其中subagent_result为5930字符，逐字包含于Markdown报告，且报告有FINALIZED标记。其status=completed、工具回执等均为WorkBuddy父端结果声明，未独立取得底层执行日志；structured_receipt_object_returned=false。回收正文与采信执行认证是不同结论，因此任务保留review、辅助审查不计产品测试的处置合理。

重新计算共享纯schema、精确加载、artifact和CLI四文件SHA256，均与上表产品验收边界一致；契约仅移除设计稿标题并追加冻结引用，未改变字段或算法。最终文档字节hash如下：

| 文件 | SHA256 |
| --- | --- |
| docs/contracts/candidate-snapshot-v0.1.md | F202E8397B7BAC68CF92C9DCDFA848D72D13746D6460A3EF80860DB413526BD1 |
| docs/candidate-replay.md | C92736D00537127D414024A6916281E76B6975796738C3B4AD6A9C402B3D750C |
| docs/verification/batch-09c-workbuddy-triage.md | EB8E84C1D8241477BB555969006C9C61706ABA029390AA57B2799D734236ADE5 |
| collaboration/workbuddy/results/WB-09C-report.md | 64151AEA73BC5C00AA032276F1BC85B77A5CD939B790FFB2361C92B5FDDA528F |
| collaboration/workbuddy/results/WB-09C-results.json | 543D622F70E86E010B920EC3B2E0B456E665A7FF1F3BA31531582F9EF0FF569F |

主控batch-09c.md记载全量451运行448通过3跳过、安装同计数、既有35项标题元数据只读冻结重放；本次仅检查这些声明与本QA50项统计及已知边界不冲突，未把读取报告当作独立执行。
