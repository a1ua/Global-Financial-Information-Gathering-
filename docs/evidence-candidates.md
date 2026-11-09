# 证据库只读候选清单

`plan_evidence_candidates(workspace, cutoff, max_candidates=5, *, include_synthetic=False)`读取已存在的schema4 `market.db`，返回`evidence-candidate-plan/0.1`及固定版本输入清单。模型schema3和报告均不改变；不采集、不读模型凭证、不调用模型、不写审计或预算。

读取使用mode=ro/query_only和单一BEGIN事务，验证数据库完整性/外键及全部被event引用的bundle，再进行scope/回执/时点过滤。复用现有单raw/event/evidence契约验证结构、文本hash、quote及时间顺序；DB行身份和evidence外键列必须与payload一致，重复逻辑版本拒绝。未来或scope排除bundle也先作结构校验，不能靠限量绕过坏尾项；孤立raw/evidence正文不加入候选闭包。

默认排除合成标签。真实标签事件必须具有有效提交后receipt，缺回执计入missing_receipt并排除；无时区或早于三对象available_at最大值的回执拒绝。标签本身不是来源认证。合成事件仅在显式include_synthetic时可选，receipt即使存在也忽略并在清单中为null。effective_available_at使用真实receipt和全部对象可用时间；source_published_at不放行候选。

每个event_id取截点内最高可用version；较高版本未来或缺回执时保留较低可用版本。全部最新可用候选的原始文件在截断前验证固定内容地址、路径/链接拒绝、UTF8字节及SHA-256，然后按effective时刻、event_id、event_version_id排序，取0–100项。cap0仍校验这些文件；不可用版本不读取raw文件。

输入清单含精确对象ID/版本、来源配置、时间、内容地址及三payload的canonical SHA-256，不包含标题、正文、quote、URL或绝对工作路径。manifest hash仅覆盖选择参数与所选闭包，不含当前时间或全库诊断计数。有效时间晚于旧cutoff的追加且既有内容未改时，旧manifest保持相同；人工回填旧时刻、特权改写或include_synthetic回填不在稳定保证内。

返回计数区分scope排除、缺receipt、截点后、可用版本、被较高可用版本替代、可用事件、限量未选及已选。计数严格分区；data_status只描述所选集合empty/real/synthetic/mixed，不以空清单推断真实覆盖。content_support_reviewed=false、model_called=false始终保留，不代表重要性、事实支持或NLP02通过。

数据库快照不与文件系统原子，不能抵御恶意换文件或特权回填。SQLite读WAL可维护-wal/-shm协调文件，因此只读表示无SQL业务/schema写，不是零文件系统副作用；不用immutable忽略WAL。不创建缺失库或自动迁移旧schema，固定ValueError码不回显正文、路径或底层错误。

定向验收使用完全合成fixture（包括用false标签模拟真实receipt边界，不是联网真实来源验证）。设置PYTHONPATH=src和工作区内TEMP/TMP，运行`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_evidence_candidates.py -v`。实际18项通过，覆盖回执/时间/版本、未来追加、限量前损坏文件、严格JSON/身份/逻辑冲突、路径逃逸/链接、单事务只读及WAL并发新提交。首跑测试错误patch了调用模块中的链接别名而非文件helper所属模块，修正测试目标后复验通过；非产品缺陷。最终独立验收由QA另记。
