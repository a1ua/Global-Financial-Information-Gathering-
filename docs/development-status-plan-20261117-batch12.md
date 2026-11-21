# 最新开发计划：Batch12

2026-11-17。Batch12已完成只读供应商验证证据预检，API/CLI与独立QA通过；全量离线518运行515通过3权限跳过，详见verification/batch-12.md。未做真实模型/账单认证/生产恢复或本轮GitHub发布。

主任务仍9 done、3 in_progress、13 planned、1 cancelled；ENG-04/MKT-01/NLP-01继续进行。已完成能力与后续总体依赖沿用development-status-plan-20261110-batch11.md。

下一项：最小合成真实模型smoke及供应商账单取证，必须安全本地凭证及明确启用，不在聊天中提供密钥；10元/UTC日单账本估算。无凭证则保留阻塞，不冒认完成。随后可信高水位/结算/恢复→NLP-02/03、MKT-02→RPT-01/02与OPS-01→REV-01/02/03→QA-01/02和至少7交易日运行、另3交易日人工基线。

后台全套测试两个进程状态未知且OS拒绝清理；前台完整回归已独立成功。WorkBuddy未派发，独立子Agent审查不冒充WorkBuddy。
