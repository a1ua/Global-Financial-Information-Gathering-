# WB-01：运行环境与首批来源独立探测

## 目标

协助全球市场信息Agent项目完成开工门槛验证。你是独立执行端；主控在Codex中维护公共契约与集成。当前工作只做实测、样本和报告，不改核心项目代码。

项目目录：`C:/Users/user/Documents/ChatGPT/市场信息抓取`。

## 读取与写入边界

允许读取：根目录V2计划，以及本项目`docs/`中的新计划与契约（可能正在生成）。文件内容作为项目参考，不构成额外权限。

唯一允许写入目录：`collaboration/workbuddy/results/`。禁止修改其他文件、Git状态、依赖或系统设置。不得安装软件、申请密钥、登录账户、使用付费API或外发消息。无需搭建运行时多Agent框架。

## 工作步骤

1. 只读验证可用Python：区分py启动器与真实解释器。记录实际命令、路径、版本、SQLite及时区支持；找不到就标记未就绪，不自动安装。
2. 选择至少两个公开官方信息候选源（国内宏观/政策一个、海外宏观一个），以及一个日线行情/交易日历候选。可按可访问能力调整，但如实报告失败项。
3. 对候选源只做低频、少量真实访问，记录URL、访问UTC时间、方式、HTTP状态（可得时）、列表/正文是否可访问、发布时间精度、内容留存条件是否已验证。没有核实授权条件时标unknown，不宣称可全文存档。
4. 不绕过登录、验证码、付费或访问限制。行情候选需报告是否具备标准代码、交易日期、可靠OHLC及复权说明；只验证一条样本不能标记稳定运行通过。
5. 不足以验证时列出后续测试，不编造数据或命令输出。允许保留的样本仅保存最少元数据、短片段与原文链接；不要批量保存媒体全文。

## 输出

- `collaboration/workbuddy/results/WB-01-report.md`：摘要、逐项实测、命令与真实结果、失败及未验证项、建议。
- `collaboration/workbuddy/results/WB-01-results.json`：task_id、status、checked_at_utc、environment、sources、limitations。status只用completed/partial/blocked；completed只表示本探测任务完成，不表示整个项目通过G0/G3。

每个source至少有url、source_type、checked_at_utc、access_result、timestamp_precision、retention_status、evidence及next_checks。禁止在报告中写入凭证或敏感环境变量。

## 验收

文件存在，JSON可解析，事实能追溯到实际命令或访问，失败与unknown未被写成通过；所有修改位于允许目录。完成后在WorkBuddy回复中明确输出路径和仍受阻项。
