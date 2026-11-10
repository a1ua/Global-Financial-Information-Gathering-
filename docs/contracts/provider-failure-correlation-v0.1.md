# 失败响应关联 v0.1

2026-11-10，Batch11，扩展Batch10成功关联，不回写旧调用。只保存已收到响应的completion ID哈希观察，不保存失败正文、原ID、响应头或不完整usage。不是HTTP请求ID、账单证据、签名或可信高水位。无真实API启用。本地格式沿用ASCII1..256/原字节SHA256，不对官方新增字段做假设。

设计经独立QA无阻断复核后冻结。异常载体hash若遭突变为非法/null，客户端丢弃观察并保持原安全错误/全额，不让二次校验错误泄漏；正常响应仅hash通过后才能暂存failure_hash。所有失败计费仍不传response给_finish。

## 载体与传输

client.py定义`ObservedTransportError(ModelError)`，构造(code,response_id_sha256)，code严格小写固定码格式[a-z][a-z0-9_]{0,79}，hash必须非null且64小写hex；错误构造统一ModelError('invalid_provider_observation')。实例仅保存安全code及hash，不保存raw result/text/header/usage，str仍code。transport抛出它时原有ModelError错误码白名单和不重试规则不改变；不把hash作为重试/结算/身份凭据。

DeepSeek既有_parse主体移为私有辅助，wrapper调用它，成功返回保持不变。仅捕获其ModelError且其code在既有ERROR_CODES中；只有已解析dict、model恰deepseek-flash、存在合法id，才用ObservedTransportError携带code/hash。否则重抛原错误，优先级不变；非法id不覆盖先前的usage等错误。缺id、错误model/JSON、HTTP失败/超时/网络/超限在_parse外发生时均不附关联。不从HTTP错误体或header提取标识，不增加API字段假设。

ModelClient每次尝试重置failure_hash=None；收到ObservedTransportError且其hash仍通过共享校验，使用该hash，但错误码仍原白名单和retryable=false。若正常ModelResponse已通过hash校验，随后usage/输出schema/JSON/长度检查失败，则保留其hash作为观察；非法hash本身不保留。无hash不创造关联。非ObservedTransportError的异常即使有同名属性也不采信；无响应超时/瞬时错误不关联。只持久化安全hash，不传失败response给_finish计费。

## 持久化纯契约

既有request_metadata新增可选`provider_failure`严格对象仅schema_version='provider-failure-correlation/0.1'、response_id_sha256（非null/64小写hex）。共享correlation.py新增`validate_provider_failure`，并扩展validate_call_correlation：provider_failure与provider_response互斥；failure只允许call.status='failed'且input_tokens/output_tokens均恰null；成功仍按10批原规则。缺键/类型错误统一ValueError('provider_correlation_invalid')；兼容sqlite.Row，不强制dict调用行。

_finish新增仅内部failure_hash=None参数，只在failed时写合法非空provider_failure，与status/finished_at/error同事务提交。失败usage/输出列继续null，charged_tokens/cost保持原reserved，无缓存插入；成功关联逻辑不变，不能让观察释放费用。异常中断未提交仍pending且无观察，保留全额。每次retry独立行，不继承上次hash；旧失败/成功/缓存无字段不回填。

ops/llm_backup._ledger既有validate_call_correlation调用自动验证新字段，继续检查失败列为空及全额占用；备份/隔离恢复/预检保留原metadata字符串，自洽hash不授予生产切换。schema3/原列不变。真实usage、逐调用账单、结算与pending释放未验收。

## 只读摘要

inspect_model_call和现有model-call-info CLI摘要schema_version升级为model-call-info/0.2（字段集合保持26个，使用方应识别新版本）。新provider_failure有hash时correlation_status='failure_recorded'且response_id_sha256为该hash；既有成功recorded/id_unavailable与旧行absent语义不变。旧格式账本仍读，不迁移/回填。固定invoice_verified=false/settlement_allowed=false/model_called=false，无failed body/metadata/原ID输出。查询仍绑定schema3单只读BEGIN全库业务验证、路径/身份/错误脱敏，0成功1错误，无新live/force/settle入口。

## 验收

非法/缺失/额外字段/互斥/错误状态、失败usage列非null拒绝；Observed错误安全构造/秘密不出错码；同model合法id+不完整finish/usage失败可观察、缺id/坏id/错误model不造；正常响应输出错可观察、无响应超时无观察。重试上次hash不继承、未知费用全额、失败更新事务回滚pending、缓存不补写。备份恢复保存新字段，坏关联或hash重算仍不能释放；只读CLI升级0.2且失败摘要不泄正文。回归旧485项、独立验证，模拟HTTP与真实API分列。
