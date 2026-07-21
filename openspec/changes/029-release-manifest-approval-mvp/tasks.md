# 029 任务（风险 A；知识/迁移独占）

- [ ] T1 冻结 manifest canonical schema，写 RA1 RED（重排稳定、任一内容变化改 hash、Evidence 计入）
- [ ] T2 实现 manifest builder 与只读 view，不改 018 SnapshotFact 语义
- [ ] T3 写 RA2 RED：授权 actor、完整 hash、append-only approval；实现模型/表/service
- [ ] T4 写 RA3 RED：approval mismatch、篡改、expected current CAS、并发单赢家；实现 promote
- [ ] T5 写 RA5/RA6 RED：有效旧批准回滚、零模型、P-1 前 production UI fail closed；实现 rollback guard
- [ ] T6 迁移 0013；SQLite + PostgreSQL focused 验证，合入前重新指向实际 Alembic head
- [ ] T7 暴露 ApprovedSnapshotReader 的 snapshot/manifest hash 公开合同，供 013/032 使用；不修改其文件域
- [ ] T8 写 RA7 RED/实现治理专用 CLI：只消费 sealed compilation bundle 与真人填写的 review/approval request，按 apply-review-decisions→build-candidate→approve-manifest→promote-approved→seal-run-artifacts 执行；禁止默认/自动批准、runtime/model/TS 调用，final artifact manifest 最后写
- [ ] T9 focused + PG + PR ready 一次 full deterministic；独立 review/validation report/HANDOFF 七段时间
