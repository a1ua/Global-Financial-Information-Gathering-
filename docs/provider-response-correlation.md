# 成功调用的供应商响应关联

后续Batch11已增加失败响应的可选hash观察，现查询摘要默认0.2；成功路径仍按本文规则。失败新规则见[provider-failure-correlation-v0.1.md](contracts/provider-failure-correlation-v0.1.md)，不释放全额费用、不保存失败正文。下文“失败不保存关联”描述Batch10当时范围。

Batch10，2026-11-10。契约见[provider-correlation-v0.1.md](contracts/provider-correlation-v0.1.md)。本批不改变证据schema4或模型账本schema3，不运行真实付费请求。

DeepSeek适配器在既有非流式响应与usage检查通过后，读取响应体的`id`，使用共享纯函数计算原始ASCII字节的SHA256并作为`ModelResponse.response_id_sha256`返回。只返回哈希，不返回或保存原ID，不读取HTTP响应头，也不把其它`request_id`字段替换为completion ID。传输版本、请求payload和缓存键语义保持不变。

[DeepSeek官方Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)将响应体`id`定义为chat completion标识；这里不把它称为已认证HTTP请求ID、账单ID或签名。API真实返回及逐调用账单关联仍需另行验证。

本地受限格式是1至256个ASCII字母、数字、下划线、点或连字符，不声称这是官方所有可能ID格式。缺少`id`时返回null以兼容既有模拟/旧适配器；存在但null、空白、Unicode、非法类型或超长时返回固定`deepseek_invalid_response`，不回显值。缺字段兼容不能当作官方完整schema验证。

只有ModelClient最终成功且正整数usage在预留内被接受时，才在同一事务持久化可选关联元数据；失败、超时或输出不合格不保存关联，未知费用保留全额预留。缓存命中沿用原调用记录，不制造新供应商关联。哈希只是本地相关性线索，不证明账单、来源、事实、高水位或结算权限，NLP-01整体仍进行中。

## 传输工作包验收

专用模拟HTTP测试`tests/test_deepseek_correlation.py`覆盖精确字节哈希、原ID不返回、缺失兼容、1/256字节边界、非法存在值拒绝、关闭响应、禁止响应头访问，以及先执行既有响应/usage检查。

实际命令（项目根、PowerShell7，PYTHONPATH=src;tests，TEMP/TMP=out/test-temp）：`.venv/Scripts/python.exe -X utf8 -m unittest test_deepseek_correlation test_deepseek -v`。结果25项全部通过、0.034秒、exit0，其中6项为本轮新增，19项为既有传输回归。使用注入模拟HTTP，无真实密钥、网络或模型请求。完整安装、备份、客户端事务、只读CLI和独立QA由对应负责人记录，不以本包测试代替。
