# ENG-03：公共 bundle 校验器实施说明

日期：2026-11-07。状态：本轮单bundle实现已集成并经独立审查；证据见`verification/batch-02.md`。输入设计依据为 `contracts-v0.1.md`；本文件将该设计收窄为可执行的单条bundle配置，不代替正式来源验证、数据库schema或语义事实核查。

## 1. 公共接口

```python
from market_intel.contracts import ContractError, validate_bundle

validate_bundle(bundle, allow_synthetic=True)  # 有效返回None，不修改输入
```

`ContractError`继承`ValueError`。错误消息格式为字段路径加稳定原因码，不回显正文、URL、凭证或其他原始输入值。函数不调用网络，不读写证据、数据库或报告文件，不进行类型强转、不补字段、不修改时间。IANA时区解释依赖解释器可用的标准时区数据。

仅接受带 `raw`、`event`、`evidence` 三个键的dict，每个对象只支持相应v0.1 schema。首版是单RawItem、单EventVersion、单Evidence的纵向链路；多证据和多来源事件必须后续明确升级，不能用列表扩展偷偷绕过引用检查。

`allow_synthetic=False`拒绝合成记录；设为True表示允许合成及真实记录，不表示只接收合成记录。三个对象的is_synthetic必须为真正bool且一致；调用方负责额外限制离线演示只能使用合成数据。

## 2. 本轮校验范围

### 对象与字段

必需字段与 `contracts-v0.1.md` 三个JSON样例一致；未知字段拒收，避免拼写错误或未经协商扩展静默生效。源实现转换层先映射契约，再送校验器。未来模型调用元数据等扩展应正式升级字段集合，当前不能直接塞入任意字段。

ID字段使用ASCII字母/数字起始，后续允许字母、数字、下划线、点和连字符，总长1–128；禁止路径分隔符、空格与URL。源项目标识source_item_key作为非空外部文本保留，不用作文件路径。版本标签normalization_version等是非空UTF-8文本。字符串拒绝不成对Unicode代理项。

event.version必须为正整数；bool、float和数字字符串均不接受。entities仅支持name、code、type三字段；code允许null，type为index、stock、sector、commodity、currency、institution、country或other。markets必须非空、无重复，当前仅A、US、GLOBAL。

### 枚举

| 字段 | 接受值 |
| --- | --- |
| source_tier | primary、secondary |
| storage_policy | full_text、excerpt_metadata、metadata_only；full_text_fixture仅合成数据 |
| category | macro、policy、company、fund_flow、geopolitics、sentiment、calendar、other |
| extraction_method | fixture、rule、model、manual；fixture仅合成数据 |
| extraction_quality | validated_fixture、structurally_valid、needs_review、metadata_only；validated_fixture仅合成数据 |
| relation | supports、reports、contradicts |
| claim_key | fact_summary、title |
| validation_status | exact_quote_match |
| locator.field / offset_unit | normalized_text / unicode_code_point |

`structurally_valid`不表示语义被证据支持，`exact_quote_match`只表示片段与文本一致。校验器不会把任何记录升级为语义已验证，真实摘录的内容支持度仍需后续抽检。

### 时间

运行时间字段必须是完整UTC Z时间戳，支持1–6位小数秒；日期必须为有效YYYY-MM-DD。拒绝无时区、偏移形式运行时间、无效日期和大小写变体。parsed来源时区必须可解释为IANA名、UTC/GMT/Z或明确±HH:MM/±HHMM偏移；未解析状态允许保留未知原时区token，不猜测UTC。不能因来源是GMT而强制改写为IANA名称。

| time_parse_status | source_time_precision | 来源发布时间规则 |
| --- | --- | --- |
| parsed | minute / second | source_published_at非空，来源时区与原始时间文本非空；如有source_published_date，须与该时区下日期一致 |
| date_only | date / day | 必须有source_published_date；source_published_at必须null，不伪造午夜 |
| missing / invalid / timezone_missing / failed / ambiguous | unknown | source_published_at必须null，不推断UTC时刻 |

`date`与RSS解析接口一致，`day`是原契约用词兼容项。来源发布时间不能晚于fetched_at，出现时由调用方隔离并审查，不自动校正。

运行顺序：first_seen_at ≤ fetched_at ≤ persisted_at == raw.available_at；event.processed_at == event.available_at，且event/evidence.available_at均不早于raw.available_at。event和evidence允许分别提交，其先后不强制一致；报告仍须等所有引用对象可用。

本函数不与当前墙钟比较，不证明客户端声明的时间是真实提交时刻；历史fixture可描述未来日期。正式持久化层必须自己产生可信提交时间、记录时钟异常，不能直接信任外部bundle的available_at。

### 内容、引用与定位

content_sha256必须是normalized_text UTF-8字节的实际小写SHA256；content_ref必须精确为 `raw/<64位hash>.txt`，禁止绝对路径、父路径和替代文件名。该哈希不是HTTP原始响应字节哈希，若要保存原始响应，需要新字段与独立hash。

event.input_raw_item_ids、event.evidence_ids必须分别只引用本bundle的raw和evidence；evidence指向本event_version与raw。supersedes可为空或合法ID，但不得自引用；被替代记录是否存在及是否同事件，属于存储层的跨记录检查。

locator.start/end为真正整数、左闭右开、合法非空范围；按Python Unicode码点切片必须与quote逐字一致。CRLF保留，不隐式改换行；emoji按一个码点处理，不按UTF-16两个码元计数。

### HTTP链接

original_url和canonical_url仅接受有主机的http/https，拒绝凭证、反斜杠、空白/控制字符、裸引号、尖括号、无效端口、明显本地/私有IP、单标签及.local/.localhost/.internal主机、数字混淆主机。域名按IDNA结构检查，不进行DNS查询。

这是URL形状与明显危险目标过滤，**不是联网SSRF防护或来源许可认证**。域名仍可能解析至私网；真正HTTP调用层须独立限制DNS结果、重定向、响应大小及超时。正常包含百分号编码的URL路径不会因有编码而整体拒收，主机中的百分号则拒收。

## 3. metadata_only 的保守实现

本轮metadata_only仅支持“标题原样留存”的收窄模式：normalized_text等于raw.title；event.title及fact_summary均与该标题相同；完整标题作为quote；relation必须reports；extraction_quality必须metadata_only。

这允许系统保存“该来源出现此标题”的记录，不把未保留正文变成已确认政策或经济事实。URL及时间元数据继续保存。若未来需要允许日期、主体等更多元数据抽取，应定义显式字段白名单及支持规则后升级；当前不猜测哪些自由文本句子可由元数据证实。

full_text/excerpt_metadata仍只通过结构、一致性与片段检查，不判断正文许可是否合法，也不证明fact_summary被quote逻辑蕴含。真实来源必须先通过来源注册与独立审查。

## 4. 稳定错误码与集成

主要码包括：missing_or_unknown_fields、unsupported_schema、boolean_required、invalid_id、invalid_enum、invalid_unicode、utc_z_timestamp_required、invalid_timestamp、timestamp_order_invalid、invalid_event_version、single_bundle_reference_required、broken_reference、invalid_locator、quote_mismatch、normalization_mismatch、content_hash_mismatch、content_address_required、synthetic_not_allowed、mixed_synthetic_status、metadata_only_cannot_assert_body_facts。

存储专属immutable_id_conflict、重复逻辑版本、跨记录外键等不属于本函数。UTC错误使用utc_z_timestamp_required，不保留旧原型英文文案“UTC timestamps”；原测试应对齐稳定码。URL格式错误统一可能返回invalid_url，调用方不应依赖底层urlsplit异常文案。

主控后续在持久化入口调用公共校验器，再写文件/数据库；不能只在CLI校验而让内部导入绕过。当前工作包未修改offline.py、CLI、pyproject或数据库schema。

## 5. 验证证据与限制

可重复命令（PowerShell，使用实际已存在的解释器路径文件）：

```powershell
$contractPython = (Get-Content -LiteralPath './scripts/python-path.local.txt' -Raw).Trim()
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $contractPython -m unittest discover -s tests -p test_contracts.py -v
```

专属测试覆盖现有fixture兼容且不变、真实excerpt/full_text、合成隔离、缺字段/未知字段、枚举、严格整数、ID、UTC/日期、时间顺序、时区偏移、私网与畸形URL、内容哈希/寻址、引用、Unicode码点/CRLF、不成对代理项、metadata_only标题保护以及“不擅自升级语义”。实际测试结果由交接记录注明；不得将这些离线测试解释为真实来源接通或全部ENG-03/G1验收通过。

未实现：Prediction、MarketSnapshot、ReviewResult、ReportManifest校验，跨记录历史关系、实际截点查询、文件存在与磁盘哈希检查、数据库事务、网络、来源权限、完整语义支持、模型预算或真实价格评价。
