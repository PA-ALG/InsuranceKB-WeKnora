# 035 任务（P1 Job + Outbox；小 PR；先冻结 Contract Card 再写代码）

## Contract Card

### 单一职责与非目标

单一领域不变量：**at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
一次领域提交**。P1 只拥有 `wiki_jobs`/`wiki_outbox_events` 两表、其唯一
迁移与 JobStore/Outbox 存储层 API。非目标（proposal「不做什么」全文有效）：
WeKnora 交互、Compiler、Candidate/Release 语义、通用 DAG/DSL、动态 worker
拓扑、exactly-once 宣称、Redis/Kafka、031 式 ledger/PTU/ceremony/文件系统
operation store、模型部署生命周期、外部 provider reconciliation、P3 进程壳。

### 读写权威、事务边界与幂等键

- 写权威：所有任务状态与 outbox 写只经 JobStore 单一存储层入口；调用方
  不得绕过入口直接改行。
- 事务边界：enqueue、claim、heartbeat、单次状态转换、「完成 + 领域写 +
  outbox 追加」各为一个 PostgreSQL 事务；完成事务是任务领域结果的唯一
  写入口。
- 幂等键：enqueue = `(space_id, job_type, idempotency_key)` 数据库唯一；
  outbox 投递 = `event_id`（消费端去重键）；人工 Decision 唤醒 = 任务当前
  状态本身（仅 `awaiting_human → queued` 可成功，重复提交 typed
  duplicate）；结果提交 = 状态机终态 + fencing generation。

### 状态机

固定 8 状态封闭枚举（033 §12），合法转换只有 spec P1.1 列出的十条，其中
backoff 到期 `retry_wait → queued` 与过期回收
`leased|running → queued|dead_letter`（记 `lease_expired` retryable 失败
并按 `max_attempts` 路由）都仅限存储层执行；`succeeded | blocked |
dead_letter` 为终态；其余一律 typed `illegal_transition` 在存储层拒绝。

```text
queued → leased → running → succeeded
                    ├→ retry_wait → queued
                    ├→ awaiting_human → queued
                    ├→ blocked
                    └→ dead_letter
```

### 威胁矩阵

| 威胁 | P1 冻结的处理 |
|---|---|
| 并发 double-claim | 单事务 `FOR UPDATE SKIP LOCKED` 领取 + 每任务 generation 单调 +1，同 generation 至多一个成功 claim |
| lease 过期后 stale writer | 全部写路径（heartbeat/转换/结果/outbox）校验 generation，旧 generation typed `stale_generation` 拒绝、零变更 |
| 崩溃重放（同任务执行两次） | 完成事务受状态机终态 + fencing 保护至多成功一次；enqueue/outbox 幂等键去重；恰好一份领域结果 |
| 跨 Space 泄漏 | 两表 NOT NULL `space_id`；所有入口校验 scope fail closed；无默认跨 Space 聚合，全局视图显式命名 |
| outbox 双写不一致 | 领域写与 outbox 行同一事务；无绕过事务的直接外发入口；dispatcher 只读已提交行、按持久 `dispatched_at` 标记扫描 |
| 时钟漂移 | 过期判定只用数据库时钟；写权威只看 generation 不看时间戳；worker 本地时钟不参与任何判定 |

### exact 验收测试清单

1. 状态机合法转换表穷举 + 非法转换 typed 拒绝 + 错误分类映射（unit）；
2. `wiki_jobs`/`wiki_outbox_events` schema/约束合同：NOT NULL space_id、
   `(space_id, job_type, idempotency_key)` 唯一、outbox 有序 id（PG）；
3. 重复 enqueue 幂等去重（并发）（PG）；
4. ≥8 连接并发单领、无双领、无互相阻塞、空队列 typed 空结果（PG）；
5. per-Space/全局限额两组配置值生效 + 超限排队不丢失 + 跨 Space
   claim/read/写 fail closed（PG）；
6. heartbeat 延长/拒绝、过期回收记 `lease_expired` retryable 失败并按
   `max_attempts` 路由（未达上限回 queued）、generation 严格递增（PG）；
7. 迟到 worker 旧 generation 的 heartbeat/转换/结果/outbox 全部拒绝（PG）；
8. retryable → retry_wait → queued 的 backoff 只由配置决定；max_attempts →
   dead_letter 并保留 attempt/错误分类/摘要；未分类异常按 retryable 计入（PG）；
9. awaiting_human 同事务释放 lease、并发额度立即归还、Decision 幂等
   requeue（PG）；
10. 完成事务原子性：领域写 + outbox 同事务，注入中断后零半写，重复完成
    拒绝且零第二结果（PG）；
11. dispatcher at-least-once：投递成功未标记即崩溃 → 重投 → 消费端
    event_id 幂等收敛；无已提交行永不投递（PG）；
12. 崩溃接管端到端：强制终止 A → lease 过期 → B 以 g+1 完成 → A 苏醒提交
    被拒 → 领域结果与完成事件各恰好一份；重复崩溃循环有界——毒性任务在
    attempt 达上限时由回收路由进 dead_letter，不无限 requeue（PG）；
13. 指标查询与预置分布精确一致（per-Space + 全局；最老可调度年龄覆盖
    retry_wait；enqueued/started/finished 时间戳持久化）（PG）；
14. 迁移链：恰好一个新迁移、只建两表、down_revision=当时真实 head、无
    multi-head、upgrade 干净通过（PG）。

PG 项全部使用 `integration_postgres` marker，在 PostgreSQL 16 lane 执行且
JUnit `skipped=0`；默认 deterministic lane 如实记 NOT RUN。

### 路径预算

- logical files ≤ 13：生产约 7（唯一迁移 1、states、models、store、outbox
  dispatcher、metrics 查询、配置接线），tests 约 5–6；
- 生产代码目标 500–700 行；超过约 900 行触发重新切分评审（033 §16.2）；
  单文件 400/700（测试 500/800）行仅作警报线；
- 恰好 1 个新 Alembic 迁移，只建 `wiki_jobs`/`wiki_outbox_events`。

## Tasks

严格 TDD：每个任务先落 RED 再实现 GREEN；按 HANDOFF 0g.1，开工后 15 分钟
内必须落下 T1 的首个 RED，30 分钟内有可核验产物。

- [x] T1 RED（≤15 分钟）：纯单元测试冻结状态机——8 状态封闭枚举、合法转换
  表穷举、非法转换 typed `illegal_transition`、错误分类 → 目标状态映射。
  GREEN：`job_runtime` 状态机纯函数核。
- [x] T2 RED：PG schema 合同测试（`integration_postgres`）——两表列/NOT
  NULL space_id/幂等键唯一约束/outbox 有序 id 与 event_id。GREEN：先在
  README 迁移台账占号，再写唯一迁移（down_revision=当时真实 head，起草时
  观测 0006）与 ORM models。
- [x] T3 RED：重复 enqueue 幂等去重（含并发）+ claim 并发单领（≥8 连接、
  SKIP LOCKED、空队列 typed 空结果）。GREEN：JobStore.enqueue/claim。
- [x] T4 RED：per-Space/全局限额（两组配置值断言不同行为）+ 超限排队不
  丢失 + 跨 Space claim/read/写 fail closed。GREEN：claim 限额与 Space
  scope 校验。
- [x] T5 RED：heartbeat 延长/拒绝、数据库时钟过期回收（回收记
  `lease_expired` retryable 失败并按 `max_attempts` 路由，未达上限回
  queued）、generation 严格递增、旧 generation 全写路径
  `stale_generation` 拒绝。GREEN：heartbeat/回收路由/fenced write guard。
- [x] T6 RED：完成事务原子性——领域写 + outbox 同事务、注入中断零半写、
  重复完成 typed 拒绝零第二结果。GREEN：complete/fail 转换 API（
  retry_wait/blocked/dead_letter/awaiting_human 四个落点）。
- [x] T7 RED：backoff 序列与 max_attempts 只由配置决定、达上限进
  dead_letter 并保留 attempt/分类/摘要、未分类异常按 retryable 计入不
  静默。GREEN：重试策略。
- [x] T8 RED：awaiting_human 同事务释放 lease、并发额度立即归还、人工
  Decision 幂等 requeue（重复提交 typed duplicate）。GREEN：Decision
  唤醒入口。
- [x] T9 RED：outbox dispatcher at-least-once——投递成功未标记即崩溃 →
  重投 → 消费端 event_id 幂等收敛；扫描基于持久 `dispatched_at`，无已提交
  行被跳过。GREEN：dispatcher。
- [x] T10 RED：崩溃接管端到端——强制断开 A 连接 → lease 过期 → B 以 g+1
  接管完成 → A 苏醒提交被拒 → 领域结果/完成事件各一份；重复崩溃循环
  有界——毒性任务反复崩溃时 attempt 达上限的回收路由进 dead_letter，不
  无限 requeue。GREEN：残余缺口修补，不引入新状态或新分支。
- [x] T11 RED：指标查询（per-Space + 全局各状态计数、队列深度、覆盖
  retry_wait 的最老可调度年龄、attempt/retry_wait/dead_letter 计数、
  enqueued/started/finished 时间戳持久化）与预置分布精确一致。
  GREEN：只读 metrics 查询。
- [x] T12 收尾：focused → Ruff/mypy → `openspec validate 035-p1-job-outbox
  --strict` → PostgreSQL 16 lane 全量 `integration_postgres`（JUnit
  `skipped=0`）；validation report 如实记录已运行项与 NOT RUN；更新 README
  迁移台账实际链序与 HANDOFF 当前状态块。
- [ ] T13 独立 Spec/质量复审。复审中若出现新的同域基础不变量，按 033 §18
  停止补丁循环、回到边界设计，不追加状态和异常分支。

完成 T12 前不得宣称 P1 验收达成；P3 及后续消费方 PR 不得提前开工接线。
