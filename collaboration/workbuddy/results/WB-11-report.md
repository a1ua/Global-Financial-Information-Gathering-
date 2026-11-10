# WB-11 失败响应关联静态审查 — 结果报告

## 执行与状态

- task_id: WB-11
- status: completed（未触发 blocked：普通同步阻塞子Agent能力可用，且一次调用即返回完整实际正文）
- execution_mode: 恰一次普通同步阻塞只读子Agent调用；run_in_background=false；未设 team/name；契约全文内嵌于子任务提示；子任务被明确禁止调用任何工具、读写文件、联网、运行命令或测试。
- subagent_used: true；raw_result_recovered: true
- tests_run: 0；finalized: true

## 父端范围（如实记录）

- 仅只读：collaboration/workbuddy/WB-11-task.md 与 docs/contracts/provider-failure-correlation-v0.1.md 全文。
- 未读取代码、配置、环境、密钥、运行数据或其它会话；未运行命令/网络/测试；未操作旧WB任务。
- 仅写本文件与 collaboration/workbuddy/results/WB-11-results.json；写入前已确认两者均不存在，属新文件，定稿后不覆盖。
- 不编造时间：任务单与工具回执均未提供可引用的执行时间戳，故本报告不记录任何时间。

## 实际工具回执

本次同步子Agent调用的工具返回中所携带的实际回执标识（原样）：

`[Agent ID: agent-c565773a-df53-48da-a3b3-df06d7cd494c]`

工具返回除该标识与下方完整正文外，未提供其它可记录的元数据（无时间字段、无文件读写、无命令或测试输出）。

## 子Agent完整实际正文（原样，未改写、未删减）

1) 依据「只保存已收到响应的completion ID哈希观察」「无响应超时/瞬时错误不关联」「非ObservedTransportError的异常即使有同名属性也不采信」与「每次尝试重置failure_hash=None」，无响应造关联由构造路径、异常类型、白名单、重置四重约定拦截。但「已收到响应」被窄化为「已解析dict、model恰deepseek-flash、存在合法id」，且明确允许「同model合法id+不完整finish/usage失败可观察」；hash「不是…签名或可信高水位」，共享校验只约束 64 位小写 hex 格式及持久化层互斥/失败状态，对「该 hash 确来自真实已收响应」无数据层可验证性，若错误响应体在 `_parse` 内被解析成带合法 id 的 dict，仅剩「不从HTTP错误体或header提取标识」这一文本约束。

2) 依据「不传失败response给_finish计费」「失败usage/输出列继续null，charged_tokens/cost保持原reserved」「provider_failure…与status/finished_at/error同事务提交」「异常中断未提交仍pending且无观察，保留全额」，失败写入与状态/费用原子绑定且「不能让观察释放费用」。残留边界是「每次retry独立行，不继承上次hash」叠加每行「保持原reserved」「旧失败/成功/缓存无字段不回填」，重试链会留下多行各自全额占用而契约未定义其去重/汇总；且「真实usage、逐调用账单、结算与pending释放未验收」，全额只是当前不释放的预占态，「坏关联或hash重算仍不能释放」仅断言不得释放，未定义 pending 何时、经何路径释放及与观察字段的交互。

3) 依据「schema_version升级为model-call-info/0.2（字段集合保持26个，使用方应识别新版本）」「旧格式账本仍读，不迁移/回填」「旧行absent语义不变」「备份/隔离恢复/预检保留原metadata字符串」「schema3/原列不变」，0.2 为纯版本号升级、旧行仍可读。残留边界是兼容责任被「使用方应识别新版本」外推、未定义未升级消费方遇 `failure_recorded` 的降级行为，0.1 的 absent 与 0.2 的 failure_recorded 长期并存却不迁移，跨版本对账口径由使用方承担；备份虽「自动验证新字段」并「继续检查失败列为空及全额占用」，但「缺键/类型错误统一ValueError('provider_correlation_invalid')」的失败粒度（逐行或整库阻断预检）未定义，且「自洽hash不授予生产切换」把恢复数据排除在生产关联/结算之外，「真实usage…结算…未验收」。

## 结论

三点分别覆盖任务单要求的边界：无响应不能造关联；失败/重试全额与同事务；摘要0.2及旧账本/备份兼容的边界。以上均为纯静态只读审查结论，未执行契约「验收」中的回归485项、独立验证或模拟HTTP/真实API分列（tests_run=0）。

WB-11 FINALIZED
