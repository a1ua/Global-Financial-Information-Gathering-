# Batch43 独立验收

`QA-B43` 于 2026-11-24 验收合成事件聚类的成对标注评测。测试文件为 `tests/clustering/test_batch43_cluster_evaluation.py`。输出契约为 `synthetic-event-cluster-evaluation/0.1`。

使用项目可用的 Python，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m unittest clustering.test_batch43_cluster_evaluation clustering.test_batch42_synthetic_cluster test_contracts test_batch39_score_diagnostics -v
```

37 项定向回归全部通过，耗时 7.632 秒，退出码 0。新增 4 项测试覆盖以下行为。

- 六条成对标注产生 1 个真阳性、2 个误合并候选、2 个漏合并候选和 1 个真阴性。同标题待核对候选在该组中计为 1 个漏合并候选。未标注的精确候选不计入总数。空标注返回全零。
- 反转 bundle、标注及版本 ID 对内部顺序后，结果不变。误合并和漏合并候选列表按版本 ID 排序。函数不修改输入。
- 重复或反向重复标注、同一逻辑事件的两个版本、不可见或不存在的版本、非布尔值和超量标注均被拒绝。晚一微秒的证据到达截点后，其版本可参与评测。
- 实际 CLI 输出与 API 相同，输入文件和目录保持原样。未知字段、重复 JSON 键和 `NaN` 退出 1，仅返回固定错误，结果未披露输入路径、原文、标题或来源网址。

测试使用合成标注，反映精确候选规则与这些标签的一致性。真实事件聚类效果和人工待核对结果仍待评估。
