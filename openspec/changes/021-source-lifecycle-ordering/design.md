# 021 设计：可排序的来源状态机

## 1. 核心模型

新增 durable `SourceHead`，唯一键为 `(space_id, knowledge_id)`，至少保存：

- `raw_kb_id`；
- `head_revision`；
- `head_processed_at` 或严格单调的 `generation`；
- `state = active | deleted`；
- `event_id`、`updated_at` 与审计 actor；
- CAS/version 列。

必要时增加 append-only `SourceEvent`，记录 notify/import/retract 的输入顺序、决定、前后 head 与 ChangeSet 关联。`SourceImportIdentity` 必须携带可验证的 ordering 字段；该字段从 WeKnora metadata/`SourceRevision.processed_at` 无损传入，不能从 hash 反推。

## 2. 顺序规则

1. 相同 revision/generation 为幂等重放。
2. 小于当前 head 的事件为 stale event，零业务副作用并留审计。
3. 大于当前 head 的 active 事件可推进 head，并触发旧 Evidence stale/recompile。
4. delete 将 head 置为 `deleted`，并绑定删除时的 generation。
5. deleted 后只有严格更新的 revision/generation 可重新激活；相同或更旧 import/notify 必须 fail closed/no-op（由规格场景决定并保持一致）。

## 3. 事务与并发

- PostgreSQL 中按 `(space_id, knowledge_id)` 取得 SourceHead 行锁；首次事件用唯一插入 + savepoint/CAS 建 head。
- 如需 advisory lock，lock key 必须由 scope 与 knowledge 的稳定摘要派生，并在同一数据库事务中持有。
- notify、source-aware import、retract/delete 都必须在取得同一 source lock 后读取 head、比较 ordering、写 ChangeSet/Evidence/SourceEvent，并以一次事务提交。
- CAS 失败必须重读并重新裁决，不得盲重试写入。
- 任一步失败回滚全部 head、Evidence、ChangeSet/Item 与 tombstone 副作用，caller Session 仍可用。

## 4. Scope 与安全

- 所有入口先深度重校验 identity，并用当前 Session 的 bound `KnowledgeScope` 闭合 `space_id/tenant_id/raw_kb_id`。
- SourceHead、SourceEvent、ChangeSet、Claim/Evidence 查询均按 Space 限定；child aggregate 通过 scoped parent join 校验。
- legacy replay 不参与生产 SourceHead，也不得删除或推进 source-aware 状态。

## 5. 发布与兼容

- head 推进、stale/recompile 或 delete 不直接移动 `CurrentRelease`；发布仍由审核后的 snapshot 流程负责。
- 017 现有 exact revision key 保留为批次幂等键，SourceHead 负责跨 revision 顺序，两者职责不混淆。
- 迁移先 backfill 可证明的 head；无法判定顺序的历史多 revision 状态进入人工/死信队列，不猜测 latest。

## 6. 验证策略

- SQLite：纯状态机、scope、CAS 决策、迁移形状与失败回滚。
- PostgreSQL live：同 revision 双会话、不同 revision 逆序、B/C 并发、delete-vs-import、delete-vs-notify、CAS loser 重读。
- live 缺少 URL/fixture 时必须明确 skip，并记录 `NOT RUN`，不得以 mock 代替。
