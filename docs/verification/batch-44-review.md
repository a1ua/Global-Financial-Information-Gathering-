# Batch44 独立验收

`QA-B44` 于 2026-11-24 验收合成事件聚类的同标题候选覆盖。新增用例位于 `tests/clustering/test_batch44_title_review_coverage.py`，样例位于 `config/synthetic-event-cluster-evaluation.example.json`。

使用本地 Python，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m unittest clustering.test_batch44_title_review_coverage clustering.test_batch43_cluster_evaluation clustering.test_batch42_synthetic_cluster test_contracts -v
```

36 项全部通过，耗时 7.235 秒，退出码为 0。其中 4 项新增测试覆盖以下行为。

- 截点 `2026-11-06T00:06:00Z` 下，样例的 4 个标注对包含 1 个真阳性、0 个假阳性、2 个假阴性和 1 个真阴性。新增待审覆盖计数为 2，包含 1 个同事件对、1 个不同事件对，仍有 1 个假阴性未被待审候选覆盖。
- 仅启用选项才附加 `title_review`，精确规则评测结果保持一致。正序和反序输入结果相同，输入对象保持原样。即使精确规则把不同事件对列为候选，待审覆盖仍排除该重叠对。
- 空标注时返回零计数，未标注的待审候选不计入报告。Python API 拒绝非布尔开关。
- 实际命令输出与 API 一致。截止提前一微秒时返回固定错误、退出码 1、标准输出为空。样例文件保持字节不变，成功输出未披露原文、标题或来源网址。

本次使用合成标注衡量待审候选覆盖。真实事件上的人工核对效果仍待独立评估。
