# Batch09-B 证据候选输入清单验收

2026-11-09，基线本地cca420a、GitHub7f2f96b。契约`docs/contracts/evidence-candidates-v0.1.md`；任务/目录责任见`collaboration/batch-09b-plan.md`。

发布核验：本地代码`d918076e1467751dcd1002f68675ee94f498af4a`、GitHub快照`eb20ca476401a81e15d0a6206ba02045d8663e97`，相同tree`b10fab220a48e7d0df4b9ac75ace17849bccc9c1`；非强制更新，保留本地开发历史。最终发布记录另作后续归档提交。额度恢复后只补文档/交接，产品SHA与既有独立验收一致，没有重复运行已通过测试。新出现output/tmp目录保留且不提交。

## 交付及设计处置

独立QA先复核设计，主控明确合成receipt忽略及历史稳定性仅适用于新增effective晚于旧cutoff且既有引用未改，再冻结并派发。证据Agent仅写模块、18项测试及API说明；主控接CLI及5项集成；独立QA不改产品。

新增`evidence-candidate-plan`：schema4 mode=ro/query_only单读事务内验证完整性、严格bundle/身份/外键/回执；默认真实标签、缺receipt排除、早于对象可用时间回执拒绝；截点内每event取最新可用版本，再校验全部最新可用候选文件后限量。输出精确raw/event/evidence版本与payload/file哈希、可用时间和回执，不输出标题/正文/URL。不调用采集或模型，不写模型/审计/报告，不改schema。

未来较新版本/晚回执不替换旧截点版本；人工旧时刻回填及特权改写不在稳定保证内。完整input_manifest的hash不含全库诊断计数或当前时间；摘要计数变化不等于已列精确输入改变。

## 实际验证

- 证据Agent18项定向测试通过，1.805s，exit0；首跑一项测试patch错链接helper位置，修正测试目标后通过，不是产品路径缺陷。按主控复核给SQLite close错误加固定码，模块稳定后交QA。
- 主控CLI5项通过，0.841s，覆盖默认排除fixture、显式合成manifest哈希复算、正文/URL/路径不输出、缺库不建、cap0坏文件拒绝和无密钥/网络/ModelClient/可写connect陷阱。
- `./scripts/dev.ps1 test`完整407项，405通过、2项Windows符号链接权限跳过，实际junction分支通过，47.334s，exit0；日志`out/batch09b-tests.log`。
- `TEMP/TMP=工作区out/test-temp`下`./scripts/setup-env.ps1`普通隔离安装、项目外CLI help、明确合成demo和隔离全套通过，407项405通过2跳过，50.230s，exit0；证据`.venv/setup-runs/20261109-143201-cfa93ef6/`，日志`out/batch09b-install.log`。安装后控制台对既有真实库cap5清单哈希与源码验证一致，selected=5、model_called=false，exit0，输出留`out/batch09b-installed-plan.json`。
- 独立QA89项，88通过、1权限跳过，8.911s，exit0；另5组场景验证高版本缺/晚回执、孤立raw/旧时刻回填、WAL并发补receipt的固定快照、严格JSON/私密错误、真实Windows junction拒绝。细节与实现SHA见`batch-09b-review.md`；QA不替主控未亲测的全套/安装及真实样本出独立证明，重叠测试数不相加。

## 现存真实归档元数据只读验证

主控运行`PYTHONPATH=src .venv/Scripts/python.exe -X utf8 out/verify-real-candidates09b.py`，exit0；只读已有`data/live`，未联网刷新。固定cutoff为2026-11-09T00:00:00Z。

| 项目 | 实测 |
| --- | --- |
| raw/event/evidence/receipt | 各35条 |
| 已归档来源 | fed_press_all 20、nbs_releases 15 |
| cap100选择 | 35 |
| cap5选择/限量未选 | 5 / 30 |
| cap100 input_manifest_sha256 | 135cbf281b26dba6b9f9239fe04c87afd3cd6d6cdbc9c025c8bdfb3abcc935d9 |
| cap5 input_manifest_sha256 | a5b147d7f9a65017b7b5d6f6be3089427b80859a76987e08ded4667190322df8 |
| 重复计划/模型调用 | 完全一致 / false |
| 主库与35份raw文件字节哈希、四表行数 | 前后一致 |

原始验证摘要留`out/batch09b-real-verification.json`，实际清单/库/原始文件不上传。此结果只证明此前归档的标题元数据能形成清单，不代表今日刷新、来源长期稳定、全文支持或供应商验收。故障测试内人工构造false标签仍为合成测试，不混入此真实样本统计。

## 限制与下一项

SQLite正常WAL读取可能维护协调侧文件，只读不保证整个目录零变化。DB与raw文件读取不是跨介质原子快照，不能抵抗恶意并发换文件/特权回填；false标签和哈希不认证来源/事实。当前载入本机候选版本，无大规模吞吐/长期公平保证。source_published_at不放行候选。

NLP-01仅接受这个候选输入子集，NLP-02、真实API/tokenizer/账单、可信外部高水位、结算与生产恢复仍未完成。下一项09-C固定候选清单验证与重放，按精确版本/哈希复核，不重新查询最新关系；不自动调用模型。WorkBuddy设计交接与独立测试分开记录，不以父端回执自述代替实现证据。
