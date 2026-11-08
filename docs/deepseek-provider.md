# DeepSeek 固定端点传输与人民币预算

Batch 06。用户指定 DeepSeek、每日人民币10元；默认配置仍为 `enabled=false`。本轮实现基于官方文档并以合成 HTTP 响应验收，**尚未使用真实密钥调用 DeepSeek**。不把适配器代码、文档可访问或 mock 响应标成供应商连通与实际计费验证。

## 接口与启用范围

`market_intel.llm.deepseek.DeepSeekTransport(api_key, *, opener=None)` 是标准库 HTTP 传输，`provider="deepseek"`、`version="deepseek-http/0.1"`。它不自行读取环境变量或配置，不自行重试，不调用模型之外的工具；`opener` 仅用于离线测试注入。

仅使用固定 `https://api.deepseek.com/chat/completions`，不可传自定义主机、代理或 URL；默认 `http.client` 直接连接并使用 `ssl.create_default_context()` 验证证书，不继承环境代理，不自动跟随重定向。密钥只在本次请求的 Authorization 头中使用，不进入请求正文、预算元数据或错误文本；对象默认 repr 不包含密钥。

模型选择 `deepseek-flash`，显式关闭思考、流式输出和工具调用，启用 `response_format={"type":"json_object"}`。仅允许额外设置0至2的有限数值 temperature；不能通过参数覆盖模型、messages、max_tokens、端点或工具。system 消息由调用方固定提示词、JSON 输出约束和 schema 说明组成，user 消息仅包含待处理输入的 JSON。来源文本仍是不可信数据；这种分离不构成已验证的提示注入防护或事实支持证明。

`build_payload(request)` 是纯函数式载荷构造，不调用网络。`input_token_bound(request)` 返回实际发送的 UTF-8 JSON 正文字节数加4096，作为消息特殊 token 的保守余量；这不是对真实 tokenizer 的已认证上界。上层仍需执行单次输入上限与调用前预算预留。线上首次样本必须核对实际 prompt_tokens，异常超限不得被伪装为正常精确结算。

## 每日10元的口径

`config/deepseek.example.json` 是公开配置样例，不包含密钥，也不会自行启用付费调用。每日额度为 `10_000_000` microCNY，1元=1,000,000 microCNY；不用美元字段、不按汇率换算。每日 token 另限100,000，单次输出最多512 token，默认不重试。

2026-11-08核实的[官方人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)中，Flash 高峰时段缓存未命中输入为2元/百万token，输出为8元/百万token。样例预留采用该较高费率，不依赖空闲时段或缓存折扣。每次预留和成功 usage 的金额均由上层账本按当前配置估算并向上取整；不能把本地数字当作供应商账单。官方可调整价格，启用前须复核费率，不自动接受网页内容改写预算。

每日按 UTC 自然日、同一配置账本累计，与北京时间交易日不同。10元是本项目单个受控账本的本地估算上限，**不是 DeepSeek 账户全局限额**；别的应用、另一个账本、旧备份回滚或供应商价格变动不受此估算自动控制。不能新建、切换、删除或回滚账本来规避额度；固定生产入口、人工对账和恢复切换须另行验收。未知费用、超时及无效结果保守保留预留，不凭失败自行退费。

## 响应与错误

仅接受单个、正常 stop 的 assistant 结果，返回原始 `message.content`，不重写空白或 JSON 字节。空白内容、length截断、工具请求、非空思考内容、其他模型名都拒绝。响应只核对服务端模型名 `deepseek-flash`，不声称锁定了其后端模型版本。实际输出结构/schema及事实引用由上层校验，本传输不代替证据审核。

usage 的输入、输出、总 token 必须为非布尔正整数，总量与分量一致，输出不得超过本次 max_tokens；可选缓存分量存在时核对范围与总和，非思考调用的 reasoning_tokens 只能为精确整数0。缺失或不可信 usage 拒绝成功，上层应保留预留并显式处理，而非将实际费用补成零。

HTTP 401/402、请求不合法和重定向等映射为固定 ModelError；429/500/503为明确可重试错误，次数与每次新预留由上层控制。网络异常不保留原文；不读取或打印错误响应正文、请求头和密钥。所有响应流在成功和失败路径都关闭。公开 `ERROR_CODES` 供上层按白名单保存固定原因码，不能将任意异常字符串作为账本错误记录。

响应总字节上限为本次 max_output_bytes加64KiB，内容另受 max_output_bytes约束。单次输出token最多8192、输出字节最多1MiB是该传输的额外产品边界，不代表供应商能力上限。

## 超时的实际边界

发送、HTTP响应头和正文读取使用同一 monotonic 截止时点，socket 每次接收前更新剩余时间；服务器连续发送空白或慢速字节不会重置这部分时限。连接完成后也检查已消耗的总时间，再决定是否发送请求。响应读取使用 read1并检查累计字节，避免把逐次 socket timeout误称为整个响应的时限。

操作系统同步 DNS解析、多地址TCP尝试和底层TLS连接不能由此同步 Python 客户端强制中断；它们可能使实际墙钟耗时超过配置值，连接返回后会检查截止时间。本轮不宣称具备所有系统环境下的硬墙钟终止保证，也不创建后台线程来掩盖超时。尚未验证真实网络、证书链、DNS、代理环境或服务端长连接行为。

## 离线验证与后续启用

```powershell
$env:PYTHONPATH = 'src'
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_deepseek.py -v
```

实现者实际运行19项定向测试通过，覆盖固定载荷/密钥边界、HTTP错误、重定向拒绝、无内部重试、总截止时点、慢滴socket、响应关闭、字节上限、模型/usage异常和严格参数。所有 HTTP 响应均为注入合成值，未发送真实请求；独立审查结果由主控回收。后续须在用户本地安全配置密钥，并显式启用后，以少量合成输入核对真实返回与预算记录，再讨论正文抽取和生产使用。

官方参考：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[错误码](https://api-docs.deepseek.com/quick_start/error_codes/)。JSON有效不等于字段受schema或事实支持，上层必须保留本地校验。
