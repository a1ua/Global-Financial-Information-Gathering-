# Batch09-A 合成候选限量与预算联验

日期2026-11-09，基线本地84ca192、GitHub73cf935。输入契约`docs/contracts/candidate-batch-v0.1.md`，独占目录/负责人见`collaboration/batch-09-plan.md`。

发布核验：本地代码`979d50697ae0158a3f639b397fd730460f62d5c2`、GitHub快照`0346c2a76cf7b1a4b9fad8b925bef779b4083761`，相同tree`a4b4430a874915ba27cc77718d45d785d8f146a3`；非强制更新，保留本地开发历史。最终发布记录另作后续归档提交。

## 交付

QA先设计审查，主控补充DeepSeekTransport显式拒绝和expected_ledger_id签名/格式/构造时机及TOCTOU限制后冻结，再派候选Agent实现。候选Agent只写纯选择器、定向测试/说明；主控负责runner、CLI和集成；独立QA不修改产品。

- select_candidates先验证最多1000个原始合成项，再按ID去重/冲突拒绝、UTC截点过滤、时刻与ID稳定排序，取0–100项。计数区分重复/未来/限量，不以截断绕过坏尾项。输出复制输入，纯函数无I/O。
- candidate-plan严格解析最多1MiB JSON，只读输出ID/计数，不回显title、不创建账本。
- candidate-mock-run固定mock策略和合成transport，显式写入绑定工作区CNY账本。直接真实传输/策略拒绝；空选择不建库。缓存仍占所选名额；首ModelError停止后续，不回滚已成功或未知费用。重试可多于候选数，每次仍由ModelClient先事务预留。模型schema3/证据schema4不变。
- 提供config/candidates.synthetic.example.json，全部合成、无市场事实。真实候选必须以后接证据版本和availability receipt，不能把任意available_at当系统真实可用时间。

## 实际测试

1. 选择器实现者11项通过。主控runner8项+CLI7项共15项通过，无本轮产品故障修复或测试脚本修正。
2. `./scripts/dev.ps1 test`：384项，382通过、2项Windows符号链接权限跳过，实际junction通过，44.561s，exit0，日志`out/batch09-tests.log`。
3. 独立QA112项，111通过、1权限跳过，8.402s，exit0；另5组stdin场景：future坏尾在cap0/1仍拒绝无库；真实传输子类/非法期望ID建库前拒绝；传输改请求不污染候选或后续schema；UTC跨日归账；CLI拦key/socket仍mock成功、缓存重跑调用逐列不变。详细命令/SHA及边界见`batch-09-review.md`。目标联验为全套子集，计数不叠加。
4. `TEMP/TMP=工作区out/test-temp`下`./scripts/setup-env.ps1`普通隔离安装、项目外CLI help、明确合成demo和隔离测试通过；384项，382通过、2权限跳过，45.841s，exit0。证据`.venv/setup-runs/20261109-140320-57d8829a/`，日志`out/batch09-install.log`。
5. 已安装控制台运行README示例：candidate-plan得到input3/unique3/future1/eligible2/limited1/selected1；candidate-mock-run的2项均成功，provider=mock、is_synthetic=true、live_called=false。工作区`out/batch09-example`，日志`out/batch09-example-plan.log`/`out/batch09-example-run.log`，两命令exit0，未调用真实模型。

仅合成输入/响应/usage；未读取真实密钥、未调用真实模型/来源或供应商账单。不使用真实证据库；NLP-01仅接受此子集，NLP-02和G3不通过。

## 剩余边界

单次候选上限不是跨调用全局数量、transport尝试次数或账户硬费用上限；可信Python transport回调不抵御恶意包装联网。ensure到ModelClient构造非原子，期望ID只保证失败前不generate，不保证期间缺库不被构造器新建。合成标题进入本地请求哈希等元数据，不应放入凭证；CLI不输出title。

真实API/tokenizer/账单、可信外部高水位、结算、生产恢复、真实证据候选与分类均未完成。下一项09-B先冻结既有证据版本/系统回执的只读候选清单，不自动调用模型。WorkBuddy仅设计审查，完整正文和底层工具日志独立认证分开，不能替代代码测试。
