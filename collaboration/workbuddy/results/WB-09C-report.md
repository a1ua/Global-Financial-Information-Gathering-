# WB-09C 结果报告：固定候选快照与重放设计审查

- task_id: WB-09C
- status: completed（取得子任务实际完整返回正文，非 blocked）
- execution_mode: 恰一次普通同步阻塞只读子任务（run_in_background=false，未设 team/name）；契约全文内嵌于子任务提示；子任务被明确禁止读写文件、调用工具、联网或运行测试
- subagent_used: true
- raw_result_recovered: true
- tests_run: 0
- finalized: true

## 读取范围（严格按任务单）

1. collaboration/workbuddy/WB-09C-task.md（本任务单）
2. docs/contracts/candidate-snapshot-v0.1.md（固定契约全文）

未读取任何其它会话、代码、配置、密钥或运行数据；未运行命令、网络或测试；未改动、重启或停止任何旧 WB 任务。父端仅写本文件与 WB-09C-results.json。

## 实际工具回执

- 调用方式：Agent 工具恰一次；subagent_type=general-purpose；run_in_background=false；未设 team/name。
- 契约全文已内嵌于子任务提示；子任务被要求不读写任何文件、不调用任何工具、不联网、不运行测试，仅依据内嵌全文作文字层面设计审查，最多三点。
- 工具实际返回：完整中文审查正文（三点），返回末尾附带的实际回执行为 `[Agent ID: agent-62be9dab-10fa-464c-9ee1-cf78ebbf3cc2]`。
- 工具返回未提供任何时间戳，故不记录、不编造时间。
- 无同步能力缺失、无正文残缺，因此未触发 blocked；未轮询、未重试、未代写。

## 子任务实际完整返回（逐字保留）

**一、是否真正固定精确版本而非查询 latest（selection_version 与精确 ID 加载的内在张力与边界）**

**【契约中确有明文依据的部分】**
- 契约把 input_manifest 的 `selection_version` 固定为字面量 `'latest-available/0.1'`，作为 `evidence-candidate-input/0.1` 的沿用字段由纯校验严格校验；快照顶层严格仅三字段，`input_manifest_sha256` 为整个 input_manifest 的 canonical JSON UTF8 SHA256。
- 加载环节明文规定「仅按每条描述中的精确 event_version_id、raw_item_id、evidence_id 加载」，并明文「不要调用 plan_evidence_candidates、_bundles 或查询当前最大 version」；第 1 节亦明文「后续复核有意不重查排名或 latest 关系，避免人工回填替换已列输入」。
- 重放环节明文「自包含输入不需再查 latest 或重新读声明」；freeze 仅「调用 09-B planner 恰一次」生成清单，之后不再触发 planner；契约另以验收项文字写明「旧清单在新版本/旧时刻回填后仍复核原版本（planner 可改）」——此处仅取其为契约文字依据，不代表任何已执行结论。
- 第 1 节自认「该纯校验不证明清单曾由可信 planner 生成、选择时完整/最优/latest 或来源真实」。因此「复核与重放阶段按清单精确版本 ID 加载、不查 latest/最大 version」在契约内有一致且反复出现的明文，且其适用范围被契约自身限定。

**【契约未覆盖 / 仍属风险或夸大嫌疑的部分】**
- 语义张力未被消除：字段名 `selection_version` 取值 `'latest-available/0.1'` 字面指向「最新可用」，契约却把它当作不可变常量校验；契约未定义该字符串与 planner 选择语义、版本演进之间的对应关系，也未说明为何「latest-available」可承载「固定精确版本」。免责（「不证明…latest」）只是否定式声明，未化解标签与用途的字面矛盾，仍存在被读成「清单即当前 latest」的误读空间。
- 「固定精确版本」仅覆盖复核/重放阶段，不覆盖清单产生阶段。契约明文 freeze 由「09-B planner 恰一次」产出，并明文「不证明选择时完整/最优/latest 或来源真实」「攻击者可生成自洽清单/哈希」；planner 生成时是否查询 latest/最大 version 契约未约束，仅以「不改 09-A mock-run 或 09-B 只读 plan 语义」带过。不能把「重放不查 latest」外推为「清单生成时即锁定权威精确版本」或「选择最优」。
- 「不查询当前最大 version」只在第 2 节加载处明文；而加载仍以「mode=ro/query_only 单 BEGIN 读事务，schema4/integrity/FK 全库校验」为前提，并明文「全库完整性/FK 失败仍拒绝」「无关新 event、旧时刻回填或无关坏 payload 不影响已列输入」。即精确加载并不脱离当前库状态：契约未覆盖库整体完整性变化时对「已列精确版本」的连带影响边界，也未把「精确」证明为该 version 在数据源中的正确性，仅证明「按三对象/真实回执重新构建描述，必须与清单条目全部字段相同」。
- `event_id`/`event_version_id` 分别唯一、按 (有效时刻, event_id, event_version_id) 严格升序等均为纯校验的静态自洽规则，不构成「该版本即权威精确版本」的承诺；契约本身未作此宣称，若作此解读即属夸大。

**二、重放是否复用同一验证输入且离线闭包完整**

**【契约中确有明文依据的部分】**
- 契约明文 replay「读取快照一次，调用 load_candidate_snapshot_inputs 一次取得同一已验证快照的 bundles」，「全部验证及容量检查后才创建新目录」；写出 `candidate-manifest.json`（「同一逻辑快照」）与 `candidate-inputs.json`，后者严格仅 `{schema_version:'evidence-candidate-replay/0.1', input_manifest_sha256, bundles}`，为 canonical UTF8 JSON、无额外字段。
- 离线侧明文 `verify_candidate_replay(directory)`「离线只读验证恰好这两个文件的清单/重放闭包；不要求源 workspace 存在，不查 DB/文件 ref 指向的源路径」，并「严格 parse、快照纯校验、bundles 顺序/长度、每 bundle validate_bundle 及身份/回执/描述全字段/hash 一致；raw 内 normalized_text 已自包含并匹配 content_sha256，不能从 content_ref 读取其它文件」。第 4 节亦以验收项文字列有「离线原库不可用仍验证自包含重放」「明文仅显式 replay 文件」，此处同样仅作文字依据，不代表已执行结论。
- 「复用同一验证输入/同一描述」有明文支撑：共享纯函数 `describe_candidate_bundle(bundle, receipt_committed_at)`「不访问路径/DB」，「workspace 加载和离线 artifact 校验均用它，避免两次读取产生不同证据」；且 replay「候选正文只写显式本地 destination，不打印到 stdout，不作为模型调用」。
- 故「离线校验不依赖源库/源路径、闭包由两文件与内嵌 normalized_text 自足、加载与离线校验共用同一描述算法」在契约内自洽成立。

**【契约未覆盖 / 仍属风险或夸大嫌疑的部分】**
- 「同一」的口径需收窄：replay 的 bundles 来自 `load_candidate_snapshot_inputs` 对当前 workspace 库与 raw 文件的重新加载（第 2 节明文「核对所列 version/来源/时间/receipt/三个 payload hash/文件地址与真实字节」「所有对象/真实 receipt 必须在冻结 cutoff 内」、拒绝 symlink/junction），并非从快照字节反序列化。「同一已验证快照的 bundles」在契约里指与清单描述全字段相同，而非「冻结时字节被原样复用」；第 2 节同时明文「不保证抵抗特权重写历史、DB/raw 恶意并发换文件或原文件长期可用」「SQLite 快照不与 raw 文件系统原子」。把「复用同一验证输入」读成字节级原样复用且与冻结时刻完全一致，缺乏明文依据，属夸大嫌疑；契约未覆盖 freeze 与 replay 之间库/文件变化的比对与告警。
- 「同一逻辑快照」而非「同一字节」：契约未明文要求写回的 `candidate-manifest.json` 与读入快照逐字节相等，也未定义该文件字节与输入 manifest 的哈希等式（`replay_sha256` 明定为「candidate-inputs.json 实际字节 hash」，仅覆盖正文文件）；离线闭包靠 `input_manifest_sha256` 与纯校验/全字段一致来闭合。契约以「逻辑」二字留白，未作更强承诺。契约亦未明文「读取快照一次」所得解析对象与 load 内「先纯校验」所依据的快照为同一实例，次数是明文、对象同一性未明文。
- 「闭包完整」仅指结构、字段、顺序、哈希与内嵌正文自洽。契约明文「不能从 content_ref 读取其它文件」「不核实来源事实」「不刷新来源或认证事实」「不加载凭证/环境，不联网」，故闭包不含源文件、来源真实性与认证事实；把它解释为「事实完整」或「可独立证明内容为真」超出明文，属夸大。契约未覆盖上层调用方把「自包含」误当作「来源可信」的防护。
- 「完整」不含写入完成性：契约明文「中断可能留下半成品，verify 明确拒绝」「这是新目录独占发布，不称多文件整体原子」，故闭包完整仅对通过 verify 的文件集合成立，不构成原子写入保证。

**三、发布 / 容量 / 哈希 / 真实标签边界是否夸大（免责与断言的一致性）**

**【契约中确有明文依据的部分】**逐条核对，免责与断言相互印证：
- 发布：「这是新目录独占发布，不称多文件整体原子或外部可信持久锚点」，与「中断可能留下半成品，verify 明确拒绝」「不自动清理失败目录」「不覆盖、不删除/自动修复现存目录」、`mkdir(parents=True)` 且 `exist_ok=False` 独占声明、各文件 `open('x')`/`flush/fsync`、「新目录创建竞争可安全失败，不承诺恶意本机换链防护」一致；契约只主张独占式新建与拒绝半成品，未主张整体原子或外部持久锚点。
- 容量：「manifest 最大 1MiB，candidate-inputs 最大 64MiB；是本批读写容量限制，超限拒绝，不更改原 09-B planner 容量。正常最多 100 项；本批不保证任意大 full_text 数据可重放」，与纯校验「cap 严格 int 0..100」「len(candidates)<=cap」一致；「只是本批」与「不保证任意大」为明确定界，未把容量表述为通用或无限。
- 哈希：定位为 canonical JSON（`ensure_ascii=False`/`sort_keys=True`/`separators=(',',':')`/`allow_nan=False`）UTF8 SHA256 自洽校验，`input_manifest_sha256` 必须等于整个 input_manifest 哈希，`replay_sha256` 为 candidate-inputs.json 实际字节 hash；免责明文「攻击者可生成自洽清单/哈希，不能当签名」「不证明…来源真实」。「哈希不是签名 / 不能当来源真实性」与断言一致。
- 真实标签 receipt：校验口径明定为「真实标签 receipt 非 null 且有效」「原真实 receipt 必须存在且与冻结字符串精确相等、合法不早于三对象 available_at」「合成忽略 receipt 且 descriptor 为 null」，并「既有 35 条真实归档仅验证此前标题元数据，不刷新来源或认证事实」「不核实来源事实」、字段 `content_support_reviewed=false`。「只校验存在与字符串相等、不刷新来源或认证事实」与断言一致。
- 验收边界：「不要把已验证输入/重放称研究或生产验收」，与 status 取值 `'verified_inputs'`/`'verified_replay'`/`'frozen'`/`'replayed'`、字段 `model_called=false`/`content_support_reviewed=false`/`read_only=true`、「不采集、不调用模型、不核实来源事实」以及「NLP-01 整体、NLP-02 和真实模型/账单/可信高水位仍未完成」一致，命名与状态未使用研究或生产验收字样。
- 综合：这一组免责在契约内部自洽，未发现把局部/结构保证拔高为整体原子、外部可信、来源真实或验收通过的明文夸大。

**【契约未覆盖 / 仍属风险或夸大嫌疑的部分】**
- 免责多为否定式措辞约束（「不称…」「不保证…」「不能当…」「不把…称…」），契约未定义「外部可信持久锚点」「来源真实性」「生产验收」的判定标准，也未规定上层系统或调用方把这些 status/哈希当作凭据时的技术防护；覆盖的是「契约自身不宣称」，未覆盖「被误读或被当作凭据」的风险，不能据此补充「已防误用」的保证。
- 语义落差：`verify_candidate_replay` 返回 `status='verified_replay'`、`verify_candidate_snapshot` 返回 `'verified_inputs'`，且校验项含「描述全字段/hash 一致」；尽管契约以 `content_support_reviewed=false` 与第 1 节「自洽清单/哈希」限定，但「verified」字样与「仅结构/字节自洽」之间仍有文字层面的误读空间，契约未明文禁止把 `verified_*` 解释为事实真实性已被验证。这是残余夸大嫌疑，而非契约已作出的宣称。
- 容量口径留白：1MiB/64MiB 已声明为「本批读写容量限制」，但契约未覆盖多字节 UTF-8（`ensure_ascii=False`）下的字节计量口径、「100 项叠加」与两个上限的组合边界、「正常最多 100 项」中「正常」的定义；这些属未覆盖的实现细节，契约既不保证也不宜被要求保证，不能补写成「任意规模安全」。
- receipt「有效」的判定集合未完整写明：契约只给「非 null 且有效」「合法不早于三对象 available_at」「与冻结字符串精确相等」「effective 为规范化微秒 Z，等于 receipt」，其中「与冻结字符串精确相等」仅保证与清单一致，不保证 receipt 由权威方签发；「不刷新来源或认证事实」是免责而非对「有效」含义的穷举定义。据此宣称「真实标签已被认证」即属夸大，契约未覆盖该结论所需的前提。
- 发布留白：与「flush/fsync」「open('x')」并存的同时，契约未覆盖断电/崩溃下跨文件系统一致性、未指定「外部持久锚点」由谁提供，并以「不承诺恶意本机换链防护」「新目录创建竞争可安全失败」明示剩余风险。这些是已声明的风险留白，与免责一致、不构成夸大；但不可反向补成「发布具备原子性或抗恶意换链」。

[Agent ID: agent-62be9dab-10fa-464c-9ee1-cf78ebbf3cc2]

## 定稿说明

以上为子任务实际完整返回正文与实际工具回执，逐字保留，未代写、未轮询、未重试、未运行测试。定稿后不再覆盖。

WB-09C FINALIZED
