# Batch34 独立验收

`QA-B34` 于 2026-11-22 验收 `validate_synthetic_extraction`。新增测试位于 `tests/test_batch34_synthetic_extraction.py`，使用现有演示样本和由其构造的合成变体。输入提案使用 `synthetic-extraction-proposal/0.1`，返回 `synthetic-extraction-validation/0.1`。

将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 与 `TMP` 指向工作区内 `out/test-temp` 的绝对路径，使用可用的 Python 解释器运行。

```powershell
& $qaPy -X utf8 -m unittest test_batch34_synthetic_extraction test_contracts test_candidate_snapshot_contract test_evidence_candidates -v
```

共 51 项定向测试，全部通过。耗时 1.814 秒，退出码 0。

- 使用含补充平面字符和组合字符的合成文本，确认 Unicode 码点区间和逐字匹配。误用 UTF-16 偏移或使用视觉相同但编码不同的引文都会失败。
- 核对来源可用 UTC 时刻的等值边界，提前一微秒、缺少时区或偏离既有 UTC 格式都会失败。提案中的标识、内容哈希和归一化版本须与指定来源一致。
- 核对坏引用、未知字段、无效类别、布尔或非整数偏移等输入的固定错误。结构有效的仅元数据和非合成来源也会被拒绝。
- 成功结果只保留约定的状态、标识、哈希、类别和偏移。引文和全文未出现在结果中，原输入保持不变。

本轮验证覆盖合成提案的结构与引用定位。真实抽取、类别准确率与事实支持度仍待后续验收。
