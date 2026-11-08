# 工作区模型账本身份绑定

Batch07 使用固定工作区文件 `llm-state.db` 和 `llm-binding.json`。账本 schema 3 内的 `ledger_identity` 只保存一个 `ledger_id`；绑定文件保存相同身份及规范化绝对路径，避免误删账本后自动创建空账本、换库或移动工作区时悄悄重置预算历史。

## API 与状态

`market_intel.llm.binding.check_workspace_ledger(workspace)` 只读检查，不建目录、不迁移、不读取模型密钥。返回 `{status, ledger, ledger_id}`，其中 `ledger` 是固定账本的规范化绝对路径。

| 文件状态 | check 结果 | ensure 行为 |
| --- | --- | --- |
| 两者均不存在 | `uninitialized`，身份为空 | 创建 schema 3 账本及绑定，返回 `initialized` |
| 只有账本 | `unbound`，旧 schema 身份为空 | 默认拒绝；显式采用后返回 `adopted` |
| 只有绑定 | 抛出 `bound_ledger_missing` | 拒绝创建空账本 |
| 两者匹配 | `bound` | 返回 `bound`，不改文件 |
| 身份或路径不匹配、文件损坏 | 固定错误码 | 拒绝，显式采用也不覆盖 |

`ensure_workspace_ledger(workspace, adopt_existing=False)` 初始化或验证工作区。只有明确传入 `adopt_existing=True` 才采用无绑定旧账本；采用前只读验证现有业务行，再保留 `days`、`calls`、`cache` 和 pending 预留费用进行迁移。已有有效 schema 3 身份继续沿用。

绑定 JSON 只允许四个字段：`schema_version: "ledger-binding/0.1"`、`ledger_id`、`ledger_path`、`created_at`。身份格式为 `ledger_` 加 32 位小写十六进制，时间为实际系统 UTC 的 `Z` 时间戳。重复键、额外字段及无时区时间均拒绝。

## 拒绝条件与失败语义

文件及全部祖先目录的符号链接和 Windows junction 均拒绝。存在 `ledger-backup-manifest.json` 的隔离恢复目录禁止初始化或采用；这类目录用于校验备份，不能直接成为真实模型运行工作区。

新账本和绑定均独占创建，绝不覆盖已有文件。并发调用允许安全失败；初始化中途失败可能留下无绑定账本或不完整绑定，后续调用拒绝自动修复。完整旧账本的无绑定状态可由用户明确采用；损坏文件需要人工排查，不能通过自动删除重建恢复额度。

主要错误码：`ledger_binding_required`、`bound_ledger_missing`、`ledger_binding_path_mismatch`、`ledger_binding_identity_mismatch`、`ledger_identity_invalid`、`ledger_binding_invalid`、`ledger_adoption_invalid`、`ledger_binding_schema_unsupported`、`ledger_binding_link_forbidden`、`isolated_ledger_not_live`。SQLite 和文件系统异常分别转换为固定的 `ledger_binding_database_error` 和 `ledger_binding_io_error`；不包含来源文本、路径或底层错误正文。

## 验证和范围

离线针对性验证：设置 `PYTHONPATH=src` 及工作区内的 `TEMP`/`TMP`，运行 `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_ledger_binding.py -v`。覆盖只读检查、显式采用、成功缓存及 pending 行/费用保留、孤立文件、身份缺失、移库与替换、并发独占创建，以及实际 Windows junction。符号链接创建需系统权限，不可用时该项明确跳过。

本机制不能阻止删除账本与绑定双方后重新初始化、另建工作区、持有文件权限者篡改，或回退同一身份的旧快照。它不提供供应商账户总预算保证，也不宣称已完成生产备份恢复验收。所有测试使用合成模型响应，不调用 DeepSeek、不产生真实费用。
