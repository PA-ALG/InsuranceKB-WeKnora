# 029 任务（风险 A；知识/迁移独占）

- [x] T1 冻结 manifest canonical schema，写 RA1 RED（重排稳定、任一内容变化改 hash、Evidence 计入）
- [x] T2 实现 manifest builder 与只读 view，不改 018 SnapshotFact 语义
- [x] T3 写 RA2 RED：授权 actor、完整 hash、append-only approval；实现模型/表/service
- [x] T4 写 RA3 RED：approval mismatch、篡改、expected current CAS、并发单赢家；实现 promote
- [x] T5 写 RA5/RA6 RED：有效旧批准回滚、零模型、P-1 前 production UI fail closed；实现 rollback guard
- [x] T6 迁移 0013；SQLite focused 与真实 PostgreSQL 16 guard/downgrade/concurrency 矩阵均已通过，PG JUnit `tests=4 skipped=0`，migration 为单 head `0013`
- [x] T7 暴露 ApprovedSnapshotReader 的 snapshot/manifest hash 公开合同，供 013/032 使用；未修改其文件域
- [ ] T8 RA7 本域 RED/实现、stable-root-FD/atomic-final remediation 与独立 Spec/Quality review 均已完成并 `APPROVED FOR DRAFT`；028 sealed producer 合同与 production composition root 尚未集成，缺合同路径保持 fail closed
- [ ] T9 validation report 已创建，rebase 后最新代码 HEAD 真实 PostgreSQL `tests=4 skipped=0`；full deterministic 按 Draft 规则未运行，push/Draft PR 待完成；本会话按总控要求不修改 HANDOFF
