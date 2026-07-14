# 018 任务

- [ ] T1 先写 SnapshotFact migration/immutability 失败测试，再实现表与投影构建器（R1）
- [ ] T2 先写 current/effective-date/coverage-gap 测试，再实现 SnapshotReader（R2）
- [ ] T3 先写 Wiki 由快照渲染测试，再切换 publisher 数据源
- [ ] T4 先写状态机与“失败不移动指针”测试，再实现 PublishAttempt（R3）
- [ ] T5 先写回滚失败/补偿测试，再实现 reconciliation（R4）
- [ ] T6 先写 curated-first/raw fallback policy 测试，再实现协议层（R5）
- [ ] T7 live upsert/rollback、Runbook、validation-report、HANDOFF/13/16/20 对账

状态：待实施；依赖 016，Evidence 完整性接入 017。
