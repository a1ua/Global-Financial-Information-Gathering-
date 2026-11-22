# Batch31 独立验收

`QA-B31` 于 2026-11-22 验收 `compare-provider-receipt`。新增测试位于 `tests/test_batch31_provider_receipt_cli.py`，使用 `provider-receipt-claim/0.1` 合成声明和模拟调用生成的本地账本。

使用可用的 Codex Python 解释器，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的完整路径。

```powershell
& $py31 -X utf8 -m unittest test_batch31_provider_receipt_cli test_provider_receipt test_provider_preflight test_model_call_info -v
```

31 项定向测试全部通过，耗时 6.700 秒，退出码为 0。

- 一致与不一致的有效声明均退出 0，输出与 Python API 的 `provider-receipt-comparison/0.1` 完全一致。输出保留未认证状态及字段差异，声明中的私有值没有出现在结果中。网络和模型入口设置了失败断言。声明文件、账本和绑定文件的字节保持一致。
- 16 KiB 声明文件通过，比上限多一字节时返回固定大小错误。缺少声明文件、重复 JSON 键、非标准数字、非 UTF-8 和字段不符合契约时均退出 1，仅标准错误包含固定原因码。有效声明指向缺失工作区时保持工作区未创建。

本轮数据均来自合成验证。真实模型用量、供应商收据真实性和账户扣款仍待验证。
