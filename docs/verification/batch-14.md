# Batch14：供应商声明离线比对验收

2026-11-17。承接用户先离线准备，本轮无密钥读取、真实API、账单认证、结算或来源刷新。设计QA先冻结，receipt14独占ops/provider_receipt.py、tests/test_provider_receipt.py、docs/provider-receipt.md；qa14独立审查；主控契约及集成。

新增API compare_provider_receipt(workspace,call_id,receipt)，精确10字段内存声明provider-receipt-claim/0.1，严格校验先于读库，固定安全错误。不新增CLI/文件读取/schema/依赖。一次inspect_model_call复用单只读事务，返回provider-receipt-comparison/0.1安全摘要、有序缺失/差异和金额比较口径。原UTC预算日/原估算，异币种跳过金额。所有字段相等仍未认证；失败/pending全额占用不变。

验收：实现者8/8（1.491s）。主控scripts/dev.ps1 test：526运行523通过3符号链接权限跳过，52.303s exit0；日志out/batch14-tests.log。独立32定向全部通过5.655s+4场景全部通过0.622s，共36有效覆盖，不与主控全套重叠相加；包括WAL修改前后快照、异币种和多差异顺序、失败0金额不释放、非法声明不查库及不泄漏声明内容。QA初始fixture使用禁用key导致3setup错误，修正为普通text后场景通过，非产品问题。详细证据及SHA见batch-14-review.md。初始设计字段计数11更正为列明的10，未增加字段。

限制：声明都是手工/合成未认证内容，不保证供应商提供逐调用账单，不证明扣款。读库可维护SQLite/WAL协调文件，非跨绑定文件原子或防特权改写。没有本轮普通隔离安装；Batch13已完成安装，新增模块本轮以源码全套验收。WorkBuddy工具不可用未派发；既有取消任务不重启、WB-06不停止。主任务与闸门保持原状态。Batch12/13/14未提交发布，output/tmp保持未触碰。

下一步：凭证+显式启用+当日官方模型费率复核后执行最小合成真实smoke和取证，当前仍离线等待。此项前不继续叠加对账辅助功能；可独立推进ENG-04判断持久化契约设计，真实评价仍须行情/日历及评价协议达标。
