# 合成抽取结果的证据绑定

`validate_synthetic_extraction(reference_bundle, proposal, *, cutoff)` 用于离线验证一个类别及其引用。参考输入复用项目的 raw、event、evidence bundle 校验，只接受标记为合成的 `full_text_fixture`。原始记录的 `available_at` 必须不晚于传入的 UTC 截点，等于截点时允许。参考事件及证据用于校验 fixture 结构，提案类别不要求沿用参考事件标签。

提案为包含以下精确字段的对象。

| 字段 | 要求 |
| --- | --- |
| `schema_version` | `synthetic-extraction-proposal/0.1` |
| `is_synthetic` | `true` |
| `raw_item_id`、`content_sha256`、`normalization_version` | 与参考 raw 逐字段完全一致 |
| `category` | 项目现有事件类别之一 |
| `start`、`end` | Unicode 码点整数位置，左闭右开，且 `0 <= start < end <= len(normalized_text)` |
| `quote` | 非空文本，与固定规范化文本切片逐字符一致 |

成功返回 `synthetic-extraction-validation/0.1`，状态为 `structurally_valid`，并附 `is_synthetic`、`raw_item_id`、`content_sha256`、`category` 和位置 `start`、`end`。返回值只保留定位所需信息。输入校验失败时抛出固定的 `ValueError("synthetic_extraction_invalid")`。

验收范围是合成输入的结构、截点及片段定位。类别准确率和片段对类别的支持度，仍需独立标注验证集与真实模型输出。函数仅计算内存输入。

## 合成分类批量评测

`evaluate_synthetic_extraction(cases, *, cutoff)` 按调用方提供的标签评测 0 至 1000 条合成样本。每条为精确包含 `reference_bundle`、`expected_category` 和 `proposal` 的对象。参考输入和截点沿用上述规则，`raw_item_id` 在批次内必须唯一。期望类别由调用方单独提供，允许与参考事件类别不同。无效参考、期望类别、截点或重复 ID 导致整批拒绝，原因码为 `synthetic_extraction_evaluation_invalid`。

输出版本为 `synthetic-extraction-evaluation/0.1`，标记 `is_synthetic=true`。所有样本都计入 `counts.total`，每条只进入下列一个计数。

- `correct` 与 `incorrect` 分别计数结构有效且与期望类别相同或不同的提案。
- `invalid` 计数结构或证据绑定失败的提案。
- `missing` 计数提案为 `null` 的样本。

`category_pairs` 只包含结构有效提案，逐对列出 `expected_category`、`proposed_category` 和 `count`，按前两个字段排序。报告只输出聚合计数。类别一致表示与传入标签相符，片段支持度仍需单独标注。

### 本地命令

```powershell
python -m market_intel evaluate-synthetic-extraction --input config/synthetic-extraction-evaluation.example.json --cutoff 2026-11-06T00:05:03Z
```

输入为本地 UTF-8 JSON 数组，最大 1 MiB，按原始字节计。拒绝链接、UNC 路径、重复键和非标准 JSON 数字。有效批次将报告写到标准输出，退出码为 0。即使所有提案都无效或缺失，退出码也为 0，质量评估须查看各项计数。文件、JSON 或批次级错误返回 1，标准错误仅含固定原因码。

仓库样例包含四条不同的合成文本，其中正确、错误、引文不匹配和提案缺失各一条。预期 `counts` 为 `{"total":4,"correct":1,"incorrect":1,"invalid":1,"missing":1}`。类别对只有 `company → company` 与 `policy → macro`，各出现一次。样例标签和提案均为人为构造，用来复现计数和错误处理。
