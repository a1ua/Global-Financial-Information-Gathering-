# 证据库候选输入清单 v0.1（已冻结）

2026-11-09，Batch09-B。只读既存证据库，不采集、不调用模型、不改NLP02/报告/账本。支持现有一raw/一event/一evidence形状；不是重要性排序、全文支持评测或真实模型验收。

QA-B09B独立设计复核通过，补充合成receipt忽略和历史稳定性条件后冻结；实现另行验收。

术语补充：本文“真实”及结果real仅指is_synthetic=false数据库声明，不认证来源或事实；“冻结/设计复核通过”仅为设计状态。version复用bundle契约的正整数（非bool）并按整数比较；时刻复用instant的UTC Z及最多6位小数秒，均解析为时刻比较。由于合法真实receipt不早于全部对象available_at，真实effective数值等于receipt；缺receipt分支仅适用于真实标签。历史稳定性的文字均以第3节条件限定为准。

## 1. API与快照

`plan_evidence_candidates(workspace, cutoff, max_candidates=5, *, include_synthetic=False)`。cutoff必须有效UTC Z，max_candidates为0..100严格int，include_synthetic恰bool，bool不充当整数。workspace及全部祖先、market.db、引用raw文件和中间目录拒绝symlink/junction；固定原始引用raw/<content_sha256>.txt，不允许任意路径/逃逸。

只接受已存在schema4 market.db。mode=ro/query_only、单个BEGIN读事务，事务内校验user_version、integrity_check/foreign_key_check并读取raw_items/event_versions/evidence/availability_receipts；不使用会创建/迁移schema的store.connect。缺库/旧库/坏库拒绝固定ValueError，不建目录。SQLite WAL可能维护-wal/-shm协调侧文件，read_only仅指无SQL业务/schema写，不保证目录零副作用；不用immutable忽略WAL。

使用严格JSON（重复键/非有限值/非法Unicode拒绝），所有event版本都先解析、检查数据库id与payload身份、raw/evidence引用及evidence外键列与payload一致，并复用validate_bundle验证现有结构/时间/quote/内容hash。支持全库同时有真实/合成记录，但每bundle内部标签必须一致；不同event_version_id不能重复(event_id,version)。不按cap/时间提前截断来跳过非法bundle，包括未来或被scope排除者。孤立raw/evidence不在候选引用闭包时无需加载验证其正文；外键完整性仍全库检查。

## 2. scope、回执与版本

默认只选is_synthetic=false的真实标签记录；include_synthetic=True允许两类，供显式离线fixture验证。标签是数据库声明，不因false就认证来源。合成测试中构造的false标签仅用于回执故障验证，不计真实来源联网验收。

逐event：先按scope排除合成；真实event缺receipt时计missing_receipt，不作为候选（可能处于提交后尚未记录回执窗口，不当作已可用）。存在receipt必须有效UTC Z且不早于raw/event/evidence全部available_at的最大时刻；非法/过早回执拒绝整次计划。合成不要求receipt，有效可用时刻取三对象available_at最大值；真实取其与receipt.committed_at最大值。source_published_at不是可用时间，不参与候选排序或截点放行。

合成event即使在receipt表存在行也忽略该行，不作为系统可用凭证；其manifest.receipt_committed_at始终null。上述receipt格式/顺序规则只适用于真实标签事件，外键检查仍全库执行。

effective_available_at<=cutoff才可用。每个event_id从可用版本中取version最大者；较高版本未来/缺receipt时允许选择较低可用版本，不查询“当前最新”覆盖旧截点。选定各event最新可用版本后，验证这些全部候选的raw文件真实字节哈希、与normalized_text UTF8字节相等和固定content_ref，再按effective_available_at升序、event_id升序、event_version_id升序取前cap。cap0仍验证所有上述最新可用候选文件。未来、缺回执或scope排除版本无需读取原始文件；结构仍验证。文件路径拒绝链接；DB快照不与文件系统原子，不能抵抗恶意并发换文件或被特权修改历史。

## 3. 结果与计数

严格返回：schema_version='evidence-candidate-plan/0.1'、status='planned'、read_only=true、model_called=false、content_support_reviewed=false、data_status='empty|real|synthetic|mixed'、is_synthetic（所选非空且全部synthetic才true）、mixed_test_data（所选两类都有才true）、event_versions_count、excluded_synthetic_count、missing_receipt_count、after_cutoff_count、eligible_versions_count、superseded_count、eligible_events_count、limited_count、selected_count、input_manifest、input_manifest_sha256。

按上述scope→缺receipt→after_cutoff→eligible优先级计数，互不重复：event_versions_count=excluded_synthetic_count+missing_receipt_count+after_cutoff_count+eligible_versions_count；eligible_versions_count=superseded_count+eligible_events_count；eligible_events_count=limited_count+selected_count。data_status只按所选，不用真实标签推断空计划real。

input_manifest严格字段schema_version='evidence-candidate-input/0.1'、selection_version='latest-available/0.1'、cutoff（保留原输入）、max_candidates、include_synthetic、candidates。candidates按选择顺序，每项严格：event_id、event_version_id、version、event_available_at（event原字段）、receipt_committed_at（真实原回执/合成为null）、effective_available_at（规范化UTC微秒Z）、raw_item_id、evidence_id、source_id、source_config_version、content_ref、content_sha256、raw_payload_sha256、event_payload_sha256、evidence_payload_sha256、is_synthetic。

所有payload hash使用canonical JSON：ensure_ascii=False、sort_keys=True、separators=(',',':')、allow_nan=False，UTF8 SHA256。input_manifest_sha256为canonical整个input_manifest的SHA256；不包含当前时间、全库计数或最新关系。未来追加、较新版本/晚回执不应悄悄改变已固定旧截点的input_manifest（全库诊断计数可变化）；哈希是本次观察完整性引用，不是签名、防回退或事实真实性证明。

历史稳定性限定：新增记录的effective_available_at晚于旧cutoff且既有引用内容未改时，追加及较新版本/晚回执不会改变旧manifest。人工回填有效时间早于旧cutoff的记录（尤其include_synthetic测试数据）、回写历史或特权篡改可改变结果，不在稳定保证内；本批不禁止合成回填，不宣称任意版本追加永远不改变计划。

不输出title、fact_summary、quote、normalized_text、URL或凭证/本地绝对路径。它是未来抽取的版本化输入清单，不承诺重要性或语义正确。API/CLI不写manifest文件，不调用模型、不自动写审计、不更改任何模型预算。

## 4. CLI与验收

`evidence-candidate-plan --workspace data/live --cutoff ... --max-candidates 5 [--include-synthetic]`只读stdout JSON，成功包括空/受限计划exit0，结构/哈希/receipt/路径错误exit1，固定错误码不回显底层异常或正文；不读DEEPSEEK_API_KEY、不联网。没有--live/--model/--force参数，不转入candidate-mock-run。

验收：缺库/旧schema/坏JSON/身份/外键拒绝；cap0/上限/布尔；缺receipt排除、receipt晚于cutoff、无时区/过早拒绝、发布时间不放行；全部对象可用时间与小数秒；最新可用版本、同版本冲突、未来新版本不污染旧截点；文件损坏/缺失/逃逸/symlink/junction在限量前拒绝；合成默认排除与显式混合标签；单读事务与WAL并发新提交不污染快照；manifest hash可复算，追加后旧清单稳定；静态非WAL库与文件字节不变、无模型/密钥/网络/预算写入。真实运行只验证此前已保存Fed/NBS标题元数据，不代表刷新来源、正文事实、七交易日或NLP02通过。
