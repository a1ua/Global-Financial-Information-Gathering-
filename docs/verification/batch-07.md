# Batch07 账本身份与固定入口验收

任务ID：NLP-01-BINDING、NLP-01-BACKUP3、QA-B07；主控负责schema迁移、CLI与集成。边界/所有权见`collaboration/batch-07-plan.md`。输入契约`ledger-binding/0.1`，模型账本schema3，备份0.2兼容旧0.1；证据库仍schema4。

## 已交付行为

固定工作区绑定身份与规范化绝对路径。已有无绑定账本必须明确采用，费用、pending和缓存保留；新建独占，不覆盖冲突状态。只读check不读取密钥、不迁移建库。live入口核对ensure结果与client身份，客户端后续连接拒绝丢库/异身份替换。祖先及文件符号链接/junction拒绝。schema3备份清单核对库内身份，恢复仅新隔离目录且不建立活动绑定。

修改范围：`src/market_intel/llm/{client,binding}.py`、`cli.py`、`ops/llm_backup.py`及对应测试、契约、计划与交接文档。两名实现者停止写入后由独立QA验收。

## 实际验证

- `./scripts/dev.ps1 test`：291项，289通过、2项Windows符号链接权限跳过；实际Windows junction分支通过。原始日志`out/batch07-tests.log`。
- `./scripts/setup-env.ps1`：初次因沙箱无法访问系统AppData临时工作目录失败；将TEMP/TMP明确设为工作区`out/test-temp`后重跑，普通隔离安装、包外CLI help、明确合成demo及隔离模式完整测试通过，291项、289通过、2跳过，exit0。证据`.venv/setup-runs/20261108-210528-3cfec227/`，日志`out/batch07-install.log`。
- 独立QA目标联验133项，132通过、1符号链接权限跳过；另行实际验证三种旧账本迁移逐列不变、保留pending/cache、无预算时钟消耗、5类非法身份不改库，以及构造客户端后换库/删库零transport。细节、命令、实现哈希和QA脚本自身修正记录见`batch-07-review.md`。

未执行真实DeepSeek请求、未读取真实密钥、未产生已知真实费用。模拟HTTP只验证本地行为，不证明云端连通或真实账单。日志与本地数据按忽略规则不发布。

## 仍未完成

绑定不能检测相同身份旧快照回退、同时删除两个文件、另建工作区、可信文件持有者篡改或跨账户调用。人工账单对账、pending终态修复、受控生产恢复、供应商真实usage/tokenizer尚未验收；NLP-01仍in_progress，NLP-02未开始，G3未通过。下一项先冻结人工对账与恢复切换契约，不默认释放未知费用。

WB-06后续partial自述与历史blocked区别见`batch-06-workbuddy-triage.md`；WB-07实际状态另记，不作为本轮代码通过前提。发布采用已授权GitHub连接保存精确文件树，保留本地独立历史，不强推。
