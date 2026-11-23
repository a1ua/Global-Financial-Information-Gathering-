# Batch42 独立验收

`QA-B42` 于 2026-11-24 对合成事件聚类计划执行 API 和实际命令行验收。用例位于 `tests/clustering/test_batch42_synthetic_cluster.py`，从仓库现有的合成 bundle 构造历史版本、重复候选和显式冲突证据。

使用项目可用 Python，将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的绝对路径。

```powershell
& $qaPy -X utf8 -m unittest clustering.test_batch42_synthetic_cluster test_contracts test_batch34_synthetic_extraction test_batch35_synthetic_score test_batch36_synthetic_score_cli test_batch38_evaluation_provenance test_batch39_score_diagnostics -v
```

定向回归共 50 项，全部通过，耗时 12.679 秒，退出码 0。

- 核对了市场集合排序、分类及规范化版本边界、精确内容候选和同标题审查候选。反转输入后输出不变，同一事件的版本按数字排序，单个事件的历史版本不自行形成候选组。
- 原始记录、事件或证据晚于 UTC 截点一微秒时，整条记录从本次候选排除；达到截点时可用。原有版本仍可见，显式 `contradicts` 在其证据可用后保留。
- 核对重复版本 ID、同事件版本号、证据 ID、同 raw ID 内容不一致和未来记录结构错误均拒绝。相同原始记录可被不同事件版本引用。真实标签、非完整合成存储策略、非 `Z` 截点和超出条数上限均拒绝。
- 实际命令输出与 API 完全一致，运行不修改输入字节。测试覆盖重复键、NaN 和超 1 MiB 文件，失败时退出 1，且标准错误不含输入路径或合成私有标记。成功结果也不含原文、标题或来源 URL。

本轮验收覆盖合成证据上的候选划分和记录保留。真实事件的误合并、漏合并及实质冲突需另行用独立标注评估。
