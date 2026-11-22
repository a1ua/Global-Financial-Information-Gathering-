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
