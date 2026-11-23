# 合成事件聚类候选计划

`plan_synthetic_event_clusters(bundles, *, cutoff)` 接收最多 1,000 个合成全文 bundle，复用 `raw-item/0.1`、`event-version/0.1` 和 `evidence/0.1` 的结构、哈希和引文校验。三个对象的 `available_at` 均不晚于 UTC 截点才纳入。整批校验包括截止时间之后的输入。相同事件版本 ID、相同逻辑事件与版本号组合、相同证据 ID，以及同一原始记录 ID 对应不同原始记录均拒绝，返回固定错误 `synthetic_event_cluster_invalid`。

结果版本为 `synthetic-event-cluster-plan/0.1`，标记 `is_synthetic=true`。含以下字段。

- `members` 保留所有符合截点的版本，按逻辑事件 ID、数字版本号排序。每项含 `event_id`、`event_version_id`、`version`、`raw_item_id`、`evidence_id` 和原始 `relation`。明确标记为 `contradicts` 的证据保持原关系。
- `excluded_after_cutoff` 计数至少一个对象晚于截点的 bundle。
- `exact_duplicate_groups` 按相同类别、市场集合、文本规范化版本和原文哈希列出跨逻辑事件的精确去重候选。
- `ambiguous_title_groups` 按相同类别、市场集合和逐字标题列出跨逻辑事件、含不同内容哈希的待核对候选。组内可能同时包含精确去重候选。

组内版本 ID 和组列表均按字典序排序。结果不含原文、标题或引文。候选供人工核对，流程保留每个版本和全部可用证据。文本一致或标题相同只能说明匹配规则命中；语义归并、误合并和漏合并评估仍需独立标注。

```powershell
python -m market_intel plan-synthetic-event-clusters --input out/synthetic-cluster-bundles.json --cutoff 2026-11-06T00:06:00Z
```

输入是最多 1 MiB 的本地 UTF-8 JSON 数组，沿用现有文件和严格 JSON 校验。合法结果写入标准输出并退出 0，失败退出 1。整个命令只读取输入文件并在内存中计算。

## 按标注评测精确去重候选

`evaluate_synthetic_event_clusters(bundles, labels, *, cutoff)` 使用同一截点重建计划，再逐对比较人工标签。每个标签恰有 `event_version_ids`（两个版本 ID）和布尔值 `same_event`。两版本须属于不同逻辑事件且在截点可见。同一无序对只允许标注一次。允许 0 至 1,000 个标签。

同属一个精确去重候选组表示规则将该对列为正例。只出现在同标题待核对组的对仍按规则负例计数。未标注的对完全排除在评测分母外。

结果版本为 `synthetic-event-cluster-evaluation/0.1`，标记为 `is_synthetic=true`。 `counts` 包括 `labeled_pairs`、`true_positive`、`false_positive`、`false_negative` 和 `true_negative`。 `false_positive_pairs` 定位可能的误合并候选，`false_negative_pairs` 定位漏掉的同事件对。列表及每对 ID 均按字典序排列。两类差异属于固定标注集上的规则评测，流程保留所有原始事件版本。

```powershell
python -m market_intel evaluate-synthetic-event-clusters --input out/synthetic-cluster-evaluation.json --cutoff 2026-11-06T00:06:00Z
```

CLI 输入为恰含 `bundles` 和 `labels` 的本地 UTF-8 JSON 对象，最多 1 MiB。合法结果写入标准输出并退出 0。无效输入退出 1，其中非法评测参数或标签使用固定原因码 `synthetic_event_cluster_evaluation_invalid`。

### 同标题候选覆盖

添加 `--include-title-review`，或在 Python API 传入 `include_title_review=True`，可附加 `title_review`。该对象只统计截点可见、已标注、同属一个待核对标题组且未被精确规则命中的版本对。

- `labeled_candidates` 是新增的待核对对数，等于 `same_event_candidates` 与 `different_event_candidates` 之和。
- `covered_false_negative_pairs` 列出待核对队列覆盖的精确规则漏报，版本 ID 和列表均按字典序排列。
- `uncovered_false_negatives` 是待核对队列仍未覆盖的精确规则漏报数。

精确规则的原有计数与差异列表保持不变。报告中的新增对仍需人工核对。默认命令和 API 保持原有输出。

```powershell
python -m market_intel evaluate-synthetic-event-clusters --input config/synthetic-event-cluster-evaluation.example.json --cutoff 2026-11-06T00:06:00Z --include-title-review
```

样例使用合成记录和人工构造标签。精确规则在 4 个标注对上得到 1 个正例命中、0 个误报、2 个漏报和 1 个负例命中。同标题队列新增 2 个已标注候选，覆盖其中 1 个漏报，并带来 1 个异事件对待核对。
