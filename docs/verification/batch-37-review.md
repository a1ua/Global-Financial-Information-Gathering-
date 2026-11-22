# Batch37 独立验收

`QA-B37` 于 2026-11-22 验收合成样例 `config/synthetic-extraction-evaluation.example.json` 及 `evaluate-synthetic-extraction` 的实际模块入口。输出契约为 `synthetic-extraction-evaluation/0.1`。

使用可用的 Python 解释器，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 与 `TMP` 设为工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m market_intel evaluate-synthetic-extraction --input config/synthetic-extraction-evaluation.example.json --cutoff 2026-11-06T00:05:03Z
& $qaPy -X utf8 -m market_intel evaluate-synthetic-extraction --input config/synthetic-extraction-evaluation.example.json --cutoff 2026-11-06T00:05:02.999999Z
& $qaPy -X utf8 -m unittest test_batch36_synthetic_score_cli test_batch35_synthetic_score test_batch34_synthetic_extraction -v
```

- 首次调用退出 0，标准错误为空。总计 4 条，正确、错误、无效、缺失各 1 条。`company → company`、`policy → macro` 各 1 条。
- 截点提前一微秒时退出 1，标准输出为空，错误原因码为 `synthetic_extraction_evaluation_invalid`。
- 四条来源文本和来源标识分别唯一，全部参考记录标记为合成。独立计算规范化文本的 UTF-8 SHA-256，四条均与记录一致。两个有效引文与源码点切片逐字一致。无效引文被拒绝，修正副本的引文后通过结构校验。两次命令调用后，样例文件字节不变。
- Batch34 至 Batch36 定向回归共 14 项，全部通过，耗时 1.456 秒，退出码 0。

本轮验收覆盖离线样例的可复现性。真实模型输出和独立人工标注仍待验证。
