# Batch13 独立审查

日期2026-11-17。审查者qa13，独占本文；未修改产品、脚本或共享任务板。

## 设计阶段

已阅读 scripts/dev.ps1 与 scripts/setup-env.ps1 原实现。dev在候选验证前无条件拼接ProgramFiles/WindowsApps，导致即使明确配置可用解释器仍可能失败。setup既有venv可执行文件存在不等于可运行，应用升级移除旧基础Python后会退出103。

设计复核通过：dev先验证明确候选，只有均不可用时才进行受保护的运行时发现；ProgramFiles不存在不阻断明确候选。setup优先MARKET_INTEL_PYTHON再本地记录，验证新解释器；既有venv仅在cfg/exe存在、启动失败且cfg版本与新解释器major.minor相同时用标准venv --upgrade原位恢复。禁止clear/递归删除/移动；不完整、跨版本或升级失败保留失败。升级是恢复运行环境，不代表业务真实模型验证。

设计时tests_run=0。实现和独立实测待追加。

## 最终实现与独立验证

最终静态复核无阻断。dev先验证明确候选，不依赖ProgramFiles；setup优先显式解释器，对失效同版本venv使用标准--upgrade，未新增clear、递归删除或移动。固定Python -c helper在既有setup-run内以唯一UUID/UTF8无BOM落文件，保留-I/-B/-X与后续参数，避免PowerShell5字符串引号破坏。Invoke-Checked仅在native调用期间局部Continue，finally恢复偏好，保留真实退出码检查；非RemoteException PowerShell启动错误仍抛出，不以stderr存在误判失败。

独立实测：Windows PowerShell AST两脚本解析通过；抽取Find-WorkingPython，先不存在路径后实际Python3.12.14，返回正确实际路径。独立隔离复制setup脚本到out/test-temp/qa13-8pcrMG：incomplete仅建空.venv，退出1并出现精确Incomplete .venv exists；crossversion使用cfg3.11.9和不可执行fixture，退出1并出现精确Stale .venv Python version differs。两者无setup-runs，目录内容保持原fixture（前者空，后者cfg/Scripts），不进入升级/安装。两负例复制版为helper文件修复后的脚本，后续最终native stderr改动不改变此前拒绝分支；已静态核对该边界。以上为5项独立检查，不宣称产品全套测试。

环境与初始失败如实保留：最小env PowerShell子进程不能得到native执行结果/LASTEXITCODE，切回继承环境后探针通过，非产品缺陷；初次隔离fixture未加标准脚本ExecutionPolicy Bypass而被执行策略阻断，不计分支通过。重跑加启动参数后两负例实际到达指定拒绝分支。回调延迟超过名义timeout，最终均自然返回；不宣称成功终止进程。统一exec入口helper启动仍失败，独立验证使用node child_process，不修改系统策略。

已阅读docs/deepseek-smoke-runbook.md：离线范围明确；真实调用前另验当日供应商模型、端点、费率和usage，当前默认不当作供应商事实；凭证不入聊天/日志/库；失败预算、账单可信与外部锚点边界保留。无真实模型调用由QA执行。

主控报告普通隔离安装最终exit0、518运行515通过3权限跳过（53.764s），项目外安装入口help/demo通过，证据.venv/setup-runs/20261117-231122-f6bf2f5b及out/batch13-install-accepted.log；只作交接一致性引用，QA未复跑该全套/安装。主控最初PS5引号及stderr两类失败与最终成功分开，不计为成功运行。WorkBuddy/真实API/凭证/账单/生产切换均未由QA验证。

SHA256:
- scripts/dev.ps1: e8e74425976a5a46377ed6604f1939470ef9d6f133d3390e9dc3ea34ee890f47
- scripts/setup-env.ps1: e8aff27285fdd45807d9ee8f076c53cd0feec61c771314b90e33c35c1477b044
- docs/deepseek-smoke-runbook.md: 3befd3660d47ead1b68f42592aecd55f4a4eeaeca4ffd0d308e38adfea3c9d75
