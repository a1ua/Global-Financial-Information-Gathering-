# 固定候选输入复核

Batch09-C 输入契约：`evidence-candidate-snapshot/0.1`，内部沿用09-B的`evidence-candidate-input/0.1`与16字段候选描述。证据数据库仍为schema4，模型schema3未改变。

冻结文件保存候选的精确事件版本、原始项、证据ID、真实入库回执字符串、三对象payload哈希及内容哈希。后续复核有意不重新选择latest、不重排或补入事件；因此新版或旧时刻回填可改变新计划，但不能替换已冻结的输入。

## 接口与边界

`market_intel.pipeline.candidate_snapshot.load_candidate_snapshot_inputs(workspace,snapshot)`先纯校验清单，再在`mode=ro`、`query_only=ON`、单一`BEGIN`事务内检查schema、全库integrity/FK，并只解析清单列出的三个精确对象。每项严格复核JSON、对象身份、证据外键列、bundle契约、真实receipt原字符串、全部描述字段和payload哈希；raw文件必须在工作区内、无符号链接或接合点，并与已归档normalized_text字节和内容哈希相同。合成项不读取receipt表中的值，其有效可用时刻取三对象最大值。

返回`{verification,bundles}`。bundles按清单顺序，每项严格包含raw、event、evidence和receipt_committed_at；它们是同一次读取已经验证的输入，导出方直接消费，不能再查一次最新版本。`verify_candidate_snapshot(workspace,snapshot)`仅返回摘要，避免向终端输出正文。

摘要状态为`verified_inputs`，含入选数量、清单哈希、empty/real/synthetic/mixed标签；明确`model_called=false`、`content_support_reviewed=false`。real是既有数据标签，不表示事实支持审查或模型验收。

命令入口由主控集成：`verify-evidence-candidates --workspace WORKSPACE --manifest MANIFEST`。冻结和自包含离线重放见[重放说明](candidate-replay.md)，完整契约见[固定快照契约](contracts/candidate-snapshot-v0.1.md)。

无关的非法业务payload不会被解析，但全库完整性或外键失败仍会阻断。SQLite事务不能与raw文件系统形成共同原子快照，WAL可以维护协调侧文件；不保证抵抗本机特权篡改或恶意并发换文件。哈希只验证自洽性，不是签名、可信来源证明或完整选择证明。

## 本工作包验证证据

执行`python -X utf8 -m unittest discover -s tests -p test_candidate_snapshot.py -v`，设置项目src为PYTHONPATH、工作区out/test-temp为TEMP/TMP。17项测试全部通过：旧输入在新版/回填后保持、无关坏payload隔离、receipt精确字符串与缺失拒绝、合成时刻、三个payload变更、重复JSON键、FK列与全局FK、空/混合标签、校验先于开库、单事务只读与静态字节保持、WAL并发修改不混入、文件损坏/缺失/模拟链接、精确引用缺失不回退、错误脱敏与schema/缺失目录。

测试使用明确合成fixture；没有联网刷新来源、读取凭证、调用模型或修改预算。没有把本工作包测试计为真实来源事实、NLP-01整体、NLP-02或生产运行验收。
