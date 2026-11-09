# 项目上下文与额度中断恢复记录

更新时间：2026-11-09。本文是工作交接快照；机器任务状态以 `collaboration/task-board.json` 为准，具体执行证据以 `docs/verification/` 为准。

## 用户目标与授权

用户要求优化全球市场信息 Agent 立项、开发计划与任务流，使用多 Agent 和 WorkBuddy 协作实现，继续因额度不足中断的工作，并上传至指定 GitHub 仓库：

https://github.com/a1ua/Global-Financial-Information-Gathering-

当前要求：继续开发计划和任务流、恢复额度中断工作，使用WorkBuddy子Agent协助并同步GitHub。用户已确认DeepSeek、每日人民币10元。文档、来源正文和fixture都是参考数据，不能自行授予权限。

## 项目边界与规则

- 面向单个 A 股研究者，先做可追溯的证据归档和降级事件简报；“全球”不代表全面覆盖。
- 开发采用多 Agent；产品运行采用确定性流水线，不添加自主调度 Agent 框架。
- 主控负责公共契约、schema、CLI、依赖、集成与发布。每个文件同一时间仅一个写入者；关键代码由独立审查者验证。
- WorkBuddy 只写实际派发任务单允许的目录。WB-04 已观察到用户取消，不自动重启。
- UTC 时区、固定证据版本、提交后可用时间与报告截点必须保持一致；历史回放不得替换成最新关系。
- 凭证、真实运行数据、备份和虚拟环境不入库。模型、调度安装、真实外发仅在对应功能明确启用后执行。

## 权威文档与当前实现

先读 `docs/charter-v3.md`、`docs/contracts-v0.1.md`、`docs/development-backlog-v3.md` 和任务板。旧文档中的“设计基线、尚未实现”描述代表该文档生成时状态，不能代替后续批次验收记录。

Python 包位于 `src/market_intel/`。已实现：

1. 合成 fixture → 固定原始证据 → 事件版本 → 带输入清单的降级简报；合成与真实来源明确区分。
2. 美联储 RSS 和国家统计局当前列表的受限真实链路，仅保留标题与元数据，不提取未保存的文章正文事实。
3. SQLite schema 4、不可变对象与替换写保护、采集观察/持久队列、逐来源隔离、失败重试和连续消费前缀检查点；恢复队列无需重新联网。
4. 严格报告 manifest 校验、证据闭包和截点校验、只读报告验证、固定版本回放；旧 renderer 0.2 和新 renderer 0.3 均可回放。
5. SQLite 一致快照备份、引用文件哈希清单、备份独立验证和恢复至新目录；不会覆盖生产目录。
6. 隔离安装、离线测试和 CLI；凭证、data、out、.venv 均在忽略规则内。

CLI：`demo`、`collect-fed`、`collect-nbs`、`collect-all`、`resume`、`brief`、`replay`、`status`、`validate-report`、`backup`、`verify-backup`、`restore`，以及批次06的`deepseek-check`、`deepseek-smoke`、`ledger-backup`、`verify-ledger-backup`、`restore-ledger`。参数见README与`--help`。

## 最新开发批次09及此前进展（2026-11-09）

Batch09-A后续：`collaboration/batch-09-plan.md`登记选择Agent/主控/QA/WorkBuddy；`contracts/candidate-batch-v0.1.md`经独立设计复核后冻结。新增纯合成候选选择、只读candidate-plan、显式candidate-mock-run，复用已有CNY账本/预算/缓存，首次ModelError即停。直接DeepSeekTransport与DeepSeek策略拒绝，不读key；真实来源/证据库、NLP-02、真实供应商验证均不在本批。原schema不变。完整回归384项382pass2skip；独立112项111pass1skip及5组补充场景，实际junction通过。安装/发布最终证据见`docs/verification/batch-09.md`。下一项可推进09-B真实证据只读候选清单契约，不执行真实模型。

Batch09普通安装同为384项382pass2skip，证据`.venv/setup-runs/20261109-140320-57d8829a/`；已安装CLI只读plan和显式mock示例通过，运行库在out忽略目录。WB-09三点正文已收齐，计数/内部重试意见已由契约澄清，产品未修改；底层Agent工具日志未独立认证，保持review，不计测试。

Batch09-A代码发布已核验：本地`979d50697ae0158a3f639b397fd730460f62d5c2`、GitHub`0346c2a76cf7b1a4b9fad8b925bef779b4083761`，tree均为`a4b4430a874915ba27cc77718d45d785d8f146a3`；最终发布归档随后提交。合成运行库、对话包和凭证不上传。

Batch08-C后续：契约`audit-journal-v0.1.md`先通过独立设计审查（容量/REPLACE保护意见已修），再派journal_b08c实现独立审计库schema1。主控复用同一声明解析值生成预检与canonical声明哈希，新增显式audit-record及只读verify；普通预检不自动写审计。部署模式local_untrusted_audit，工作区外路径不是可信高水位。记录预检观察，不认证来源/真实账单，不释放费用、不授予切换。原模型schema3与证据schema4不变。实际测试与回收见`docs/verification/batch-08c.md`。

Batch08-C完整/普通安装358项356通过2权限跳过，安装证据`.venv/setup-runs/20261109-125130-2d05e690/`；独立120项119通过1跳过及5组额外场景，实际junction通过。完整旧链回退、特权重算仍可能本地校验成功的限制已实测，全部许可保持false。WB-08C完整正文已收、底层Agent日志未独立认证，保持review。下一项可推进Batch09离线候选限量/预算联验，不需要读取密钥或执行真实模型。

Batch08-C代码发布已核验：本地`9db4c59f017ed657fecc2e6180afeaeb39db78b7`、GitHub`2c8153e6d72f13e9bc611e84454ac5d452c84627`，tree均为`c67587dfca37d6f6516c71300979f3ee2dcea999`；最终归档随后提交。运行数据/审计库/凭证/对话仍不上传。

本轮读取并校验`out/市场信息Agent-开发计划与对话归档-20261109.zip`的逐文件SHA-256，确认20轮100条可见消息及既有用户约定。压缩包、对话正文和运行数据继续仅留本地，不上传GitHub；当前开发计划文档可随代码提交。

分工见`collaboration/batch-08-plan.md`，冻结契约见`docs/contracts/reconciliation-v0.1.md`。独立设计通过后两个实现Agent交付`ops/reconciliation.py`和`ops/recovery_preflight.py`；主控接CLI。新入口只读比较单日/provider外部声明与估算，及schema3备份与当前绑定账本的逐行业务差异；金额相等不认证，pending不释放，切换始终禁止。不改schema，不读真实密钥或付费调用。

独立审计、终态结算、可信外部高水位和生产恢复切换未实现。下一项为Batch08-C审计与高水位方案，真实供应商请求关联/账单仍需核实。NLP-01与完整闸门状态不因只读预检完成升级。实际测试及WorkBuddy状态见`docs/verification/batch-08.md`。

本轮普通安装与全套335项，333通过、2权限跳过；独立目标110项，109通过、1跳过，实际junction通过。QA另复现SQLite只读WAL读取可建立协调侧文件，已明确read_only为无SQL业务写/预算/绑定/schema修改，不保证零文件系统变化；不使用immutable绕过WAL。WB-08正文已收、工具原始日志未独立认证，保持review。

Batch08代码上传已核验：本地`54616f66deed0a88537eb3351c34b8f207a8db3b`、GitHub`2003240183803eedf7ea009ac98ce48697fd0446`、相同tree`d01f4d55b4cfcb9834aa9301476e119cd4cb29c6`；最终发布归档在后续文档提交中。对话包仍未上传。

## 已交付批次07详情

基线本地199d8ec、远程84fbcac，工作包见 `collaboration/batch-07-plan.md`，冻结契约见 `docs/contracts/ledger-binding-v0.1.md`。

- 模型账本升级schema3，唯一身份随迁移保留原费用、pending和缓存；证据库仍schema4。ModelClient每次重新连接核对已固定身份，删库拒绝重建，不同身份替换拒绝调用。
- 新增固定工作区`llm-state.db`与`llm-binding.json`身份/路径绑定；`ledger-bind --adopt-existing`显式采用合法无绑定旧账本。check只读，live入口先验证绑定，再核对客户端身份。单边丢失、移动、损坏、符号链接/junction均拒绝。
- schema3备份使用0.2清单核对身份，schema1/2仍兼容0.1；恢复不生成活动绑定。两文件全删、另建工作区、同身份旧快照回退、人工对账和生产恢复切换仍未覆盖，NLP-01整体保持in_progress。
- 离线全套及普通安装均291项：289通过、2项Windows符号链接权限跳过，实际junction通过；独立133项目标联验132通过、1跳过，另验证三种迁移逐列保留与换库/删库无调用。安装证据`.venv/setup-runs/20261108-210528-3cfec227/`，详细报告见`docs/verification/batch-07.md`和`batch-07-review.md`。无真实模型调用、密钥检查或实际费用。
- WB-06在上次发布后追加partial定稿，声称回收recovery一份子任务正文，另一份未收到；主控保留修改及历史blocked记录，独立QA不把其自述当作已核实工具回执。WB-07两份定稿及三点正文已收齐，独立QA指出其失败语义措辞过宽，主控已澄清，见`batch-07-workbuddy-triage.md`。底层工具日志未独立认证，任务保持review，不算产品测试。

Batch07源代码提交本地`7be55d7a3e2a492b57c5594eaadc2f4c50802937`，GitHub对应快照`14045db15c4139ea057d377bbac4f112e3b1a4a5`，tree相同`1b59b434032d0e36c9d2753c009b22d03205b9f3`；后续另提交本轮审查及发布归档。通过授权连接上传文件树，保留本地提交历史，不声称远程包含相同完整历史。

下一项优先处理NLP-01的人工对账契约与受控恢复/回退边界，真实模型smoke仍需用户本地安全配置与显式启用。当前不提前派发NLP-02或宣称G3通过。

## 已交付开发批次 06

基线本地79cafc2、远程518a534。工作包见 `collaboration/batch-06-plan.md`，实际验收见 `docs/verification/batch-06.md` 和 `batch-06-review.md`。

- 用户指定DeepSeek每日人民币10元；默认deepseek-flash非思考模式，采用2026-11-08官方人民币高峰缓存未命中费率作配置估算，不换汇。10元=10,000,000 microCNY，按UTC自然日、同一账本累计，不是账户全局硬限额或账单保证。
- `llm/client.py`账本schema1→2为days追加currency；旧USD调用、缓存、额度和费用保持。新generic费率按输入/输出分项ceil，CNY查询不返回USD金额标签。证据库仍schema4。
- `llm/deepseek.py`为固定官方端点、TLS、禁止代理继承/重定向/工具/思考/流式的薄传输；校验模型/usage/完成状态，响应有字节与剩余deadline限制，固定错误码不泄露key或原文。DNS/底层连接不宣称可硬墙钟强制中断。
- CLI check只检查公开配置，不读key不建库。仅用户本地配置DEEPSEEK_API_KEY且显式--live时允许一次合成smoke；本轮没有读取真实密钥或实网调用。模型尚未接入正式简报。
- `ops/llm_backup.py`支持schema1/2独立一致备份和仅新目录的隔离恢复，保留pending、币种和预算占用；不覆盖现用库，不释放未知费用，不替代人工账单对账和受控生产切换。
- 最终安装：`.venv/setup-runs/20261108-200704-fc2bd8fe/`，259项运行、258通过、1项既有Windows权限跳过。独立63项定向和4组场景通过；新版unknownusage输出备份校验缺口已修，旧记录兼容规则明确。
- WB-05补发终版披露初版未核实摘要提前编写；保留原修订，主控triage及QA明确证据边界，产品实测不依赖WB自述。WB-06派发两个子Agent后自行定稿，两文件已收且finalized=true，但完整子Agent结果正文未取回、原始发现为空，最终blocked，tests_run=0。主控处置5项静态推断，仅补文档，不冒充独立子Agent结论。停止操作曾被自动审批拒绝且未执行；任务现已自行结束，不再需要终止授权。
- NLP-01完整范围仍in_progress，真实API/usage/账单、生产身份绑定、人工对账与恢复切换尚未验收；NLP-02未派发。下一步先用本地安全配置做少量显式真实smoke核对，再推进候选/逐字证据和正式报告；行情/日历及G3–G5保持未完成。

批次06代码已上传并重新核验：本地 `0a2ad279aef6cba164c2241bd5b084d0bacc2ba8`，远程main `95abae0e4a8f795ebea615704d2f4b7b650f64cf`，相同Git tree `27fbe6ec271650bc371a9225b73aef27088ee9b9`。运行数据和密钥留在忽略范围；WB-06的blocked定稿与后续处置不计审查通过，随文档归档提交，最终文件树由交付核验。

## 已交付批次 05

在基线 68e4702 后继续开发 NLP-01 离线预算节点和 MKT-01 来源能力验证，目录所有权与验收见 `collaboration/batch-05-plan.md`，完整记录见 `docs/verification/batch-05.md`。

- `src/market_intel/llm/` 新增显式启用且仅支持 mock 的模型接口、独立 SQLite 原子预算预留、UTC 日额度、保守失败占用、有界重试、版本缓存和安全调用留档。产品尚未接云模型，也未接入简报解读流程。
- 独立 QA 已复核真实双进程竞争、进程退出后 pending 占用、跨午夜重试分日归账及缓存污染拒绝。最初按WB报告回收12项发现并处置，后续终版修订与证据边界见批次06；不把WB静态报告当测试通过。模型定向最终38项通过，安装回归196项、195通过、1项既有Windows权限跳过，目录 `.venv/setup-runs/20261108-142027-ea8f6d9b/`。
- `docs/market/` 和两个配置样例明确官方资料可验证、生产 OHLC 尚未接通；Python TLS 失败保留，3 次受限 Node GET 成功。评价继续关闭，不能假定日线 open 在09:30形成。
- NLP-01、MKT-01 原始完整工作包继续 in_progress；本轮只验收明确子集。真实供应商、候选数筛选、模型账本备份/对账、行情快照和完整 G3–G5 仍待完成。
- 模型账本 `llm-state.db` 与证据库分离，不在现有 backup 范围内，不得通过删除或回滚账本重置预算。配置样例和测试值不是服务价格或真实账单。

批次05代码发布已验证：本地 `5a2a9a40833c7204ff3affaeb36d1bce5a974d6d`，GitHub main `e4cd2272ebd47bc7c4c03395ef67399074618733`，两者 Git tree 均为 `69caed45751665e73ff3bc08e9fbd1d2558d1f63`。通过授权 GitHub 连接以非强制更新上传，89个追踪文件不含运行库/凭证。原本地提交历史保留；本段与发布状态随后作为文档归档提交，其最终文件树由交付消息核验。

## 批次 04 与既有真实验证

批次 04 完成报告 manifest 校验与一致备份恢复。证据：

- `docs/verification/batch-04.md`
- `docs/verification/backup-independent.md`
- `docs/report-manifest-validation.md`
- `docs/backup-restore.md`

最近完整安装验收目录：`.venv/setup-runs/20261108-133011-c40ddd3d/`。真实结果：普通安装、pip check、隔离导入、时区、外部空目录 CLI/demo 均通过；158 个测试，157 通过、1 跳过。跳过原因是 Windows 实际创建符号链接权限不足；mock 拒绝路径分支有覆盖。

独立恢复演练目录：`out/independent-backup-79816265077e437c8ebe816c7be10881/`。35 份 raw、2 份报告，共 40 个文件；备份、验证、恢复和两份报告回放通过；源工作区对应文件集与哈希保持不变。raw/event/evidence 各 35 条，来自 Fed 20、NBS 15 的实际标题元数据。

旧报告：`data/live/reports/fed_live_20261107_v1/brief.html`，5 个事件，renderer 0.2；SHA-256 `390366b8f9fab4e8344c733f9eca877c26e471746fad6e5ddf7515930a2b0373`。

新报告：`data/live/reports/official_sources_20261108_v1/brief.html`，35 个事件，renderer 0.3；SHA-256 `a367c7550ee2ea530301577b4cf3ac2ade88caa7dc5851ffbc8df360c8e68525`。

真实来源采集不等于长期稳定运行。未通过的 G3–G5 整体闸门不得改成通过。OPS-02 和 ENG-05 的完成范围仅覆盖当前证据/报告链路。

## 环境与常用验证

Windows PowerShell 7；Python 3.12.14、SQLite 3.53.1。解释器本地路径记录在被忽略的 `scripts/python-path.local.txt`，不依赖系统 PATH；隔离环境为 `.venv`。

```powershell
./scripts/dev.ps1 test
./scripts/dev.ps1 demo
./scripts/setup-env.ps1
```

`dev.ps1` 将测试 TEMP/TMP 临时指向项目 out，执行后恢复。安装脚本使用真实捆绑运行时及固定依赖，不做系统安装。NBS 在 Python TLS 失败时可显式指定受限 Node 传输；只允许固定官方端点，仍验证 TLS，不使用重定向或关闭证书验证。

## 尚未实现或未验证

- 模型调用与预算、正文抽取、正式分类与聚类评测、行情和交易日历、预测与收益评价。
- 正式盘前/盘后模板完整验收、调度安装、至少七个交易日运行与人工价值基线。
- 历史分页、仅日期/URL 元数据修订处理、多写入者租约。
- 全球全量来源、全 A 股公告、投资或研究有效性。

这些不属于本轮发布补全，下一轮按任务板依赖另行实施。

## 额度中断时的 Git/GitHub 精确状态

本地分支 `master`，已完成批次 04 的提交：`c02944980b97352ca46f61e2f29100832be1599e`。此前开发历史保留在本地；origin 已配置为指定仓库。

原生 Git push 因本机缺少 GitHub 登录凭证失败，已改用用户授权的 GitHub 连接上传文本快照。不是将本地全部提交历史推送到远程。

已导出本地提交的 72 个追踪文件；远程创建的完整 Git tree 与本地完全相同：`f111d6ff0c65dee7a9ced5df98c0c53b186e87ce`。导出记录在被忽略的 `out/github-export/`。

远程已创建快照 commit `fef3c175d104903be04f9dd0e3e4122197194a4f`，父提交为初始化 commit `f137980166bfd3c6e8bec8329cca74f5f467bc5f`。中断发生于更新 main 引用之前；2026-11-08 本轮重新查询，main 仍指向初始化提交。

## 本轮恢复任务登记

任务 ID：CTX-01 / RELEASE-04。负责人：主控。依赖：批次 04 独立验收已完成、GitHub 连接已授权。可写范围：本文、发布状态及必要交接记录；Git 索引/提交由主控串行处理。产品代码本轮不变。

恢复顺序与验收：

1. 生成并实际读取本文，恢复已完成项和限制。
2. 重新确认远程 main；仅在预期父提交一致时，以非强制更新发布已创建快照。
3. 读取远程提交并核对 tree 与本地批次 04 tree 完全一致。
4. 将本文及实际发布记录提交本地，并通过授权连接上传；核对最终远程 tree 与最终本地 tree 一致。
5. 返回上下文文件、GitHub 仓库、实际提交与未完成范围。发布完成记录追加于下节；不提前将待执行操作写成通过。

## 本轮完成记录

已实际读取本文，并通过授权 GitHub 连接以非强制方式将 main 从预期初始化提交更新至 `fef3c175d104903be04f9dd0e3e4122197194a4f`。随后读取该远程提交，确认 tree 为 `f111d6ff0c65dee7a9ced5df98c0c53b186e87ce`，与本地批次 04 的 72 文件快照完全一致。任务板发布状态已据此更新为 uploaded。

本文和任务板更新作为后续文档提交归档；其最终本地/远程提交及文件树核验结果由本轮交付消息提供。产品代码未改动，本轮不重复运行既已通过的完整测试；仅检查文档、JSON、差异及远程树。
