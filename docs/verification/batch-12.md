# Batch12 验收与交接

日期2026-11-17。范围：只读供应商验证证据预检。契约provider-preflight/0.1，调用摘要model-call-info/0.2，模型schema3不变。设计QA先通过，preflight12独占模块/测试/使用说明，root负责契约与CLI集成，qa12独立审查。

交付API preflight_provider_evidence(workspace,call_id)及CLI provider-evidence-preflight --workspace PATH --call-id ID。复用一次已校验只读快照；输出原预算UTC日、原费率估算、安全摘要和有序缺口清单。供应商凭证始终缺失，不认证、不结算、不释放预算、不调用模型。

验证：实现者7/7，主控新增功能及CLI8/8（1.347s）；独立24回归+4自构造场景共28全通过，详见batch-12-review.md。零usage fixture初始错误已修正，产品未因此改变。git diff --check通过。

环境：统一exec启动器失败；旧venv引用被卸载runtime，退出103。通过load_workspace_dependencies定位新的bundled Python3.12.14。首次dev.ps1因子进程ProgramFiles缺失启动失败，补环境后的后台dev.ps1及另一次后台direct完整测试均停在既有audit busy测试，未计通过。再次以前台await运行相同unittest discover -s tests -v，明确完成518运行515通过3权限跳过，50.932s exit0；日志out/batch12-awaited-tests.log。未做普通隔离安装。后台两进程清理请求被OS拒绝访问，完成前状态未知，不冒认已经退出；与WB-06无关，未停止WB任务。

WorkBuddy本轮无可用入口，未派发；没有真实凭证/API/账单/来源刷新，无生产切换。NLP-01保持in_progress，主任务和闸门不升级。没有提交或上传本轮变更。

下一轮：安全本地凭证及显式启用后最小合成真实smoke与账单取证；无凭证时只能继续离线取证协议设计。预算为UTC日单账本10元估算；外部可信高水位、终态结算、账户全局限额及生产恢复待实现。
