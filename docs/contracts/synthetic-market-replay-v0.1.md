# 合成行情重放文件

将 Batch23 的合成行情快照保存为可独立核验的重放文件。输入为本地 UTF-8 JSON，精确键包含 calendar_source、instrument_id、bars、cutoff、start_date、end_date。行情及日历格式沿用 Batch23。输入与输出文件各限 1 MiB。

```powershell
python -m market_intel create-synthetic-market-replay --input config/market-replay.synthetic.example.json --destination out/market-replay-example
python -m market_intel verify-synthetic-market-replay --replay out/market-replay-example
```

目标必须是新目录。创建完成后，目录仅包含 market-replay.json，保存版本 synthetic-market-replay/0.1、日历来源对象、快照及按日期排列的选定版本。输出摘要包含快照 SHA-256、选定数和缺失数。已有目标保持原样。创建中断后留下的无效目录无法通过核验。

核验读取新目录内的文件，校验固定日历、所选版本及快照哈希和缺失日期。额外行情行、重复行或文件会被拒绝。样例预期选定 1 日，缺失 1 日。文件保留选中版本和日历内容。哈希核对该闭包的一致性，原始输入文件及未选中的版本不随文件保存。生产数据来源另行验收。
