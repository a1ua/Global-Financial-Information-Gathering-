# Batch16 独立验收记录

日期 2026-11-18。

依据 Batch15 语义契约、P16 输入契约及现有候选读取器审查。合成证据固定 ID 与快照哈希绑定。模型 fixture 同时绑定证据 manifest 与判断输出投影。协议与日历快照必须对应，已发生的可用时间与预先发布的未来会话分别比较。建议模型 fixture 的可用时间不早于证据截点，避免声称输出早于输入。内容不携带提交回执，更正前驱由后续持久化工作包复核。读取入口复用既有固定候选快照读取器。

开发机器旧 .venv 指向已移除的 Python，启动退出 103。当前工作区运行时 Python 3.12.14 可正常启动，独立测试使用该解释器。

## 实现审查与实测

契约将模型 fixture 的可用时间下限固定为证据截点，上限为判断创建时间。输入边界先于规范 JSON，限制深度、节点数、整数范围和 UTF-8 字节数。源码复用现有 UTC、ID、规范 JSON 和固定证据读取器。读取前完整校验，证据读取失败返回固定错误，纯校验的错误有独立标识。

使用 Python 3.12.14，在 out/test-temp 下的临时 schema4 库运行独立脚本。全部断言通过，退出码 0。

- 新版本入库后，原判断仍读取旧证据并保持文件清单及字节一致。
- 重新计算哈希后，早于证据截点的模型可用时间仍被拒绝。更改判断方向但保留原输出哈希同样失败。
- 伪造描述符且重新计算各层哈希能通过纯自洽检查，实际库核对仍以 prediction_inputs_unavailable 拒绝。
- 循环对象和未配对 Unicode 代理项统一返回 prediction_input_invalid。
- 原文文件损坏时，固定读取失败并返回 prediction_inputs_unavailable。

同一解释器执行 unittest 套件 test_candidate_snapshot、test_candidate_snapshot_contract、test_evidence_candidates，40 项全部通过，3.022 秒，退出码 0。独立验收集中覆盖本轮输入和既有读取器的接合点。

## 核对文件 SHA256

- docs/contracts/prediction-input-v0.1.md a215a5cd758c32b558ece811df6581b2405106af3b6b6e50536fe8b1e516acc1
- src/market_intel/contracts/prediction_input.py fe25020df6e7d7f5173b8fc05119bf10e9c3e414b2d4ca6dfb8626a256526ee2
- src/market_intel/pipeline/prediction_input.py f73f8295d003d66475fb274009bf5d4c1764aedf7e6c05eff04d894cb8eb85f8
