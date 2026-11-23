# Batch45 独立验收

`QA-B45` 于 2026-11-24 核对 `B45-TITLE-ADJUDICATION` 的 Python API 与实际命令。测试位于 `tests/clustering/test_batch45_title_adjudication.py`，使用既有合成事件夹具和独立构造的裁决输入，核对 `synthetic-event-cluster-adjudication/0.1`。

将 `PYTHONPATH` 设为 `src;tests`，将 `TEMP` 和 `TMP` 指向工作区内 `out/test-temp` 的完整路径，使用可用的 Python 解释器执行。

```powershell
& $qaPy -X utf8 -m unittest clustering.test_batch45_title_adjudication clustering.test_batch44_title_review_coverage clustering.test_batch43_cluster_evaluation clustering.test_batch42_synthetic_cluster test_contracts -v
```

**40 项定向回归全部通过**，0 项跳过，耗时 9.183 秒，退出码 0。

- 三种裁决各计 1 项。版本对和输出顺序稳定，保留原 UTC 截点写法、事件版本、证据 ID 及 `contradicts` 和 `reports` 关系。以独立规范 JSON 序列化和 SHA-256 运算核对各成员完整 bundle 的哈希，包含中文和补充平面字符的证据内容。
- 两个版本须归属不同逻辑事件、同属标题待核对组，而且没有同时命中精确规则。反向重复、缺失版本、同逻辑事件、组外成员、错误裁决类型、未知字段和超过上限均返回固定错误。证据在截点后一微秒时拒绝裁决，在该时刻重新评估时纳入。
- 实际 `python -m market_intel` 命令和 API 完全一致，输入文件字节保持原样，临时目录只含测试输入。成功输出未包含原文、标题、引文或网址。无效结构和重复 JSON 键使用固定错误，且标准输出为空。

生产裁决的标注质量、来源授权和人工签核仍待独立验收。
