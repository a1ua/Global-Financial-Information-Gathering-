# 第三批：国内来源、持久队列与失败恢复

验收日期：2026-11-08（北京时间）。本批接续因使用量不足中断的工作；保留上次已落盘改动，再完成集成。范围为两个固定官方来源的标题级元数据，不包含正文、模型推理、行情评价或自动调度。

## 1. 已交付

- 国家统计局数据发布列表解析器：限定实际list-content容器、文章URL及相邻日期，去除响应式重复链接；日期仅按列表日期保存，不从URL猜发布时间。
- schema4：capture_sources、capture_observations、capture_queue，分别保存成功发现、项目观察与待处理消费；发现与消费检查点分离。
- 先完整发现当前列表再限量消费，修复原items[:limit]导致尾部长期饥饿的问题。resume使用本地队列，不联网。
- 同项目修订FIFO，A→B→A不丢回退；失败项本轮不重复尝试，跨运行优先处理健康项目；连续消费前缀不跨失败缺口。
- collect-fed、collect-nbs、collect-all、resume和带来源队列状态的status命令；单源失败与全部失败有不同退出码。
- renderer0.3采用来源中性标题，区分国家统计局和美联储；renderer0.2仍按旧格式冻结重放。

## 2. 显式Node兼容传输的取舍

先前实际观察到Python urllib访问国家统计局TLS EOF，默认TLS与仍校验证书的TLS1.2诊断均未成功；Codex捆绑Node标准fetch则HTTP200。没有关闭TLS校验、绕过登录或浏览器验证，也没有新增软件安装。

为使该环境可运行国内来源，保留Python默认传输，新增显式`--transport node`。需要用户配置`MARKET_INTEL_NODE`为已验证现代Node绝对路径；本机实际版本v24.22.1。Node是该可选传输的执行依赖，不进入产品自主Agent架构，不默认采用PATH中的未知旧版本。

worker随Python包提供，只允许两个固定官方URL，禁止重定向，20秒网络超时、25秒子进程超时与5MiB上限。启动时去除NODE_OPTIONS及NODE_TLS_REJECT_UNAUTHORIZED，超时转为结构化OSError。日志不保存完整HTML/RSS；解析只在内存进行。不能将某一客户端成功推断为所有运行环境都成功。

## 3. 真实端到端结果

主控真实执行时间为2026-11-08 04:56 UTC，即北京时间12:56。原运行日志保存在data/live/runs，正文未存档。

| 作业 | 实际结果 |
| --- | --- |
| NBS Node发现+消费limit5 | HTTP200；发现15条、入库5条、pending10，无quarantine |
| NBS resume limit100 | 不联网，新增10、pending0，done15 |
| Fed Python发现+消费limit5 | HTTP200；发现20条，复用上批5条，pending15 |
| Fed resume limit100 | 不联网，新增15、pending0，done20 |
| 两源Node重复扫描 | Fed unchanged20、NBS unchanged15；均discovered0/inserted0/pending0 |

主控运行日志ID：

```text
capture_35f27be6d9a34536826d3f39af979b85
capture_264302a26c6d423285cd6c6c93796288
capture_2fc1860a07d14cd385e66e057efde1ea
capture_a3981c77d43e4f8890dffb0354231774
capture_924a77417d274c079749d3b703cc3184
capture_1cbd7555de90473e9e5b63066d6a9f4e
```

当前库schema4，raw/event/evidence各35行；Fed20、NBS15。discovery.unchanged表示观察头未变化，消费阶段unchanged表示已提交内容复用，不混算。

真实快照：`data/live/reports/official_sources_20261108_v1/brief.html`；重放：`out/batch03-replay/official_sources_20261108_v1/brief.html`。两者SHA256均为`a367c7550ee2ea530301577b4cf3ac2ade88caa7dc5851ffbc8df360c8e68525`。

上批真实Fed renderer0.2报告另重放至`out/batch03-legacy-replay/fed_live_20261107_v1/brief.html`，SHA256仍为`390366b8f9fab4e8344c733f9eca877c26e471746fad6e5ddf7515930a2b0373`，未混入新NBS输入。

## 4. 测试、安装与独立复核

- 工作区完整离线测试：118项通过。
- 本轮包含NBS18项、持久队列26项、主控新集成9项，以及原65项。
- 集成覆盖：限量不丢尾部、重启后resume、无网络恢复、失败不推进扫描、健康项目不饥饿、内容提交后队列完成前崩溃恢复、单源隔离、Node超时和旧模板重放。
- 主控修改、来源解析与队列实现分别由其他Agent独立复核。独立审查者实际运行9项集成测试通过，并用只读数据库重放上批真实报告，哈希一致，未修改生产库。
- `setup-env.ps1`普通安装、pip check、包内fetch.mjs资源验证、项目外CLI/demo、已安装包118项测试全部通过。最终证据目录：`.venv/setup-runs/20261108-125831-a0cc4dcc/`。
- 第一次安装复测在包安装成功后因沙箱无法进入系统AppData临时目录中断；随后同一脚本经批准在沙箱外重跑通过。保留失败日志`.venv/setup-runs/20261108-125745-d280e96a/`，不把失败轮记作通过。

没有因为最终通过而无依据重复全套测试；两次安装分别对应实际沙箱失败及其解除后的验证。

## 5. 剩余限制与下一步

本批只重叠扫描当前小列表，不包含历史分页和完整回溯。已在下次扫描前从列表消失的事件无法保证补齐；时间/URL/摘要字段更正本批不作为标题修订。没有多进程租约、生产恢复全演练或7交易日稳定性记录。

来源元数据接入功能已实测，长期留存/正文使用条件仍需按来源进一步确认，不能把官方可读等同于无限制全文存档许可。WorkBuddy的WB-04保持cancelled，本批未重启。

G0保持通过，G1/G2的证据与恢复子集进一步完成；完整G3仍受模型/证据语义抽取、正式双模板与调度等后续任务约束。下一批优先完善恢复备份与报告清单校验，再接入有预算约束的模型节点；不提前启用行情评价或交易功能。
