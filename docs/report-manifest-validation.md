# 已发布报告清单校验

日期：2026-11-08。范围：当前实际输出的`report-manifest/0.1`，支持`evidence-brief/0.2`与`evidence-brief/0.3`。本模块是纯结构与内部一致性校验；不读文件、不联网、不更改输入，也不证明新闻事实、来源许可或磁盘文件真实完整。

## 接口

```python
from market_intel.contracts.report import validate_report_manifest
from market_intel.contracts import ContractError

validate_report_manifest(manifest, expected_report_id="my_report_v1")
```

有效返回`None`，错误抛现有`ContractError(ValueError)`，消息为字段路径与稳定原因码，不回显输入正文或秘密值。`expected_report_id`通常来自已发布目录名，防止目录与清单身份不一致。

## 字段与版本

以当前渲染器实际字段为准，必需字段完整且拒绝未知字段；不强加设计示例中存在、实际渲染器尚未写出的`published_at`。若将来增加字段、状态或新能力，应同步升级契约与调用方，不通过接受任意未知字段掩盖拼写错误。

- `report_id`、`run_id`、可空`supersedes_report_id`限1–128个ASCII字母、数字、下划线或连字符；禁止路径分隔符、点路径或自我替代。
- `report_type`仅当前`offline_fixture / rss_snapshot / source_snapshot`。
- `information_cutoff`和`generated_at`为完整UTC Z格式；生成时间不得早于信息截点。`market_session_date`允许null，否则必须是有效日期。展示时区必须是可解释IANA名称。
- renderer/template必须同为0.2或同为0.3，rules必须对应`strict-cutoff/0.2`或`strict-cutoff/0.3`。
- 固定`canonical_json_version=python-json-sorted-utf8/0.1`，按照UTF-8、ensure_ascii=False、sort_keys=True与紧凑分隔符重新计算输入清单SHA256。
- SHA256必须是64位小写十六进制；仅符合形状不等于磁盘内容已被验证。

## 输入、来源与产物

`input_manifest`只含raw_item_ids、event_version_ids、evidence_ids、prediction_ids、market_snapshot_id。ID列表必须真正list、每项合法且唯一，原始证据、事件及片段输入必须同时为空或同时非空；跨对象引用闭包需由数据库验证层继续检查。

当前没有Prediction和MarketSnapshot能力，因此prediction_ids必须空、market_snapshot_id及market_data_as_of必须null。不能用非空字段给尚未实现的模型/行情结果背书。

`source_config_version`是当前渲染器的逗号分隔、排序且去重配置ID；有原始输入时必须非空，无原始输入时必须是空字符串。该字段不替代正式配置文件版本内容验证。

`artifact_refs`固定为`["brief.html"]`，拒绝父路径、绝对路径、额外文件或字符串伪装列表。调用方仍须检查该文件是否存在、是否为允许的普通文件，以及实际字节SHA256是否匹配。

## 状态与真假标记

当前0.2/0.3渲染器总是没有行情评价，且内容支持度未做语义审核，因此仅接受status=degraded、citation_check=passed、content_support_check=not_performed。本轮不预留未实现的succeeded完整报告；未来能力上线后应明确成功含义并升级校验规则。

所有reason_codes必须已知且唯一：

- 合成清单：is_synthetic=true，report_type=offline_fixture，原因集合必须为synthetic_fixture、retrospective、market_data_unavailable。
- 真实/混合清单：is_synthetic=false，report_type为两类snapshot；必须含content_support_not_reviewed和market_data_unavailable，并按0.2/0.3分别使用rss_excerpt_only/source_metadata_only。
- mixed_test_data可作为真实标记清单中的额外原因，但必须有非空证据输入；实际是否含两种数据仍由闭包验证层检查，不能仅信任标记。

该校验只验证自述不互相矛盾。citation_check=passed不代表每个事实被语义支持，输入hash也不是数字签名。

## 验证记录

定向命令：

```powershell
$env:PYTHONPATH = "$PWD/src"
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_report_manifest.py -v
```

本模块实际运行13项测试，全部通过。覆盖0.2/0.3、输入不变、字段/类型/UTC/日期/时区、目录身份、hash重算、重复ID/原因、产物路径、当前能力约束、合成与混合标记、空报告，以及实际渲染合成fixture后的清单兼容。

另在只读模式读取两份已有真实manifest并直接执行校验，均通过：

- `fed_live_20261107_v1`，renderer0.2，5个事件输入。
- `official_sources_20261108_v1`，renderer0.3，35个事件输入。

未修改真实报告、数据库或其他文件。磁盘hash、证据闭包、报告重放及备份恢复演练由主控与对应工作包独立执行；不将本模块13项测试计作完整报告或系统验收。
