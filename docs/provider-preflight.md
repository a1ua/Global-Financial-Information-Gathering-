# 供应商验证证据只读预检

Batch12，2026-11-17。API：market_intel.ops.provider_preflight.preflight_provider_evidence(workspace, call_id)。契约provider-evidence-preflight/0.1；复用model-call-info/0.2全部26个安全摘要字段。

仅调用一次inspect_model_call：工作区绑定/schema3/整个账本先验和精确call_id在原有单只读事务完成。返回后在内存派生缺口，不另查数据库、不读取外部凭证、不调用模型。继承固定model_call_*错误，无部分成功输出。SQLite只读观察仍可能维护WAL协调文件，绑定与数据库不是跨文件原子快照。

budget_day_utc取已验证started_at的UTC日期；原账本校验确保该日期等于调用所属day。摘要保留原日币种、费率及估算，不按查询日期重算。

缺口顺序固定：response_hash_missing（无响应标识哈希）、usage_missing（任一用量为null）、supplier_receipt_missing（始终）。合法0用量只是本地已记录，不能证明供应商用量。成功或失败有哈希均只说明本地观察；哈希不证明来源、扣费或真实性。

supplier_receipt_requirements列出后续取证所需response_id_hash/provider/model/utc_day/currency/input_tokens/output_tokens/billed_amount/provenance。清单不读取、验证或认证这些材料，字段齐备也不构成认证。人工声明不能被该接口接受为可信凭证。

status始终evidence_incomplete；read_only为true；model_called、invoice_verified、settlement_allowed、switch_allowed均false。失败/pending仍全额占用，既有记录不回填、不结算、不切换生产、不修改预算。返回无请求/输出正文、原始响应ID、密钥或路径。

验证仅离线合成账本及mock传输，不代表真实模型、账单或生产验收。实际测试命令与结果见后续交接记录。

初次验证环境记录：统一命令入口setup helper失败；Node测试启动先因process全局不可用而未启动，改显式环境后旧.venv解释器退出103，提示原运行时Python路径不存在。这些不是产品测试失败，也不能计为用例通过；等待恢复解释器后执行专用和独立验收。

恢复后使用新运行时Python（v26-1112-737-0）及PYTHONPATH=src;tests、TEMP/TMP=out/test-temp执行：python -X utf8 -m unittest test_provider_preflight -v。首轮6项5通过1失败：自写fixture误以为0/0响应会存零，实际client兼容路径保存NULL，产品正确报usage_missing。修正真实fixture预期，并增加纯projection的mock摘要0值边界；最终7项全部通过，1.123秒，exit0。零值mock仅验证is None语义，不冒充真实零usage入账。无产品修改。
