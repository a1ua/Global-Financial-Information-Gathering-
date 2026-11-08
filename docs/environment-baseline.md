# 环境基线与执行端差异

检查日期：2026-11-07（北京时间）。项目要求Python≥3.11。以下为实际检查，不代表虚拟环境安装与全G0验收完成。

## Codex执行端：主控已复跑

- `load_workspace_dependencies`返回真实解释器，位置在本机CodexPrimaryRuntime安装包的`dependencies/python/python.exe`。
- `sys.version`：3.12.14；`sqlite3.sqlite_version`：3.53.1。
- `ZoneInfo('Asia/Shanghai')`、`ZoneInfo('America/New_York')`均成功。
- 本轮已验证`./scripts/dev.ps1 test`与`demo`。解释器完整路径保存于忽略的`scripts/python-path.local.txt`，不绑定到版本库。Codex升级后须重新定位。
- `py -0p`在主控PowerShell执行时返回`No Installed Pythons Found!`；PATH没有可直接调用的Python。不能据此判定整机无Python。
- WindowsApps目录枚举未返回可用候选，因此脚本当前依赖明确路径文件或环境变量。此限制已写入README。

主控实际验证命令：

```text
<Codex依赖Python> -c "import sys,sqlite3,zoneinfo; print(sys.version); print(sqlite3.sqlite_version); print(zoneinfo.ZoneInfo('America/New_York'))"
./scripts/dev.ps1 test
./scripts/dev.ps1 demo
```

## WorkBuddy执行端：独立报告加主控复核

- WorkBuddy报告Git Bash中PATH解析到`C:/Users/user/.workbuddy/binaries/python/versions/3.13.12/python.exe`。
- 主控直接执行此路径确认实际版本3.13.14、SQLite3.53.1、`tzdata`未安装。目录名不作为版本判断依据。
- WorkBuddy报告该运行时无法加载IANA时区；主控未独立复跑它的ZoneInfo失败用例，因此将此项标为WorkBuddy实测结论。
- WorkBuddy还报告`py`可找到3.8.10，与主控观察不同；原因未核实，不推断注册配置变化。
- 3.8.10仅能作为其本次简单探测工具，不满足项目版本要求，不能作为产品备选。

## 决策与待办

暂以明确验证过的Codex3.12路径运行离线原型；产品正式部署应选可维护的独立Python环境并锁定依赖。统一使用IANA时区与已验证时区数据，不采纳固定UTC偏移或手写DST规则。

ENG-02仍需验证全新隔离环境安装、CLI分发及Git基线。真实来源客户端的网络行为由SRC任务独立验证；不能将WorkBuddy HTTPS成功直接套用到其他运行时。
