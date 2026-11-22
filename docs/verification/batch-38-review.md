# Batch38 独立验收

`QA-B38` 于 2026-11-22 使用 Batch37 合成样例验证 `evaluate-synthetic-extraction --include-provenance`。评测输出沿用 `synthetic-extraction-evaluation/0.1`。

用可用的 Python 解释器运行，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 与 `TMP` 设为工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m unittest test_batch38_evaluation_provenance test_batch36_synthetic_score_cli test_batch35_synthetic_score test_batch34_synthetic_extraction -v
```

定向回归共 17 项，全部通过，耗时 6.961 秒，退出码 0。三项新增测试通过实际模块入口检查以下行为。

- 样例报告仍为四条，各结果计数均为 1。默认报告与去掉 `provenance` 后的扩展报告一致。独立计算输入文件的 SHA-256，结果与 `input_sha256` 一致。
- 对同一 JSON 添加空白后，评测计数和类别对一致，SHA-256 随字节变化。两种等价写法 `2026-11-06T00:05:03.000Z` 与 `2026-11-06T00:05:03Z` 在各自报告中保留传入格式。
- 重复 JSON 键和提前一微秒的截点均退出 1。标准输出为空，标准错误有固定原因码，且未出现输入路径、原始内容标记、摘要或追溯字段。原样例和临时输入文件字节保持原样。成功调用未在当前工作目录生成额外文件。

本次验收覆盖离线合成数据的评测追溯。真实模型输出和独立人工标注仍待验收。
