# Batch15：ENG-04判断持久化设计交接

2026-11-17。依据完整开发计划，完成ENG-04下一设计子包，不是判断存储实现。主控负责共享契约，judgment_design15负责存储/迁移设计，qa15独立审查。无源码/schema/CLI/依赖/运行库修改，无真实模型、来源刷新、调度或WorkBuddy派发。

成果：contracts/prediction-storage-v0.1.md定义不可变内容+提交后回执envelope、精确输入闭包、模型跨库固定摘要、原UTC可用时间、同ID幂等与冲突、单根线性更正、无回执不可评价、时钟回退及孤立内容恢复。prediction-storage-design.md列出拟议表/外键/迁移与读者兼容方案。

实际设计发现：store SCHEMA_VERSION4；evidence_candidates._plan及candidate_snapshot._load严格版本4；backup仅验证raw/report闭包，不能只提升版本放行schema5。模型账本3与审计1不随证据迁移改变。

独立审查补强：一个family仅一根（唯一约束），同family固定目标/基准/basis/协议/日历；更正回执不早于前驱，无分叉，换上下文新家族。回执后置采样不声称精确物理提交时刻或联合原子，不可把created_at当评价起点。协议/日历/真实模型引用未就绪时，初期实现只许显式合成fixture，不允许任意ID通过生产引用。

验证为设计静态审查，tests_run=0。本轮不复跑未变源码的完整测试，不把此前Batch14的526/523/3当本轮执行。精确JSON键集/长度上限/错误码/规范哈希及合成协议快照结构尚需P16-CONTRACT冻结，不能称本轮完成可执行schema。

下一批：P16-CONTRACT纯输入契约和合成引用闭包→独立QA→P16-VALIDATE纯校验（不迁移）。再P17-STORE证据schema5/不可变表/连接/回执、P17-COMPAT候选快照与备份兼容、独立故障/迁移/安装全套验收。后续再评ENG-04全量完成，不提前开启REV评价。

当前主任务9done/3in_progress/13planned/1cancelled，闸门保持；用户离线选择保持。Batch12至15尚未提交上传；无关output/tmp未触碰。
