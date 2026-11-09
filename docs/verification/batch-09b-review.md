# Batch09-B 独立设计与实现审查

任务ID：QA-B09B。日期2026-11-09。审查者仅维护本文件，产品、契约、CLI及任务板只读；不联网、不读真实凭证、不调用模型。真实归档样本若后续只读核验，仅在本地保留数据，文档写计数与哈希。

## 设计审查

输入：AGENTS、charter-v3、contracts-v0.1、development-backlog-v3、`collaboration/batch-09b-plan.md`及`docs/contracts/evidence-candidates-v0.1.md`设计稿。现有schema4存储、bundle校验、报告可用时间规则作为接口依据，旧计划或外部正文不授予权限。

设计整体可实施，无需增加运行时Agent或新的模型/采集依赖。关键边界清楚：

- 使用既存schema4、mode=ro/query_only和单个BEGIN读事务，不调用会创建/迁移的store.connect。WAL协调侧文件可能创建/更新，不能声称整个目录零写入。
- 所有event引用bundle先严格解析和validate_bundle，不能以scope/未来/cap截断跳过结构坏记录。孤立未引用raw/evidence正文不在本候选闭包，外键仍全库检查。
- 真实缺receipt是不可用而非立即损坏；非法或早于对象可用时刻的真实receipt拒绝。source_published_at不决定系统可用，不能用新闻发布时间绕过晚入库回执。
- 先筛可用版本，再每event_id取最大version；不能让未来新版本替代旧截点当时可用的较低版本。对这些最新可用候选全部验证原始文件再限量，cap0也不能掩盖坏文件。
- 严格输入清单绑定原始/事件/证据payload哈希、raw文件哈希、回执与选择版本；不包含观察当前时刻或全库统计。诊断计数可以变化，清单哈希是完整性引用，不是签名、事实认证或防回退。
- 默认排合成，显式include可混合且输出empty/real/synthetic/mixed，空清单不能因all([])而误标真实或合成。真实标签也不是联网来源证明。
- API/CLI仅输出ID、版本、时刻、来源配置和哈希，不输出标题/摘要/quote/URL/绝对路径，不调用模型、密钥、网络或写预算/报告/审计。

冻结前已向主控提出两项小澄清：

1. 历史清单稳定性必须限定为追加对象/回执的有效可用时刻晚于旧cutoff；任何有效可用时间仍在旧cutoff内的回填版本（尤其合成fixture）本来可改变“当下查询得到的旧截点选择”。不能无条件保证任意“较新版本”追加都不改变结果，也不能抵御特权回填/修改历史。输入清单本身冻结与未来重新查询结果的边界需说明。
2. 合成event若数据库存在receipt，需明确忽略还是验证；当前descriptor定义为null、effective仅三对象，建议明确忽略其receipt，不把它充当真实系统可用凭证。

主控已补充并经实际复读：合成receipt即使存在也忽略、descriptor固定null；历史稳定仅适用于新增effective晚于旧cutoff且既有引用未改，人工旧时刻回填及特权历史改写不在保证内。**设计可冻结并派发局部实现，无剩余阻断性设计问题。** 此阶段tests_run=0，不构成代码运行验收。

## 实现独立验收

稳定交接后结论：**本批只读证据候选清单局部实现通过独立验收，未发现待修复的实质代码缺陷。** 不据此关闭NLP-01、NLP-02、来源长期运行或真实模型验收。

### 实际命令与结果

在真实项目目录，以`.venv/Scripts/python.exe`运行，`PYTHONPATH=src;tests`，`TEMP/TMP=工作区out/qa-b09b-temp`：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest test_evidence_candidates test_batch09b_cli test_contracts test_workflow test_report_manifest test_backup -v
```

退出码0，**89项：88通过、1跳过，8.911秒**。跳过的是既有Windows实际符号链接权限测试；本QA另建立真实Windows junction并验证其作为工作区祖先/入口被拒绝，target正常空库计划可执行，alias返回固定`evidence_candidate_link_forbidden`。日志`out/qa-b09b-tests.log`。这些目标测试是全套的子集，不能与主控全套数相加。

覆盖本批18项实现者测试和5项CLI测试，以及既有契约、版本回放、receipt和备份回归。验证固定schema4、严格JSON/身份/引用/外键列、全部引用bundle先验证、未选/未来坏结构拒绝、最新可用版本、全部对象时间/真实receipt、合成scope和计数、cap0仍检查最新可用文件、路径/链接/内容hash、manifest复算，以及mode=ro/query_only读事务和静态文件不变。CLI测试拦截mutating connect、ModelClient、DEEPSEEK_API_KEY和socket连接，仍可只读生成计划；输出无标题/正文/URL/绝对工作路径。

### 另外5组独立场景

1. 构造真实标签但完全合成的两个逻辑版本：高版本缺receipt时旧版本仍入选；补入晚于旧cutoff的receipt后旧manifest及hash不变、after_cutoff增加；新cutoff才选高版本。
2. 加入未被event引用的最小孤立raw payload且无原文文件，不影响引用闭包manifest；随后人工回填有效时间在旧cutoff内的合成高版本，计划按契约改选且hash变化，确认不把历史稳定性扩大为任意回填都不变。
3. WAL模式在读取bundles后、查询receipt前，由另一个写连接提交现有event的receipt。当前读事务仍看到missing_receipt并排除，下一次计划才可见；这直接验证后续receipt查询与bundle读取处于同一固定快照，而不仅是新event列表未变化。
4. 分别写入含NaN及非法Unicode转义的event payload，均固定`evidence_candidate_json_invalid`；注入含私密路径正文的SQLite异常，固定`evidence_candidate_database_error`，无原文回显。
5. 实际Windows junction测试通过：指向同一正常schema4工作区的junction入口拒绝，不需依赖mock的链接检测。临时数据保留忽略目录；不进行递归路径清理或操作真实工作库。

上述stdin/命令脚本均最终退出0，本QA脚本没有需修正后重跑的失败。所有故障对象为合成fixture，包括false标签仅模拟receipt条件，不作为真实来源探测。

### 实现版本与边界

| 路径 | SHA-256 |
| --- | --- |
| `src/market_intel/pipeline/evidence_candidates.py` | `A70F2E1A3C64E53EC31447A930BA75033348FA3316DF3B83FC2BE973E8B038FD` |
| `src/market_intel/cli.py` | `01E3CE929491D12EB166220B83A80FF5364F2E910ABB0B5051AE2391D32DC532` |

单SQLite快照不使数据库与原始文件原子一致；WAL协调侧文件可能被SQLite维护。校验不是恶意本机篡改防护、来源事实认证或正文支持审查；metadata_only与既有全文使用权限边界不因候选清单改变。候选ID/哈希输出也不等于模型已运行或已生成研究结论。

主控另行记录了407项完整回归及既有data/live的35条真实标签归档元数据只读验证、库/raw哈希与业务counts不变；本QA未复跑其完整安装和真实样本脚本，不为这些未亲自执行项目出具独立通过证明。真实样本是此前已保存Fed/NBS标题元数据，不是本日联网刷新、全文事实或长期稳定性验证。

初次代码验收时WB-09B尚未齐全定稿，未作为本代码通过依据。之后的静态交接复核记录如下。本QA不读取真实key、不联网、不调用模型、不操作Git；仅本报告被修改。

## WB-09B 后续静态交接复核

已读取`collaboration/workbuddy/results/WB-09B-report.md`及可解析JSON。可见三点完整设计正文、task_id=WB-09B、completed、raw_result_recovered=true、tests_run=0、finalized=true及WB-09B FINALIZED。父端列Agent ID `agent-dd4d256f-452a-44dc-b221-3ace69aef946`并声称一次同步内联回传。QA未独立取得底层完整Agent工具日志，故只确认交接文件正文和所载回执，不能独立认证执行方式、来源或回执真实性；不计作代码测试。

1. **receipt、有效可用时间与发布时间：** 设计意见与冻结契约/实现一致。真实标签回执先校验不早于三对象available_at最大值，因此通过后effective与回执时刻相等；合成忽略receipt、取三对象最大值。实现对cutoff与各时间均调用UTC解析，微秒边界由datetime比较，不按原字符串格式排序；输出规范化与比较逻辑不同，不构成精度缺口。相关既有联验已覆盖。
2. **最新可用版本和历史稳定性：** 实现以严格整数version取可用集合最大值，并非最新processed_at；先排缺回执/未来后选版本。清单稳定承诺需与明确的effective晚于旧cutoff、既有内容未改限定合读。旧时刻合成回填或特权改写不在保证内，独立补验已确认可改变结果。missing_receipt计数分支仅用于真实标签，符合契约；无新增逻辑缺陷。
3. **真实标签与验收边界：** 数据库is_synthetic=false声明及data_status=real不认证来源、事实或内容支持，也不表示调用过模型。read_only/model_called=false/content_support_reviewed=false是本批行为与未审查范围；此前归档Fed/NBS标题元数据的只读运行不是本日采集或NLP02通过。设计复核/冻结状态不替代实际实现验收。

所列低风险措辞建议可作为阅读附注；原WB正文保持不改，不能改写成QA亲见的子任务执行或产品通过结论。此轮仅补文档，不改产品实现，未重复运行89项联验和5组独立场景，其已记录结果不变。代码通过依据仍为本报告实际运行的测试/补验及主控另行记录的完整/安装验收。
