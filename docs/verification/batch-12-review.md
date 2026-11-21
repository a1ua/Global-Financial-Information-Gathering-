# Batch12 独立审查

日期：2026-11-17。审查者 qa12；仅本文件可写。

## 设计审查

无阻断，可冻结：预检单次调用 inspect_model_call，复用绑定schema3完整账本校验与单只读事务。llm_backup._ledger要求call.day等于严格UTC started_at日期，因此可从已验证摘要派生原预算日，无需跨快照二次读库。金额与费率仅复制原调用，不查询当前费率。

缺口以None判断usage，0值不自动当缺失；无论成功、失败或pending，外部receipt始终缺失，权限均false。固定字段清单是取证要求，不是认证协议；不接收人工声明、外部文件或原ID，不改变费用或释放pending。只读SQLite仍可能维护WAL协调文件，绑定文件与DB非跨文件原子。

本阶段tests_run=0，仅设计复核；实现完成后另记独立实测。

## 独立实现验收

结论：通过，无剩余阻断。实际以当前运行时Python3.12.14、src/tests置入sys.path、tempfile.tempdir=工作区out/test-temp物理路径执行。

定向套件：test_provider_preflight、test_batch12_cli、test_model_call_info、test_failure_call_info；最终24项全部通过，4.573秒，exit0。覆盖缺库不创建、坏账本拒绝、模型/网络/密钥访问守卫、原费用占用及无正文摘要，既有实际junction及WAL回归通过。

另外4个独立内联场景全部通过，0.684秒，exit0：跨UTC午夜完成仍保留原预算日；开始日期与账本day矛盾拒绝且文件不变；独立mock摘要零usage为存在并验证清单无跨调用共享；另一调用费用损坏阻断当前精确查询。最终有效独立覆盖28项全部通过，不与主控全套重叠相加。

首轮23项22通过1失败：新增0usage测试错误假设client存0/0；实际旧兼容路径存NULL。实现者修正fixture并另测纯projection的0值边界，产品代码无需改。独立4场景首跑3通过1setup失败：自构造第二次请求命中旧cache，未进入timeout；先清合成cache后4项全通过，测试构造问题。

环境：旧.venv解释器退出103，指向已卸载运行时；py -0p无安装。主控提供当前只读runtime绝对路径后运行。未修复/修改venv，不将环境启动失败记成产品失败。

静态：CLI分支直接调用预检并输出JSON；未创建ModelClient或写连接。预检只调用一次既有inspect，原费率/金额和摘要复制，权限固定false。哈希与字段清单不证明来源/计费真实性；未实际调用供应商、验证账单或切换生产。WorkBuddy本轮未派发，不计辅助验收。

验收时文件SHA256：

- src/market_intel/ops/provider_preflight.py 9aa6eca176dfb4848d58173a8efa58fadacc9c3db2a9c7c8ad98f4a0c49f3ee6
- src/market_intel/cli.py 122dbe84714f4d46f50dba3fc874daac230c808eda581d2c46fd5f9e3cf307ec
- tests/test_provider_preflight.py 8d0ac1d8c05cf9a0c1bf0765bc7b646e8bc3d52b71a6dcc7dc0b231a90a4c586
- tests/test_batch12_cli.py ae0ba85d74154865db3a1523251bc3dd89206869cd3aa49c2ec3d2d473905154
- docs/contracts/provider-preflight-v0.1.md d0750120189bafb94c382f0e873996cf4bab1c888ed66e36f14c5df1fe3f5e61
