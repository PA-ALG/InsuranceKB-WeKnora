# 021 验证报告 — Source lifecycle ordering

> 本 change 只解决来源文档的确定性生命周期：`notify/import/delete/reactivate`
> 共用一个 Space-scoped source root、锁与事件账本。它不执行 020 的真实模型 baseline，
> 也不替代 WeKnora live 文档解析验证。

## 主流程结果

```text
SourceRevision
  → per-source PostgreSQL advisory lock
  → SourceHead + append-only SourceEvent
  → notify / source-aware import / delete
  → stale-or-blocked audit no-op
  → strictly-newer active revision reactivate
```

- ordering 联合支持 `generation` 与 timezone-aware `processed_at`，不同 kind、同 ordering
  不同 revision、非法深层值均 fail closed。
- 首次 create、同 identity reuse、B/C 乱序、delete 优先、严格更新 delete/reactivate
  均在同一锁和 caller-owned nested transaction 内裁决。
- `SourceLifecycleBackfillIssue` 不猜历史 head；open issue 阻断正常 lifecycle，只能通过显式、
  审计化 resolver 解除，exact retry 返回原 resolution event。
- source-aware import/notify/delete 只消费与本次 decision 精确匹配的聚合；legacy 路径保持互斥。
- SourceEvent 在 PostgreSQL 由触发器拒绝 UPDATE/DELETE；发布快照边界保持零变化。

## 真实 PostgreSQL 16 证据

运行环境：本机受控 `postgres:16`，测试 runner 与数据库通过 Compose 私网连接；每组测试创建
随机临时 database，执行真实 Alembic 到 `0006`，设置 connection/statement/lock/future timeout，
结束时终止残留连接并 drop database。URL/密码未写入日志或报告。

- 021 核心 lane：**21 passed / skipped=0**（业务并发 13 节点 + 迁移 8 节点）。
- 全量 `integration_postgres`：**25 passed / skipped=0**（1906 deselected，8.92s）。
- JUnit guard：`tests=25 skipped=0`。
- CI allowlist/三 lane 互斥与穷尽检查：**39 passed**。

业务并发节点覆盖：首次同 identity、B/C 两种持锁顺序、resolver-vs-normal、首事件 delete、
active/deleted 严格更新 delete、delete-vs-notify、delete-vs-import、严格更新 reactivate、
C 后迟到 B、controlled CAS loser reread、故障回滚后 caller Session 仍可用。

迁移节点通过真实 Alembic `0012 → 0006` 覆盖：PostgreSQL schema/复合约束/触发器、历史来源
生成 zero heads + 每 source 唯一 open issue、Head/Event/Issue/历史 provenance 四类非空 downgrade 在首个 DDL 前拒绝、
空数据 `0006 → 0012 → 0006` 往返、`alembic check` 与单 head `0006`。

## 确定性门禁

- 021 邻接 focused：**217 passed**。
- OpenSpec strict：`Change '021-source-lifecycle-ordering' is valid`（exit 0；离线环境只造成
  PostHog telemetry flush warning，不影响校验结果）。
- Ruff：All checks passed。
- mypy strict：**248 source files**，no issues。
- deterministic：**1901 passed / 30 deselected**（175.73s）。
- Alembic：single head `0006`；fresh SQLite `upgrade head → downgrade 0012 → upgrade head → check`
  全部 exit 0，`No new upgrade operations detected`。
- 最新 diff 的全 PostgreSQL：**25 passed / skipped=0**（16.24s），JUnit guard 通过。
- `git diff --check`：通过。
- 独立规格复审：PASS；独立质量复审：APPROVED，无剩余 P0–P2。

## 运维与恢复

按 Space 监控待处理历史来源，不跨租户聚合：

```sql
SELECT space_id, count(*) AS open_issues
FROM source_lifecycle_backfill_issues
WHERE status = 'open'
GROUP BY space_id
ORDER BY open_issues DESC;

SELECT space_id, decision, count(*) AS events
FROM source_events
WHERE decided_at >= now() - interval '1 hour'
GROUP BY space_id, decision
ORDER BY space_id, decision;
```

- `blocked_deleted`/`stale` 突增先检查上游 ordering 与 revision 生成，不得直接改 Head/Event。
- open BackfillIssue 必须核对原始来源、目标 revision、ordering 与期望 active/deleted state 后，
  调用 `resolve_source_lifecycle_backfill_issue`；失败可安全重试，成功 exact retry 不新增事件。
- 业务 callback 失败时 nested unit 全回滚，不会留下半个 Head/Event/聚合；修复输入后以相同
  causation 重放。禁止手工 UPDATE/DELETE `source_events`，PostgreSQL trigger 也会拒绝。
- `0006` 仅在 SourceHead/SourceEvent/BackfillIssue 与历史 source-aware provenance 均为空时允许
  downgrade；否则必须先完成业务清理/归档并走变更审批。空库回滚路径为
  `alembic downgrade 0012`，恢复为 `alembic upgrade head`，随后执行 `alembic check`。

## 边界与下一步

- AI worker 不 commit/push；最终 commit、push 与 PR 由人工执行。
- 本次 PostgreSQL 证据证明 Harness 自有库的并发/迁移语义，不等价于 WeKnora 文档上传、解析或
  模型调用 live。
- 021 合入后只解锁 020 的 **T1 零模型 run-admission**。在模型身份、输入指纹、总预算硬闸、
  checkpoint 与停止条件全部 READY 前，不允许直接启动 13 产品 baseline。
