# DeepSeek 最小合成验证操作手册

2026-11-17。当前用户选择先完成离线准备；本轮无真实请求。不要在聊天、任务单、日志、仓库中提供密钥。

## 前置条件

1. 使用scripts/setup-env.ps1完成普通隔离安装，保留setup-runs证据。运行时升级后通过MARKET_INTEL_PYTHON指定已验证Python3.11+；同版本失效venv按脚本安全恢复，跨版本不得自动覆盖。
2. 真实调用前另行确认供应商当日支持的模型、API端点、费率和usage语义。当前代码默认deepseek-flash和配置费率均不代表已验证的当日供应商事实。
3. 本地安全配置DEEPSEEK_API_KEY并显式启用live；仅检查是否配置，不打印值。每日10元是UTC日单账本配置费率估算，不是账户扣款或全局上限保证。
4. 同一workspace只用固定绑定账本，不为绕过已用预算另建生产账本。隔离恢复副本不可直接live。失败和pending继续占用全部预算；不要自动重试或人工减记。

## 离线命令

在安装成功的项目环境运行：

```powershell
.\.venv\Scripts\market-intel.exe deepseek-check --workspace data/live
.\.venv\Scripts\market-intel.exe provider-evidence-preflight --workspace data/live --call-id call_<32位十六进制ID>
```

deepseek-check不读取key，不创建账本。缺失绑定时不可宣称模型已就绪；预检只接受已有精确call_id，不认证账单。

## 将来经明确启用后的最小验证

```powershell
.\.venv\Scripts\market-intel.exe deepseek-smoke --workspace data/live --live
```

只发送代码内合成样本，不发送市场原文。缓存命中不算新供应商调用；检查返回call_id、cache_hit、原预算日及调用摘要。错误后先核对账本，不重复尝试来获得成功截图。已有命令失败可能只返回安全原因码，此时应在本地账本识别对应尝试，不直接输出request_metadata或失败正文。

## 取证与退出

通过model-call-info及provider-evidence-preflight保存安全摘要：call_id、provider/model、UTC预算日、响应标识哈希、用量有无、原费率估算。人工在供应商端核对可用的逐调用记录、币种和金额、用量及可信来源；无逐调用证据时明确缺失。不要将供应商原始ID、密钥、完整HTTP头或响应正文写入共享报告。

具备逐调用资料后，可以按契约准备本地声明 JSON，再运行 `compare-provider-receipt --workspace data/live --call-id <调用ID> --claim out/receipt-claim.json`。查看 `missing_local_fields`、`mismatched_fields` 和 `amount_comparison`。声明及原始资料保存在本地。 [输入与输出契约](contracts/provider-receipt-v0.1.md)

声明中的响应哈希应从供应商证据里的响应标识独立计算。若授权允许将标识暂存为本地单行文件，可用以下命令生成哈希。将结果填入声明的 `response_id_sha256` 字段。

```powershell
Get-Content -LiteralPath out/provider-response-id.local.txt | .\.venv\Scripts\market-intel.exe hash-provider-response-id
```

本地哈希不是供应商认证，手工声明和余额差也不是逐调用结算依据。清单字段齐全不代表账单验证通过。现阶段任何真实验证结果只记观察，不释放失败预算、不结算、不切换生产恢复。真实tokenizer/usage/费用以及可信高水位分别验收，证据不足保持NLP-01进行中。
