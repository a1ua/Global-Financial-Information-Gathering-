# 第四批：报告清单与一致备份恢复

日期：2026-11-08。本轮交付范围：报告清单结构与引用闭包校验、一致备份、备份校验、恢复副本，以及Git本地提交与用户指定GitHub仓库上传准备。最终远程状态以Git/GitHub实际提交验证为准，不以本文件预先宣称成功。

## 1. 实现与接口

- `contracts.report.validate_report_manifest`：严格校验实际report-manifest/0.1字段、UTC/日期、唯一ID、输入hash、模板/渲染/规则版本、固定产物路径与真假/降级标记。
- `report.verify.verify_report`：只读核对精确输入版本、事件/证据/raw闭包、截点与提交后receipt、来源配置、合成/混合标签及磁盘字节hash。损坏输入返回稳定验证错误。
- 发布前与冻结重放前接入校验；保留renderer0.2/0.3实际历史产物的兼容性。未扩展预测/行情或完整报告声明。
- `ops.backup.create_backup/verify_backup/restore_backup`：SQLite backup API一致快照，WAL快照转换成独立数据库，复制引用证据与已发布报告，生成带路径/hash/大小的清单。
- CLI新增`validate-report`、`backup`、`verify-backup`、`restore`。备份与恢复只用新目录，拒绝源/目标包含、路径越界、链接与覆盖。

不直接复制运行中的market.db文件；不备份凭证、venv、任意外部文件、孤立raw或未发布staging。主动篡改后同时重写全部清单不是本轮哈希防护能证明的场景。

## 2. 实际验证

最终安装验证：`.venv/setup-runs/20261108-133011-c40ddd3d/`。

- 普通隔离安装、pip check、site-packages导入、IANA时区、项目外CLI与包内demo通过。
- 全量158项测试：157通过，1项因本机Windows账户无创建实际符号链接权限跳过；另有mock分支验证链接拒绝逻辑。整体为OK(skipped=1)，退出0。
- 报告清单13项定向、备份18项定向及报告验证9项回归纳入全量；未把合成测试当真实来源验证。
- 首轮备份测试遇到AppData父目录沙箱限制，开发脚本改为工作区out/test-temp并在finally恢复TEMP/TMP；没有放宽路径安全校验。
- 前一次安装验证中旧测试假设两次Windows墙钟读取必定递增而偶发失败。已将该用例的“提交前时间”固定为明确历史值，保留真实提交后receipt检查；产品时点规则未放宽。修复后最终安装及全部测试通过。

## 3. 独立真实库恢复演练

详见`backup-independent.md`。非实现者只读源data/live，全部备份/恢复/重放产物写入独占out目录：

```text
out/independent-backup-79816265077e437c8ebe816c7be10881/
```

真实结果：一致备份、verify和restore均通过，40个文件、35条raw、2份报告；恢复库schema4，raw/event/evidence各35条。旧0.2和新0.3报告均可校验与重放，字节SHA与原文件一致；源库、证据与报告共40文件前后路径集合及哈希完全不变。

负向验证也确认：引用一份“确实存在但不属于该事件”的raw并重算输入hash，仍被拒为输入闭包不匹配。缺失证据、损坏字节、未来schema、WAL未提交写、目标冲突及路径逃逸均有回归。

## 4. Git与GitHub交付边界

用户指定：`https://github.com/a1ua/Global-Financial-Information-Gathering-`。GitHub连接确认owner、写权限及空仓库；原本地项目无remote。上传范围为已跟踪代码、合成fixture、计划与验收文档，不含data/out、venv、真实数据库、本地解释器路径文件或凭证。

上传前检查未发现常见token/私钥/WorkBuddy seed模式；已有文档含通用user本机路径和应用版本，属于开发环境记录，未为上传擅自改写本地历史。所有真实运行/恢复产物继续留在忽略目录。

本文件记录的是可审核发布内容；远程提交SHA和上传结果在最终交付消息中提供，不以静态计划替代实际上传验证。

## 5. 剩余工作

当前证据库与报告恢复能力通过；预测库、模型预算/调用、正式解读、行情/日历、研究核对、定时调度、异地备份和至少7交易日运行仍未交付。本轮不提前宣称完整G3–G5或研究有效性通过。
