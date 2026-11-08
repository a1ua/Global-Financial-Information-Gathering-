# 固定工作区账本绑定契约 v0.1

本批只防止意外删除、不同身份替换或移动后的自动建空库，不是恶意本机管理员防护或同身份旧快照回退检测。真实调用仍需显式--live和本地密钥；本批不执行实网。

## 模型账本schema3

在schema2追加ledger_identity表，列：singleton INTEGER PRIMARY KEY CHECK(singleton=1)、ledger_id TEXT NOT NULL UNIQUE、created_at TEXT NOT NULL。恰一行，singleton=1，ledger_id为ledger_加32位小写十六进制，created_at为有效UTC Z时点。schema1/2迁移不改变days/calls/cache任何原行或费用；仅先完成既有currency迁移、再添加身份。schema3身份缺失/非法不能自动生成新身份，必须拒绝。

ModelClient初始化后暴露ledger_id。身份创建使用真实UTC系统时间，不消耗用于预算回归的注入clock。证据库仍schema4。

## 绑定API及文件

固定工作区文件llm-state.db与llm-binding.json。绑定文件严格字段：schema_version='ledger-binding/0.1'、ledger_id、ledger_path（规范化后的绝对固定账本路径）、created_at（UTC Z）。它是运行状态，放data/out等忽略目录，不入库。

check_workspace_ledger(workspace)只读，不建目录、不迁移、不读key；返回JSON可序列化字典含status、ledger、ledger_id（未知为null），status为uninitialized/unbound/bound。身份/路径不符、损坏绑定、绑定存在但库缺失，抛固定ModelError，不回显输入或底层异常。

ensure_workspace_ledger(workspace,adopt_existing=False)返回同类字典status=initialized/adopted/bound：

- 两文件都不存在：建立新库schema3及绑定；并发初始化可安全失败，不覆盖别人的文件。写绑定用独占创建或不覆盖的原子发布；崩溃留下单边/不完整文件时下次拒绝，不静默重建。
- 库存在而绑定不存在：默认ledger_binding_required；只有显式adopt_existing=True可验证并迁移已有库、建立绑定，所有预算/pending保持。不接管隔离恢复清单所在目录。
- 绑定存在而库缺失：拒绝bound_ledger_missing，不建空库。
- 两者存在：严格核对固定路径与库身份；不一致拒绝，即使adopt_existing=True也不覆盖重绑定。拒绝文件/目录的symlink或junction及路径逃逸。

CLI ledger-bind可显式--adopt-existing；deepseek-check调用只读check，deepseek-smoke在显式live和key检查后调用ensure、随后ModelClient。预检和失败都不能发起网络请求。直接Python ModelClient是受信任库接口，本批绑定只约束工作区入口，不能声称阻止调用方另建工作区或重写全部文件。

## 备份兼容

schema1/2继续使用llm-ledger-backup/0.1。schema3使用llm-ledger-backup/0.2，在既有清单严格字段上新增ledger_id，必须等于快照库唯一身份，返回结果也带ledger_id。其余原业务闭包、费用、pending和路径校验不变。

恢复仅创建新隔离目录ledger.db及恢复清单，不生成活动绑定、不覆盖当前库。不能用同一个ledger_id证明快照最新，也不能把旧snapshot配回原绑定当作安全生产切换；同身份旧快照需要后续高水位/对账与受控切换设计。
