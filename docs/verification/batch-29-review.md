# Batch29 独立验收

`QA-B29` 于 2026-11-22 验证 `summarize-synthetic-week` 的 Markdown 输出。输入沿用 `synthetic-abnormal-return/0.1`，汇总沿用 `synthetic-weekly-review/0.1`。新增回归位于 `tests/test_batch29_weekly_markdown.py`。

使用可用的 Codex Python 解释器，设置 `PYTHONPATH=src;tests`，并将 `TEMP` 与 `TMP` 指向实际工作区的 `out/test-temp`（完整路径，避开沙箱工作目录的连接点）。

```powershell
& $python29 -X utf8 -m unittest test_batch29_weekly_markdown test_batch28_cli test_weekly_review -v
```

11 项通过（0.485 秒，退出码 0）。默认 JSON 与显式 JSON 完全一致，Markdown 使用相同的计数和 CAR，保留完整协议哈希并按协议稳定排序。仅有待计算结果时显示 `N/A`，空周显示四项零计数及无协议提示。测试确认输入字节保持原样，并在数据库连接与网络连接入口设置失败断言。

```powershell
& $python29 -X utf8 -m market_intel summarize-synthetic-week --input <本地示例JSON全路径> --week-monday 2026-11-09 --format markdown
```

用 `config/weekly-review.synthetic.example.json` 实跑命令，退出码 0。Markdown 标题标明合成数据，展示总计 2 条、已计算 1 条、待计算 1 条、缺价 0 条，以及该协议的 CAR 均值 `0.15000000`。

本次为离线验收。真实数据源、模型和正式周报仍待对应任务验收。
