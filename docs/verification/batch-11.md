# Batch11：失败/不完整响应关联验收

日期2026-11-10。基线本地445845860e09939c19b0fc8e33e8907dd9043a89、GitHub1a6d462d512208ecd43d7da2d547ab6602f15f26。只做离线合成与注入HTTP；不读取真实key、刷新来源或调用付费API。

## 实现与契约

独立QA先复核设计后冻结contracts/provider-failure-correlation-v0.1.md。主控负责安全异常载体、纯schema、client事务和集成；transport_b11负责DeepSeek包装，inspect_b11负责摘要0.2；独立qa_b11仅写审查报告。分工见../../collaboration/batch-11-plan.md。

DeepSeek只在既有解析失败且code在安全白名单、dict模型匹配、id合法时传ObservedTransportError(code,hash)，不改原错误优先级。HTTP/网络/超时/前置JSON或线体超限无观察；不是供应商额外API字段或账单认证。正常ModelResponse的hash先合法才可供后续本地校验失败观察。异常hash突变非法/null则丢观察；普通异常同名属性不采信。

provider_failure只含版本/hash，与失败状态同一事务存储；usage/失败正文列仍null、charged保持reserved，无缓存。重试每attempt重置观察，旧成功/失败/缓存不回填。备份既有完整业务验证调用共享校验，自然继承互斥/状态/类型校验和全额检查；模型schema3/证据4不变。model-call-info默认schema0.2、26字段，failure_recorded明确失败观察；invoice_verified/settlement_allowed/model_called均false。

## 实际测试

- 主控25项新增测试全部通过，1.964秒；传输Agent33项全过（8新增+25旧），0.040秒；查询Agent16项全过（4新增+12旧），3.126秒。计数重叠不相加。
- `./scripts/dev.ps1 test`完整510运行507通过3符号链接权限跳过，60.420秒、exit0，日志out/batch11-tests.log；实际junction测试通过。
- 独立QA179项178通过1 OS symlink权限跳过，17.254秒、exit0；另6自构造场景全部通过，1.345秒，合计185执行184通过1跳过。包括模拟HTTP缺usage到CNY摘要、提交前pending无观察、备份自洽重算非认证/减少费用拒绝、三attempt隔离、载体属性删除及秘密args不泄漏、非法Unicode只留hash。独立场景首跑因自写路径使用junction别名6项setup拒绝，改为物理临时路径后通过，非产品缺陷，细节见batch-11-review.md；不与主控重叠计数相加。
- 普通隔离安装`TEMP/TMP=工作区out/test-temp ./scripts/setup-env.ps1`，项目外help、明确合成demo、全套510运行507通过3跳过，63.610秒、exit0；证据`.venv/setup-runs/20261110-133522-23fc8c72/`，日志out/batch11-install.log。
- `.venv/Scripts/python.exe -I -X utf8 out/verify-b11-installed.py`：导入site-packages已安装包，注入不完整HTTP响应，在项目外工作目录调用已安装model-call-info。返回0.2/failed/failure_recorded/hash一致，CNY全额预留13298 microCNY、5113 tokens保持占用，input/output tokens均null，无失败正文/原ID，权限标志全false，exit0。仅模拟，未发真实请求；摘要out/batch11-installed-verification.json及合成库留out。

环境恢复：两次原命令启动失败CreateProcessWithLogonW 2，节点通道确认7版PowerShell路径不存在，但系统内置PowerShell路径可用；随后显式选择该路径，正常执行项目脚本。未绕过Git写入审批，不把入口失败解释为项目测试失败。

WB-11完整正文及两结果文件已回收，界面观察一次同步子任务返回；底层工具日志非独立认证、review且tests_run0。元数据探测权限错误与三点意见处置见batch-11-workbuddy-triage.md；本批无产品行为追加，不把辅助静态意见计作测试。

## 限制与交接

哈希观察不是HTTP请求ID/来源认证/账单凭证/签名或外部可信高水位。没有失败raw/body/usage原文，不能凭hash确认是否扣费，更不能自动释放pending。SQLite/WAL可维护协调文件，绑定和库非跨文件原子，不抵抗特权改写/回退或恶意换链。NLP-01整体和完整闸门未升级。

下一项只读供应商验证证据预检：整理成功/失败观察与外部凭证缺口，保持不认证/不结算；真实模型、逐调用账单/usage、可信高水位、生产恢复仍需前置证据。最新计划development-status-plan-20261110-batch11.md。运行产物/凭证/对话与output/tmp不提交，GitHub发布实际核验后归档。
