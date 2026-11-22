# Batch32 独立验收

`QA-B32` 于 2026-11-22 验收 `hash-provider-response-id`。新增覆盖位于 `tests/test_batch32_response_hash_cli.py`。测试使用合成响应标识，按现有 `response_id_sha256` 契约比对。

使用可用的 Codex Python 解释器，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的完整路径。

```powershell
& $py32 -X utf8 -m unittest test_batch32_response_hash_cli test_provider_correlation test_deepseek_correlation test_deepseek_failure_correlation test_batch31_provider_receipt_cli -v
```

30 项定向测试全部通过，耗时 3.026 秒，退出码为 0。

- 实际模块入口通过二进制标准输入读取合成标识。标准输出仅含 `response_id_sha256`，与 Python 关联函数和独立 SHA-256 计算一致。
- 256 字节标识在无行尾、LF 和 CRLF 三种输入中均有效。超长、空输入、非 ASCII、空白及多行输入返回固定错误，输出中没有原标识。
- 交互终端在读取前被拒绝，模拟读取失败返回固定错误。直接命令测试对工作区连接和供应商传输入口设置了失败断言。

本次验收覆盖本地计算和已有的合成账本回归。供应商响应、真实用量和账单仍待验证。
