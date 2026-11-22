# Batch35 独立验收

`QA-B35` 于 2026-11-22 验收 `evaluate_synthetic_extraction`。新增测试位于 `tests/test_batch35_synthetic_score.py`，使用现有演示样本构造独立原始记录标识及合成提案，核对 `synthetic-extraction-evaluation/0.1`。

将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 与 `TMP` 指向工作区内 `out/test-temp` 的绝对路径，使用可用的 Python 解释器运行。

```powershell
& $qaPy -X utf8 -m unittest test_batch35_synthetic_score test_batch34_synthetic_extraction test_contracts test_candidate_snapshot_contract test_evidence_candidates -v
```

56 项定向测试全部通过，耗时 1.945 秒，退出码 0。

- 六条混合用例产生两条正确、两条错误、一条无效及一条缺失。类别组合只包含结构有效的提案，按预期类别和提案类别排序。倒序输入所得结果一致，原输入保持不变。
- `null` 计为缺失。布尔值、空对象、数组、字符串、数字和来源哈希不符的提案均计为无效，其余已标注样本继续评测。
- 候选缺失时仍校验标注和来源。重复标识、篡改内容、无效标注、非法输入结构以及 UTC 截点之后可用的来源，均导致整批固定错误。空批次仍校验截点。
- 1,000 条用例可以评测，1,001 条整批拒绝。回归同时覆盖 Batch34 的精确引文、Unicode 码点及来源绑定校验。

本轮验证覆盖合成评测的计数与输入边界。真实模型表现和类别支持度仍需独立标注集验收。
