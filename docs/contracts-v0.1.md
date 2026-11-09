# 数据契约 v0.1：证据到简报的首条纵向链路

状态：设计基线，尚未实现 schema 或数据迁移。适用范围：单机、单用户、A 股优先的日频研究系统。本文约束代码接口与回归行为，不表示来源已接入或未来评价能力已实现。

## 1. 实施边界

MVP 必需：RawItem、EventVersion、Evidence、ReportManifest、时间截点规则、稳定标识、不可变引用、输入清单哈希、失败原因。首条纵向链路可以使用明确标注的合成 fixture 验证；合成样本不计入真实来源覆盖或研究效果。

后置契约：Prediction、MarketSnapshot、ReviewResult、真实预算预留账本。本文提前固定其交界字段，防止首版设计阻碍扩展；不要求简报 MVP 实现行情或评分。

所有 JSON 示例均为合成数据，URL 使用保留示例域名。示例哈希为结构占位值，必须由真实序列化内容计算后才能进入运行系统。

## 2. 公共字段与时间规范

- schema_version：该对象的数据结构版本，不等于业务记录版本。
- 稳定逻辑 ID 与版本 ID 分离。event_id 标识同一事件，event_version_id 标识一次不可变事实快照；正文修订产生新的 raw_item_id。
- 存储时间使用带 Z 的 UTC ISO 8601 字符串，比较前解析为时间，不能依靠任意格式字符串排序。展示时区使用 IANA 标识，例如 Asia/Shanghai。
- source_published_at 为来源声称的发布时间，可为 null；source_time_text、source_timezone、source_time_precision、time_parse_status 保留原始表达与解析质量。只有日期时，source_published_at 留空，另存 source_published_date；不补出午夜作为精确时点。
- first_seen_at 是系统第一次观察到该内容版本的时刻；fetched_at 为一次成功获取结束时刻；persisted_at 为持久化完成时刻；processed_at 为结构化输出校验并提交时刻。原始内容通常满足 first_seen_at ≤ fetched_at ≤ persisted_at，结构化对象满足 processed_at ≥ 输入的可用时刻。
- available_at 是对象可作为系统输入的最早提交时刻。RawItem 使用持久化完成时间；EventVersion、Evidence 使用各自通过校验并提交的时间。若不能在同一事务提交，则报告要求全部输入分别已提交。
- 机器时钟异常、未来时间或无法解释的先后顺序进入 quarantine，原因码 timestamp_order_invalid；不自动改写时间掩盖异常。系统记录时钟不能证明外部来源的真实发布时间。
- 金额、价格、收益在未来数值协议中采用固定精度十进制字符串；不把 null、缺失、不可用转换成数值 0。
- 枚举未知值需要显式 unknown/null 或契约升级，不能静默创造新枚举。ID 不包含 URL、标题等可变化业务字段。

## 3. MVP 对象及示例

### 3.1 RawItem：一次来源内容版本

同一 URL 的标题或正文发生实质修订时生成新版本；重复抓取不重复创建内容版本，抓取尝试记录在独立运行日志。内容身份由 source_id、规范化来源项目标识和内容哈希组合确定，不能仅用 URL 去重。

```json
{
  "schema_version": "raw-item/0.1",
  "raw_item_id": "raw_demo_001_v1",
  "source_id": "fixture_official",
  "source_config_version": "sources-demo-1",
  "source_item_key": "announcement-demo-001",
  "original_url": "https://example.com/announcements/demo-001",
  "canonical_url": "https://example.com/announcements/demo-001",
  "source_tier": "primary",
  "title": "合成示例公告",
  "source_time_text": "2026-11-09 08:00",
  "source_timezone": "Asia/Shanghai",
  "source_time_precision": "minute",
  "time_parse_status": "parsed",
  "source_published_at": "2026-11-09T00:00:00Z",
  "source_published_date": "2026-11-09",
  "first_seen_at": "2026-11-09T00:05:00Z",
  "fetched_at": "2026-11-09T00:05:02Z",
  "persisted_at": "2026-11-09T00:05:03Z",
  "available_at": "2026-11-09T00:05:03Z",
  "storage_policy": "full_text_fixture",
  "content_ref": "fixtures/raw/demo-001-v1.json",
  "content_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "normalized_text": "示例公告：机构发布产业支持文件。",
  "normalization_version": "text-normalize/0.1",
  "supersedes_raw_item_id": null,
  "is_synthetic": true
}
```

真实来源的 storage_policy 由来源条件确定，可为 full_text、excerpt_metadata、metadata_only。metadata_only 不允许抽取其未保存且不可验证的正文事实；简报应显示证据范围。规范化不得删除数字、否定词或改变事实含义；原始字节与规范化文本的哈希分别管理。

### 3.2 EventVersion：固定事实快照

一个逻辑事件可以有多个不可变版本。事实修订使用 supersedes，后续新进展保留关联但不必强行替代原事件。来源评级只表明出处类型，不代表事实绝对正确。

```json
{
  "schema_version": "event-version/0.1",
  "event_id": "event_demo_001",
  "event_version_id": "event_demo_001_v1",
  "version": 1,
  "title": "合成机构发布支持文件",
  "fact_summary": "机构发布产业支持文件。",
  "category": "policy",
  "markets": ["A"],
  "entities": [],
  "evidence_ids": ["evidence_demo_001"],
  "input_raw_item_ids": ["raw_demo_001_v1"],
  "extraction_method": "fixture",
  "extractor_version": "fixture-extractor/0.1",
  "extraction_quality": "validated_fixture",
  "processed_at": "2026-11-09T00:06:00Z",
  "available_at": "2026-11-09T00:06:00Z",
  "supersedes_event_version_id": null,
  "is_synthetic": true
}
```

MVP 类别初始集合为 macro、policy、company、fund_flow、geopolitics、sentiment、calendar、other。fact_summary 只表达有证据的事实；影响解释另存，不混入事实字段。模型生成时，保存 model_id、prompt_version、参数、输入清单哈希、原始输出与校验结果；fixture 不伪装成模型结果。

### 3.3 Evidence：具体证据片段

片段定位基于固定 normalization_version 的 normalized_text，offset_unit 明确为 Unicode code point，区间左闭右开。不能将 JavaScript UTF-16 索引直接当成码点索引；必须转换或使用一致文本库。证据同时保存 quote，运行时校验切片与 quote 一致。

```json
{
  "schema_version": "evidence/0.1",
  "evidence_id": "evidence_demo_001",
  "event_version_id": "event_demo_001_v1",
  "raw_item_id": "raw_demo_001_v1",
  "relation": "supports",
  "claim_key": "fact_summary",
  "normalization_version": "text-normalize/0.1",
  "locator": {
    "field": "normalized_text",
    "offset_unit": "unicode_code_point",
    "start": 0,
    "end": 16
  },
  "quote": "示例公告：机构发布产业支持文件。",
  "validation_status": "exact_quote_match",
  "available_at": "2026-11-09T00:06:00Z",
  "is_synthetic": true
}
```

relation 初始集合为 supports、reports、contradicts。reports 表示来源在转述，不自动升级为一手证据；contradicts 应保留并在简报中呈现冲突。exact_quote_match 只说明片段定位正确，不代表片段足以支持整个结论，仍需人工支持度抽检。

### 3.4 ReportManifest：本次报告输入与发布清单

报告必须冻结精确输入版本，不能在重渲染时查询最新事件、最新聚类或最新证据替代。manifest 中的时间字段不得参与内容哈希以外的随意过滤；哈希算法由明确的 canonical_json_version 约束。

```json
{
  "schema_version": "report-manifest/0.1",
  "report_id": "brief_A_pre_20261109_v1",
  "run_id": "run_demo_001",
  "report_type": "A_pre",
  "market_session_date": "2026-11-09",
  "display_timezone": "Asia/Shanghai",
  "information_cutoff": "2026-11-09T00:30:00Z",
  "generated_at": "2026-11-09T00:30:20Z",
  "published_at": "2026-11-09T00:30:21Z",
  "status": "degraded",
  "reason_codes": ["synthetic_fixture", "market_data_unavailable"],
  "input_manifest": {
    "raw_item_ids": ["raw_demo_001_v1"],
    "event_version_ids": ["event_demo_001_v1"],
    "evidence_ids": ["evidence_demo_001"],
    "prediction_ids": [],
    "market_snapshot_id": null
  },
  "source_config_version": "sources-demo-1",
  "rules_version": "rules/0.1",
  "template_version": "brief/0.1",
  "renderer_version": "renderer/0.1",
  "canonical_json_version": "canonical-json/0.1",
  "input_manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "market_data_as_of": null,
  "citation_check": "passed",
  "content_support_check": "fixture_reviewed",
  "artifact_refs": ["out/briefs/brief_A_pre_20261109_v1.html"],
  "supersedes_report_id": null,
  "is_synthetic": true
}
```

示例中 published_at 是报告发布时间，与 RawItem.source_published_at 不同。未成功发布的尝试记录在 job_runs，不生成貌似成功的发布manifest；失败尝试与最后成功报告分别展示。补版使用新report_id与supersedes_report_id，旧文件保留。

## 4. 信息截点查询语义

面向“当时系统知道什么”的正式报告，应满足以下条件：

1. 截点 T 在运行开始时固定，不随模型耗时滚动。
2. 对每条事实，RawItem.available_at、Evidence.available_at、EventVersion.available_at 均 ≤ T，且引用关系完整、对象校验通过。
3. 若同一event_id存在多个版本，只选择在T之前已经可用的版本；supersedes本身也必须在T之前可用。不能用后来新增的撤回或修订关系回写旧报告。
4. source_published_at 仅用于来源时间描述与排序辅助，不代替available_at作为入选条件。晚采集的旧新闻只进入后续报告，并标注来源发布与系统发现时间差。
5. 当证据截点已到但结构化处理尚未完成，严格模式暂不纳入该EventVersion。若采用“截止时已采集、稍后处理”模式，必须另建mode和独立说明；MVP仅启用严格模式。
6. 报告引用的未来日历事件可以在T之后发生，但该日历版本本身必须在T之前已可用；未来发生时间不等于未来已知信息。
7. 历史补跑不能冒充原时点报告。使用 replay_as_of 与实际 generated_at，标记 retrospective；重放只使用固定输入清单，不用于证明模型前瞻有效性。

## 5. 不可变关系与允许更新的状态

不可变对象：RawItem内容版本、EventVersion、Evidence、已提交Prediction、MarketSnapshot、ReviewResult、已发布ReportManifest。被引用文件的内容必须与其哈希一致。允许将相同字节去重保存，但不能让路径被覆盖为其他内容。

版本化对象：来源配置、规则、提示词、模型调用参数、交易日历、证券主数据、评价协议、聚类成员快照。历史输入应绑定版本或清单，不能仅绑定逻辑ID。

可变运行状态：抓取游标、任务队列状态、重试计数、健康检查状态、预算预留状态。状态变化记录日志；推进游标必须晚于条目和运行检查点的成功持久化。应用应保证失败重跑幂等，不能通过回退整个历史库实现恢复。

MVP允许不启用语义聚类；若启用，report/prediction必须引用固定cluster_version_id及成员版本清单。后续新增来源、修正分类或重组事件簇不得改变旧输入。

## 6. 后置：Prediction冻结协议

最小字段：prediction_id、event_version_ids、evidence_ids、cluster_version_id（可空）、model_call_id、created_at、committed_at、target_instrument_id、benchmark_instrument_id、direction、direction_basis、judgment_confidence、reasoning、counter_evidence、abstention_reason、evaluation_protocol_id、calendar_snapshot_id、rules_version、input_manifest_sha256、supersedes_prediction_id。

direction 为 positive、negative、neutral、mixed、uncertain；direction_basis 为 absolute_return 或 benchmark_relative。模型自评置信度使用低/中/高，不能显示为已校准概率。uncertain需有弃权原因；中性与混合不进入普通正负命中率。

评价协议在判断提交时固定，至少包含起点规则、窗口长度、目标与基准、收益类型、币种、价格调整口径、正负阈值、缺失/公司行动/重叠事件处理、评分公式版本。模型调用开始时间不能作为评价起点；以校验并提交成功的committed_at为准。

首版主协议采用开盘严格晚于committed_at的下一交易会话开盘，至该会话或第5个会话收盘。首段为开盘至收盘，其后为相邻收盘收益；AR逐段相减后求和得到CAR。持有期复合收益差单独命名。开盘缺失记不可用，收盘协议必须另设ID且分开汇总。

## 7. 后置：MarketSnapshot与ReviewResult

MarketSnapshot字段：market_snapshot_id、available_at、provider_id、instrument_master_version、calendar_snapshot_id、currency、price_return_type、adjustment_method、bar_version_ids、requested_session_ids、missing_session_ids、quality_flags、manifest_sha256。OHLC保留供应商标识、获取时点、会话日期及版本；供应商修订生成新bar版本和新快照，不覆盖旧引用。

ReviewResult字段：review_result_id、prediction_id、evaluation_protocol_id、algorithm_version、market_snapshot_id、input_manifest_sha256、evaluation_kind、calculated_at、state、reason_codes、start_session_id、end_session_id、target_return、benchmark_return、car、direction_hit、overlap_event_family_ids、supersedes_review_result_id。

evaluation_kind为first_evaluation或revision_recalculation；旧首次评价不被新重算替换。state为pending、eligible、evaluated、unavailable、excluded；计算结果字段只在有定义时填值。未来状态变化用追加评价记录表达，当前状态视图是派生查询。

结果幂等键包含prediction_id、evaluation_protocol_id、algorithm_version、market_snapshot_id与input_manifest_sha256。同输入重复计算应获得相同数值；不能仅以日期区间判断可复现。

汇总明确分母：total_predictions、directional_predictions、matured_predictions、complete_predictions、abstained_predictions、independent_event_families。一个事件的多个标的和窗口分别保留结果，独立事件数不随之增加。评价币种、收益类型和协议不同的结果分别统计。

## 8. 十个固定回归用例

下列为必须落地的行为用例，本文不宣称测试已运行。MVP先实现R01–R03、R09–R10及证据切片校验；其余在对应后置功能开放前完成。

| ID | 输入/故障 | 预期行为 | 阶段 |
| --- | --- | --- | --- |
| R01 | 来源08:00发布，09:00才获取入库，报告截点08:30 | 不进入08:30报告；下一报告显示来源时间与系统发现时间 | MVP |
| R02 | 08:00原文在08:10已采集，10:00正文修订 | 08:30报告只引用已可用v1；10:00之后可新增v2，v1内容不变 | MVP |
| R03 | 昨日事件已提交，今日新增证据或聚类成员 | 昨日报告的输入清单、引用文本与哈希不变化；新报告使用新快照 | MVP，聚类部分后置 |
| R04 | 判断09:29开始生成、09:31校验提交 | 不允许以当日09:30开盘评分；选择提交后下一交易会话 | 评价开放前 |
| R05 | 分别构造未成熟窗口、供应商延迟、永久缺失、停牌 | pending与unavailable/排除原因可区分；均不补0或误判失败命中 | 评价开放前 |
| R06 | 已评分会话的供应商价格后续修订 | first_evaluation保持不变；revision_recalculation使用新快照与结果ID | 评价开放前 |
| R07 | 同事件产生5个标的×2个窗口 | 保存10个结果，但独立事件家族数为1；汇总披露分母 | 汇总开放前 |
| R08 | 两任务同时请求超过剩余额度的模型预算 | 原子预留总额不超限，至少一个请求被降级/拒绝；失败可释放或结算 | 并发真实调用前 |
| R09 | 原始文件落档后崩溃，条目/游标未完整提交 | 重跑不漏项、不产生重复内容版本；游标仅在成功提交后前进 | MVP |
| R10 | 数据库副本恢复成功，但manifest引用的一份证据文件缺失或哈希不同 | 备份恢复验证失败并列明对象；不能宣称整体可恢复 | MVP交付前 |

额外边界由对应任务补充：日期型发布时间、Unicode代理对、来源重复时间戳、URL正文修订、日历假期/DST/提前收市、外部正文中的指令、同作业锁冲突、报告临时文件发布失败。它们不能用上述十例的通过结果替代。

## 9. 契约变更与交接规则

共享契约与迁移由集成负责人单点整合。开发Agent可以提出字段变更，但不得在未更新本文与fixture之前擅自改变跨模块字段。兼容新增可提升次版本；字段重命名、含义变更或枚举破坏变更需新主版本和迁移说明。

每个工作包交付：修改范围、契约版本、fixture、运行命令、实际测试结果、已知缺口。使用合成fixture、离线运行、未连接真实模型/来源时必须明确标注；未执行测试不得写成通过。

## 10. 批次05预算节点补充契约（离线 mock 范围）

后续版本说明：本节保留 Batch05 历史基线。Batch06 币种/传输契约见 `contracts/deepseek-budget-v0.2.md`；Batch07 账本 schema3、固定入口身份与路径绑定以及备份0.2契约见 `contracts/ledger-binding-v0.1.md`。身份绑定代码不代表真实调用、人工对账或同身份回退防护已验收。

Batch08对账/恢复前置契约见`contracts/reconciliation-v0.1.md`：仅只读声明比对与快照预检，不修改schema、调用状态或预算；外部声明未认证，预检结果不授予生产切换许可。不可变审计与真实结算仍为后续工作包。

Batch08-C本地追加审计见`contracts/audit-journal-v0.1.md`：独立审计库schema1、显式写入观察、链校验及幂等；SQL保护不等于外部不可回退存储。可信高水位、真实结算和生产切换仍未实现。

本节由主控整合，限定 `market_intel.llm` 的独立账本 schema 1，不改变证据库 schema 4 或既有对象格式。示例见 `config/llm.example.json`，合成输入输出及反例见 `tests/test_llm.py`。这不是云端供应商或 R08 完整上线验收。

- 预算池以应用明确配置的单一 `state_path` 为范围，多个模型共享同账本额度；它不是跨任意文件、账户或机器的全局费用控制。调用方不能新建、删除、切换或回滚账本规避额度。生产入口尚未实现固定账本绑定，真实 provider 保持关闭。
- 每次尝试开始时读取带零 UTC 偏移的时钟，以 UTC 自然日归账，不使用北京时间交易日或滚动24小时。午夜前预留、午夜后完成仍结算原日；重试重新预留并归新尝试的 UTC 日。时钟回退拒绝，不自动修正历史时间；时间先解析再比较。
- token 上界及单次限制为正整数；mock 输入上界采用整个固定请求的 UTF-8 字节数，不能作为实际供应商 tokenizer 已验证上界。金额及费率采用整数 microUSD、microUSD/token，1 USD=1,000,000 microUSD；实际小数费率必须另行精度设计或保守向上取整，禁止向下取整使预算低估。
- 每次外部尝试前以事务原子预留输入上界及最大输出额，同日全部成功、失败和 pending 占用计入上限。同一日首次冻结的限额不可被另一个客户端静默改变。额度不足时不能进入 transport。
- 无可信完整 usage、超时、崩溃或无效输出保留全额预留。可信正整数 usage 只能在各自预留内减记；所有金额仍为配置费率估算，不是供应商账单。对外查询必须披露估算依据，区分 usage 已报告与仍按预留占用的部分，不能把未知支出写成零。
- pending 重启后保留；当前不提供未经供应商对账的自动释放或人工结算入口。人工对账、终态修复及独立账本恢复是后续真实调用启用的前置任务，未通过前不宣称 R08 完整闭环或生产可恢复。
- 仅超时、明确瞬时传输错误及无效模型输出允许有限重试，每次独立预留；模型即使相同请求也不保证同样输出，因此结构失败可重试，但必须有次数/额度上限并记录结果。未知编程异常停止重试。数据库 busy/locked 或其他账本错误转换为固定错误码，不能泄露底层异常文本或当成功返回。
- 缓存键必须覆盖输入内容、provider/model、完整系统提示词、提示词/规则/输出模式及 schema 版本、schema 内容、参数和影响输出的限制。命中前检查当前输入限额；命中时验证请求归属、原始输出哈希和结构，命中不新增费用。缓存无需替代系统证据可用时点或报告截点规则。
- 原始成功响应、调用版本与安全参数元数据留档；失败响应正文及异常原文不留档。凭证不得放入任何请求/响应文本或参数；字段名过滤不是任意文本秘密检测。启用真实供应商前须重新验收传输超时、token/费用、输出限制、预算绑定和恢复。
