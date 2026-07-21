# 021 设计：可排序的来源状态机

> 本文解释正式 delta 的实现边界；规范性验收以
> `specs/source-lifecycle-ordering/spec.md` 的 L1～L6 为准。

## 1. 核心模型

新增 durable `SourceHead`，唯一键为 `(space_id, knowledge_id)`，至少保存：

- `raw_kb_id`；
- `head_revision`；
- `head_processed_at` 或严格单调的 `generation`；
- `state = active | deleted`；
- `event_id`、`updated_at` 与审计 actor；
- CAS/version 列。

同时增加 append-only `SourceEvent`，记录 notify/import/delete/reactivate 的归一化输入、
裁决、前后 head、actor/causation 与 ChangeSet 关联。`SourceImportIdentity` 必须携带可验证
的 ordering 字段；该字段从 WeKnora metadata/`SourceRevision.processed_at` 无损传入，不能
从 hash 反推。

ordering 使用显式判别联合：timezone-aware `processed_at` 归一为 UTC instant；或采用上游
服务端提供的严格单调、非负 integer `generation`。bool、float、naive datetime、缺失值、
同一 source 混用 ordering kind，以及相同 ordering 对应不同 revision 均 fail closed。

## 2. 顺序规则

1. 相同 revision、ordering 与 desired state 为幂等重放。
2. 小于当前 head 的事件为 stale event，只追加审计，不改变 head/Evidence/ChangeSet/
   tombstone/snapshot，也不产生可消费 recompile。
3. 大于当前 head 的 active 事件可推进 head，并触发旧 Evidence stale/recompile。
4. delete 携带同一 source identity；对当前相同 revision/ordering，`deleted` 优先于
   `active`，并原子写 tombstone。旧 delete 不得删除新 head。
5. deleted 后只有严格更新的 ordering 可重新激活；相同或更旧 import/notify 为审计型
   no-op。相同 ordering 却 revision 不同属于不可排序碰撞，必须 fail closed。
6. source 无 head 时首个 delete 创建 deleted head 与空 tombstone；active 或 deleted head
   收到严格更新 delete 时均推进到 incoming revision/ordering，并为该 identity 创建唯一
   tombstone。重复 delete 只复用业务 tombstone，但每次裁决可追加审计 event。

正式 delta 的 L3 矩阵是全部转移的权威定义；实现不得用到达时间补充未列出的分支。

## 3. 事务与并发

- PostgreSQL 中按 `(space_id, knowledge_id)` 取得同一 transaction-scoped lock。已有 head
  使用行锁/CAS；首次事件在 head 不存在时也必须先取得由完整 source key 稳定派生的
  advisory lock，或使用等价的唯一插入 + nested savepoint/CAS 协议。唯一冲突的 loser
  必须重读 winner 后重新裁决，不能把 IntegrityError 泄漏为随机结果。
- 如需 advisory lock，lock key 必须由 scope 与 knowledge 的稳定摘要派生，并在同一数据库事务中持有。
- notify、source-aware import、retract/delete 都必须在取得同一 source lock 后读取 head、比较 ordering、写 ChangeSet/Evidence/SourceEvent，并以一次事务提交。
- CAS 失败必须在同一 caller-owned transaction 中重读并重新裁决，不得盲重试写入。
- 服务不得 commit 或 rollback caller 的 outer transaction。一次 lifecycle unit 使用 nested
  savepoint 隔离自身写入；任一步失败只回滚该 unit 的 head、Evidence、ChangeSet/Item、
  event 与 tombstone，保留 caller 先前合法工作，Session 仍可继续使用。

## 4. Scope 与安全

- 所有入口先深度重校验 identity，并用当前 Session 的 bound `KnowledgeScope` 闭合 `space_id/tenant_id/raw_kb_id`。
- SourceHead、SourceEvent、ChangeSet、Claim/Evidence 查询均按 Space 限定；child aggregate 通过 scoped parent join 校验。
- legacy replay 不参与生产 SourceHead，也不得删除、推进或恢复 source-aware 状态；生产入口
  也不得在 identity 校验失败后降级走 legacy。

## 5. 发布与兼容

- head 推进、stale/recompile、delete 或 reactivate 不创建、修改或删除 `ReleaseSnapshot`/
  `SnapshotFact`，也不移动 `CurrentRelease`；发布仍由审核后的 snapshot 流程负责。
- 017 现有 exact revision key 保留为批次幂等键，SourceHead 负责跨 revision 顺序，两者职责不混淆。
- 迁移 `0006` 只 backfill 可证明的 head；017 历史记录只有 revision hash、没有可信 ordering，
  因此按 `(space_id, knowledge_id)` 写入 durable `SourceLifecycleBackfillIssue`，不猜测 latest、
  不创建 head。open issue 阻断正常 lifecycle，必须由 bound Space 的显式管理入口携带合法
  ordering identity、期望 state、actor/reason 原子解析。`down_revision` 在实现时绑定当时
  `main` 的唯一实际 head，而不是根据
  `0006` 数字推断。upgrade/downgrade 在首个 DDL 前执行整条目标链预检；存在多 head、
  拓扑不符或 downgrade 会丢失任何 lifecycle/provenance 数据时 fail closed，并保持 schema
  与 `alembic_version` 不变。

## 6. 验证策略

- SQLite：纯状态机、scope、CAS 决策、迁移形状与失败回滚。
- PostgreSQL live：首次 head 双会话、同 revision 双会话、不同 revision 逆序、B/C 并发、
  delete-vs-import、delete-vs-notify、CAS loser 重读，以及失败后的 caller-owned transaction。
- 本机缺少 URL/fixture 时必须明确 skip 并记录 `NOT RUN`，不得以 mock 代替；完成验收必须
  有真实 PostgreSQL lane 的 JUnit `tests>0`、`skipped=0`，并设置 connection/statement/
  lock/future timeout。
