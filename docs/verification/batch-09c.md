# Batch09-C：固定候选快照与离线重放验收

日期2026-11-09；基线本地19ec620、GitHub28c2c28、相同tree00e48af8。输入是用户指定Batch09B开发计划与本地归档包；逐文件校验99文件，26轮143条可见用户/助手正文。对话和运行数据不上传。

## 本轮交付

契约`contracts/candidate-snapshot-v0.1.md`经过独立设计复核后冻结。主控负责共享纯schema和CLI；snapshot_impl_09c负责精确版本加载，artifact_impl_09c负责新目录发布/自包含重放；独立qa_b09c只写审查报告。分工和路径见`../../collaboration/batch-09c-plan.md`。

新增四命令：freeze-evidence-candidates、verify-evidence-candidates、replay-evidence-candidates、verify-candidate-replay。严格清单结构和canonical hash；精确event/raw/evidence/receipt闭包在schema4单只读事务复核，不重新调用planner/latest。新版本及旧时刻回填不替换已列对象；损坏所列对象/回执/正文则拒绝。无关业务坏payload不读取，全库integrity/FK失败仍可阻断。

冻结仅保存清单，重放显式保存自包含正文；offline验证无需原库。新目标目录独占创建，不覆盖/自动修复；校验及1MiB/64MiB容量检查先于目录创建。中断可能留下半成品并由校验拒绝，不宣称多文件整体原子发布。终端只输出摘要，未读密钥、未联网采集或调用模型，不修改schema4/模型schema3、账本或审计。

## 实测证据

- 主控共享契约5项、精确加载17项、artifact18项、CLI4项：共44运行43通过1 symlink权限跳过；实际Windows junction拒绝通过。包括各实现Agent实际专用测试，重叠计数不相加。
- `./scripts/dev.ps1 test`：451运行448通过3 Windows符号链接权限跳过，58.406秒，exit0；日志`out/batch09c-tests.log`。既有及本轮实际junction分支均通过。
- 独立QA复跑44项43通过1跳过，另6独立场景全通过；合计50运行49通过1跳过。实证共享raw闭包、回填固定输入、跨对象WAL快照、源不可用离线验证、重新制作自洽hash不能认证历史、真实1MiB+1拒绝。命令及产品文件SHA见`batch-09c-review.md`。
- `TEMP/TMP=工作区out/test-temp ./scripts/setup-env.ps1`普通隔离安装、项目外console help、明确合成demo、隔离全套451运行448通过3跳过，63.475秒、exit0；安装证据`.venv/setup-runs/20261109-232107-e6feb2e0/`，日志`out/batch09c-install.log`。已安装`market-intel.exe verify-evidence-candidates`及`verify-candidate-replay`对35项本地产物均exit0，manifest/replay hash与源码一致，无模型调用。

## 既有真实归档元数据

运行`PYTHONPATH=src .venv/Scripts/python.exe -X utf8 out/verify-real-candidates09c.py`，exit0。只读原`data/live`，固定cutoff=2026-11-09T00:00:00Z；raw/event/evidence/receipt各35，Fed20/NBS15。分别cap100选35、cap5选5；冻结→重复精确验证→重放→离线校验通过，DB/raw字节hash和四表行数前后一致。网络连接guard开启；offline源加载guard开启。真实来源文件没有删除或改名，源消失场景由合成独立QA覆盖。

| 范围 | input_manifest_sha256 | candidate-inputs.json实际字节SHA256 |
| --- | --- | --- |
| cap100 / 35项 | 135cbf281b26dba6b9f9239fe04c87afd3cd6d6cdbc9c025c8bdfb3abcc935d9 | 54c07ea07f10cde90a3307d8af633acd75c0d425218f765ac7c8e3efb95df3fa |
| cap5 / 5项 | a5b147d7f9a65017b7b5d6f6be3089427b80859a76987e08ded4667190322df8 | aac48512e1b0e50691a291ca4da4d03cb618a7f0f43a5caab0009682fb6cc2ed |

清单hash与09-B一致。产物仅本地`out/batch09c-real-15e8533e8eb8/`，摘要`out/batch09c-real-verification.json`；不上传清单、正文、DB或运行备份。这仅证明此前标题元数据可精确复核/重放，不代表今日刷新、全文语义支持、来源许可或事实真实性。

## 限制与交接

哈希不是签名、可信来源证明、选择完整性证明或外部高水位。DB与raw文件非联合原子快照，WAL可维护协调文件；不保证抵抗本机特权改写、恶意并发换链、断电持久性或无限大正文。validated inputs不是研究事实支持或生产验收。

NLP-01整体仍in_progress；真实DeepSeek API/tokenizer/供应商请求关联/账单、外部可信高水位/结算/生产恢复仍待完成。NLP-02/03、行情/日历、正式简报、评价、调度和至少7交易日运行未完成。G0通过，其余闸门保持原状态。WorkBuddy辅助设计审查与产品测试分别记录；发布核验在完成后补记。

WB-09C已自然完成，界面显示9m48s；两文件完整三点正文和父端回执已回收，tests_run=0。底层Agent工具日志未独立认证，任务保持review。静态处置见`batch-09c-workbuddy-triage.md`，不改产品逻辑。未停止/重启旧任务。

## 已核验发布

本地代码提交`37000d3c70c8bcdf2f98369bed37d4b50335be78`，GitHub对应提交`5a8db409fbb41ba12e743cf9e14b1480fa4a2ab9`，共同tree`2b2fd3e30ecf556e5cf6d11395c23c4718514a51`。通过授权连接非强制更新main，随后重新读取分支确认一致；保留本地历史，不声称远程包含相同全部历史。24个文件无凭证模式命中，差异格式检查通过；只上传源码/测试/计划/审查，未包含对话ZIP、真实清单/正文/库/备份、虚拟环境、output/tmp。当前发布核验记录作为后续纯文档归档提交。
