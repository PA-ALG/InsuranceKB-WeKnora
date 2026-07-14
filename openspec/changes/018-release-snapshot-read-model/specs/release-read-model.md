# 018 规格（验收条件）——SnapshotFact 与统一读取

## R1 不可变事实投影

- R1.1 SnapshotFact 包含 space/snapshot/claim/revision、product version、predicate、value state/value、有效期、confidence、schema version 与 Evidence JSON；
- R1.2 snapshot published 后 SnapshotFact 和 rendered_pages 不可修改；数据库与服务层均拒绝写入；
- R1.3 同一 snapshot/claim/revision 唯一，Evidence 内容与发布时一致，不受后续 enrich/retract 影响。

## R2 SnapshotReader

- R2.1 `SnapshotReader.current(scope)` 只通过该 Space 的 CurrentRelease 读取 SnapshotFact；
- R2.2 支持按 product/version/predicate/effective date 查询，并返回 snapshot_id 与证据；
- R2.3 Wiki renderer 改从 SnapshotFact 构建页面；013 MCP 后续必须复用 SnapshotReader，不得直接查 published Claim；
- R2.4 无 current snapshot 返回显式 `coverage_gap=no_release`，不得跨 scope 回退。

## R3 发布状态机

- R3.1 snapshot 状态 building→publishing→published 或 failed；failed 可由显式 retry 使用同一冻结 PublishPlan 回到 publishing；只有 published 可成为 current；
- R3.2 先构建 SnapshotFact/页面，再幂等 upsert WeKnora；全部成功后在 DB 事务内移动该 Space 指针；
- R3.3 发布前冻结完整 PublishPlan：目标 upsert 页面、应删除的旧 managed slug、每项补偿动作；每个动作形成 PublishAttempt 明细（attempt、operation、status、error、snapshot/slug、created_new）；重试不新建业务快照；
- R3.4 任一外部写入失败时 current 不移动，snapshot=failed，并产生 reconciliation 工单；非 Harness 管理的同 slug 页面在任何覆盖前触发 collision 失败；
- R3.5 publisher 校验目标 wiki_kb_id 来自 scope，调用方不能另传不一致 kb_id。

## R4 回滚与补偿

- R4.1 回滚只允许该 Space 的 published snapshot；先重放旧页面，成功后移动指针；
- R4.2 回滚失败时指针保持、记录 attempt，不能留下“DB 已回滚但 Wiki 未恢复”的成功状态；
- R4.3 reconciliation 按失败 PublishPlan 精确恢复 current 投影：current 拥有的 slug 幂等重放旧页面；失败计划触及的、current 不拥有的所有 Harness managed slug 均删除（无论本次新建还是覆盖历史非 current 页面）；非 Harness 页面从未被覆盖；
- R4.4 发布、回滚和补偿均按 space 串行；多实例锁最终由 014 advisory lock 替换。

## R5 Curated-first

- R5.1 SnapshotReader 只有在事实不存在/无 release 时返回结构化 coverage_gap；
- R5.2 RAW fallback 必须限定同一 scope，结果标记 `unreviewed_raw`，不得写回或覆盖 SnapshotFact；
- R5.3 已存在 SnapshotFact 时禁止以 RAW 冲突文本替换答案。

## R6 验收

- R6.1 两快照+回滚测试同时断言 Reader 值、Evidence、Wiki metadata.snapshot_id；
- R6.2 多页第二页失败测试断言指针不动、同 plan 可重试；“失败快照新增 slug”和“覆盖历史非 current managed slug”测试均断言 reconciliation 删除非 current 页并精确恢复投影；
- R6.3 双空间相同 label/slug 测试互不影响；
- R6.4 Ruff、mypy、非 live pytest 全绿，live 测试验证真实 Wiki upsert/rollback。
