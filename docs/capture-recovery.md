# 持久采集队列与恢复协议

日期：2026-11-08。范围：单机、单写入者、标题级metadata_only队列。schema由主控的store迁移v4安装；本模块不建表、不联网、不安装调度或分布式锁。

## 接口与事务

```python
discover(db, source_id, items, observed_at)
pending(db, source_id, limit, *, exclude_queue_ids=())
complete(db, queue_id, event_version_id)
fail(db, queue_id, reason)
checkpoint(db, source_id)
```

写操作各自要求干净连接（`db.in_transaction == False`），以`BEGIN IMMEDIATE`原子提交并在异常时回滚。主控应先提交内容与availability receipt，再调用complete，不能包在未提交的外层事务中。

discover将**本次完整已解析列表**一次入队；limit仅限制后续消费，不限制发现。先校验全部条目形状，并复用公共URL规则拒绝带凭证、私网等明显不安全链接，再入队；同快照同项目相同标题去重，不同标题视为冲突并拒绝整个发现事务。来源抓取或解析失败时，调用方不能调用discover，因此成功扫描检查点不前进。正常空列表只有解析器确认是有效空结果时才可传入，不以解析失败替代空列表。完整bundle的时间与枚举语义仍在消费时校验，失败保留pending，不因发现检查点前进而伪装为导入成功。

队列仅保留九字段元数据形状，normalized_text强制等于title，来源description不落队列。指纹与当前make_bundle标题模式一致：canonical JSON中的title及text:title。每项目保留last_fingerprint和递增observation_no，A→B→A会产生三次观察；不会因为A的历史hash已存在就丢掉回退。标题以外的时间、URL或摘要更正本批不作为新内容修订，此限制必须在报告覆盖中披露。

pending返回每项目最早未完成观察，其字典字段为queue_id、source_id、source_item_key、observation_no、fingerprint、item（dict）、observed_at、attempts、last_error。它是读取，不claim、不完成队列。

项目间按`attempts ASC, queue_id ASC`选择。失败项增加attempts后，让尚未尝试的健康项目优先；即使每次limit=1，永久失败项也不会阻挡其他项目。项目内部仍严格FIFO，失败A会阻挡同项目后续B。调用方在同一运行中将所有已尝试queue ID传给exclude_queue_ids，避免本轮立即重试；排除A不会解除同项目后续B的顺序约束。

complete必须找到已提交receipt、对应最新事件、同来源/项目/标题的metadata_only raw。验证后才标done。重复用同一event_version_id完成是幂等的；更换完成引用会拒绝。fail保留pending、增加attempts并保存有限原因码，不保存不可信正文或凭证文本。

## 检查点语义

checkpoint将发现与消费分开：

- last_successful_scan_at / scan_items：完整discover事务的最近成功扫描；不表示所有队列已处理。
- consumed_through_queue_id：本来源按queue ID连续完成前缀的末端，不是最大done ID；健康项可先完成，但不能越过失败缺口推进此前缀。
- last_completed_at：最近一次成功消费时间，不表示整个来源全部完成。
- pending / done：本来源当前队列数量。

队列和观察头保存在SQLite，关闭/重开连接后继续存在。若内容已提交但complete前崩溃，下一运行重新处理该pending记录；调用方应复用已存内容或恢复receipt，然后幂等完成。若发现事务中途SQL失败，整个队列与成功扫描时间一起回滚。

## 主控消费建议

```text
本轮attempted = set()
while 本轮尝试数 < limit:
    pending(..., limit=1, exclude_queue_ids=attempted)
    无项则结束
    先把queue_id加入attempted
    尝试内容入库与receipt提交
    成功：complete(queue_id, 精确event_version_id)
    可恢复条目失败：fail(queue_id, 稳定原因码)，保留pending
```

外部抓取与解析日志由主控维护；本模块不证明真实来源已接通或页面长期稳定。没有实现完整分页、历史回溯或多进程租约，不能将小列表全量重叠扫描说成全网覆盖。

## 本次验证

执行：以项目venv、`PYTHONPATH=src`运行`python -X utf8 -m unittest discover -s tests -p test_capture_state.py -v`。最终定向结果由交接消息记录。

覆盖完整发现后限量读取、标题元数据保留、重复扫描、冲突快照回滚、SQL失败回滚、A→B→A、receipt要求、同项目FIFO、完成幂等、连续消费前缀、来源隔离、连接重启、同轮排除及跨运行limit=1公平性。测试使用临时/内存schema和合成标题，不代表来源实测或主控全链路集成通过。
