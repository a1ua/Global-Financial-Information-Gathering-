# 固定候选清单与离线重放

Batch09-C，契约 [candidate-snapshot-v0.1.md](contracts/candidate-snapshot-v0.1.md)。证据 schema4、模型 schema3 保持不变；不刷新来源、不调用模型，不将标题元数据当作全文事实审查。

## 使用流程

四个命令均只输出摘要。以下路径相对项目目录；freeze、replay 必须指定全新的目标目录，不覆盖旧文件。

```powershell
python -m market_intel freeze-evidence-candidates --workspace data/live --cutoff 2026-11-09T00:00:00Z --max-candidates 5 --destination out/candidates-frozen
python -m market_intel verify-evidence-candidates --workspace data/live --manifest out/candidates-frozen/candidate-manifest.json
python -m market_intel replay-evidence-candidates --workspace data/live --manifest out/candidates-frozen/candidate-manifest.json --destination out/candidates-replay
python -m market_intel verify-candidate-replay --replay out/candidates-replay
```

默认不选合成数据；测试需要时显式加入 `--include-synthetic`。安装及解释器设置遵循项目 README，不要将上述命令理解成已验证该目录存在。冻结文件目录与重放目录应为彼此独立的兄弟目录，不能在来源工作区内。

## 文件和验证边界

冻结调用既有只读 planner 一次，只写 `candidate-manifest.json`：固定输入清单及其 SHA256，不包含标题、URL、引用或正文。源库复核依据清单中的精确版本、raw/evidence 身份、回执原字符串和三个 payload 哈希，不重新挑选最新版本。

重放读取清单一次，加载同一已验证数据库快照的输入闭包一次，然后写两份 canonical UTF8 JSON：原逻辑快照 `candidate-manifest.json` 和自包含 `candidate-inputs.json`。后者包含 raw/event/evidence/receipt，**因此包含来源文本**，只写入显式指定的本地目录，不在终端摘要中返回。它不是新的来源采集、模型执行或研究结论。

离线验证只接受这两个文件，拒绝额外文件、目录和缺项。它检查严格 JSON（含重复键、非有限数和非法 Unicode）、清单 schema/排序/哈希、bundle 四字段、顺序、对象引用、真实回执、payload 与 normalized_text 内容哈希。它不读取 `content_ref` 指向的原文件；源库和原 raw 文件移除后仍可检查这份闭包。摘要 `replay_sha256` 是 `candidate-inputs.json` 实际字节的 SHA256，文件重新排版会改变该值。

数据标签保留 empty/real/synthetic/mixed。`verified_inputs` 和 `verified_replay` 仅表示输入结构和闭包一致，不等于来源真实、事实支持度验收、可信签名、完整选择证明、防回退锚点或生产模型验收。

## 容量与发布失败

清单最大 1MiB，重放输入最大 64MiB；读写均检查。路径角色和所有祖先的 symlink/junction 检查、数据验证及序列化容量检查均发生在创建目标父目录前。新目标不得与来源工作区或来源清单父目录树在任一方向重叠。

通过校验后才创建父目录，并独占创建目标目录；文件使用排他创建、flush/fsync。竞争失败不覆盖获胜者。多文件发布不是整体原子操作：中断可能留下部分文件，后续验证会拒绝，重试也拒绝占用中的目录；不自动清理、修复或删除它。调用方应检查保留目录，再另选新目标。实现不承诺抵御有权限的本机恶意并发换链或重写历史，也不提供 SQLite 与原 raw 文件系统之间的原子快照。

## 工作包交接与实际验证

- 任务：B09C-ARTIFACT；实现者仅修改 `src/market_intel/ops/candidate_snapshot.py`、`tests/test_candidate_snapshot_artifacts.py` 和本文。
- 输入：Batch09-B planner、Batch09-C 固定快照 v0.1；主控共享纯校验和 B09C-VERIFY 的精确输入 loader。
- 命令：设置项目 `src` 为 PYTHONPATH、项目 `out/test-temp` 为 TEMP/TMP，运行 `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_candidate_snapshot_artifacts.py -v`。
- 实际结果：18 项运行，17 项通过，1 项因 Windows symlink 创建权限跳过。真实 Windows junction 创建并拒绝测试通过。最初的 junction 测试命令参数引号不正确，已修正并重新运行；上述结果为修正后结果。
- 已执行：冻结只调用 planner 一次、重放只调用 loader 一次、源库删除后离线验证、合成/混合/空标签、固定旧版本与回填不重选、坏闭包、JSON/容量/目录角色拒绝、真实 junction 拒绝、中断半成品和并发目标占用均拒绝且不覆盖。
- 未验证：真实来源刷新、付费模型、发票/预算结算、防回退外部锚点、生产运行。完整项目回归、安装和 CLI 及独立验收由主控/QA 记录，不能由本工作包的专用测试代替。

## 补充阅读口径

selection_version记录生成清单时的选择算法版本，不表示复核时再次选最新。容量按UTF8编码后字节计量；清单与输入文件分别限制。receipt校验与verified状态只证明所列输入一致，不认证来源、事实或签名。重放将同次加载的已验证对象canonical编码，不保留来源JSON的排版。
