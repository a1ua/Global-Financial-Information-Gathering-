# 固定候选快照与重放契约 v0.1

日期2026-11-09，Batch09-C；输入为09-B候选清单，证据schema4/模型schema3不变。只验证和重放精确输入，不采集、不调用模型、不核实来源事实。

设计已由独立QA复核后冻结；实现验收结果见docs/verification/batch-09c.md与batch-09c-review.md。

## 1. 快照格式和纯校验

`validate_candidate_snapshot(snapshot)`位于contracts/candidate_snapshot.py，为纯函数，合法返回None，错误固定ValueError。严格顶层仅schema_version='evidence-candidate-snapshot/0.1'、input_manifest、input_manifest_sha256。

input_manifest严格沿用evidence-candidate-input/0.1字段：schema_version、selection_version='latest-available/0.1'、cutoff、max_candidates、include_synthetic、candidates。cutoff为现有instant UTC Z最多6位小数秒；cap严格int0..100，include恰bool，len(candidates)<=cap。

每candidate严格沿用09-B的16个描述字段，ID复用现有identifier规则，version正整数非bool，时间/哈希/固定content_ref严格校验。真实标签receipt非null且有效，effective为规范化微秒Z，等于receipt且不早于event_available_at；合成receipt恰null，effective不早于event_available_at。effective<=cutoff；include_synthetic=false禁止合成。按(有效时刻,event_id,event_version_id)严格升序，event_id和event_version_id分别唯一，evidence_id也唯一；raw_id/content_ref可共享。hash为canonical JSON（ensure_ascii=False/sort_keys=True/separators=(',',':')/allow_nan=False）UTF8 SHA256，必须等于整个input_manifest哈希。

共享raw_item_id时raw_payload_sha256必须相同，不允许自包含重放为同一不可变ID携带不同payload；每项仍需通过实际bundle/hash复核。

该纯校验不证明清单曾由可信planner生成、选择时完整/最优/latest或来源真实；攻击者可生成自洽清单/哈希，不能当签名。后续复核有意不重查排名或latest关系，避免人工回填替换已列输入。

## 2. 精确输入复核与加载

`load_candidate_snapshot_inputs(workspace,snapshot)`位于pipeline/candidate_snapshot.py，先纯校验，再mode=ro/query_only单BEGIN读事务，schema4/integrity/FK全库校验；仅按每条描述中的精确event_version_id、raw_item_id、evidence_id加载，严格JSON、身份、外键列和validate_bundle，再核对所列version/来源/时间/receipt/三个payload hash/文件地址与真实字节。

不要调用plan_evidence_candidates、_bundles或查询当前最大version；无关新event、旧时刻回填或无关坏payload不影响已列输入（但全库完整性/FK失败仍拒绝）。原真实receipt必须存在且与冻结字符串精确相等、合法不早于三对象available_at；合成忽略receipt且descriptor为null。按三对象/真实回执重新构建描述，必须与清单条目全部字段相同。所有对象/真实receipt必须在冻结cutoff内；raw文件内容需等于normalized_text UTF8并匹配hash，路径/所有祖先symlink/junction拒绝。沿用09-B实际路径和文件安全helper，错误固定码不回显文本/路径。

返回严格{verification,bundles}，bundles按清单顺序，每项{raw,event,evidence,receipt_committed_at}（只含既有对象及回执），verification严格字段schema_version='evidence-candidate-verification/0.1'、status='verified_inputs'、read_only=true、model_called=false、content_support_reviewed=false、selected_count、input_manifest_sha256、data_status、is_synthetic、mixed_test_data。空集合empty/false/false。`verify_candidate_snapshot(workspace,snapshot)`仅返回verification，丢弃正文，不输出bundles到CLI stdout。

SQLite快照不与raw文件系统原子；WAL可维护协调侧文件，不用immutable忽略WAL。不创建/迁移工作区/账本，不自动写审计。不保证抵抗特权重写历史、DB/raw恶意并发换文件或原文件长期可用。

## 3. 显式冻结/重放发布

API位于ops/candidate_snapshot.py：

- `freeze_candidate_snapshot(workspace,destination,cutoff,max_candidates=5,*,include_synthetic=False)`调用09-Bplanner恰一次，取其input_manifest/hash，构造快照并校验，全部有效后才创建新destination并写candidate-manifest.json。只保存清单，不复制正文或库。
- `verify_candidate_snapshot_file(workspace,manifest_path)`严格解析最多1MiB UTF8快照文件，重复键/非有限值/非法Unicode/链接拒绝，调用精确verify，返回verification；不创建文件。
- `replay_candidate_snapshot(workspace,manifest_path,destination)`读取快照一次，调用load_candidate_snapshot_inputs一次取得同一已验证快照的bundles，全部验证及容量检查后才创建新目录；写candidate-manifest.json（同一逻辑快照）和candidate-inputs.json，自包含输入不需再查latest或重新读声明。后者严格{schema_version:'evidence-candidate-replay/0.1',input_manifest_sha256,bundles}。文件为canonical UTF8 JSON，无额外字段。候选正文只写显式本地destination，不打印到stdout，不作为模型调用。
- `verify_candidate_replay(directory)`离线只读验证恰好这两个文件的清单/重放闭包；不要求源workspace存在，不查DB/文件ref指向的源路径。严格parse、快照纯校验、bundles顺序/长度、每bundle validate_bundle及身份/回执/描述全字段/hash一致；raw内normalized_text已自包含并匹配content_sha256，不能从content_ref读取其它文件。

共享纯函数`describe_candidate_bundle(bundle,receipt_committed_at)`位于contracts/candidate_snapshot.py，复用validate_bundle校验并按09-B算法返回16字段描述（可被两个模块复用），不访问路径/DB。合成receipt输入必须null；真实回执必须有效且不早于三对象；规范effective时间并计算三个payload hash，错误固定码。workspace加载和离线artifact校验均用它，避免两次读取产生不同证据。

manifest最大1MiB，candidate-inputs最大64MiB；是本批读写容量限制，超限拒绝，不更改原09-Bplanner容量。正常最多100项；本批不保证任意大full_text数据可重放。不加载凭证/环境，不联网。不把输入标题/正文当权限。

destination必须新目录，禁止与源workspace树、源manifest文件或其所在目录树重叠；检查全部祖先/文件symlink/junction及路径逃逸。路径检查本身不创建父目录；验证/容量失败不创建目标或父目录。验证完成后mkdir(parents=True)并以exist_ok=False独占声明目标，各文件open('x')、flush/fsync；不覆盖、不删除/自动修复现存目录。中断可能留下半成品，verify明确拒绝；这是新目录独占发布，不称多文件整体原子或外部可信持久锚点。不自动清理失败目录。新目录创建竞争可安全失败，不承诺恶意本机换链防护。

freeze返回schema_version='evidence-candidate-artifact/0.1'、status='frozen'、destination（绝对路径）、selected_count、input_manifest_sha256、model_called=false；replay同schema、status='replayed'，另加replay_sha256（candidate-inputs.json实际字节hash）。verify_replay返回schema_version='evidence-candidate-replay-verification/0.1'、status='verified_replay'、read_only=true、model_called=false、content_support_reviewed=false、selected_count、input_manifest_sha256、replay_sha256、data_status/is_synthetic/mixed_test_data。不要把已验证输入/重放称研究或生产验收。

## 4. CLI与验收

命令：`freeze-evidence-candidates --workspace ... --cutoff ... --max-candidates 5 [--include-synthetic] --destination NEW`；`verify-evidence-candidates --workspace ... --manifest ...`；`replay-evidence-candidates --workspace ... --manifest ... --destination NEW`；`verify-candidate-replay --replay ...`。成功含空集合exit0，格式/hash/路径/闭包/发布错误exit1，固定码脱敏；摘要可输出显式目标路径但不得title/quote/URL/正文。无live/provider/force/overwrite参数。不改09-A mock-run或09-B只读plan语义。

验证：strict字段/类型/bool/重复/顺序/hash/日期/范围；旧清单在新版本/旧时刻回填后仍复核原版本（planner可改）；无关坏payload不污染所列闭包；坏所列对象/真实回执/文件/哈希拒绝；单事务/WAL一致性；明文仅显式replay文件；输出目录/角色/链接/容量/半成品/竞争；离线原库不可用仍验证自包含重放；无模型/密钥/网络/预算或源文件写入。既有35条真实归档仅验证此前标题元数据，不刷新来源或认证事实。NLP-01整体、NLP-02和真实模型/账单/可信高水位仍未完成。
