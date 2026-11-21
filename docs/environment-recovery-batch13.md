# Batch13：本地开发环境恢复

日期：2026-11-17。范围为 scripts/dev.ps1 与 scripts/setup-env.ps1；不涉及模型、凭证、账本或产品schema。实现者 env13，独立审查 qa13，实际项目安装由主控执行。

## 行为

- dev先依次验证MARKET_INTEL_PYTHON、项目venv、local路径和PATH候选；发现可用Python后不再访问WindowsApps。只有全部失败且ProgramFiles存在时才进行可选运行时发现；缺失或无法启动的旧Python可跳过。
- setup优先显式MARKET_INTEL_PYTHON，其次local路径。显式配置无效会报错，不能静默安装至其他解释器。
- existing .venv启动失败时，只有pyvenv.cfg和Python文件存在且旧cfg major.minor等于已验证base时才执行venv --upgrade。没有--clear、删除、重命名或跨版本升级；已有包和历史setup证据保留。文件锁定或升级失败仍报错，不重试清理。
- PowerShell5.1对多行Python -c嵌套引号处理不可靠；已创建setup runRoot后，将本脚本固定Python助手保存为UTF8无BOM helper-UUID.py并执行，保留隔离参数及后续argv。助手文件留作证据，不包含外部输入或凭证。
- unittest进度使用stderr；Invoke-Checked仅在native调用期间将ErrorActionPreference设为Continue并在finally恢复，仍检查真实退出码；非native PowerShell ErrorRecord抛出，非零native退出码失败。

## 实现者实际验证

使用系统WindowsPowerShell5.1及已验证bundled Python3.12.14。仅在out/batch13-env-fixtures创建隔离脚本副本；未运行本项目venv升级或安装，避免与主控并发写入。

1. 缺ProgramFiles、显式有效解释器、隔离最小market_intel模块：dev demo退出0，stdout为ISOLATED_ENV_PROBE，stderr空。它验证解释器选择，不是产品demo或全套测试。
2. incomplete目录含preserve-marker和Scripts但无Python：base验证退出0后setup退出1，明确Incomplete .venv exists；marker保留，没有setup-runs。
3. stale fixture使用不可执行的Python占位文件和cfg version3.11.99：base验证退出0后setup退出1，明确版本不符；marker及cfg保留，没有setup-runs。此场景只证明跨版本保护，不代替同版本真实恢复。

负例stdout/stderr与退出码保存out/batch13-env-negative-probes.json。首轮demo命令错误地把脚本与参数整体作为路径，修正后成功；首轮最小子进程环境下两setup没有完成base验证，未作为负例通过。后续使用继承环境重跑得到上述明确拒绝证据。

主控另外在实际旧venv完成同版本恢复；初次安装在既有PS5 -c引号问题失败，第二次正常安装/help/demo后在stderr处理失败，因此追加上述两个修复。最终普通安装、全套回归、独立QA结果以 docs/verification/batch-13.md 和 batch-13-review.md 为准，本说明不冒认主控测试。
