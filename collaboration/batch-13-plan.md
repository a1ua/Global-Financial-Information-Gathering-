# Batch13：真实smoke前置环境恢复

2026-11-17。承接Batch12真实最小验证计划。先检查进程环境是否有DeepSeek凭证，仅输出布尔值；不打印密钥，不读取用户密钥文件，不默认开启付费调用。

B13-ENV：env13独占scripts/dev.ps1、scripts/setup-env.ps1、docs/environment-recovery-batch13.md；依赖独立设计QA，修复运行时升级后解释器发现和无破坏环境恢复。
QA-B13：qa13独占docs/verification/batch-13-review.md，独立设计及验证。
B13-INTEGRATION：root独占本计划、任务板、运行手册、最终验收和最新计划。

验收：实际解释器路径验证、脚本缺失ProgramFiles仍支持显式配置、普通隔离安装及全部离线测试、项目外CLI。不得删除已有venv/运行数据；不修改schema/deps/业务逻辑。WorkBuddy工具入口不可用，未派发。
