# 第二批开发与验收记录

日期：2026-11-07。范围：隔离安装、公共bundle契约、证据schema迁移、RSS解析、单次真实标题采集、信息快照与冻结重放。原V3计划保持为历史设计基线；本文件与任务板记录当前执行事实。

## 1. 本批成果

| 工作包 | 已完成范围 | 验收边界 |
| --- | --- | --- |
| ENG-02 | 项目venv、普通安装、固定setuptools/tzdata、包内demo、项目外CLI验证、Git基线 | G0本机开发环境通过；其他机器的联网安装未验证 |
| ENG-03 | RawItem/EventVersion/Evidence单bundle公共校验；稳定错误码、时间/引用/哈希/码点规则 | 本轮MVP接口通过；ReportManifest及Prediction等正式模型仍后置 |
| ENG-04部分 | schema v0→1→2→3迁移；证据外键、内容与版本唯一性、UPDATE/DELETE/REPLACE保护 | 证据层已验证；未有Prediction库及完整生产迁移恢复流程，不将整个任务标done |
| ENG-05功能 | 离线样例、报告输入清单、按精确版本重放及原产物hash复核 | 功能已验证；依赖ENG-04完整退出仍待审查 |
| SRC-02部分 | RSS2解析器、HTML转纯文本、时间精度、大小与XML声明限制 | 单RSS路径可用；第二类页面/API适配器未实现 |
| SRC-03部分 | 同内容重复采集不新增、标题修订/回退保留版本、失败日志 | 尚无完整增量游标、分页和漏跑补齐，不承诺全量覆盖 |

## 2. 真实安装和测试证据

`./scripts/setup-env.ps1`最终整体退出0。证据：`.venv/setup-runs/20261107-232448-c3424e95/`。

- Python3.12.14、SQLite3.53.1；普通安装market-intel-agent0.1.0。
- 构建setuptools84.2.1，运行tzdata2026.6；`pip check`通过。
- `-I`证明模块从venv/site-packages导入，上海/纽约IANA时区均可用。
- 从项目外的空TEMP目录执行console help和默认demo成功，不依赖工作目录或PYTHONPATH。
- 65项离线测试通过；安装结束时源码快照与当前12个打包文件一致。
- 独立审查确认setup边界、退出码及环境恢复无本批阻断项。随后把构建工具安装约束收紧为精确84.2.1，并单独执行该离线pip命令，结果Requirement already satisfied；未因此重复全量安装。

`dev.ps1`现优先项目venv并显式UTF8。开发脚本对工作区src做回归；setup脚本另对已安装包做隔离验证，二者用途分开。

## 3. 首条真实来源链路

固定入口：`https://www.federalreserve.gov/feeds/press_all.xml`。本轮只使用标题级metadata_only，不保存完整RSS或网页正文；尚未启用模型摘要和研究推理。

| 请求 | UTC时点 | 结果 |
| --- | --- | --- |
| 解析Agent初次探测 | 15:12:22 | HTTP404，保留失败元数据，不当作适配器通过 |
| 主控真实采集 | 15:23:24–15:23:25 | HTTP200；feed20条，本次限5条；新增5个事件版本，无quarantine |
| 主控再次采集 | 15:25:06–15:25:07 | HTTP200；新增0、未变化5，无quarantine |

两次成功均由同一项目客户端完成。404与200并存说明客户端/时点差异仍需长期观察，不能覆盖失败记录或证明长期稳定。

真实运行日志：

- `data/live/runs/capture_bdea15b824484299b5f9659a78fcb1c8.json`
- `data/live/runs/capture_55467ccdc3a44c5685a5bb578f03d483.json`

数据表当前为5个raw、5个event version、5个evidence，schema3。采集inserted表示新增事件版本数，不是三张表总行数。limit导致仅处理部分feed，运行状态主动标degraded。

报告：`data/live/reports/fed_live_20261107_v1/brief.html`。重放：`out/live-replay/fed_live_20261107_v1/brief.html`。两者实际SHA256均为`390366b8f9fab4e8344c733f9eca877c26e471746fad6e5ddf7515930a2b0373`。

报告明确显示来源标题/摘录、未全文核实、未模型解读、无行情评价。真实数据没有被标为合成，合成与混合测试数据则有醒目提示。产物位于忽略的运行目录，不纳入源代码提交。

## 4. 独立审查发现及修复

1. 来源配置版本标签原含斜杠，不符合选定ID契约；转换层统一为fed-rss-0.1。
2. 原始内容唯一性曾漏掉标题；schema2把标题纳入身份，覆盖同摘要标题修订。
3. INSERT OR REPLACE可绕过原UPDATE/DELETE保护；schema3增加插入冲突保护，显式关闭recursive_triggers仍拒绝替换。
4. 未知时区token曾被无条件解析；仅parsed状态要求可解释，timezone_missing保留原文且不构造UTC。
5. 重放原先只校验旧文件；现发布前也比较重生成HTML与原manifest产物hash，版本号未变但渲染行为变化时明确失败。

对应回归已通过，产品/数据Agent独立只读或临时数据库复核修复，无本批剩余阻断项。

## 5. 时间、恢复与重放规则

外部bundle时间不被视为可信数据库提交证明。真实内容事务成功后由存储层生成不可变availability_receipt；报告同时要求对象available_at及该提交后receipt不晚于截点。SQL单语句读取四类对象，减少跨快照引用错配。

若数据提交后、receipt提交前崩溃，报告暂不纳入该事件；重复采集可补建保守receipt，不倒填过去时点。该receipt是提交完成后的保守可用栅栏，不声称是SQLite提供的精确硬件级提交时间。

冻结重放支持evidence-brief/0.2，按原事件版本和证据清单取数，不重新选择“最新”；比较输入清单与产物hash后发布到独立目录。旧offline/0.1原型模板明确不支持自动重放，原文件继续保留。

## 6. WorkBuddy协作结果

WB-04已通过实际界面派发，目标为官方RSS使用条件与字段独立核验。后续观察到界面显示“用户已取消”，执行约5分14秒，未生成任务单要求的两份结果文件。主控未重启或补发任务，不把屏幕中的中间推理当作正式验收产物。

因此WB-04记cancelled；WB-01历史探测仍保留。来源长期留存条件继续unknown，不启用全文存档。美联储官方[RSS说明页](https://www.federalreserve.gov/feeds/feeds.htm)将reader/aggregator描述为显示链接、标题和短摘要的工具；本项目据此采用受限阅读场景，不把该说明扩大解释为无限制全文复制许可或确定法律结论。

## 7. 下一批与尚未通过项

- 完成来源注册配置、官方使用条件核对与国内第二来源；SRC-01仍进行中。
- 完成第二类页面/API适配器及真正增量游标、分页、失败恢复；RSS单次snapshot不能替代。
- 把报告与存储从原型模块拆出前先冻结接口，补齐ReportManifest全字段校验和生产迁移/恢复演练。
- 模型客户端、预算、正式抽取、语义聚类、行情/日历、收益评价、调度和7交易日观察均未实现或未验收。

本批接受G0本机开发环境，以及G1/G2的明确子集；完整G1/G2、G3–G5不提前标为通过。前瞻研究有效性和用户节时价值均未验证。
