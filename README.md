# 全球市场信息 Agent

本项目以A股盘前/盘后研究为首版场景，按证据收集、结构化、简报和结果核对逐步开发。当前支持美联储RSS与国家统计局列表标题采集、持久待处理队列、无网络恢复、版本化证据、信息快照及冻结重放；尚未加入模型解读和收益评价。

## 文档入口

- `docs/charter-v3.md`：立项价值、范围与停止条件。
- `docs/development-backlog-v3.md`：详细工作包、依赖、交付与验收。
- `docs/contracts-v0.1.md`：数据与时间契约。
- `collaboration/protocol.md`：Agent分工、文件所有权与集成闸门。
- `collaboration/task-board.json`：机器可读任务板。
- `collaboration/workbuddy/WB-01-task.md`：已派发的独立探测任务。
- `docs/verification/batch-02.md`：本批真实采集、安装、测试和剩余门槛。
- `docs/verification/batch-03.md`：国内来源、队列与失败恢复的最新验收。
- `docs/capture-recovery.md`：发现/消费检查点、修订顺序及重试规则。
- `docs/backup-restore.md`：一致备份、备份校验与恢复副本。
- `docs/verification/batch-04.md`：报告清单、恢复演练与本轮交付状态。
- `collaboration/batch-05-plan.md`：本轮模型预算节点、行情来源验证及独立审查的目录分工。
- `docs/llm-client.md`：离线注入传输、持久预算、调用记录与缓存接口。
- `docs/market/capability-review-20261108.md`：行情、标的及交易日历的部分验证与阻断项。
- `docs/verification/batch-05.md`：本轮实现、独立审查、安装回归及 WorkBuddy 协作记录。
- `docs/deepseek-provider.md`：DeepSeek固定端点、人民币预算口径与传输边界。
- `docs/llm-backup.md`：模型账本schema1/2的一致备份和隔离恢复。
- `collaboration/batch-06-plan.md`：当前批次的目录分工与依赖。

## 本地验证

PowerShell 7中执行：

```powershell
./scripts/setup-env.ps1
./scripts/dev.ps1 test
./scripts/dev.ps1 demo
```

安装脚本读取不入库的`scripts/python-path.local.txt`，在项目`.venv`普通安装，离线复用指定运行时已有的setuptools/tzdata；不改系统。当前本机路径文件已生成，应用更新后可能需要重新定位。其他机器也可使用Python3.11+的venv和`pip install .`按锁定版本安装；此联网路径尚未在其他机器验证。

开发脚本优先使用`MARKET_INTEL_PYTHON`，其次项目venv，再读取本地路径及检查PATH。`dev.ps1 test`验证工作区源码；`setup-env.ps1`另外验证已安装包，清除PYTHONPATH后从项目外目录运行CLI与测试。安装详情见`docs/setup-verification.md`。

## 单次真实采集与报告

```powershell
./.venv/Scripts/market-intel.exe collect-fed --workspace data/live --limit 5
./.venv/Scripts/market-intel.exe resume --workspace data/live --source fed --limit 100
./.venv/Scripts/market-intel.exe brief --workspace data/live --report-id my_rss_snapshot_v1
./.venv/Scripts/market-intel.exe replay --workspace data/live --report-id my_rss_snapshot_v1 --destination out/replay
./.venv/Scripts/market-intel.exe status --workspace data/live
```

采集命令只访问固定官方入口，不自动轮询、不下载文章正文。只留存标题级元数据；完整解析当前列表后先持久入队，limit仅限制本次消费。未消费记录在关闭程序后仍保留，resume不联网。run日志分别记录discovery.discovered/unchanged（发现阶段）及inserted/unchanged/consumed（消费阶段），不可将两种unchanged混算。quarantine记录保留pending供后续恢复。

### 国内来源与显式兼容传输

本机Python客户端访问国家统计局出现TLS握手EOF；已验证现代Node标准fetch可用，故提供可选Node传输，不自动安装Node、不关闭证书检查、不静默回退。使用时设置已验证的现代Node可执行文件绝对路径（本机已验证v24.22.1）：

```powershell
$env:MARKET_INTEL_NODE = 'C:/path/to/verified/node.exe'
./.venv/Scripts/market-intel.exe collect-nbs --workspace data/live --transport node --limit 5
./.venv/Scripts/market-intel.exe resume --workspace data/live --source nbs --limit 100
./.venv/Scripts/market-intel.exe collect-all --workspace data/live --transport node --limit 5
```

Node worker随安装包提供，仅接受fed/nbs两个固定来源；拒绝重定向，有限时/字节限制，清除可注入预加载代码或关闭TLS验证的Node环境选项。未配置有效Node时明确报错。无需Node的来源可继续默认Python传输。

同项目修订按FIFO消费，不同项目按尝试次数和队列ID调度；本轮失败项不立即重试，后续运行也不会一直阻挡健康项目。发现检查点只表示本次列表已持久发现，连续消费检查点不越过失败缺口。collect-all单源失败不阻断另一来源；CLI全失败返回1、部分来源失败返回2、尚有pending/quarantine但未发生源级失败返回0并明确degraded。

真实记录在内容事务提交后获得独立availability receipt，报告同时检查对象时间与receipt，避免晚入库数据进入旧截点。重放只读取已发布manifest中的精确版本并验证输出哈希；支持evidence-brief/0.2与0.3。0.3区分国家统计局与美联储标签，0.2保留旧格式。旧offline/0.1原型明确拒绝重放，不静默升级。

也可使用明确可用的Python 3.11+：

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m unittest discover -s tests -v
python -m market_intel demo --workspace out/demo
```

demo输出SQLite库、简报HTML与输入manifest；全部内容为合成测试数据，不能用作市场事实或投资判断。重复运行不会增加重复证据；已存在但内容冲突的报告不被覆盖。

## 报告校验与备份恢复

```powershell
./.venv/Scripts/market-intel.exe validate-report --workspace data/live --report-id official_sources_20261108_v1
./.venv/Scripts/market-intel.exe backup --workspace data/live --destination out/backups/my-first-backup
./.venv/Scripts/market-intel.exe verify-backup --backup out/backups/my-first-backup
./.venv/Scripts/market-intel.exe restore --backup out/backups/my-first-backup --destination out/restored/my-first-workspace
```

请为每次备份/恢复选择尚不存在的新路径。备份使用SQLite backup API取得一致快照，复制快照引用的证据和已发布报告，逐项校验数据库完整性、外键、清单闭包与字节哈希。默认不复制runs日志、凭证、环境配置、孤立证据或未发布staging。恢复不覆盖原库，副本可用于status、validate-report和replay。

报告清单发布前、验证时和重放前均校验当前schema与版本；文件哈希正确但输入关联不完整、截点越界或真实性标签错误也会拒绝。当前只支持0.2/0.3降级快照，不把它们标为完整研究报告。哈希用于损坏检测，不是签名或市场事实证明。

## 当前限制

Batch11支持失败响应的可选标识哈希观察。现有`model-call-info`默认输出`model-call-info/0.2`，仍为26字段，新增`correlation_status=failure_recorded`；使用方需识别新版本。仅已解析同模型合法标识或正常响应后本地校验失败可附观察；无响应超时/网络/HTTP失败不造关联。失败不保存正文或usage、不减记全额预算，重试各自独立，旧记录不回填。哈希不认证账单、不允许结算。契约见`docs/contracts/provider-failure-correlation-v0.1.md`。

Batch10增加成功调用的completion ID哈希关联与只读摘要查询：

```powershell
./.venv/Scripts/market-intel.exe model-call-info --workspace data/live --call-id call_0123456789abcdef0123456789abcdef
```

示例ID是占位值，需使用实际本地call_id。命令只读已绑定schema3账本，不创建模型调用；输出用量、原日费率估算和可选响应ID哈希，不输出正文/完整元数据或原ID。completion ID不是已核实的HTTP请求ID或账单凭证，invoice_verified与settlement_allowed始终false。仅成功且接受正整数usage的调用保存关联；旧行/旧缓存不回填，失败与超时仍全额占用。模型schema不变，真实API/账单尚未验收。详见`docs/provider-response-correlation.md`和`docs/contracts/provider-correlation-v0.1.md`。

Batch09-C增加候选清单冻结、精确输入复核与自包含离线重放。冻结后只读取已列版本，新版本和历史回填不会替换原输入。以下两个目标必须是尚不存在的独立目录：

```powershell
./.venv/Scripts/market-intel.exe freeze-evidence-candidates --workspace data/live --cutoff 2026-11-09T00:00:00Z --destination out/candidates/frozen-new
./.venv/Scripts/market-intel.exe verify-evidence-candidates --workspace data/live --manifest out/candidates/frozen-new/candidate-manifest.json
./.venv/Scripts/market-intel.exe replay-evidence-candidates --workspace data/live --manifest out/candidates/frozen-new/candidate-manifest.json --destination out/candidates/replay-new
./.venv/Scripts/market-intel.exe verify-candidate-replay --replay out/candidates/replay-new
```

冻结目录只保存清单；重放目录显式保存候选正文，离线校验不再依赖源库。终端仅返回摘要，不调用模型。发布不覆盖旧目录，中断半成品会被拒绝；哈希自洽不认证来源、事实或选择完整性。容量上限清单1MiB、重放输入64MiB。详见`docs/candidate-snapshot.md`与`docs/candidate-replay.md`。

Batch09-B新增`evidence-candidate-plan`，只读既有schema4证据库，不联网、不读模型密钥、不调用模型或写模型预算。默认排除合成记录；真实标签事件需已持久化的提交后receipt，取截点内最新可用版本，再按有效可用时刻/ID限量。该清单不是重要性评分或事实抽取。

```powershell
./.venv/Scripts/market-intel.exe evidence-candidate-plan --workspace data/live --cutoff 2026-11-09T00:00:00Z --max-candidates 5
```

输出input_manifest固定event/raw/evidence版本、payload与文件哈希、回执和scope，不打印标题、正文、quote或URL。仅在新增记录有效时间晚于旧cutoff且原引用未改时，重查旧截点的manifest保持稳定；合成旧时刻回填/特权改写不在保证内。`--include-synthetic`仅供显式测试，可输出mixed标签；false来源标签不认证数据真实。SQLite只读WAL仍可能维护协调侧文件。详见`docs/evidence-candidates.md`及`docs/contracts/evidence-candidates-v0.1.md`。本命令不会将真实清单送入candidate-mock-run或DeepSeek。

Batch09-A新增离线合成候选限量与mock批处理。示例文件`config/candidates.synthetic.example.json`全部为合成数据，不查询真实证据库或市场来源。

```powershell
./.venv/Scripts/market-intel.exe candidate-plan --input config/candidates.synthetic.example.json --cutoff 2026-11-09T12:00:00Z --max-candidates 1
./.venv/Scripts/market-intel.exe candidate-mock-run --input config/candidates.synthetic.example.json --cutoff 2026-11-09T12:00:00Z --max-candidates 2 --workspace out/candidate-mock
```

plan只读输出ID和计数，不建模型库。mock-run显式写合成调用账本，固定mock transport，不读真实key，不支持--live/provider/model；首次ModelError停止剩余项，保留已成功和未知费用。缓存命中仍占所选名额，不从限量外补位。单次最多100个候选；重试可能产生多次传输尝试，每次仍由现有客户端事务预留。候选数量不是账户全局额度或真实模型token保证。输入上限1MiB/1000项，所有项先验证再截断。详见`docs/contracts/candidate-batch-v0.1.md`及`docs/candidate-selection.md`。

Batch08-C增加显式本地审计命令。`ledger-audit-record`会写入独立审计库，必须为`--journal`指定工作区树之外的新路径；先解析声明一次并完成预检，再保存同一输入对应的声明哈希、未认证凭证引用和观察结果。原`ledger-reconcile-preview`仍只读，不自动写审计。

```powershell
./.venv/Scripts/market-intel.exe ledger-audit-record --workspace data/live --statement out/statement.json --journal data/audit/journal.db
./.venv/Scripts/market-intel.exe verify-ledger-audit --journal data/audit/journal.db
```

相同观察去重，账本观察变化会追加新事件。`verify-ledger-audit`只验证本地连续链、严格格式和保护定义；完整旧链仍可能校验成功。有文件权限者可替换/重算全库，因此该审计不是可信高水位，不认证账单、不结算、不许可生产切换。审计容量上限及错误码见`docs/contracts/audit-journal-v0.1.md`，部署边界见`docs/audit-trust-decision.md`。模型账本schema3不变。

Batch08新增两项只读预检。`ledger-reconcile-preview`比较人工或合成声明与单个UTC日、provider的本地估算；声明文件严格格式见`docs/contracts/reconciliation-v0.1.md`。数值相同不认证账单，缺项或pending为incomplete，预检不会释放预留。`ledger-recovery-preflight`比较当前绑定账本与schema3备份的全部业务行；结果相同也不授权切换生产，始终`switch_allowed=false`。未提供结算、覆盖生产库或强制切换参数。

```powershell
./.venv/Scripts/market-intel.exe ledger-reconcile-preview --workspace data/live --statement out/statement.json
./.venv/Scripts/market-intel.exe ledger-recovery-preflight --workspace data/live --backup out/ledger-backups/new-snapshot
```

声明是真实凭证的手工描述也不会被自动认证；当前call_id与供应商请求尚未建立可信关联。高水位、不可变对账审计、终态结算和生产恢复仍待实现。命令合法时即使differences/incomplete/not_equivalent也返回0，必须读取JSON状态及禁止操作标志；结构或账本错误返回1。详情见`docs/reconciliation.md`及`docs/recovery-preflight.md`。

预检不执行SQL业务写或预算/绑定修改；SQLite读取WAL模式仍可能创建或更新`-wal`/`-shm`协调文件，不能承诺文件系统完全零变化。保留正常WAL读取，不用immutable模式忽略未检查点数据。

尚未实现历史分页/完整回溯、正式行情/日历同步、收益评价、定时任务与7交易日运行验收。批次06增加DeepSeek传输和人民币每日10元的单账本估算上限，但真实模型连通、tokenizer和账单尚未验证；传输模拟不代表云端接通。证据采集仍为单进程/单写入者，没有并发租约验收；已验证当前证据库的一致备份与副本恢复，尚未实现预测库及全生产运维流程。独立模型账本使用单独的ledger-backup命令，不在证据backup范围内，不能通过回滚或删除它重置预算。发现范围限当前可见列表，已经在下次扫描前消失的条目无法保证补齐。标题以外的发布时间/URL/摘要更正本批不作为新版本。标题级快照不等于盘前/盘后研究简报。

## DeepSeek人民币预算与显式单次验证

用户配置为DeepSeek每日人民币10元。当前CLI固定采用该用户策略，config/deepseek.example.json仅为字段样例，不自动加载任意配置文件。默认deepseek-flash非思考模式，采用已核实的人民币高峰缓存未命中费率估算，不换汇、不把估算当账单。日预算按UTC自然日和固定工作区中的`llm-state.db`累计；不是DeepSeek账户全局硬限额，其他程序和其他账本不受此控制。默认命令不会调用模型：

```powershell
./.venv/Scripts/market-intel.exe deepseek-check --workspace data/live
./.venv/Scripts/market-intel.exe ledger-backup --ledger data/live/llm-state.db --destination out/ledger-backups/new-snapshot
./.venv/Scripts/market-intel.exe verify-ledger-backup --backup out/ledger-backups/new-snapshot
./.venv/Scripts/market-intel.exe restore-ledger --backup out/ledger-backups/new-snapshot --destination out/ledger-restored/new-copy
```

首次真实验证需用户在本地环境安全配置`DEEPSEEK_API_KEY`，无需把密钥发送到聊天或存进仓库。下面命令会显式尝试一次付费的合成输入调用；未加`--live`或未配置密钥会先失败，不创建账本或发请求。重复相同请求可能读取已验证缓存，结果会显示cache_hit。

```powershell
./.venv/Scripts/market-intel.exe deepseek-smoke --workspace data/live --live
```

本轮安装和回归只使用合成HTTP响应，没有执行上述真实调用。备份保留pending和币种/费用占用，恢复只能建立新隔离目录；CLI拒绝将带隔离恢复清单的目录直接用于live。人工账单对账、同身份旧快照回退防护及正式恢复切换仍待完成，不据此宣称全生产可用。NLP-02抽取与正式解读尚未接入简报。

Batch07 为固定工作区增加账本 schema3 身份和 `llm-binding.json` 路径绑定。新工作区可用 `ledger-bind --workspace data/live` 初始化；已有无绑定账本必须明确执行 `ledger-bind --workspace data/live --adopt-existing`，采用会保留费用、pending及缓存。`deepseek-check`只读检查绑定，live入口拒绝单边文件丢失、不同身份替换或路径移动，不自动重建空账本。备份 schema3 使用0.2清单并校验身份，schema1/2仍兼容；恢复不生成活动绑定。两文件同时删除、另建工作区和同身份旧快照回退不在此防护范围，详见 `docs/ledger-binding.md`。

最新真实验证：国家统计局15条、美联储20条，共35条标题级事件；限量消费后均可resume清空队列，重复完整扫描新增0条。此前Python TLS失败和RSS404记录保留，少量成功请求不证明长期稳定性。长期留存条件待确认，不开启全文存档；WorkBuddy的WB-04已取消，本批未重启。

原V2计划保留不变；新版立项与任务细则见docs。V3详细工作包预算90–147小时，约11–19个单人等效工作日，来源与集成风险缓冲2–3日另列，运行观察另计；日历完成日期在环境与来源验证后确认。
