# Batch 05 独立代码审查与预算验收

任务：QA-B05；执行者：独立审查 Agent。输入基线：68e4702；本轮实现位于共享工作区。契约：docs/contracts-v0.1.md，尤其 R08；本轮仅验收注入传输接口和离线预算节点，不代表真实模型供应商接通。

## 当前状态

结论：**当前离线注入式模型节点子集通过独立审查与验收**。无未解决的本轮阻断问题；NLP-01 原始完整范围仍有真实供应商传输、真实费用/usage、候选数上限和账本备份等缺口，不应整体标为全部完成。审查者仅写本文件，产品与测试文件由实现者独占写入。未调用真实模型、未读取凭证、未修改 Git。

## 初审发现与交接

1. 缓存映射需要同时验证 `calls.cache_key` 与当前请求键一致，否则错误映射到另一份同 schema 的成功调用时，输出哈希和 schema 均正确但内容属于其他输入。实现者已补请求归属校验；定向回归及独立污染案例均通过。
2. 传输层编程异常不应与明确可重试超时混为一类。实现者已区分 Timeout、TransientTransportError 和其他异常；未知异常保守记账后停止，不保存异常原文。对应回归通过。
3. 非空输入与非空输出的零 token usage 不应作为可信结算依据。修复后 0 usage 不退预留；负数、布尔、缺一项或超限 usage 拒绝成功并保留预算。对应回归通过。
4. 调用记录应保留安全版本与参数元数据、输入 hash 和原始成功输出。实现者已加入 request_metadata，并保存已验证的原始响应字符串及 SHA；独立午夜案例核对原始空白字节和版本记录通过。
5. 巨大 JSON 整数参与 `math.isfinite` 时可能触发 OverflowError。实现者改为仅对浮点执行有限性检查，JSON 整数按整数语义验证；大整数 number schema 回归通过。
6. WorkBuddy 子 Agent 后续发现 `_strict_loads` 将其自行抛出的 `ModelError(ValueError)` 捕获并改写为通用解析错误，丢失重复键和非有限值的具体原因码。实现者增加 `except ModelError: raise`，审查者只读复核该最小差异并重新运行定向测试，新增精确错误码、账本占用、无输出留存和无缓存断言通过。
7. WorkBuddy 完整报告回收后，按主控处置补齐 SQLite 稳定错误、解析后时间比较、估算口径分列、Barrier 同时争抢和三次无效 schema 重试回归。实现者还将当次两项费率与估算 basis 写入 request_metadata，并拒绝 falsey 非 Policy 配置，避免静默替换默认值。最终独立定向回归通过，详见下文。

## 最终验证

实现者明确交接代码稳定后，审查者独立执行以下命令（shell 进程内设置 PYTHONPATH 和 TEMP/TMP，仅影响该进程）：

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
$taskTemp = Join-Path $PWD 'out/qa-batch05-temp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
& ./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_llm.py -v
```

首次真实结果：30 项定向测试全部通过，`Ran 30 tests in 2.929s`，`OK`，退出码 0。WorkBuddy 错误码修复后，同一命令 31 项通过（3.478s）。完整发现回收及必要补充修复后，最终独立验证：**38 项全部通过，`Ran 38 tests in 3.679s`，`OK`，退出码 0**。覆盖默认关闭、无传输、版本缓存、输入/输出限额、错误 JSON/schema/usage、预算拒绝、超时与重试、并发、pending 重启、跨日、缓存污染、原始输出记录及精确错误码。

最终新增结果：

- SQLite 真实连接持有 `BEGIN IMMEDIATE` 写锁，客户端可先读缓存，但在预留时遇到锁超时；测试将等待缩至 10ms，得到固定 `ledger_busy`，未进入 transport、未写调用行，所有打开连接均关闭。连接初始化/建立异常转换为 `ledger_error`，测试底层路径标记没有进入错误字符串。
- 两线程在 Barrier 同步释放后同时请求仅够一笔的额度，恰有一笔成功、另一笔 `budget_exceeded`，只生成一条调用；不能将此 mock 并发当作云端真实并发验收。
- 恒定 schema 无效且 `max_retries=2`，实际三次尝试均保留全额预算，无成功输出和缓存；这是明确有界重试取舍。
- UTC 时间先解析再比较；同一时刻不同合法小数秒精度可以结算，持久化时间缺 UTC 被拒且 pending 不退款。
- `usage()` 明示 `accounting_basis=configured_rate_estimate`，分列已报告 usage 与预留/未知占用，两部分和等于总额；即使有 token usage，金额仍是配置费率估算，不是供应商结算。每条 request_metadata 保存当次输入/输出费率与 basis，可审计原估算依据。

另外使用同一解释器执行独立内联 Python 验证脚本，临时目录独占于 `out/qa-batch05-temp/independent-*`，没有写产品/测试或访问真实工作库。三个实际场景均通过，退出码 0：

1. **真实双进程与强制退出**：进程 A 完成原子预留后进入等待；进程 B 对同一账本请求预算，得到 `budget_exceeded` 且未进入 transport。随后仅终止本次创建的 A，重开客户端可见 1 条 pending，下一请求仍被预算拒绝。这比线程用例进一步核实了 R08 与进程突然退出后的保守占用。
2. **超时跨 UTC 午夜后重试**：第一次尝试于 11-08 23:59:59 预留，transport 将时钟推进至 11-09 00:00:01 后抛超时。第一次记录仍归 11-08、全额保留；重试归 11-09 并按可信 usage 4+5 结算 9 token。成功原始响应的空白、版本元数据保留，异常测试标记未出现在数据库字节中。
3. **跨请求缓存污染**：为不同输入创建返回 `v=1` 和 `v=2` 的两条有效成功调用，再将第一条 cache 映射指向第二条。重新请求第一输入得到 `cache_integrity_error`，没有新 transport 调用；不能用另一条真实、哈希正确的输出冒充当前输入。

WorkBuddy 发现处置后的最终工作区文件 SHA-256（不是 Git 规范化后的 blob SHA）。上述三项独立内联演练在先前版本执行；后续定向回归覆盖必要补充变更，没有将先前运行伪称为最终版本重新执行：

| 文件 | SHA-256 |
| --- | --- |
| src/market_intel/llm/client.py | 2ec3161a00087cfffe4c5b2b7f53dd0909add13d0132f230980596520a9b60e0 |
| src/market_intel/llm/__init__.py | a4fd01b95247642aee4609375766e769809968b2659341b01a2ec7dfabdde289 |
| tests/test_llm.py | fff38dc5417c31500b7cc082a8c2a5d532367f0371949342a0d246749a7d1009 |

## WorkBuddy 子 Agent 产物回收与处置复核

已读取 WorkBuddy 自行写入的 `collaboration/workbuddy/results/WB-05-report.md` 和 `WB-05-results.json`，JSON 可解析，`subagent_used=true`，两名 Explore 子 Agent 均记录 `result_returned=true`。主控另在桌面观察了真实委派、两名成员和返回结论；本审查者没有独立操作 WorkBuddy UI，所见证据为正式产物及主控交接。

两名子 Agent 承担设计审查；代码在其执行期间生成后的静态实现复核由 WorkBuddy 主端追加完成。WB 明确 `tests_run=0`，不能把实现者、QA 或主控的测试写成 WB 执行。交接中的 signature 文本仅为标记，不是密码学签名。

主控逐项处置见 [batch-05-workbuddy-triage.md](batch-05-workbuddy-triage.md)。已只读核对 F-01～F-12：F-03/04/06/07/08/11 的必要实现与回归已通过；F-09/10 由主控同步验收清单与公共契约；F-12 保留未运行测试事实。F-01（任意切换 state_path 无全局额度控制）、F-02（pending 人工对账/终态入口）和 F-05（模型账本恢复）仍是明确生产缺口，未被写成已解决。当前仅启用 mock，接受本轮子集不会解除真实 provider 前置门槛。

## 行情来源产物边界复核

已只读检查 `docs/market/capability-review-20261108.md`、`probe-results-20261108.json`、`config/instruments.example.json` 和 `config/calendars.example.json`。没有重复网络探测，也不将来源 Agent 的观察冒充本审查者访问。

报告明确 partial、生产 OHLC 未验收；两个配置均 `evaluation_enabled=false`，标的 provider/快照为空，日历标注为规则候选而非会话快照。保留 Python TLS 失败与 Node 有界成功的区别，不以动态框架或历史月报替代生产价格接口。开盘集合竞价与供应商 bar.open 形成时点的歧义被列为 REV 前置问题。未发现需阻断本轮文档交付的问题；MKT-02 真实数据前置仍不满足。

## 未验证与后续边界

- 没有真实云模型、tokenizer、HTTP 超时、供应商 usage 或账单验收；`provider` 仅允许 mock 启用。
- Python 可调用 transport 是受信任代码，必须履行 timeout；本客户端不能强制终止任意同步函数。
- 费率为合成整数 microUSD；不能证明真实费用精度、折扣或结算一致。
- 模型账本与证据库独立，现有 evidence backup 不覆盖它；不能删除/回滚账本重置预算，真实调用仍关闭。
- 模型结构校验不证明事实支持或提示注入抵抗；NLP-02、正式报告、行情评价和运行验收仍待开发。
- 本报告不替代主控的全量回归、安装验证与最终发布核对。
