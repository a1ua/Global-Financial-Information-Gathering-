# Batch10：成功模型调用供应商响应关联验收

2026-11-10，基线本地444dd2b166fededcae6c69a206ba45b177127063，GitHub98eaec0776df4da9503b71c8ca7ab7ddd5c45e7b。沿用用户DeepSeek每日人民币10元/UTC日单账本配置；本批未读真实密钥或调用付费API。

## 交付范围

独立QA先设计复核，主控冻结`contracts/provider-correlation-v0.1.md`后派transport_b10、inspect_b10分别实现传输与只读查询。主控负责共享纯契约、client成功事务、backup严格校验及CLI；独立qa_b10仅写review。分工/所有权见`../../collaboration/batch-10-plan.md`。

DeepSeek官方Chat Completions文档当日核实响应id是completion标识（[来源](https://api-docs.deepseek.com/api/create-chat-completion/)），不编造HTTP请求ID或账单字段。只将本地受限ASCII1..256字节id的SHA256放入可选ModelResponse字段；缺字段兼容、存在非法拒绝。原ID/headers不存储，model/endpoint/transport版本与请求缓存键不变。该格式限制是本地契约，不宣称覆盖官方所有合法标识。

只有最终成功且接受正整数usage才在现有_finish同事务更新calls.request_metadata.provider_response，并写状态/费用/输出hash/cache。无usage/0usage无关联；失败/超时/输出错误不存关联或正文，仍全额占用，重试独立预留。缓存保持原call_id，旧行不补写。新增`model-call-info`只读绑定schema3全库业务验证及精确行摘要，无模型/网络/密钥入口；invoice_verified与settlement_allowed固定false。

模型schema3和证据schema4不变，备份/隔离恢复保留原metadata字符串并严格验证可选子对象、状态及usage列；预检逐行比较自然可检测关联变化。哈希自洽不是签名、来源认证或可信高水位，不提供结算或生产切换。

## 实际验证

- 传输Agent：25项全部通过（6新增+19旧传输），0.034秒；查询Agent：12项通过，2.648秒，含实际Windows junction、WAL与身份变化拒绝。
- 主控5新增套件34项全部通过，5.348秒；另62项模型相关回归通过。修正两项CLI测试连接未close导致Windows清理失败、备份测试误用恢复文件名，均为测试问题。
- 独立QA最终154项153通过1 Windows symlink权限跳过，实际junction通过，17.157秒；另6独立场景通过，合计160执行159通过1跳过，重叠计数不与主控相加。包括成功提交前外连接仍见pending、预检关联变化不许切换、WAL、模拟HTTP到CNY摘要、0usage与非法hash重试全额。详见batch-10-review.md。
- QA发现纯validate_call_correlation缺call或缺键漏出TypeError/KeyError，主控修为固定ValueError并扩负例；独立复验通过。
- 完整回归最初485项有1错误3跳过：旧schema1测试手工清空usage却保留新关联，制造矛盾数据，被产品正确拒绝。主控更新两处历史fixture移除可选字段，不放松产品。首修命中另一同形列表，第二次全套仍同失败；精确修正后稳定运行`./scripts/dev.ps1 test`：485运行482通过3符号链接权限跳过，52.441秒、exit0，日志out/batch10-tests-accepted.log。早期失败日志保留，不充当最终通过证据。
- `TEMP/TMP=工作区out/test-temp ./scripts/setup-env.ps1`普通隔离安装、项目外console help、明确合成demo及全套485运行482通过3跳过，57.684秒、exit0；证据`.venv/setup-runs/20261110-003952-50716314/`，日志out/batch10-install.log。随后`.venv/Scripts/python.exe -I -X utf8 out/verify-b10-installed.py`加载site-packages已安装包，以注入HTTP合成响应到client/CNY账本，再从独立工作目录运行已安装model-call-info：20输入/8输出token、104 microCNY配置估算、recorded且hash一致、无原ID/输出正文，invoice_verified/settlement_allowed/model_called均false，exit0。只读查询没有发模型请求，前置模拟HTTP也不是实网。摘要out/batch10-installed-verification.json和合成运行库留out，不提交。

WorkBuddy新WB-10已自然结束、两文件正文回收；静态三点无阻断，底层Agent日志非独立认证，review、tests_run0，见batch-10-workbuddy-triage.md。未把父端completed当测试通过。

## 未验证与下一项

本轮只验证合成数据与注入HTTP；未刷新来源、读取运行真实库或改变35条归档，未执行真实模型/tokenizer/逐调用账单。未知费用继续占用；失败响应关联本批有意未保存。SQLite/WAL可维护协调文件，绑定与库不是跨文件原子；不抵抗特权改写/回退或恶意并发换链，未证明账户全局限额。

NLP-01保持in_progress，完整闸门不变。下一项可离线设计失败/不完整响应关联，真实最少合成smoke在安全本地凭证及明确启用具备后验收；外部账单可信匹配、高水位、终态结算/生产恢复仍为后续依赖。最新任务流见development-status-plan-20261110-batch10.md。对话ZIP/运行产物/凭证/无关output/tmp不上传；发布结果实际核验后归档。

## 已核验发布

本地代码`2bca05b89268ca713d6ecdf0689292f865046c72`、GitHub`1b255f3675b90ac473093ed011f26630e78a55e8`，tree均为`73c7e945a1dff02503db062f9270771284908520`。授权连接按预期父提交非强制更新main，随后重新读取分支核对一致；保留本地开发历史，不声称远程完整历史相同。暂存27文件差异格式检查和凭证模式扫描通过，未上传运行数据/对话/备份/虚拟环境/output/tmp。独立审查后仅tests/test_provider_correlation.py删除一条未使用copy导入；产品SHA未变。此发布记录随后作为纯文档归档提交。
