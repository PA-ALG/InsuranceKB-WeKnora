# 018 任务

- [x] T1 先写 `R1.1～R1.4` migration/legacy/freeze-marker/immutability/零事实投影 RED，再实现 `0005`、SnapshotFact 与完整 Space 投影构建器
- [x] T2 先写 `R2.1～R2.4` current/filter/effective-date/五类 gap/scope RED，再实现 SnapshotReader
- [x] T3 先写 `R2.3/R6.1` frozen fact renderer 与产品 A/B 完整性 RED，再切换页面编译数据源
- [ ] T4 先写 `R3.1～R3.6` 状态机、lease recovery、多页失败、collision、attempt、service-owned Session RED，再实现 ReleaseOperation/PublishAttempt 与 plan executor
- [x] T5 先写 `R4.1～R4.5/R6.2～R6.3` 回滚失败、same-plan retry、补偿、managed ownership 与并发 RED，再实现 reconciliation
- [x] T6 先写 `R5.1～R5.3` curated-first/same-scope raw fallback RED，再实现 provider protocol 与 policy（不实现搜索引擎）
- [ ] T7 按 `R6.4` 完成 PostgreSQL integration、真实 Wiki V1→V2→rollback live gate、Runbook、validation-report、HANDOFF/13/16/20 对账

状态：设计已由业务方于 2026-07-14 确认并完成复审；T1～T3/T5/T6 已实施，T4 软件实现与 deterministic 证据完成、仅余 PostgreSQL service-owned Session 外部证据，T7 的代码/Runbook/report/本地门禁已完成、仅余 PostgreSQL 与真实 WeKnora 外部 lane；依赖已合入的 016/017，018 独占 migration `0005`。

裁决记录（2026-07-15）：

- Alembic 多 revision downgrade 在 SQLite 上不是整条命令原子执行；`head → 0002` 若等到 `0003` 才校验，会先永久删除 `0005` 的四张表。`0005` 因此仅在最终目标跨过 `0003` 时镜像执行 0003 兼容性预检，拒绝后 schema 与 `alembic_version` 均停在 head；直接 `0005 → 0004` 不触发该预检，保留 R1.4 的安全降级能力。
- T4/T7 checkbox 在当前 SHA 的 PostgreSQL 16 与受控 WeKnora lane 有零 skip 证据前保持未勾；本地 collection、显式 fail 或 skip 均不替代外部证据。
