# 018 任务

- [x] T1 先写 `R1.1～R1.4` migration/legacy/freeze-marker/immutability/零事实投影 RED，再实现 `0005`、SnapshotFact 与完整 Space 投影构建器
- [x] T2 先写 `R2.1～R2.4` current/filter/effective-date/五类 gap/scope RED，再实现 SnapshotReader
- [x] T3 先写 `R2.3/R6.1` frozen fact renderer 与产品 A/B 完整性 RED，再切换页面编译数据源
- [x] T4 先写 `R3.1～R3.6` 状态机、lease recovery、多页失败、collision、attempt、service-owned Session RED，再实现 ReleaseOperation/PublishAttempt 与 plan executor
- [x] T5 先写 `R4.1～R4.5/R6.2～R6.3` 回滚失败、same-plan retry、补偿、managed ownership 与并发 RED，再实现 reconciliation
- [x] T6 先写 `R5.1～R5.3` curated-first/same-scope raw fallback RED，再实现 provider protocol 与 policy（不实现搜索引擎）
- [ ] T7 按 `R6.4` 完成 PostgreSQL integration、真实 Wiki V1→V2→rollback live gate、Runbook、validation-report、HANDOFF/13/16/20 对账

## PR review hardening（2026-07-15）

- [x] RH1 `R3.7` 使 007 legacy support 对三个退休 helper 自包含，删除仅由测试 import 存活的 production helpers，并补 production boundary 测试
- [x] RH2 `R6.4/R2.1` 启用 deterministic SQLite FK、以复合 FK 失败验真，并构造真实跨 Space pointer target
- [x] RH3 `R3.1` 补 failed plan base 已变化时零 retry/attempt/Wiki/current 副作用的回归测试
- [x] RH4 `R3.4/R4.2` 区分首动作 collision 的零补偿语义，并统一 rollback lease recovery ChangeSet 为 partially_applied
- [x] RH5 `R6.4` 将 0005 合约测试固定到 revision 0005、移除 018 live search_path 的 public fallback，刷新 validation-report 实测计数
- [ ] RH6 运行 OpenSpec strict、Ruff、mypy strict、deterministic、PostgreSQL integration；PR #10 trusted workflow 合入后再运行 5-node WeKnora live 零 skip门禁

状态：设计已由业务方于 2026-07-14 确认并完成复审；T1～T6 已实施。2026-07-16 review hardening RH1～RH5 已完成；当前未提交工作树 OpenSpec/Ruff/mypy/deterministic/PostgreSQL 16 均通过（`1224 passed`，PG `2 passed`），但远端 PR #9 仍是旧 SHA `8df6c3cf`，不得沿用其绿灯覆盖本批。RH6/T7 仅在人工 commit/push 后新 SHA CI 全绿、PR #10 合入并取得受控 WeKnora 5-node `tests=5 skipped=0` 后勾选。018 依赖已合入的 016/017，并独占 migration `0005`。

裁决记录（2026-07-15）：

- Alembic 多 revision downgrade 在 SQLite 上不是整条命令原子执行；`head → 0002` 若等到 `0003` 才校验，会先永久删除 `0005` 的四张表。`0005` 因此仅在最终目标跨过 `0003` 时镜像执行 0003 兼容性预检，拒绝后 schema 与 `alembic_version` 均停在 head；直接 `0005 → 0004` 不触发该预检，保留 R1.4 的安全降级能力。
- T4 已由 PR #9 implementation commit `a70bf025` 的 PostgreSQL 16 零 skip job 验收；T7 checkbox 在受控 WeKnora lane 有零 skip 证据前保持未勾，本地 collection、显式 fail、preflight failure 或 skip 均不替代真实 live。
- review hardening 本地 PostgreSQL 16 复跑为 `2 passed, 1229 deselected`；PR #9/#10 截至 2026-07-16 均为 Draft/open。执行顺序固定为新 SHA CI → PR #10 merge → 5-node live，不得并行误认旧证据。
