# 第六批：DeepSeek人民币预算与模型账本恢复

日期2026-11-08；本地基线79cafc2、远程518a534。用户确认DeepSeek每日人民币10元。本轮范围及唯一写入者见 `collaboration/batch-06-plan.md`；期间因额度中断后按落盘文件恢复，没有将中断的Agent当作交付成功。

## 交付结果

- 模型账本schema1→2追加day.currency；历史USD调用、缓存、额度和费用占用保持，不换汇、不重置。证据库schema4不变。
- CNY采用micro单位，1元=1,000,000 microCNY，日上限10,000,000；输入和输出每百万token费率分别向上取整。调用元数据留存当时币种、费率和估算依据，CNY用量不显示为USD。
- DeepSeek只允许固定官方端点、deepseek-flash非思考JSON请求；默认TLS，无环境代理继承或重定向，无工具、流式或参数覆盖；校验响应模型、usage、完成状态、字节上限和本地schema。异常输出不释放未知费用，安全错误码不含密钥/响应正文。
- 模型账本一致备份、严格验证与新目录隔离恢复，保留WAL已提交状态、pending、日币种/额度、费用和缓存闭包。未知未来schema或坏业务数据即使重算文件hash也拒绝。历史无generic元数据记录按其原规则归档，不宣称符合新版未知usage token上界。
- CLI新增deepseek-check、deepseek-smoke、ledger-backup、verify-ledger-backup、restore-ledger。check不读取密钥、不建库；smoke必须显式--live且配置本地DEEPSEEK_API_KEY，未满足即先拒绝。恢复目录的隔离清单不能直接用于live。

模型接口仍未接入正式简报。NLP-01的真实供应商验证、人工账单对账和生产切换尚未通过，主任务维持in_progress；NLP-02本轮未派发，正式抽取、报告、行情评价和调度继续后置。

## 官方资料与预算口径

核实日期2026-11-08。[官方模型/人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)列出deepseek-flash；本配置按高峰缓存未命中费率：输入2元/百万token、输出8元/百万token，不使用空闲或缓存折扣降低预留。[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)及[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)用于请求与响应实现。

10元是同一工作区账本、UTC自然日、配置费率估算上限，**不是DeepSeek账户的全局硬限额或供应商账单**。其他程序、换账本、旧备份回退及供应商涨价不由本地估算自动覆盖。实际tokenizer上界和计费尚未验证，保守字节上界含4096消息余量是工程假设。同步DNS和底层连接不能强制硬墙钟终止；连接返回后及发送/headers/body检查剩余deadline。

## 实际验收

主控源码第一轮 `./scripts/dev.ps1 test`：257项，256通过、1跳过，退出0，日志 `out/batch06-tests.log`。随后独立QA发现新版无可信usage输出的备份复核缺口，补两项正负回归后完成最终安装验证。

最终 `./scripts/setup-env.ps1`：普通隔离安装、pip check、site-packages导入、时区、项目外CLI/demo及 **259项测试：258通过、1跳过，退出0**。证据目录 `.venv/setup-runs/20261108-200704-fc2bd8fe/`，日志 `out/batch06-install.log`。唯一跳过是既有Windows实际创建符号链接权限限制；mock链接拒绝分支有覆盖。

独立QA验收63项唯一模块定向测试：传输19、账本恢复28、CNY10、CLI6，均通过；另4组独立场景核实分项ceil/恢复与币种篡改、旧USD逐列迁移不变及同日币种隔离、401单次保守占用与密钥边界、新版未知usage超界后重算hash仍被拒绝。详见 `batch-06-review.md`，不把合成HTTP结果冒充实网。

CLI测试首次误将stdlib gettext读取语言环境变量一并禁止，已将断言限定为DEEPSEEK_API_KEY；产品入口未因此放宽。备份回归按新旧元数据区分，避免为新校验改写历史输出或费用。

## WorkBuddy勘误与本轮协作

WB-05执行端在上轮上传后补发终版，披露初版摘要在完整子Agent回传前提前编写，修正子Agent是否追加实现审查及若干事实口径。两份原始终版保留，主控历史triage已补勘误，QA独立说明文件自述、UI派发观察和真实代码测试的证据边界，不能把文本签名当密码学证明。

WB-06只读三份固定文档，实际派发两个子Agent。最终两份文件已收到并解析，finalized=true，但状态为blocked：工具层没有取回可引用的完整子Agent结论，原始发现为空，主端撤回此前UI上的“已收到完整结论”表述。tests_run=0，不把派发/完成状态或主端推断当成独立审查通过。5项主端静态推断的文档澄清与生产缺口处置见 `batch-06-workbuddy-triage.md`，未因此修改产品代码或重复测试。

其间主控收敛请求已入队；尝试停止任务被自动审批拒绝（可能丢失未保存审查结果、缺少明确终止授权），操作未执行。任务随后自行定稿，不再需要终止授权。WB-06保持blocked，不阻断已独立验收的代码发布，也不将其标为完成或代写结果。

## 后续任务流与发布

1. 用户在本地安全配置密钥，显式执行一次合成smoke，核对真实返回、usage、费率和保留额度；本轮没有执行真实请求，也未读取真实密钥。
2. 完成固定生产账本身份、人工对账与受控恢复切换，再考虑生产模型处理。不得通过恢复旧快照、换文件或释放未知pending增加可用额度。
3. 进入NLP-02的候选上限、抽取分类、逐字证据绑定和独立质量评测，再推进正式报告；行情来源与日历前置仍独立验证。
4. 完整G3–G5、运行观察与用户价值验收保持未完成。

提交范围仅源代码、合成测试、配置样例、计划和验收文档；data/out/.venv/真实账本/凭证不入库。最终提交和远程文件树验证结果在实际发布后记录，不能以本计划代替上传。

实际代码发布：本地 `0a2ad279aef6cba164c2241bd5b084d0bacc2ba8`，GitHub main `95abae0e4a8f795ebea615704d2f4b7b650f64cf`，双方tree为 `27fbe6ec271650bc371a9225b73aef27088ee9b9`。通过授权连接非强制更新，并重新读取分支核验。103个追踪/待追踪文件的常见token/私钥/应用会话值模式检查无命中，差异检查通过。代码发布时WB-06未回收，随后收到的blocked定稿及主控处置作为文档归档，不计已完成验收；产品代码不再改变。
