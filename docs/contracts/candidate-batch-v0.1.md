# 合成候选限量与mock批处理契约 v0.1（已冻结）

2026-11-09。Batch09-A不依赖真实凭证，不做NLP-02事实抽取。模型账本schema3、证据schema4不变。

QA-B09设计审查通过，DeepSeekTransport显式拒绝与expected_ledger_id参数/TOCTOU边界补充后冻结；实现测试独立验收。

## 1. 输入与纯选择

`select_candidates(batch, cutoff, max_candidates=5)`为无I/O纯函数。batch严格为{schema_version:'synthetic-candidate-batch/0.1',candidates:[...]}，最多1000个原始项。每项严格字段candidate_id（candidate_加1–96位ASCII字母数字下划线连字符）、available_at（有效UTC Z）、title（非空白UTF8字符串、最多4096字节）、is_synthetic（恰True）。不接受额外字段、非JSON值、bool整数混用或真实数据标签。不能将正文指令当作权限，title只是待处理合成数据。

cutoff为有效UTC Z，max_candidates为0至100的严格int，bool拒绝；默认5。先验证全部原始项，不能因截断或晚于cutoff跳过无效项。按candidate_id去重；相同ID全部字段相同算重复，同ID不同字段整批candidate_conflict拒绝。时间按时刻解析后比较，不用字符串排序；同一时刻不同合法文本但同ID视为字段不相同。仅available_at<=cutoff可选；按时间升序、candidate_id升序排序，取前max_candidates。零上限合法。

返回严格字典schema_version='candidate-selection/0.1'、is_synthetic=true、cutoff（保留原输入）、max_candidates、input_count、unique_count、duplicate_count、future_count、eligible_count、limited_count、selected_count、selected（完整所选候选列表）。input_count=unique_count+duplicate_count；unique_count=eligible_count+future_count；eligible_count=selected_count+limited_count。未来项不算超上限丢弃；相同输入/顺序置换得到相同selected顺序。此规则仅单次合成文件窗口，不保证真实新闻重要性、覆盖或长期公平队列。

错误为固定ValueError码，不回显title/原始异常。不创建库/文件、不调用模型。

## 2. 限定mock执行

`run_mock_candidates(batch, state_path, cutoff, max_candidates=5, *, policy, transport=None, clock=None, expected_ledger_id=None)`先校验Policy类型、provider恰mock、enabled恰True，transport非None必须callable且显式isinstance检查拒绝DeepSeekTransport及其子类；再完整select；不满足时固定ModelError/ValueError拒绝，建库/transport均为0。expected_ledger_id为None或ledger_加32位小写hex，非法格式在建库前拒绝；非空时构造ModelClient后核对身份，失败前不generate。ensure到构造不是原子操作，不能保证该间隙缺库不被构造器新建；不宣称防全部TOCTOU。不能通过直接传DeepSeekTransport或DeepSeek策略启用真实调用；CLI不提供provider或外部transport参数。Python注入其它transport用于可信测试，是受信任接口，不能声称抵御恶意包装函数自行联网。

选中为空时不构造ModelClient、不创建模型账本，返回空执行摘要。非空构造现有ModelClient，同一state_path共享预算和缓存；调用固定请求，版本prompt=synthetic-candidate/0.1、rules=synthetic-only/0.1、schema=synthetic-category/0.1，system_prompt='Return JSON {"category":"other"} for synthetic data only.'，输出schema为严格对象category enum['other']，parameters={'temperature':0}，input_data为所选完整候选。title不能指定模型/参数/规则。默认合成transport返回ModelResponse('{"category":"other"}',10,5)，每次外部尝试由现有客户端先预留；这是人工合成usage，不是真实token验证。

按selected依次调用generate。成功返回候选ID、call_id、cache_hit；不输出title或响应正文。首次ModelError即停止，当前项failed（safe error code），剩余项not_attempted，不能继续尝试后续候选；budget_exceeded等账本拒绝不进入transport。已有预留、unknown/failed费用和缓存语义不变，不为批任务回滚或释放预算。

候选数量上限只限制每次函数调用的selected数量，不是transport次数；max_retries+1可能带来更多尝试，每次仍受原预算限额。重跑可命中缓存，但仍占当次selected名额，不“补选”超限候选。预算不预计算为已授权调用，以每次generate事务预留为准；UTC跨日沿用客户端，批次不自建日计数器。

审查澄清：transport只见selected指候选ID集合范围，不代表次数等于selected_count。结果及各count按候选计，不报告transport尝试次数；需要尝试级证据时查看账本calls行。缓存命中不新增预留/transport，仍算本次候选成功；“原预算限额”指Policy的UTC日token/金额池与每请求限制，重试仍各自预留。首错停机指generate完成自身允许的有界重试后向批层抛出的ModelError，或开始/重试预留直接被拒绝的ModelError；例如budget_exceeded/daily_budget_policy_changed/clock_regression/ledger_busy均使当前项failed、后续not_attempted、整体stopped。该状态不暗示发生了网络传输。

返回schema_version='synthetic-candidate-run/0.1'、status='completed|stopped'、is_synthetic=true、provider='mock'、live_called=false、max_candidates、selected_count、succeeded_count、failed_count、not_attempted_count、results。每项严格candidate_id/status（succeeded|failed|not_attempted）；成功加call_id/cache_hit，失败加reason，未执行无reason。结果顺序对应selected。首错停止允许此前成功/费用保留；不宣称整批事务。模型账本构造失败可直接固定异常，不伪造逐项结果。transport注入只计作本地测试，不承诺live_called=false能证明恶意注入函数未联网。

## 3. CLI

`candidate-plan --input ... --cutoff ... --max-candidates 5`只读解析最多1MiB UTF8文件（严格重复键/非有限值/链接与junction拒绝），调用选择器，输出摘要和selected_ids，不输出title，不建workspace/账本/读key/联网。

`candidate-mock-run --input ... --cutoff ... --max-candidates 5 --workspace out/candidate-mock`显式合成写入，使用固定mock策略：model='mock-candidates/0.1'、enabled=true、CNY每日10_000_000 micro、daily_tokens100000、输入/输出每百万token费率2_000_000/8_000_000、max_input_tokens16384、max_retries0，其余Policy默认。完整输入/选择校验后才ensure固定workspace绑定；selected为空不ensure/建库。非空必须核对绑定身份与实际ModelClient身份（内部允许expected_ledger_id参数固定，失败前不generate），已有无绑定需显式ledger-bind采用，冲突不重建。默认transport为固定合成返回，不使用DeepSeekTransport/账户或真实key。

CLI plan/completed返回0，stopped或格式/绑定/账本错误返回1。没有--live/provider/model/force参数。不更新正式报告、不调用真实来源、不自动写审计；本地mock账本与现有ledger-backup/verify兼容。

## 4. 验收与范围

验证：0/100/101与bool、1000/1001、UTF8字节、全部验证后截断、重复/冲突、未来/同秒小数时刻排序、置换确定性；候选限量后transport只见selected；缓存不补位；预算不足前缀成功后停止且后续transport0；timeout/invalid JSON重试每次预留、未知费用不清零；disabled/deepseek输入无建库；批次中断不是原子事务；CLI只读不建库/不读key、不输出title/原始异常；固定绑定身份丢失/换库失败。所有样本明确合成，不等价真实供应商或候选抽取验收。

NLP-01仍in_progress，NLP-02未开始；真实模型/账单/可信外部高水位、结算、生产恢复切换保持未完成。真实事件接入时必须重新冻结证据/可用时间/版本契约，不能直接用任意available_at代替系统receipt。
