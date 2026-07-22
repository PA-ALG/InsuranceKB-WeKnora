# 029 任务（风险 A；知识/迁移独占）

- [x] T1 冻结 manifest canonical schema，写 RA1 RED（重排稳定、任一内容变化改 hash、Evidence 计入）
- [x] T2 实现 manifest builder 与只读 view，不改 018 SnapshotFact 语义
- [x] T3 写 RA2 RED：授权 actor、完整 hash、append-only approval；实现模型/表/service
- [x] T4 写 RA3 RED：approval mismatch、篡改、expected current CAS、并发单赢家；实现 promote
- [x] T5 写 RA5/RA6 RED：有效旧批准回滚、零模型、P-1 前 production UI fail closed；实现 rollback guard
- [ ] T6 迁移 0013；SQLite focused 已完成且 migration 当前为单 head；真实 PostgreSQL guard/downgrade/concurrency 矩阵须 `skipped=0` 后才可勾选
- [x] T7 暴露 ApprovedSnapshotReader 的 snapshot/manifest hash 公开合同，供 013/032 使用；未修改其文件域
- [ ] T8 RA7 本域 RED/实现与 Quality review 已完成、Spec 为 `LOCAL PASS`；028 sealed producer 合同与 production composition root 尚未集成，缺合同路径保持 fail closed
- [ ] T9 validation report 已创建；真实 PostgreSQL、整包独立 review、最终 rebase 后一次 full deterministic、push/PR 与七段时间仍待完成；本会话按总控要求不修改 HANDOFF
