# Batch14 独立审查

2026-11-17。QA-B14仅写本报告。设计复核：无阻断，可冻结。

输入为严格内存dict声明provider-receipt-claim/0.1，精确10字段、规范call_id与请求一致、非空64小写hexhash、固定provider/currency、模型ASCII有界、规范UTC日期、非bool有界整数。所有输入类型先验证再调用一次inspect_model_call，非法输入固定provider_receipt_claim_invalid，既有账本错误保留model_call_*。

输出provider-receipt-comparison/0.1精确13字段；仅返回已验证安全本地摘要和固定原因，不回显任意供应商文本。missing_local_fields独立于mismatched_fields，本地null不伪装零；金额仅同币种与原本地configured_rate_estimate比较，异币种not_comparable_currency_mismatch，不计算金额差或进行汇率换算。原预算日取已验证started_at日期，_ledger保证与call.day相同。全部认证/结算/切换/模型权限false，状态永远unverified_comparison，字段匹配不认证来源或账单。失败/pending全额占用不改变。

当前仅设计审查，tests_run=0；实现冻结后独立实测。

## 实现与独立验收

最终静态复核通过，无阻断。契约精确输入10字段（初始口述11的计数已纠正，列举字段未变），输出13字段；validate在任何读库前，类型/枚举/正则/日期/非bool整数上下界严格。compare仅一次inspect_model_call；继承全账本业务校验和只读事务，无新数据库/文件/网络入口。金额只在同币种比较原charged_cost估算，无金额delta，不回显声明原值。失败及pending预算不变，任意匹配仍不认证。

独立实际命令：恢复后的.venv/Scripts/python.exe -X utf8 -c <inline unittest loader>；inline显式插入项目src/tests及工作区out/test-temp，不读凭证。定向模块test_provider_receipt、test_provider_preflight、test_model_call_info、test_failure_call_info、test_batch12_cli：32项全部通过，5.655秒、exit0；实际Windows junction检查通过。

另4独立自构造场景全部通过，0.622秒、exit0：全部字段差异固定顺序与异币种金额抑制且不回显声明模型；失败哈希观察+零扣款声明仍全额预留/数据库字节不变；非法list/dict/bool/日期/Unicode在任何inspect前固定错误；WAL验证后并发改hash，本次单快照原hash、下次新hash且query_only单事务。有效覆盖36执行36通过0跳过，不与主控全套重叠相加。

初始独立内联测试以secret作为模型输入键，触发既有credential_field_forbidden保护，3场景在setup未建调用就失败（另1场景通过）；改为text键后上述4全过，属于自写fixture错误，无产品代码修正，不计初始失败为通过。实现者冻结后8项专用测试结果不冒领为QA新覆盖。

只写本审查文件；未真实模型/账单/来源刷新，未WorkBuddy，未结算或释放预算，未执行完整安装。主控完整回归由主控另记。

SHA256：
- src/market_intel/ops/provider_receipt.py: 8207cba0e2f7142846c4fea06f2de48b3e15155d4f928afc4d9d67df8fef0fe9
- tests/test_provider_receipt.py: ad3d406c9c527b3b999ce6e7ca90c9336cbe5e01daef68e7fdf1af1545f3c881
- docs/provider-receipt.md: 676e6fba1efb0bd892c47fc407816bf5cb1aaf3ebad5cba37538c6a17a77892c
- docs/contracts/provider-receipt-v0.1.md: 9dbba5240a0a8a6a47f6fad7979100ac8d0914238910a423673f919495968c0e
