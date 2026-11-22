# Batch36 独立验收

`QA-B36` 于 2026-11-22 验收 `evaluate-synthetic-extraction` 的本地文件输入与命令行输出。新增测试位于 `tests/test_batch36_synthetic_score_cli.py`，沿用合成参考样本、`synthetic-extraction-proposal/0.1` 提案和 `synthetic-extraction-evaluation/0.1` 评测结果。

将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的绝对路径，再使用可用的 Python 解释器运行。

```powershell
& $qaPy -X utf8 -m unittest test_batch36_synthetic_score_cli test_batch35_synthetic_score test_batch34_synthetic_extraction test_batch28_cli test_contracts -v
```

39 项定向测试全部通过，耗时 1.724 秒，退出码 0。

- 通过实际模块入口和进程内命令调用运行同一份合成输入。两者均退出 0，结果与 Python API 一致，包含 1 条正确、1 条无效和 1 条缺失的提案。输入文件字节保持不变，临时目录未产生额外文件。进程内测试对网络、SQLite 和工作区连接设置了失败断言。
- 恰好 1 MiB 的 UTF-8 JSON 输入通过，超出一个字节时拒绝。重复 JSON 键、非标准数字、非法 UTF-8、残缺 JSON、错误批次结构和无效 UTC 截点均退出 1。标准输出为空，标准错误仅保留固定原因码等结构化字段，未包含输入内容或文件名。

本轮验证面向合成样本的离线评测命令。真实模型表现和证据对分类的支持度仍待独立评估。
