# 021 Tasks — Source Lifecycle Ordering

状态：`implemented / verified / pending human git`；正式 delta 为
`specs/source-lifecycle-ordering/spec.md`。T1～T10 已完成；按仓库边界等待人工 commit/push/PR。

- [x] T1 **规格冻结（L1～L6）**：以 SDD 复核 ordering 判别联合、delete 优先级、
  reactivate、stale 审计型 no-op、caller-owned transaction 与 Snapshot 边界；完成独立规格审查
  和 `openspec validate 021-source-lifecycle-ordering --strict`。
- [x] T2 **ordering 贯通（L1）**：先写 `test_l1_*` RED，覆盖 timezone-aware
  `processed_at` UTC 归一、严格 integer generation、kind/revision/ordering 碰撞与深度
  fail-closed；再将 ordering 从 WeKnora `SourceRevision` 无损贯穿 canonical revision、
  SourceImportIdentity、manifest/import context。
- [x] T3 **迁移与 durable root/event（L2/L5）**：先写 `test_l2_*`/`test_l5_*`
  migration RED；实现 revision `0006` 的 SourceHead/SourceEvent、Space 复合约束、唯一键、
  CAS/version、append-only guard 与 SourceLifecycleBackfillIssue。既有 017 source-aware 状态
  只生成唯一 open issue，不从 hash/extracted_at/created_at 猜 head；实现显式、审计化、原子
  issue resolution 管理入口，open issue 阻断正常 lifecycle。`down_revision` 指向实现时 main
  的实际单 head；覆盖首 DDL
  前的 upgrade/downgrade 链级预检、非空数据拒绝 downgrade、空数据 downgrade→roll-forward。
- [x] T4 **notify 状态机（L2/L3）**：先写 `test_l2_*`/`test_l3_*` RED，再让 notify
  在同一 per-source lock/CAS 下处理首次并发 create、same-revision reuse、严格更新推进、旧
  Evidence stale、唯一 recompile 与 CAS loser 重读。
- [x] T5 **source-aware import（L1/L3/L4）**：先写 `test_l3_*`/`test_l4_*` RED，
  再让 import 共用同一 lock/state machine，拒绝 stale、deleted 同代/旧代、ordering 碰撞与
  legacy fallback，并保持 Space 闭合。
- [x] T6 **delete/reactivate（L3）**：先写 `test_l3_*` RED，再让 retract/delete 原子
  写 deleted head、tombstone、scoped Evidence retraction 与 event；相同 identity delete 胜过
  active，旧 delete stale，首事件 delete 创建空 tombstone，active/deleted 收到严格更新 delete
  均推进 ordering 且每 identity 只有一个 tombstone；只有严格更新 active revision 可留下独立
  reactivate event，并逐格覆盖 L3 完整转移矩阵。
- [x] T7 **事务、隔离与发布边界（L3/L4）**：以 `test_l3_*`/`test_l4_*` 覆盖 nested
  savepoint 故障注入、caller 既有工作保留/Session 可用、跨 Space 同 knowledge_id、畸形
  aggregate、legacy 互斥，并断言 ReleaseSnapshot/SnapshotFact/CurrentRelease 零变化。
- [x] T8 **真实 PostgreSQL 双会话（L2/L3/L6）**：用两个独立 connection/Session 覆盖
  首次 head 竞争、同 revision、B/C 逆序与并发、C 后迟到 B、delete-vs-import、
  delete-vs-notify、首事件 delete、active/deleted 的严格更新 delete、严格更新 reactivate、
  CAS loser 重读和失败回滚；设置 connection/
  statement/lock/future timeout，测试名使用 `test_l6_*` 或被验条款前缀。
- [x] T9 **运维与证据（L5/L6）**：更新运行手册、SourceEvent/待处理状态监控、迁移回滚与
  死信恢复；本机缺 PostgreSQL 时只记录 `skip/NOT RUN`，受信 lane 保存 exact SHA、PG 版本、
  node identities 与 JUnit `tests>0, skipped=0`。
- [x] T10 **最终门禁（L6）**：运行 OpenSpec strict、Ruff、mypy strict、非 live/非
  integration_postgres pytest、Alembic upgrade/downgrade/check、真实 PostgreSQL 双会话 lane
  与 `git diff --check`；逐项保存 RED→GREEN，依次完成独立 spec review 与 quality review。

执行约束：所有行为变更先有对应 `test_l1_*`～`test_l6_*` 正确原因 RED；characterization
明确 baseline GREEN。AI worker 不 commit/push；未取得真实 PostgreSQL `tests>0, skipped=0`
证据不得宣称乱序安全或 implementation complete。
