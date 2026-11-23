# 当前活跃上下文（自动生成）

> 本文件由 `scripts/build-active-context.py` 从 `collaboration/task-board.json` 自动裁剪生成，供新会话快速启动。
> 完整历史总账见 `collaboration/task-board.json`（仅在需要追溯历史批次时按需查阅，勿全量读入）。

## 1. 基线快照

- **更新时间**：`2026-11-24`
- **任务统计**：已完成 `10` / 进行中 `2` / 待开发 `13` / 已取消 `1`
- **最新状态**：Batch45 synthetic title-review adjudication accepted. 718 run, 714 passed, 4 Windows symlink permission skips; 40 independent targeted checks passed. Production clustering and independent labels remain pending.
- **最新交接**：`docs/development-status-plan-20261124-batch45.md`
- **闸门状态**：`G0`: passed_local | `G1`: partial | `G2`: partial | `G3`: not_accepted | `G4`: not_started | `G5`: not_started

## 2. 当前进行中任务（优先推进）

### `MKT-01` 验证标的、基准、行情与交易会话来源
- 负责人：`data-review-agent` | 闸门：`G4` | 依赖：`ENG-03`
- 可写路径：`docs/market/`, `config/instruments.yaml`, `config/calendars.yaml`, `tests/fixtures/market/`
- 当前进展：Batch18 reviewed CSI/SSE source evidence and 2 historical OHLC rows, validated normalized OHLC against explicit sessions. Tushare index_daily documentation candidate; authorized direct sample, actual open/arrival semantics, historical session coverage, revisions and retention pending. Batch19 generated 242 SSE scheduled dates from official notices and linked OHLC audit. Actual session and authorized provider coverage still pending. Batch20 offline documented Tushare sample normalization and session audit accepted. Real sample not accessed. Batch21 offline file-to-coverage audit accepted; Antigravity reviewed synthetic edge cases; authorized real source pending. Batch22 validated SZSE plan and offline .SZ audit with non-interchangeable SSE/SZSE provenance. Authorized samples and actual sessions pending. Batch30 added opt-in offline scope diagnostics for SSE and SZSE sample audits. Authorized samples and actual sessions still pending. Batch33 compares exact OHLC values across two complete same-scope offline samples and binds both response hashes and the schedule snapshot.

### `NLP-01` 实现模型客户端、预算与缓存
- 负责人：`model-report-agent` | 闸门：`G3` | 依赖：`ENG-03`
- 可写路径：`src/market_intel/llm/`, `tests/llm/`, `config/llm.example.yaml`
- 当前进展：DeepSeek10 CNY/day per UTC ledger. Candidate snapshots plus successful/failed response hash observations accepted offline. Real API/tokenizer/usage/invoice verification, account-wide bound, terminal settlement, trusted external high-water and production switching remain pending. Failed observations never release reservations. Batch31 added a bounded offline CLI for manual provider receipt claims, retaining unverified comparison semantics. Batch32 added local response ID hashing on stdin for independently preparing receipt claims.

## 3. 待开发任务队列

**等待前置依赖**：

| 任务 | 标题 | 闸门 | 未满足依赖 |
| :--- | :--- | :--- | :--- |
| `MKT-02` | 实现行情与日历的版本化同步 | `G4` | `MKT-01` |
| `NLP-02` | 实现抽取分类与证据绑定 | `G3` | `NLP-01` |
| `NLP-03` | 实现规则聚类、歧义裁决与冲突保留 | `G4` | `NLP-02` |
| `RPT-01` | 实现报告截点与引用检查 | `G3` | `NLP-02` |
| `RPT-02` | 实现双模板、降级与原子归档 | `G3` | `RPT-01` |
| `REV-01` | 冻结判断与评价协议 | `G4` | `MKT-02`, `NLP-03` |
| `REV-02` | 实现成熟队列与AR/CAR核对 | `G4` | `REV-01` |
| `REV-03` | 实现周度样本与结果报告 | `G4` | `REV-02` |
| `OPS-01` | 实现调度、锁与漏跑恢复 | `G3` | `RPT-02` |
| `QA-01` | 独立集成、故障与时间边界回归 | `G5` | `OPS-01`, `REV-03` |
| `QA-02` | 运行观察、手册与最终交付验收 | `G5` | `QA-01` |
| `WB-02` | WorkBuddy时间与收益黑盒复核 | `G4` | `REV-02` |
| `WB-03` | WorkBuddy报告阅读与证据抽检 | `G3` | `RPT-02` |

## 4. 最近批次收尾（`batch45_work_packages`）

- `B45-TITLE-ADJUDICATION`（`done` / `coordinator`）：`src/market_intel/pipeline/process/cluster.py`, `src/market_intel/cli.py`, `docs/contracts/synthetic-event-cluster-v0.1.md`, `docs/development-status-plan-20261124-batch45.md`, `docs/ACTIVE_CONTEXT.md`, `collaboration/task-board.json`
- `QA-B45`（`done` / `title_adjudication_qa`）：`tests/clustering/test_batch45_title_adjudication.py`, `docs/verification/batch-45-review.md`

## 5. 新会话最小启动清单

1. 必读：`AGENTS.md` + 本文件 `docs/ACTIVE_CONTEXT.md` + `docs/development-status-plan-20261124-batch45.md`
2. 按需读：本轮任务对应的 `docs/contracts/*.md` 与允许修改的 2~3 个源码/测试文件
3. 刷新本文件：更新 `collaboration/task-board.json` 后运行 `./.venv/Scripts/python.exe scripts/build-active-context.py`
