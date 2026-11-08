# ENG-02：隔离安装脚本与验证记录

日期：2026-11-07。实现范围：`scripts/setup-env.ps1`、本记录及工作区`.venv`；按主控追加要求，在原TEMP创建一个空目录作为项目外验证cwd，所有产物仍写venv，完成后仅删除该空目录。未修改共享契约、源代码、README、pyproject、dev.ps1、任务板或Git；依赖声明和包内fixture由主控负责整合。本记录区分中途失败与最终稳定版本验证。

## 1. 使用方式与安全边界

```powershell
./scripts/setup-env.ps1
```

脚本读取`scripts/python-path.local.txt`的实际解释器路径，要求Python >=3.11。该本地文件由主控维护，不自动猜测WorkBuddy的运行时或调用Windows商店别名。当前已验证的基础运行时是Codex捆绑Python3.12.14，SQLite3.53.1；启动器未注册不等于电脑没有Python。

脚本创建或复用项目`.venv`，不启用system-site-packages、不安装系统软件、不修改系统PATH。已有不完整`.venv`会明确失败，脚本不自动删除环境。环境创建、安装和测试的临时文件均定向到`.venv/setup-runs/<run-id>/tmp`；pip使用`--no-index --no-cache-dir`，不访问包索引或用户全局缓存。

每次安装将当前`pyproject.toml`及`src`复制到`.venv/setup-runs/<run-id>/package-source`，记录`source-manifest.json`的SHA256，再从该快照普通安装。这样setuptools产生的build、egg-info等位于隔离目录，不在共享源码旁生成。安装不是editable模式。

在清除继承的PYTHONPATH/PYTHONHOME后执行；Python命令使用`-I -B -X utf8`，不将src加入搜索路径。脚本结束或失败时恢复它修改的进程级环境变量。测试临时目录及demo产物均位于`.venv`。

## 2. 离线依赖引导

实测基础解释器已有pip26.2.2、setuptools84.2.1、wheel0.48.0、tzdata2026.6。venv由ensurepip引导得到pip25.0.1，不自动继承基础运行时的setuptools或tzdata。

本脚本只从指定、已安装基础运行时读取setuptools和tzdata的distribution文件、METADATA及WHEEL，校验为支持py3-none-any的纯Python分发，将文件重新归档到`.venv/wheelhouse`并重新计算RECORD哈希；不从未知网络位置下载，也不把基础site-packages整体放入venv搜索路径。该本地重归档用于开发环境引导，不作为第三方官方发布wheel或可分发供应链工件。

先离线安装构建工具，再由pip正常读取项目声明、从本地wheelhouse解析运行依赖；不使用`--no-deps`掩盖声明缺失。基础运行时缺包、构建要求不满足或wheel不兼容时明确失败，记录阻塞后由主控调整依赖方案，不静默改用网络。

当前项目依赖声明由主控固定为构建setuptools84.2.1和运行tzdata2026.6。脚本不替代依赖锁，也不假设基础运行时永久不变；重定位运行时或更改版本后需重新验证。

## 3. 自动检查顺序

1. 指定基础解释器实际执行并确认版本。
2. 创建/复用venv，检查其sys.prefix与项目`.venv`一致且与base_prefix不同。
3. 验证venv pip、离线构建依赖引导及普通项目安装；所有外部退出码立即检查，非零停止后续步骤。
4. `pip --isolated check`确认声明依赖完整。
5. 在`-I`模式导入`market_intel`，验证`__file__`位于venv的`Lib/site-packages`，显示安装版本、setuptools/tzdata版本并解析上海和纽约IANA时区。
6. 在原TEMP创建一个空目录（项目树之外）并切换到该目录，执行真实console entry point的`market-intel --help`。验证后仅删除该空目录；如果出现意外文件则保留供检查，不递归清理。
7. 从同一外部目录执行`market-intel demo --workspace <venv-run-id>/demo`；不传fixture路径，验证默认fixture来自已安装包，而非当前工作目录。
8. 使用venv解释器执行`-I -B -m unittest discover -s <项目绝对路径>/tests -v`，导入已安装包。测试本身可读取工作区测试fixture，但不能借助PYTHONPATH导入工作区src。

成功日志必须出现最后的PASS；没有PASS或任一退出码非零，都不能记录整条安装验证通过。日志逐命令记录实际参数、输出与退出码，位置为`.venv/setup-runs/<run-id>/setup.log`。

已独立提取脚本中的命令调用函数进行负向检查：调用真实PowerShell子进程`exit 7`，观察到`exit_code=7`，函数抛出包含`exit code 7`的异常，外层仅将该预期异常作为负向测试成功；未将失败子命令误标为通过。PowerShell AST语法检查无错误。

## 4. 中途执行与已修复问题

### 4.1 venv创建与基础能力

已使用本地路径文件记录的解释器执行`-m venv .venv`成功；venv是Python3.12.14，SQLite3.53.1，pip25.0.1，初始没有setuptools。这验证了本机可创建隔离环境，不代表全部G0或正式依赖已验收。

### 4.2 首次安装失败：默认用户缓存越界

运行目录：`.venv/setup-runs/20261107-231016-2a021408`。setuptools离线安装通过，项目构建因pip尝试使用用户AppData缓存而返回WinError5，脚本准确捕获exit1并停止。未声称该次项目安装成功。修复为显式`--no-cache-dir`并将TEMP/TMP定向到venv运行目录。

### 4.3 第二次安装成功，但中途集成测试失败

运行目录：`.venv/setup-runs/20261107-231132-eb6dc0bc`。正常安装market-intel-agent0.1.0、pip check、site-packages导入证明、console help、显式fixture的synthetic demo均exit0。

当时工作区存在并行修改，全量53测试为9失败、8错误。主要环境缺口是隔离venv没有tzdata，而当时pyproject运行依赖为空；基础解释器有IANA数据不代表隔离venv继承数据。另有RSS校验/编码测试与中途快照不同步。该结果已反馈主控，未擅自修改依赖或源代码，也不作为最终稳定版本的质量结论。

主控随后声明锁定tzdata并将默认fixture放入安装包；setup脚本已改为解析正式运行依赖、检查IANA支持、从非项目根目录使用默认demo。不用固定UTC偏移或手写DST修补时区。

## 5. 最终稳定版本验证

主控确认源码稳定后，于本地时间2026-11-07 23:24开始执行一次完整`./scripts/setup-env.ps1`，整体退出码0，日志最后出现PASS。

证据目录：`.venv/setup-runs/20261107-232448-c3424e95/`。

| 检查 | 真实结果 |
| --- | --- |
| 运行环境 | venv Python3.12.14，SQLite3.53.1，pip25.0.1 |
| 依赖 | setuptools84.2.1，项目依赖解析并安装tzdata2026.6；pip check输出No broken requirements found |
| 普通项目安装 | market-intel-agent0.1.0构建及安装成功；未启用editable或PYTHONPATH |
| 源码快照 | 12个文件记录SHA256；执行结束逐项比对当前pyproject/src与快照一致 |
| 导入位置 | `.venv/Lib/site-packages/market_intel/__init__.py`，`-I`验证通过 |
| IANA时区 | Asia/Shanghai与America/New_York均解析成功 |
| 项目外cwd | `C:/Users/user/AppData/Local/Temp/market-intel-installed-check-3a4d4e7c1ebe46bba6f10db592730994`，开始为空，结束确认已删除 |
| 真实console help | `market-intel --help`退出0，列出demo/collect-fed/brief/replay/status |
| 默认demo | 未传fixture路径，从项目外cwd成功读取包内fixture；退出0，report_id为demo_A_pre_v2 |
| 当前全量离线测试 | 65项，2.072秒，OK，退出0；导入已安装包 |
| 真实网络/行情/模型 | 此安装验证未执行，不据此作通过声明 |

本次构建wheel：`market_intel_agent-0.1.0-py3-none-any.whl`，构建日志SHA256为`04832883f02ea6b11f9550bd8b44f7860609252153119345b17aeec2a6d73d8f`。安装快照及具体命令见setup.log与source-manifest.json。

demo产物为`demo/reports/demo_A_pre_v2/brief.html`与manifest。manifest明确`is_synthetic=true`、`status=degraded`，reason_codes包含synthetic_fixture、retrospective、market_data_unavailable，content_support_check为not_performed；这些标记不能解读为真实市场报告或人工事实支持度抽检通过。

因此本次ENG-02环境子包的自测结果是：正常隔离安装、声明依赖解析、项目外默认demo与当前全量离线测试通过；仍待独立审查后由主控决定任务/闸门状态。没有重新跑第二遍全量测试，因为最终稳定快照的一次运行已通过，当前没有新代码变化或未解决测试失败。

## 6. 限制与独立审查

- 本包检查的是本机开发安装能力与合成离线原型，不包括真实来源长期运行、模型调用、调度安装或前瞻收益有效性。
- 不直接修改Git基线，交由主控保存安装脚本与记录。
- 基础运行时位于应用安装目录，应用更新后本地路径可能失效；脚本会失败并要求刷新已验证路径。
- 每次运行留存独立快照与日志，不自动清理旧环境。输出目录不是可发布的真实市场报告。
- 完整安装结果须由独立代码审查者复核；实现者自测通过不能代替该审查。
