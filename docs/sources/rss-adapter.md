# SRC-02：RSS 2.0 隔离解析模块交接

日期：2026-11-07。基线为 `docs/contracts-v0.1.md`；接口中的时间状态已与主控及公共契约 Agent 对齐。本模块是独立解析器，不代表 SRC-01 来源门槛或完整 SRC-02（另一个页面/API适配器）已经通过。

## 接口与输入边界

`market_intel.adapters.news.rss.parse_rss(data: bytes, *, feed_url: str) -> list[dict]`

纯标准库实现；不联网、不写数据库、不调用模型、不执行来源指令。输入上限为 5 MiB。仅接受 RSS 2.0，有 channel 的空 feed 返回空列表；坏 XML、缺 channel、错误格式和超限均显式报错。拒绝 DTD 或 ENTITY 声明，包括常见 UTF-16/UTF-32 编码形式；标准 XML 内置字符转义仍正常解析。

输出严格包含九个字段：`source_item_key`、`original_url`、`title`、`normalized_text`、`source_time_text`、`source_published_at`、`source_time_precision`、`source_timezone`、`time_parse_status`。持久化时间、哈希、来源评级、可用时间与合成标识由主控集成层补齐，解析器不补造这些字段。

每条 item 必须有非空标题和链接；不合格 item 导致整次解析失败，不静默漏项。GUID 优先作为 `guid:` 项目标识，否则使用 `link:` 加解析后的链接；GUID 只作为不透明数据，不作为跳转地址或执行对象。相对链接相对 feed_url 解析，绝对链接及 feed_url 仅允许有主机名的 HTTP(S) URL，非 HTTP(S)、坏端口和含未转义空白/反斜杠的链接拒收。原始链接参数不删减，不实现通用URL规范化。

重复 item 保留，重跑幂等与内容版本由集成层负责。同一GUID对应正文修订仍产生相同逻辑项目key，集成层必须结合内容哈希区分内容版本，不能仅以key去重丢掉修订。

## 文本与时间

description 读取 RSS 的文本（支持 CDATA 和 XML 转义后的 HTML），通过 HTMLParser 转成纯文本；去除 script/style 内容，按块级标签分隔并规范空白，保留数字、否定词和普通指令样式文字。title 同样规范化为纯文本。输出依然是不可执行数据；报告渲染器必须继续执行自己的HTML转义。

时间使用 pubDate 的原始文本。支持带明确RFC时区的日期，转换为 UTC Z；保留来源给出的 GMT、+0000、-0500 等时区标记，不猜测 IANA 地点。时间精度与状态：

| 状态 | source_published_at | 精度 |
| --- | --- | --- |
| parsed | UTC Z | minute 或 second |
| date_only | null | date |
| missing | null | unknown |
| invalid | null | unknown |
| timezone_missing（含未知时区及 -0000） | null | unknown |

仅日期时保留原始日期文本，接口不添加 source_published_date；集成层可在验证后派生。未声明时区时不按 feed 所在国家、运行机器时区或今天夏令时补出精确时点。

XML编码由ElementTree处理，另对其不能直接处理的声明 GB2312/GBK/Big5 使用标准库解码后解析。未实现 Atom、RSS1、任意命名空间扩展、content:encoded 正文、HTTP抓取/重试、游标或来源合规自动判定。

## 文件与测试证据

- 实现：`src/market_intel/adapters/news/rss.py` 与包初始化文件。
- 测试：`tests/test_rss.py`。
- 合成样本：`tests/fixtures/sources/rss-synthetic.xml`，首部明确 SYNTHETIC，URL使用example.com；不是实际Fed内容。
- 真实探测元数据：`tests/fixtures/sources/fed-probe-metadata.json`，只保存请求结果，不保存完整feed。

实际执行命令（解释器由项目脚本环境定位）：

```powershell
$rssPython = (Get-Content scripts/python-path.local.txt -Raw).Trim()
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& $rssPython -m unittest discover -s tests -p test_rss.py -v
```

结果：15项测试通过，覆盖空channel、坏XML/格式、缺必需字段、缺可选字段、时区和日期精度、未知时区、HTML及字符转义、GB2312编码、非法链接、相对链接、GUID稳定性、重复记录保留、DTD/ENTITY和输入字节上限。首次运行发现GB2312解码与`https://`被urljoin补成合法地址两个问题，已修复后重跑通过。独立审查与完整集成测试仍由主控安排，不将实现者自测作为最终验收。

## 真实联网探测与未验证项

仅请求一次 `https://www.federalreserve.gov/feeds/press_all.xml`，尝试时间 `2026-11-07T15:12:22.738295Z`（北京时间23:12）。实际返回 `HTTP Error 404: Not Found`；没有得到可用于验证本解析器的真实feed，未重试、改换入口或绕过限制。

因此真实Fed解析、字段稳定性、保留条件、长时间连通性及正式来源门槛均未通过或未验证。元数据中的 `formal_source_gate_passed=false`、`source_terms_reviewed=false` 明确保留；不能把合成测试通过解释为真实来源可用。
