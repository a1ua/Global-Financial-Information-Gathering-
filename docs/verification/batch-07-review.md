# Batch 07 独立验收

任务：QA-B07。输入契约：`docs/contracts/ledger-binding-v0.1.md`；证据库仍为 schema4，本批仅模型账本升级为 schema3。审查者只读实现与测试，仅维护本文件；不执行 Git 写操作、真实模型请求或凭证读取。

验收时间：2026-11-08T13:06:00Z。结论：**本批固定工作区身份/路径绑定及备份兼容子集通过独立离线验收，未发现待修复的实质缺陷**。父任务 NLP-01 不据此标记完成；真实供应商、账单对账和生产恢复切换未验证。

## 审查范围与已知限制

绑定只约束固定工作区入口，防单边状态丢失、不同身份替换和移动后的误建库。两文件同时不存在按契约允许初始化；不检测同身份旧快照回退，不提供跨工作区或账户总额度防护。直接 Python `ModelClient` 是受信任接口，隔离恢复不等于生产恢复切换。

WB-06 两份结果现记 `partial`，声称回收 `wb06-recovery` 一份正文，另一份 `pending/not_received`，自述运行测试和命令均为 0。这些文字仅作为设计审查与交接记录；本独立审查未核实其原始子 Agent 工具回执，不能将自述当作独立实现验证。WB-07 若未回收完整结果，也不能等同于审查通过。

## 验收记录

稳定交接后，在真实工作区使用 `.venv/Scripts/python.exe`，`PYTHONPATH=src;tests`，`TEMP`/`TMP` 指向工作区内 `out/qa-batch07-temp`，实际执行：

```powershell
& ./.venv/Scripts/python.exe -X utf8 -m unittest test_ledger_binding test_identity_migration test_batch06_cli test_llm_cny test_llm_backup test_llm test_deepseek -v
```

退出码 0，**133 项：132 通过，1 跳过**，用时 11.286 秒。跳过的是实际符号链接创建，原因是 Windows 本地权限不足；实际 Windows junction 祖先拒绝测试通过，模拟链接分支也通过。此前独立执行绑定 19 项也是 18 通过、1 跳过；这 19 项已包含在 133 项中，不能累加计算。

| 验证面 | 实际覆盖及结果 |
| --- | --- |
| 迁移与预算 | schema1 USD 迁移、CNY 明确单位、10 元上限/分别向上取整、同日币种与策略变更拒绝、未知费用保守保留均通过 |
| 身份稳定 | 初始化不消耗预算注入时钟；重启身份不变；schema3 缺身份不重建；已有实例换库/删库拒绝均通过 |
| 绑定与接管 | 预检不建目录、不读 key；未绑定库默认拒绝，显式接管保留成功/cache/pending 行与金额；缺库、丢绑定、不同身份替换、移动路径、非法 JSON/重复键/额外字段、空库中断状态均通过 |
| 并发与路径 | 并发初始化只有一个初始身份，不覆盖绑定；文件与祖先链接拒绝、实际 junction 拒绝通过；真实 symlink 权限项如上跳过 |
| CLI | 无 live 不读 key；缺 key 不预留不建库；合成 HTTP 验证/缓存可用；ensure 后实例身份再次匹配；隔离恢复标记禁止 live，均通过 |
| 备份兼容 | schema1/2 使用 manifest0.1，schema3 使用 manifest0.2 且 ID 与库严格一致；缺失/非法/多身份、清单身份篡改及库身份改变后重算 hash、版本降级/缺字段/多字段均拒绝；pending、费用和缓存闭包、WAL 一致快照、隔离目录恢复均通过 |

另用 stdin 独立脚本构造合成数据，而非只依赖实现者测试断言，实际验证：

1. 已构造实例后将路径替换为另一合法 schema3 库，`generate` 返回 `ledger_identity_mismatch`，transport 调用为 0，替换库 calls 仍为 0。随后删库，返回 `bound_ledger_missing`，transport 为 0 且文件不重建。
2. schema1/USD、schema2/USD、schema2/CNY 各含成功调用、成功缓存及 pending 调用。迁移前保存 `days/calls/cache` 所有列与行；迁移后逐列相等（schema1 仅新增 USD currency）；显式接管后再次逐列相等，身份不变。用于身份创建的预算 clock 被设置为一旦调用即抛错，迁移仍成功。
3. schema3 身份表缺失、空表、非法大写 ID、无时间的日期、`+00:00` 而非 Z 五种状态，构造均返回 `ledger_identity_invalid`，数据库字节均未改动。

这些脚本最终均退出 0。过程有 QA 脚本自身的未关闭 SQLite 连接导致 Windows 删除失败、CNY fixture 未提供完整费率导致 `invalid_budget_units`，修正验证脚本后通过；另有工具默认工作目录投影到 reparse 路径时被按规则拒绝，改用真实工作区绝对路径后通过。以上不是产品缺陷，也未计作通过次数。

## 审查处置与证据版本

初审提出：ensure 与实际客户端构造之间需核对身份，且客户端每次重新连接也要核对已固定身份、避免删库后隐式新建。主控实现了 CLI 二次核对与 `_connect` 的身份 pin、`mode=rw`，上述联验与额外脚本已验证实际效果。绑定测试中 `success`/`succeeded` 断言拼写由对应实现者修正，独立复验通过。QA 未修改实现文件。

验收实现 SHA-256：

| 路径 | SHA-256 |
| --- | --- |
| `src/market_intel/llm/client.py` | `4BE8EB65E1441274920A9242E70C239D6E1C2981F3FBDF2C0EF80D6480184409` |
| `src/market_intel/llm/binding.py` | `DB5D4734B6C9297D941C85E5E838484AE0AE3543A2A2DBA2640312564F911ACD` |
| `src/market_intel/cli.py` | `EBD1AB068BC2164462A50C2294F74489F2853D42A07324D1635935138DC43236` |
| `src/market_intel/ops/llm_backup.py` | `5A3E9567AD2C463F57757F6556F0E9715D8AA1096E6E9500B0AB8DBC58A153FB` |

本 QA 未执行全项目安装验收或 Git/GitHub 发布，不替主控声称其结果。未调用真实 API、未读取真实 key；测试使用合成响应、合成 key 和临时库。首次验收时未观察到 WB-07 结果文件；后续定稿文件复核如下。本报告的实现通过不等于 WB-07 底层工具回执已由 QA 独立核实。

## WB-07 定稿补充复核

2026-11-09（Asia/Shanghai）仅复核 `WB-07-report.md`、`WB-07-results.json` 及固定绑定契约；未改 WB 文件或产品，未重复运行测试。

两份定稿文件确实包含三点完整结论正文，而非只有派发/完成状态；JSON 记载 `status=completed`、`raw_result_recovered=true`、`tests_run=0`，并自述单次同步 Agent 返回正文，标识为 `agent-6a4f43d9-1d31-4eb3-9138-99e5ba6edf83`。QA 可确认这些文件内容可见、结论可供逐条审查，但未见该次 Agent 的底层工具调用/返回日志，因此不能独立认证其执行方式、调用次数或正文来源。该材料属于契约静态设计审查，不是实现测试或实网证据，也不增加前述 133 项测试数量。

第 1 点正确说明 UUID 不能证明快照最新、直接可信库接口与另建工作区不受全局约束。第 3 点正确区分显式接管已有库与新目录隔离恢复；其中禁止把旧快照作为安全生产切换是契约边界，不代表已经实现同身份回退检测。

第 2 点的“任何异常态一律拒绝、绝不补齐”和“没有隐式创建、重建或覆盖路径”过度概括，应限定为契约明确拒绝的状态：两文件都不存在时 `ensure` 允许初始化库与绑定；完整合法的无绑定库默认拒绝，但显式 `adopt_existing=True` 允许验证、迁移并建立绑定，且保留费用与 pending。该点自身与第 3 点存在措辞张力，不能据此宣称所有单边状态永远不可处理，或双文件被删除后也不能重新初始化。另“原子发布”应保留契约的“独占创建或不覆盖的原子发布”二选一表述；契约允许崩溃留下不完整 JSON 并在下次拒绝，不保证每次写入必然整体原子完成。

建议主控将第 2 点按上述状态表限定后用于交接；原始 WB 正文保留。本补充不改变已完成的独立实现验收结论，也不将 WorkBuddy 的自述升级为已独立核实的工具执行证据。
