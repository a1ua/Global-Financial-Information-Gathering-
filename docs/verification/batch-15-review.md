# Batch15 判断持久化契约独立设计审查

2026-11-17。审查范围为ENG-04判断持久化契约冻结；本批无代码、schema、运行库或迁移修改。qa15仅写本文件。tests_run=0，未执行测试，设计审查不能替代实现验收。

## 已读实际基线

- docs/contracts-v0.1.md第5/6节：不可变对象、Prediction字段、方向/评价口径及提交后下一会话起点。
- src/market_intel/store/__init__.py：schema4，0至4迁移，三证据表及不可变回执，UPDATE/DELETE/INSERT冲突保护。record_visibility仅在内容提交后采样再单独写回执。
- src/market_intel/ops/backup.py：当前备份检查raw文件、报告及schema上限，不检查未来判断对象语义；恢复只到新目录。
- docs/contracts/candidate-snapshot-v0.1.md和contracts/__init__.py：精确候选闭包和payload哈希；元数据不能支持正文事实。

## 设计前置要求

1. committed_at不能作为调用方可信输入或在内容COMMIT前产生；存储payload与系统保守可见回执分离，读取envelope才派生committed_at。无回执内容不用于报告/评分。回执不是精确SQL物理提交时刻。
2. 精确event/evidence/raw版本及hash闭包；不可查latest。更正关系后来添加不得改变旧manifest引用。
3. 跨模型账本无SQL FK/原子提交，必须冻结ledger_id/call_id及安全摘要；不能把模型备份冒称证据备份一并覆盖。
4. 首实现仅合成fixture。协议/日历/模型/主数据版本引用没有真实闭包时不得接受为生产判断，不得因结构完整就启用评分。
5. 判断内容、引用和回执均防普通UPDATE/DELETE/REPLACE；哈希不是签名，不承诺防特权改写。
6. 同ID同canonical内容幂等并保持原回执；同ID不同内容拒绝。更正用新ID/supersedes，首版线性家族防分叉，缺前驱/自引用/跨家族拒绝。未封存恢复需显式重验证，采新保守时刻，不回填旧时间。
7. schema5迁移必须同时更新严格schema4读取者、备份语义及闭包校验。只提升常量不够。旧备份只读验证不静默迁移，未来schema拒绝。

## 首实现验收矩阵（尚未执行）

- 字段/类型/枚举/UTC/hash/排序/重复及引用闭包；uncertain弃权和未就绪真实依赖拒绝。
- 幂等/冲突/追加更正/缺前驱/重复后继；旧对象与旧报告不变。
- COMMIT前不可见；内容成功回执失败保留未封存；显式恢复用新时间；时钟回退拒绝。
- 普通SQL UPDATE/DELETE/REPLACE，包括recursive_triggers OFF不能替换。
- 缺引用、跨event、未来可用、坏文件/hash拒绝；WAL读取不混新写；事务失败无半关联。
- schema4副本升级5失败回滚，既有payload不改；老备份仍可验证；新判断/引用/回执损坏拒绝；恢复新目录不冒称独立模型账本可恢复。

## 当前结论

设计方向无阻断，同意本批仅冻结文档，不升级ENG-04或G1/G4；共享契约落盘后追加最终复核。


## 最终共享契约复核

已逐段读取docs/contracts/prediction-storage-v0.1.md。结论：语义设计可冻结，无剩余阻断；精确JSON键集/边界/错误码/合成依赖快照及canonical结构显式留待P16-CONTRACT独立冻结，不把本批设计写成完整可执行schema。

初次审查建议已落实：每family独立唯一根约束，前驱唯一后继防分叉，同家族target/benchmark/basis/协议/日历上下文不变，改变上下文另建家族；提交后回执不得早于前驱回执。内容幂等排除服务器回执时间，无回执显式重新验证并采新边界。

引用固定闭包、跨模型账本非联合原子、合成首包拒绝真实模式、schema4消费者与备份随schema5协调迁移均有明确边界。当前schema4/账本schema3保持不变，未实施迁移，不开放报告或评价。原内容与回执两事务之间崩溃保留未封存状态的限制明确。

未执行测试，tests_run=0；没有修改产品代码/运行库，不冒认真实模型、市场评价、实现或生产恢复通过。ENG-04与闸门不升级。

共享契约SHA256：f9f93cd3461e27860cec65ad380d19166b5b0b1bee4c47a3bd3c871c7c6d0660


## 设计说明最终一致性复核

已完整读取docs/prediction-storage-design.md最终版，确认其服从共享契约，概念model_call_ref/protocol_ref/calendar_ref分组明确映射正式flat字段，不另造可直接实现的JSON键集。后续S1/S2精确结构冻结与S3/S4协调schema迁移次序清晰，未把本轮语义设计当作完整validator/schema已实现。

设计说明§3步骤4回执tuple已补齐为prediction_availability_receipts(prediction_id, content_sha256, committed_at)，与共享契约一致。首版合成限制、内容/回执拆分、显式resume、新fence/clockguard、同家族单根单后继/上下文固定，以及旧报告/备份兼容边界均与共享契约一致。未发现新增阻断或范围扩张。

设计说明SHA256：d9d91f43ff6e3cbac1ebe506a6cc8eca0657429af2ed80dbde6542766cc32ea4

仅追加静态复核；tests_run仍为0，不运行或冒认代码、安装、真实模型、收益评价验收。
