# 021 规格（验收条件）——Source Lifecycle Ordering

## L1 可排序身份

- L1.1 生产 source identity 必须携带 timezone-aware `processed_at` 或服务端严格单调 generation，并与 source revision 的 canonical input 一致。
- L1.2 ordering 字段必须无损进入 manifest、import context、SourceHead/SourceEvent；禁止按 revision hash 字典序判断新旧。
- L1.3 identity、scope 或 ordering 缺失/矛盾时在业务写入前 fail closed。

## L2 Durable SourceHead

- L2.1 每个 `(space_id, knowledge_id)` 最多一个 SourceHead，并闭合 tenant/raw KB 归属。
- L2.2 SourceHead 保存 latest revision、ordering、active/deleted 状态和 CAS version；状态变化有 append-only 审计事件。
- L2.3 无法可靠 backfill latest 的历史状态不得猜测，进入明确待处理状态。

## L3 原子状态机

- L3.1 notify、source-aware import、retract/delete 必须在同一 per-source PostgreSQL lock/CAS 临界区裁决。
- L3.2 同 revision 重放幂等；旧 ordering 事件不覆盖新 head、不 stale 新 Evidence、不创建可消费 recompile。
- L3.3 新 active revision 原子推进 head、标旧 Evidence stale 并创建/复用对应 recompile；失败全回滚。
- L3.4 delete 原子写 deleted head/tombstone并按 scope 撤回 Evidence；相同或更旧 revision 不得复活。
- L3.5 deleted 后只有严格更新的 ordering 可重新激活，且重新激活必须留下独立审计事件。
- L3.6 状态机变化不直接移动 ReleaseSnapshot/CurrentRelease。

## L4 隔离与兼容

- L4.1 所有 head/event/evidence/change 查询按 bound Space 限定；相同 knowledge 字符串不得跨 Space 影响。
- L4.2 legacy replay 与生产 SourceHead 严格互斥，不能删除、推进或恢复 source-aware 状态。
- L4.3 畸形 head/event/change aggregate 统一 fail closed，且 Session 在回滚后仍可用。

## L5 并发验收场景

- L5.1 两会话通知同 revision：一个创建、一个复用，head 与 recompile 各一份。
- L5.2 两会话以 B/C 不同 revision 并发：最终 head 由 ordering 决定，与提交先后无关，旧事件不得 stale 新 Evidence。
- L5.3 C 已 active 后迟到 B：B 被识别为旧事件，零业务副作用。
- L5.4 delete 与同/旧 revision import 并发：最终 deleted，不能复活。
- L5.5 delete 与严格更新 revision 并发：结果由 CAS/ordering 唯一决定，并可从 SourceEvent 重建。
- L5.6 竞争测试仅在真实 PostgreSQL 运行；必须设置 connect/statement/lock/future timeout。缺环境时明确 skip 并记录未运行。

## L6 工程门禁

- L6.1 迁移与 018 串行协调，不占用其预留 `0005`。
- L6.2 非 live pytest、Ruff、mypy、Alembic upgrade/downgrade/check 与 diff check 全绿。
- L6.3 独立规格审查和质量审查通过后方可标记实施完成。
