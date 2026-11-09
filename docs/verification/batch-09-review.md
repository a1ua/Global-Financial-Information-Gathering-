# Batch09-A 独立设计与实现审查

任务：QA-B09。日期：2026-11-09。审查者只维护本文件，产品实现、共享契约、CLI、任务板均只读；不联网、不读取真实凭证、不执行真实供应商请求。

## 设计审查

输入：项目AGENTS、charter-v3、contracts-v0.1、development-backlog-v3、`collaboration/batch-09-plan.md`、`docs/contracts/candidate-batch-v0.1.md`设计稿及现有ModelClient预留/重试/缓存接口。

**本批合成候选选择与限定mock预算联验设计可以进入局部实现，未发现需要扩大框架的阻断性问题。** 设计不代表实现运行通过。模型账本schema3、证据库schema4不变，不查询真实证据库、不代表NLP-02抽取或供应商验收。

已确认：

- 所有原始候选先验证，再去重、截点和限量，不能用max=0、未来时间或超限位置跳过无效项。同ID不同字段整批拒绝；相同ID完全一致去重。
- UTC时刻解析后比较与排序；candidate_id作为同刻稳定顺序。选择计数把未来项与限量排除分开，选中数不超过单次上限。
- 限制的是当次selected数量，缓存仍占名额且不补选；transport次数可能因重试超过候选数量。每次generate仍由已有客户端独立事务预留，不能把批前估算当作已授权额度。
- 首次ModelError即停止，当前failed、后续not_attempted，保留此前成功、缓存、失败与未知费用占用；不是整批原子事务，不清零pending。
- 空选择不构造ModelClient、不建库；CLI plan仅输出摘要和ID，不输出title、不读key、不联网。mock-run显式写本地合成账本，固定mock策略，不提供live/provider等参数。
- `live_called=false`仅描述固定mock模式；Python注入transport是受信任测试接口，不能用这个标志证明任意注入函数未自行联网。
- 真实事件以后必须接入证据版本与系统receipt；本批合成available_at不能替代真实来源可用时点证明。NLP-01继续in_progress、NLP-02未开始，其余高水位/对账/结算/恢复缺口不被本批关闭。

已向主控提示两项实现前细化：

1. 要显式拒绝`DeepSeekTransport`实例。provider为mock并不使任意已注入transport失去联网能力；已知真实transport必须在建库/调用前拒绝，任意恶意包装回调仍属于受信任Python接口边界，不扩展成安全沙箱。
2. CLI依赖的`expected_ledger_id`应正式列为API可选参数，校验格式并明确构造后、generate前核对。ensure到客户端构造并非原子阶段，缺库/换库时失败前不generate的承诺不能扩大为抵御所有文件替换或保证从未产生文件副作用。

主控已补入上述两项并经实际复读：签名含`expected_ledger_id=None`，格式非法在建库前拒绝、构造后调用前核对；显式拒绝DeepSeekTransport及子类并校验其它非空transport可调用；ensure到构造非原子且其它注入回调为受信任接口的限制已写清。**契约可冻结并派发实现，无剩余阻断性设计问题。**

## 实现独立验收

稳定交接后，已实际检查`pipeline/candidates.py`、`llm/batch.py`和CLI实现及相关测试。**本轮明确合成输入的候选限量与mock预算联验子集通过独立离线验收，未发现待修实质产品缺陷。** 本结论不关闭NLP-01、不代表NLP-02抽取或真实供应商已验收。

在真实工作区以`.venv/Scripts/python.exe`运行，`PYTHONPATH=src;tests`，`TEMP/TMP=工作区out/qa-batch09-temp`：

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest test_candidates test_candidate_batch test_batch09_cli test_llm test_llm_cny test_deepseek test_ledger_binding -v
```

实际结果：**112项，111通过、1跳过，8.402秒，exit0**。跳过为Windows实际符号链接创建权限不足；实际junction祖先拒绝分支通过。日志`out/qa-batch09-targeted.log`。这些定向测试属于全项目回归的重叠子集，不能与主控全套数相加。

覆盖：严格输入与全部项验证先于限量、UTF8容量、ID冲突及UTC小数秒排序、置换确定性、0上限和空选择无建库、缓存占名额不补选、预算允许前缀后停、每次重试独立预留、失败未知费用保持、禁用/真实策略及真实transport拒绝、绑定身份核对、CLI格式与路径/密钥边界及固定错误码。

### 额外独立场景

另行用stdin脚本执行以下5组，全部退出0，日志`out/qa-batch09-extra.log`，未修改产品或测试文件：

1. 将无效真实标签放在未来尾项，分别cap0和cap1，仍完整验证后拒绝，模型库及父目录均未创建。
2. 构造DeepSeekTransport子类，其调用函数为失败陷阱；以及非法expected_ledger_id，均建库前拒绝，transport0。
3. 注入合成transport主动修改收到的input title与output_schema枚举；两个候选仍成功，原始batch逐字段不变，后续固定schema未被污染。
4. 注入跨UTC午夜时钟：第一候选午夜前reserve、午夜后finish，费用仍在原日；第二候选使用新日预算。两条调用各记原/次UTC日60 microCNY，未出现批次自建日计数器。
5. CLI执行时对DEEPSEEK_API_KEY读取及socket.create_connection设失败陷阱，固定mock执行成功；再次运行命中缓存，calls逐列完全不变，stdout不含title。此陷阱验证被执行的固定CLI路径，不能证明任意恶意Python注入回调都无法联网。

### 信任与范围复核

Python transport注入仍是受信任测试接口，显式拒绝DeepSeekTransport及子类不等于网络沙箱。CLI不提供该注入或live/provider参数。expected身份核对发生在构造后、generate前；ensure至构造有TOCTOU，不能保证该间隙缺失文件不会被构造器新建。合成输入available_at不是系统receipt，不能据此宣称真实新闻时间隔离或覆盖通过。

选择上限按当次selected计数，重试可增加transport次数，缓存不补位；所有尝试仍受现有账本事务预留。首错保留已成功/未知占用，不做批事务回滚。本轮不接入真实来源、报告、审计自动写入或结算/恢复切换。

| 实现路径 | SHA-256 |
| --- | --- |
| `src/market_intel/pipeline/candidates.py` | `FAA88553C716110868114BF7C61FB020F2E07AD9843DBF4F6D2D428E10123714` |
| `src/market_intel/llm/batch.py` | `761FC0282B831122993873C30CF829D31D878032BA7522058883001F2142E9EE` |
| `src/market_intel/cli.py` | `2BA81C390EC90BD0CC1A4AFA77AFB6815767F95A6BDEF1226C09BC7005CFDC37` |

QA未做普通安装或Git/GitHub写操作，不替主控声称其结果。所有调用、usage、金额为合成验证，没有读取真实密钥、请求真实模型或认证真实账单。

## WB-09 静态交接复核

已实际读取两份定稿，JSON可解析、task_id=WB-09、completed、raw_result_recovered=true、tests_run=0、finalized=true；报告包含三点完整设计正文及WB-09 FINALIZED。父端列Agent ID agent-38c9bcb4-10ec-4cb3-bc82-b7d19da47a2c及单次同步阻塞回执自述。QA未独立取得底层Agent完整工具日志，只确认交接正文和所载声明，不能认证执行方式、来源或回执真实性，不计作代码测试。

1. 候选集合与尝试次数/缓存口径：审查提出“transport只见selected”可能被读成次数相同。主控已在冻结契约“审查澄清”中明确只限候选集合；selected/succeeded/failed等按候选计数，重试尝试看账本calls，缓存没有新预留或transport但占当次名额。这是口径澄清，现实现及已运行的重试/缓存测试一致，无需为本轮新增尝试计数字段。
2. 首次ModelError与内部重试：应理解为generate对外抛错后批次停止，不是打断generate内部合法有界重试。预算预留拒绝如budget_exceeded本来即为ModelError，同样导致当前failed、后续not_attempted和整体stopped。主控已补充说明；先前独立联验验证了成功前缀、预算拒绝和未知占用保留，不是本轮新增代码缺陷。
3. 设计/实现/真实验证：正文未将合成usage、固定mock或live_called=false当作真实token/来源/账单认证。设计审查通过仍不能替代运行验收，Python可信回调也不等于网络沙箱。该边界保留，NLP-01等父任务不升级。

原WB文件保留，不以主控后见澄清覆盖其原文。此次仅复核文档，产品哈希未变，未重复112项联验；普通安装和主控示例运行结果由主控验收记录单列。
