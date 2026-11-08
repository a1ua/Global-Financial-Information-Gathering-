# WB-01：运行环境与首批来源独立探测报告

| 项 | 值 |
|---|---|
| task_id | WB-01 |
| status | `partial` |
| 首次探测 UTC | 2026-11-07T14:50:19Z |
| 报告生成 UTC | 2026-11-07T14:55:38Z |
| 项目目录 | `C:/Users/user/Documents/ChatGPT/市场信息抓取` |
| 唯一写入目录 | `collaboration/workbuddy/results/`（本任务创建，此前不存在） |
| 交付文件 | `WB-01-report.md`、`WB-01-results.json` |

> `partial` 的含义：本工作包要求的只读探测动作、两份文件均已完整交付；该标记仅表示存在**未通过或未验证的依赖项**（时区支持、行情候选、留存授权、稳定性），不代表工作包未完成，也不代表项目通过 M0 / G0 / G3。

---

## 0. 结论摘要

1. **找到了真实 Python 解释器，不必安装。** PATH 首项解析到 WorkBuddy 托管的 CPython 3.13.14，SQLite 库 3.53.1；另有一个 py 启动器注册的 CPython 3.8.10（SQLite 3.35.5）。WindowsApps 下的 `python.exe` 是商店别名，不是解释器；`Python39` 目录只有 `Scripts`。
2. **与任务前置说明不一致：`py` 启动器本次实测是有注册 Python 的。** `py --version` → `Python 3.8.10`，`py -0p` 列出 `-3.8-64`。差异原因未查明，未改动注册状态。
3. **关键环境缺口：IANA 时区不可用。** 3.13 的 `zoneinfo.TZPATH` 为空且无 `tzdata`，`ZoneInfo('Asia/Shanghai')` / `ZoneInfo('America/New_York')` 均抛 `ZoneInfoNotFoundError`；3.8 根本没有 `zoneinfo` 模块。契约 v0.1 要求的展示时区与跨市场 DST 处理目前无法用标准库验证。按边界**未安装 tzdata**。
4. **两个官方来源已取得真实样本**：国家统计局数据发布（列表 + 正文，HTTP 200）与美联储 Press Release RSS（列表 + 正文，HTTP 200）。中国政府网列表可达但条目/正文未验证。
5. **行情候选不达标**：Stooq CSV 被 JavaScript 浏览器校验页拦截，未取得数据、未绕过；备用 FRED SP500 CSV 可达但只有日期 + 单列点位，无 OHLC、无复权说明、无标准证券代码，**只验证少量样本，不标记稳定运行通过**。
6. **所有来源的内容留存条件均为 `unknown`**：未核实 robots / ToS / 版权 / 许可，未做全文存档，不宣称可全文存档。
7. 全程未安装软件、未申请密钥、未登录、未调用付费 API、未外发消息、未改 Git 或核心代码；仅保存 ≤350 字符片段与原文链接。未沿用旧 V1 计划的任何"已验证"假设，本包结论全部来自本次实测。

---

## 1. 边界与执行方式

- **只读参考**：列出根目录 V2 计划文件名（未读取其内容），读取 `docs/charter-v3.md`、`docs/contracts-v0.1.md` 用于对齐 `source_time_precision`、`storage_policy`、MarketSnapshot 等字段口径。文件内容不构成额外权限。
- **写入范围**：仅 `collaboration/workbuddy/results/` 目录本身及其两个文件。未写入工作区记忆或其他任何路径。
- **访问方式**：所有 HTTP 访问为**单次 GET、低频、无并发**，`User-Agent: WB-01-ReadOnlyProbe/1.0 (single-request dependency check)`，未伪装浏览器、未执行对端 JS 校验、未重试绕过。
- **网络客户端**：`/c/WINDOWS/system32/curl` 的 Schannel 通道失败后，改用真实解释器的标准库 `urllib.request`，以内联 `python -B -c` 脚本运行（`-B` 禁止写 `__pycache__`），**不落盘临时文件**。
- **总请求量**：约 15 次 GET，分散在 14:51–14:55 UTC 的 4 分钟内，单个 URL 最多 3 次。

---

## 2. 环境实测：命令与真实输出

### 2.1 启动器与 PATH 解析

实际命令（Git Bash）：

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
for c in python python3 py; do printf "%s: " "$c"; command -v "$c" || echo NOT_FOUND; done
where.exe python
where.exe py
py --version
py -0p
```

真实输出（摘要，逐字保留关键行）：

```
PROBE_UTC=2026-11-07T14:50:19Z
python: /c/Users/user/.workbuddy/binaries/python/versions/3.13.12/python
python3: /c/Users/user/.workbuddy/binaries/python/versions/3.13.12/python3
py: /c/WINDOWS/py
C:\Users\user\.workbuddy\binaries\python\versions\3.13.12\python.exe
C:\Users\user\AppData\Local\Microsoft\WindowsApps\python.exe
C:\Windows\py.exe
Python 3.8.10
Installed Pythons found by C:\WINDOWS\py.exe Launcher for Windows *
 -3.8-64        C:\Users\user\AppData\Local\Programs\Python\Python38\python.exe
```

**结论**：`py` 启动器（launcher）≠ 真实解释器。本次 `py -0p` 明确列出已注册 3.8-64，与任务给定的"无注册 Python"前提不符；如实记录，不臆测原因，不修改注册状态。

### 2.2 真实解释器逐个验证

实际命令形态（对三个候选路径逐个执行同一内联脚本，`-B` 不写字节码）：

```bash
PYEXE="/c/Users/user/.workbuddy/binaries/python/versions/3.13.12/python.exe"
"$PYEXE" -B -c 'import sys, sqlite3, platform, importlib.util, datetime; ...'
```

真实输出：

```
=== ...\.workbuddy\binaries\python\versions\3.13.12\python.exe ===
exe=C:\Users\user\.workbuddy\binaries\python\versions\3.13.12\python.exe
version=3.13.14 (main, Jun 11 2026, 04:04:46) [MSC v.1944 64 bit (AMD64)]
impl=CPython
sqlite_api=2.6.0 sqlite_lib=3.53.1
tzdata=absent
zoneinfo_import=ok
TZPATH=()
zone=Asia/Shanghai ERROR=ZoneInfoNotFoundError: 'No time zone found with key Asia/Shanghai'
zone=America/New_York ERROR=ZoneInfoNotFoundError: 'No time zone found with key America/New_York'

=== ...\AppData\Local\Programs\Python\Python38\python.exe ===
exe=C:\Users\user\AppData\Local\Programs\Python\Python38\python.exe
version=3.8.10 (tags/v3.8.10:3d8993a, May  3 2021, 11:48:03) [MSC v.1928 64 bit (AMD64)]
impl=CPython
sqlite_api=2.6.0 sqlite_lib=3.35.5
tzdata=absent
zoneinfo_import=ERROR ModuleNotFoundError

=== ...\AppData\Local\Programs\Python\Python39\python.exe ===
FILE_NOT_FOUND
```

注意：目录名 `3.13.12` 与 `sys.version` 报告的 `3.13.14` 不一致，**按实测版本记录**，不按目录名推断。`Python39` 目录内容只有 `Scripts`。

### 2.3 别名与 CLI

```
=== WindowsApps aliases ===
python.exe -> .../Microsoft.DesktopAppInstaller_.../AppInstallerPythonRedirector.exe
python3.exe -> .../AppInstallerPythonRedirector.exe
=== sqlite3 CLI ===
NOT_FOUND
```

`sqlite3` 命令行工具不存在，但 Python 内置 `sqlite3` 模块可用（3.53.1 / 3.35.5），嵌入式存储不依赖 CLI。

### 2.4 时区支持（本包最重要的环境结论）

`docs/contracts-v0.1.md` 第 2 节要求"展示时区使用 IANA 标识，例如 Asia/Shanghai"。实测两个真实解释器都**无法解析** `Asia/Shanghai` 与 `America/New_York`：3.13 缺 `tzdata` 且 `TZPATH=()`，3.8 无 `zoneinfo`。因此：

- 跨市场事件时间双标、美股 DST 推导、交易会话对齐，**当前环境无法用标准库验证**；
- 按任务边界**未安装 `tzdata`、未改环境变量或系统设置**；
- 这是 M0 的环境依赖缺口，需由主控决定依赖方案。

### 2.5 curl 通道失败（保留原始记录）

```
/c/WINDOWS/system32/curl
curl 8.14.1 (Windows) libcurl/8.14.1 Schannel zlib/1.3.1 WinIDN
URL=https://www.federalreserve.gov/feeds/press_all.xml
REQUEST_UTC=2026-11-07T14:51:41Z
META=__META__|000||0|15.642432|...
curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_REVOCATION_OFFLINE (0x80092013)
URL=https://www.stats.gov.cn/
REQUEST_UTC=2026-11-07T14:51:59Z
curl: (35) schannel: ... CRYPT_E_REVOCATION_OFFLINE (0x80092013)
```

两次均 HTTP 状态不可得（`000`）。这是本机 Schannel 证书吊销检查离线导致的客户端 TLS 失败，**不是目标站点不可达的结论**。未使用 `--ssl-no-revoke` 之类的降级开关，未修改证书或网络设置；改用 Python urllib（OpenSSL 后端）完成全部来源实测。

### 2.6 环境判定

| 项 | 判定 |
|---|---|
| 真实 Python 解释器 | 就绪（3.13.14 主要；3.8.10 备选） |
| SQLite（Python 模块） | 就绪（3.53.1 / 3.35.5） |
| IANA 时区 / DST | **未就绪** |
| curl HTTPS 通道 | 不可用（客户端 TLS） |
| Python urllib HTTPS 通道 | 可用，已完成实测 |
| sqlite3 CLI | 不存在（不影响嵌入式方案） |

---

## 3. 首批来源逐项实测

### 3.1 国家统计局 · 数据发布（国内宏观，官方，primary）

- **URL**：首页 `https://www.stats.gov.cn/`；列表 `https://www.stats.gov.cn/sj/zxfb/`；正文样本 `https://www.stats.gov.cn/sj/zxfb/202611/t20261103_1965738.html`
- **方式 / 时间**：`python-3.13-urllib` GET，14:52:34Z、14:53:31Z、14:54:23Z、14:54:53Z（UTC）
- **HTTP 状态**：全部 `200`，`Content-Type: text/html`
- **列表可访问**：是。前 8000 字节内解析不到 `.html` 链接；读取前 60000 字节后得到 **59 个静态 html 链接**，样例 `./202611/t20261103_1965738.html`，日期 token `2026-11-04`、`2026-10-31`、`2026-10-30`、`2026-10-27`，未见 `.json` / api 标记。即静态可解析，但需要足够读取量。
- **正文可访问**：是，HTTP 200。短片段：`<title>2026年10月下旬流通领域重要生产资料市场价格变动情况 - 国家统计局</title>`，`meta ArticleTitle` 同名，`meta PubDate content="2026/11/04 09:30"`。
- **发布时间精度**：列表为**日期级**；正文 meta 为**分钟级文本** `2026/11/04 09:30`。**时区未标注**，且未核实它是发布时点还是页面生成/更新时点 → 按契约应保留 `source_time_text`、`source_timezone=unknown`、`time_parse_status` 待定，不得补出午夜或默认北京时区。
- **留存条件**：`unknown`。未核实 robots / ToS / 版权；本次仅保留短片段与链接，**未做全文存档**。
- **后续测试**：核实 PubDate 时区与语义；审阅 robots 与使用条款后确定 `storage_policy`；连续多日增量、去重键、正文修订新版本、发布与采集时间差；抽样核对列表日期与正文日期是否一致。

### 3.2 美联储 Press Release RSS（海外宏观/监管，官方，primary）

- **URL**：`https://www.federalreserve.gov/feeds/press_all.xml`；正文样本 `https://www.federalreserve.gov/newsevents/pressreleases/enforcement20261105a.htm`
- **方式 / 时间**：`python-3.13-urllib` GET，14:52:33Z、14:53:28Z、14:53:29Z、14:54:22Z（UTC）
- **HTTP 状态**：RSS 与正文均 `200`；`Content-Type: text/xml` / `text/html`；`Last-Modified: Thu, 05 Nov 2026 16:00:14 GMT`
- **列表可访问**：是。RSS 2.0，`channel title=FRB: Press Release - All Releases`；前 12000 字节含 **16 个 item**；首条 title / link / pubDate / description 均可解析。
- **正文可访问**：是（HTTP 200，标准 HTML head）。
- **发布时间精度**：`pubDate` 为 RFC 822 GMT **秒级文本**，前 5 条：

  ```
  Thu, 5 Nov 2026 16:00:00 GMT
  Thu, 29 Oct 2026 20:30:00 GMT
  Wed, 28 Oct 2026 18:00:00 GMT
  Fri, 16 Oct 2026 15:00:00 GMT
  Tue, 13 Oct 2026 18:00:00 GMT
  ```

  至少具备分钟级有效变化；但这是**来源声称值**，系统记录时钟不能证明外部真实发布时间。
- **robots**：`https://www.federalreserve.gov/robots.txt` → `404`，不据此推断授权状态。
- **留存条件**：`unknown`。未审阅 `feeds.htm` 使用条款与版权/许可，未存档全文。
- **后续测试**：核实 feed 覆盖范围（货币政策 / 监管 / 执法是否齐全）与是否有更细分官方 feed；连续多日观察更新延迟、Last-Modified 与 pubDate 关系、正文修订；按契约记录时区字段；验证正文事实段落可稳定解析，而非仅 HTTP 200。

### 3.3 中国政府网 · 最新政策（国内政策补充候选，官方，primary）

- **URL**：`https://www.gov.cn/zhengce/zuixin/`
- **方式 / 时间**：`python-3.13-urllib` GET，14:54:24Z、14:54:53Z（UTC）
- **HTTP 状态**：`200`，`text/html`
- **结果**：页面可达，标题 `最新政策_政策_中国政府网`，`meta others=页面生成时间 2026-11-06 17:12:54`；读取 21484 字节（页面全长）后得到 19 个 `.htm/.html` 链接，但样例均为 2023 年导航链接（如 `https://www.gov.cn/home/2023-03/29/content_5748953.htm`），日期 token 仅 `2026-11-06`。**最新政策条目链接未从静态 HTML 验证，正文未访问。**
- **发布时间精度**：`unknown`。页面生成时间 ≠ 条目发布时间。
- **留存条件**：`unknown`。
- **判定**：`partial_list_only`，**不计入已接通清单**。
- **后续测试**：分析列表脚本/接口来源、确认条目与正文可获取、核实条目发布时间与精度、核实授权条款、连续多日增量验证。

### 3.4 Stooq 日线 CSV（行情候选，第三方）

- **URL**：`https://stooq.com/q/d/l/?s=%5Espx&i=d`
- **方式 / 时间**：`python-3.13-urllib` GET，14:52:35Z（UTC）
- **HTTP 状态**：`200`，但 `Content-Type: text/html; charset=utf-8`，返回 796 字节的 JavaScript 浏览器校验页，片段含 `noindex,nofollow` 与 `This site requires JavaScript to verify your browser`。
- **判定**：`blocked_by_browser_verification`，**未取得任何 CSV 数据**。按任务边界未执行其 JS 挑战、未伪装浏览器重试、未绕过访问限制。
- **行情质量**：标准代码 / 交易日期 / 可靠 OHLC / 复权说明**全部无法评估（无数据）**。
- **留存条件**：`unknown`。
- **后续测试**：由主控决定是否更换有明确授权与复权说明的行情源；本包不绕过校验。

### 3.5 FRED SP500 CSV（行情候选备用，官方机构，公开无需密钥）

- **URL**：`https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500`
- **方式 / 时间**：`python-3.13-urllib` GET，14:53:31Z（UTC）
- **HTTP 状态**：`200`，`application/csv`，`Last-Modified: Fri, 06 Nov 2026 16:26:49 GMT`
- **短片段**（仅前 600 字节）：

  ```
  observation_date,SP500
  2016-11-07,2131.52
  2016-11-08,2139.56
  2016-11-09,2163.26
  ...
  2016-11-24,
  2016-11-30,
  ```

- **质量核对（按任务第 4 步）**：

  | 要求 | 实测 |
  |---|---|
  | 标准代码 | **不满足**：`SP500` 是 FRED series id，非交易所标准证券代码，未见证券主数据映射 |
  | 交易日期 | **部分**：`observation_date` 为 `YYYY-MM-DD`，但存在空值行，未验证交易日/节假日/修订语义 |
  | 可靠 OHLC | **不满足**：仅单列数值，无 Open / High / Low / Volume |
  | 复权说明 | **未核实**：CSV 无价格调整字段；指数点位通常不涉及个股复权，但序列口径、来源与修订政策未查 |
  | 稳定运行 | **未验证**：单次请求、少量样本，按任务要求不标记通过 |

- **发布时间精度**：`observation_date` 日期级；未验证完整交易日历覆盖。
- **留存条件**：`unknown`（未核实使用条款与序列许可，未下载完整序列）。
- **后续测试**：核实条款与序列口径/时间限制/修订政策；统计完整序列缺失率与更新延迟；连续多日重复访问；若 M2 需要 OHLC 与复权口径须另选数据源；独立验证交易日历。

### 3.6 汇总

| 来源 | 类型 | HTTP | 列表 | 正文 | 时间精度 | 留存 | 判定 |
|---|---|---|---|---|---|---|---|
| 国家统计局 | 国内宏观·官方 | 200 | 可 | 可 | 列表日级 / 正文分钟级（时区未标） | unknown | 有真实样本 |
| 美联储 RSS | 海外宏观·官方 | 200 | 可 | 可 | RFC822 GMT 秒级（来源声称） | unknown | 有真实样本 |
| 中国政府网 | 国内政策·官方补充 | 200 | 页面可 | 未验证 | unknown | unknown | 部分 |
| Stooq CSV | 行情候选·第三方 | 200（校验页） | 否 | 否 | 无数据 | unknown | 受阻 |
| FRED CSV | 行情候选·官方机构 | 200 | 可 | 可 | 日期级 | unknown | 单样本部分 |

---

## 4. 失败与未验证项（明确清单）

**失败 / 受阻**

1. 本机 `curl` Schannel 两次 HTTPS 均 `CRYPT_E_REVOCATION_OFFLINE`，HTTP 状态不可得；改用 Python urllib 完成实测，未改系统。
2. Stooq 行情 CSV 被浏览器 JS 校验拦截，**未取得数据**，未绕过。
3. `https://www.federalreserve.gov/robots.txt` → `404`。
4. 中国政府网最新政策条目链接与发布时间未从静态 HTML 解析到，正文未访问。

**未验证（不得写成通过）**

5. **IANA 时区 / DST 支持未就绪**，两个解释器均无法解析 `Asia/Shanghai`、`America/New_York`；未安装 `tzdata`。
6. `py -0p` 与"无注册 Python"前提不一致，差异原因未查；目录名 `3.13.12` 与实测版本 `3.13.14` 不一致，原因未查。
7. 国家统计局 `PubDate` 的时区与语义（发布 vs 生成/更新）未核实。
8. **全部 5 个来源的 robots / ToS / 版权 / 许可条件均未核实**，`retention_status` 一律 `unknown`，未存档全文。
9. **交易日历候选未实测**（A 股 / 美股节假日、提前收市、DST）。
10. **稳定性未验证**：单日、单客户端、低频少量样本；未做连续多日运行、重跑幂等、正文修订检测、限速观察、失败重试。
11. 未验证模型调用、预算、依赖清单、CI / 验收命令；未使用密钥、付费 API、登录账户或外发消息。
12. 未验证 Git 状态与核心代码（按边界不得触碰）。

---

## 5. 对主控的建议（仅建议，不越界执行）

1. **M0 环境门槛**：真实解释器与 SQLite 已就绪，但 `zoneinfo` 不可用是硬缺口。请在依赖清单中显式决策：引入 `tzdata`（本包未安装），或改用固定 UTC 偏移 + 独立 DST 规则；并在冻结前实测 `Asia/Shanghai` 与 `America/New_York` 及跨市场对齐。
2. **M0 来源门槛**：`charter-v3` 要求"至少两个官方来源有真实样本"——本包为国家统计局与美联储各提供了列表 + 正文的 200 真实样本与短片段证据，可作为该条输入之一；但**中国政府网、Stooq、FRED 均不得计入已接通清单**。
3. **证据与留存**：在确认授权条件前，建议 `storage_policy` 暂按 `excerpt_metadata` / `metadata_only` 设计，不启用 `full_text`；契约 v0.1 第 2 节的 `source_time_text` / `source_timezone` / `source_time_precision` / `time_parse_status` 需要为"统计局分钟级但时区未知""列表仅日期"分别设计解析与 `quarantine` 规则。
4. **行情与日历**：当前两个行情候选均不足以支撑 M2 的 MarketSnapshot / 评价协议（缺 OHLC、缺复权说明、缺标准证券代码、缺交易日历）。建议单列工作包重新选型并验证证券主数据映射与价格调整口径。
5. **不要据本包宣称 G0/G3 或 M0 通过**；本包只交付环境事实、首批来源事实与缺口清单。

---

## 6. 交付与自检

- 写入文件（仅此两项 + 结果目录本身）：
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-01-report.md`
  - `C:/Users/user/Documents/ChatGPT/市场信息抓取/collaboration/workbuddy/results/WB-01-results.json`
- JSON 自检：由本包用同一真实解释器执行 `json.load` 校验可解析性，并检查必需字段 `task_id / status / checked_at_utc / environment / sources / limitations` 及每个 source 的 `url / source_type / checked_at_utc / access_result / timestamp_precision / retention_status / evidence / next_checks`。校验结果见下方最终回复；如校验失败会如实说明。
- 未写入凭证或敏感环境变量；未包含任何未实际执行的命令或访问输出。
