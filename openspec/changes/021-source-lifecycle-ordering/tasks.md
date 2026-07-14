# 021 Tasks — Source Lifecycle Ordering

状态：`proposed / pending`；未实施。

- [ ] T1 以 SDD 明确 source ordering、删除与重新激活状态机，完成规格审查。
- [ ] T2 先写 RED：`processed_at/generation` 从 WeKnora SourceRevision 到 SourceImportIdentity/manifest/import 的无损传播与深度校验。
- [ ] T3 先写迁移 RED，再实现 SourceHead/SourceEvent、scope FK/唯一键/CAS/version；迁移编号与 018 串行协调，不占 `0005`。
- [ ] T4 先写 RED，再让 notify 在 per-source lock 下比较 head、推进 revision、stale Evidence、创建/复用 recompile。
- [ ] T5 先写 RED，再让 source-aware import 在同一 lock/CAS 下拒绝旧、同代 deleted 与乱序事件。
- [ ] T6 先写 RED，再让 retract/delete 原子写 tombstone/head/event，并仅允许严格更新的 revision 重新激活。
- [ ] T7 覆盖 scope/legacy 隔离、畸形 aggregate、事务失败回滚、snapshot/current pointer 不动。
- [ ] T8 增加真实 PostgreSQL 双会话测试：同 revision、不同 revision 逆序、B/C 并发、delete/import 与 delete/notify 竞争；为连接、语句、锁和 future 设置超时。
- [ ] T9 更新运行手册、监控与死信恢复；缺 live 前置条件时显式 `skip/NOT RUN`。
- [ ] T10 运行非 live pytest、Ruff、mypy、迁移检查、diff check，并依次完成独立 spec review 与 quality review。

执行约束：每个行为修复必须先有失败测试；AI worker 不 commit/push；未完成真实 PostgreSQL 证据不得宣称乱序安全。
