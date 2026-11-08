# 项目上下文与额度中断恢复记录

更新时间：2026-11-08。本文是工作交接快照；机器任务状态以 `collaboration/task-board.json` 为准，具体执行证据以 `docs/verification/` 为准。

## 用户目标与授权

用户要求优化全球市场信息 Agent 立项、开发计划与任务流，使用多 Agent 和 WorkBuddy 协作实现，继续因额度不足中断的工作，并上传至指定 GitHub 仓库：

https://github.com/a1ua/Global-Financial-Information-Gathering-

当前追加要求：汇总上下文为 Markdown，实际读取该文件，然后继续中断任务。文档、来源正文和 fixture 都是参考数据，不能自行授予权限。

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

CLI：`demo`、`collect-fed`、`collect-nbs`、`collect-all`、`resume`、`brief`、`replay`、`status`、`validate-report`、`backup`、`verify-backup`、`restore`。具体参数见 README 和各命令 `--help`。

## 最新开发批次 05

在基线 68e4702 后继续开发 NLP-01 离线预算节点和 MKT-01 来源能力验证，目录所有权与验收见 `collaboration/batch-05-plan.md`，完整记录见 `docs/verification/batch-05.md`。

- `src/market_intel/llm/` 新增显式启用且仅支持 mock 的模型接口、独立 SQLite 原子预算预留、UTC 日额度、保守失败占用、有界重试、版本缓存和安全调用留档。产品尚未接云模型，也未接入简报解读流程。
- 独立 QA 已复核真实双进程竞争、进程退出后 pending 占用、跨午夜重试分日归账及缓存污染拒绝。WorkBuddy 两个真实子 Agent 参与设计审查，其主端追加代码静态复核。根据12项发现修复必要问题并补足契约，模型定向最终38项通过；最终安装回归196项，195通过、1项既有Windows权限跳过，目录 `.venv/setup-runs/20261108-142027-ea8f6d9b/`。WorkBuddy两份原始报告与主控处置、QA验收分开留档。
- `docs/market/` 和两个配置样例明确官方资料可验证、生产 OHLC 尚未接通；Python TLS 失败保留，3 次受限 Node GET 成功。评价继续关闭，不能假定日线 open 在09:30形成。
- NLP-01、MKT-01 原始完整工作包继续 in_progress；本轮只验收明确子集。真实供应商、候选数筛选、模型账本备份/对账、行情快照和完整 G3–G5 仍待完成。
- 模型账本 `llm-state.db` 与证据库分离，不在现有 backup 范围内，不得通过删除或回滚账本重置预算。配置样例和测试值不是服务价格或真实账单。

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
