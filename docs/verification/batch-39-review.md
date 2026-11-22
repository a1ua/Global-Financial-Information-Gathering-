# Batch39 独立验收

`QA-B39` 于 2026-11-22 使用 Batch37 合成样例验证 `evaluate-synthetic-extraction --include-diagnostics` 及对应 Python API。评测报告沿用 `synthetic-extraction-evaluation/0.1`。

用可用的 Python 解释器运行，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 与 `TMP` 设为工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m unittest test_batch39_score_diagnostics test_batch38_evaluation_provenance test_batch36_synthetic_score_cli test_batch35_synthetic_score test_batch34_synthetic_extraction -v
```

定向回归共 22 项，全部通过，耗时 9.395 秒，退出码 0。五项新增测试验证以下行为。

- 实际命令同时启用诊断和追溯。样例第 2、3、4 条分别标为错误、无效和缺失；仅错误条目包含已校验的预测类别。移除两个可选字段后的报告与默认命令结果相同。
- 颠倒样例顺序后，诊断条目按新的输入位置排列，汇总计数和类别对保持一致。空批次和仅包含正确提案的批次返回空诊断数组。Python API 拒绝非布尔诊断开关。
- 诊断未输出原始标识、文本、引文或单条来源内容哈希。追加重复项导致整批退出 1，标准输出为空，标准错误仅含固定原因码及既有错误结构。成功与失败调用均保留输入文件的原始字节。

本次验收使用离线合成样本。真实模型输出和独立人工标注仍待验收。
