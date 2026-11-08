# 国内第二来源：国家统计局最新发布列表解析器

更新日期：2026-11-08。官方候选入口：`https://www.stats.gov.cn/sj/zxfb/`。当前状态：解析器、18项定向测试及一次真实列表解析已验证；完整来源接入、连续运行及留存适用性仍需主控验收。

## 历史失败探测

在 `2026-11-07T15:39:41.785448Z`（北京时间23:39）使用标准库urllib及声明开发用途的User-Agent请求该官方入口一次，实际得到：

```text
URLError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)
```

未得到响应HTML或列表样本；没有保存全文，没有重试、关闭TLS验证、改用HTTP或下载正文。不能由此判断网站永久不可用，也不能声称已经验证页面结构、字段稳定性、保留条件或来源覆盖率。

## 已确认的目标接口

`parse_nbs_list(data: bytes, *, page_url: str) -> list[dict]`

输出沿用RSS九字段：source_item_key、original_url、title、normalized_text、source_time_text、source_published_at、source_time_precision、source_timezone、time_parse_status。metadata-only的normalized_text严格等于title。发布时间只能取列表中对应条目的明确文本，不能用文章URL中的日期补造；日期型只标date_only、published_at=null、timezone=null。

只接受 `www.stats.gov.cn/sj/zxfb/YYYYMM/t...html` 白名单文章路径，支持相对路径。解析器限定真实观察到的`div.list-content`内的ul/ol列表li条目，排除header/nav/footer；同条响应式重复链接按URL归并并选最长可见标题。日期只取同li且不在锚点标题内的明确文本；无已验证空列表标识时，零条结果显式报错。

任何合成fixture与单测均只能证明相应假设结构下的解析行为，不能替代真实页面结构验证。下面的单次真实请求作为当前HTML与实现兼容的独立证据；不将其扩大为长期稳定性或全量覆盖证明。

## 2026-11-08真实列表验证

使用本机Codex捆绑Node执行现有受限HTTPS worker，对固定官方入口仅请求一次；未关闭TLS证书校验，重定向策略error，20秒HTTP超时和5MiB读取上限。HTML只在内存传给Python工作区解析器，没有保存完整HTML或网页正文。

| 项 | 实际结果 |
| --- | --- |
| 获取完成UTC | `2026-11-08T04:51:49.152Z` |
| HTTP / 最终地址 | 200 / 与官方入口相同 |
| 响应字节数 | 73203 |
| 解析产物 | 15条不同文章元数据 |
| 首条标题 | 2026年10月下旬流通领域重要生产资料市场价格变动情况 |
| 首条列表日期 | `2026-11-04` |
| 首条链接 | `https://www.stats.gov.cn/sj/zxfb/202611/t20261103_1965738.html` |
| 时间契约 | date_only / precision=date / source_published_at=null / timezone=null |

列表日期与URL中的20261103不同，输出证明没有从URL推造发布时间。原Python失败仍保留；Node成功不证明Python客户端同时恢复。

## 定向测试与限制

实际执行：设置`PYTHONPATH=<项目>/src`后，使用项目`.venv/Scripts/python.exe -X utf8 -B -m unittest discover -s tests -p test_nbs.py -v`。结果18项通过，0.013秒。覆盖实际容器范围、响应式重复链接、导航排除、日期不从标题/URL推断、冲突、损坏页、Unicode/数字/否定词与输入限制。

输入为UTF-8 bytes（可含BOM），超过2MiB拒绝。坏编码、未闭合列表、缺标题、缺/非法/歧义日期、多文章同li及非法URL明确失败；script/style不进入标题。本模块不联网、不存数据库、不下载正文、不推测分页URL、不决定来源许可。

官方使用说明已有链接可查，但自动化长期留存适用性、robots、速率与文章例外仍待确认，默认metadata_only。没有把当前15条可见记录当作全部历史或覆盖率分母。
