# Batch08-C 本地追加审计验收

日期2026-11-09，基线本地9e30027、GitHub115a141。分工见`collaboration/batch-08c-plan.md`，契约`docs/contracts/audit-journal-v0.1.md`，信任决策`docs/audit-trust-decision.md`。本批只实现本地预检观察审计，不认证账单，不提供可信高水位、结算或生产切换。

## 交付范围与过程

QA先独立设计审查，指出容量兼容承诺过宽及REPLACE隐式删除绕过风险；主控修正后冻结，才派审计Agent实现。主控维护共享预检/CLI/集成测试，审计Agent独占新模块/定向测试/说明，独立QA只维护审查记录。

新增独立SQLite审计库schema1，模型schema3与证据schema4不变。显式`ledger-audit-record`读取声明一次，同一解析值用于预检、canonical声明哈希及未认证凭证引用；审计路径必须工作区树外、角色不冲突。`verify-ledger-audit`只读校验。普通预检不自动写审计。

审计使用完整观察哈希幂等，跨账本全局连续序号及前序链；BEGIN IMMEDIATE内先验证全链/表/精确触发器保护，再去重或追加。UPDATE/DELETE保护，INSERT guard预拒绝全部唯一键冲突，覆盖recursive_triggers=OFF的REPLACE隐式删行。严格观察schema/数值语义、容量、canonical payload、UTC顺序和错误脱敏。审计库首次显式独占创建，既存空库/坏库拒绝；verify缺文件不创建。

## 实际验证

- 审计Agent定向17项全部通过，含真实SQL两类REPLACE逐4唯一字段、幂等先验坏链、容量/bool、时钟回退、跨账本/并发、旧整库回退和busy/私密错误；日志`out/b08c-journal-tests.log`。
- 主控CLI与单次解析6项通过，包含声明读取后修改文件仍对应同一已解析值、角色冲突、不自动写审计、模型账本/绑定前后不变、观察变化追加。
- `./scripts/dev.ps1 test`完整358项，356通过、2项Windows符号链接权限跳过，实际junction分支通过；日志`out/batch08c-tests.log`，44.703s，exit0。
- 独立QA目标120项，119通过、1权限跳过，实际junction通过；补充场景及最终结论见`batch-08c-review.md`。目标测试与完整回归重叠，不累加为总通过数。
- `TEMP/TMP=工作区out/test-temp`下`./scripts/setup-env.ps1`普通隔离安装、项目外CLI help、明确合成demo与隔离测试通过；358项，356通过、2权限跳过，41.286s，exit0。证据`.venv/setup-runs/20261109-125130-2d05e690/`，日志`out/batch08c-install.log`。

合成观察/声明与临时库仅用于本地验证；没有真实供应商请求、账单认证、凭证读取或云服务部署。记录过的恢复快照与对话压缩包不作为外部高水位，也不上传运行库/对话到仓库。

## 信任与未完成项

本地链只发现部分损坏，文件所有者可重算/整体回退自洽链，`verified_local_chain`不保证最新。全部输出固定trusted_high_water=false、settlement_allowed=false、switch_allowed=false，现有恢复blockers不变。审计记录预检观察，不是所有预算事务的连续日志，也无模型调用/恢复切换跨库原子性。

只读校验保持正常WAL可见性，SQLite仍可能维护-wal/-shm侧文件；不宣称零文件系统写入。源码/秘密目录避让为操作约定，不声称自动识别任意目录用途。审计库备份/恢复、外部可信锚点、供应商调用关联、结算与生产切换未验收。

下一步可推进Batch09不依赖凭证的候选数量限制/预算联验；外部可信高水位及实际对账继续独立前置，NLP-01不整体done。WorkBuddy仅设计审查，完整正文回收和原始工具日志独立认证须分开；实际处置见`batch-08c-workbuddy-triage.md`。
