# 合成候选的确定性限量

`select_candidates(batch, cutoff, max_candidates=5)`位于`market_intel.pipeline.candidates`，按`contracts/candidate-batch-v0.1.md`验证并选择合成候选。它是无文件、数据库、模型或网络I/O的纯函数，不读取真实证据库。

全部原始项先验证，最多1000项；候选严格字段、ASCII ID、UTC Z时点、非空白且最多4096 UTF8字节的title、is_synthetic恰True。即使上限为0、条目晚于截点或预计会被截掉，也不能跳过无效输入。

同ID全部字段相同计重复；同ID字段冲突整批拒绝，即使两个时间文本指向同一时刻。通过验证及去重后，按解析时刻筛选available_at<=cutoff，再按时刻升序、ID升序排序，取前0–100项。默认5；bool不能充当整数上限。时间比较不依赖文本字典序。

结果分别统计原始项、唯一项、重复项、未来项、可选项、因上限未选项和最终所选项；未来项不计作超上限。返回的候选记录独立复制，不修改或暴露输入记录的可变别名。相同集合的顺序置换不会改变selected或计数。

固定错误码为candidate_limit_invalid、candidate_batch_invalid、candidate_invalid、candidate_timestamp_invalid、candidate_conflict；不回显title或原始异常。输出selected含原始合成title供内部mock处理，CLI另负责仅输出摘要/ID，不应将该函数返回值直接当脱敏日志。

这只验证单次合成文件限量与顺序，不代表真实新闻筛选、重要性排序、长期队列公平、供应商token或NLP-02验收。真实来源接入必须另冻结证据版本及系统可用时间回执契约。

定向测试命令：设置PYTHONPATH=src、TEMP/TMP为工作区out/test-temp，运行`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_candidates.py -v`。测试使用合成对象；实际结果以工作包交接及独立QA报告为准。
