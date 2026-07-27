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
| **过期未回收的持有者仍在写**（D-16 边界冻结） | 写权威 = 当前 generation **∧** lease 未过期；四条写路径对称执法，过期一律 typed `lease_expired`、零变更 |
| **停滞过期 lease 抬高并发上限**（D-16） | 限额计入全部 `leased \| running` 行（不按过期缩小分母）；饱和且存在过期行时先做一次 `maintenance_batch_size` 有界、无 Space 过滤的回收再重算 |
| **未 start 即崩溃 ⇒ 无界重排队**（D-16） | 回收 `leased` 行时先 `attempt += 1` 再按 `max_attempts` 路由；界不依赖 worker 自报 `start` |
| **无人枚举的 Space 永不收敛**（D-16） | 显式命名的跨 Space 回收入口（与 P1.9 全局聚合同形），不依赖调用方枚举 Space |
| **调用方直达 storage-only 转换**（D-16） | storage-only 转换必须有可执行执法点；失败上报要求源状态 `running`，pre-start 失败一律走回收兜底 |
| **领域写句柄越出通道**（D-16） | 语句面约束：回调前后校验完成事务/保存点身份不变，变更即 typed 拒绝并回滚；禁写 `wiki_` 自有表（含跨 Space 行与 `lease_generation`） |
| **事件在调用方事务内追加 ⇒ 重复发布**（D-16） | 事件只能在完成事务内追加；不暴露调用方事务内的公共追加入口（重放会换新随机 event_id，消费端幂等无法折叠） |
| **瞬时消费端不可用被当成毒性**（D-16） | 投递让位改持久化退避（`next_dispatch_at` + 配置化序列），不因失败计数永久移出扫描窗口；熔断/隔离属消费方 reconciliation |
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

**D-2026-07-27-16 边界冻结新增的强制验收项**（双独立评审 findings 的持久
回归载体，后续重构不得删除）：

15. 过期未回收的持有者在 `start`/结果提交/失败上报/outbox 追加四条路径全部
    typed `lease_expired` 且零变更；接受侧：未过期 lease 的同四条路径正常
    通过（unit + PG）；
16. 停滞过期 lease 不抬高上限：任意时刻 `leased | running` 行数不超过配置
    的 per-Space 与全局上限（跨 Space 与单 Space 两种拓扑）；接受侧：未过期
    lease 仍精确占额、达限返回 typed 拒绝（PG）；
17. 饱和触发无 Space 过滤的有界回收：饱和集合中属未声明 Space 的过期行被
    回收后放行，且不向调用方返回跨 Space 任务内容（保留 C1 的反饥饿语义）（PG）；
18. 未 start 即崩溃的循环有界：每次回收 `attempt += 1`，累计达 `max_attempts`
    进 dead_letter；接受侧：crash-after-start 的界与 attempt 计数不变（unit + PG）；
19. 无人枚举的 Space 经显式跨 Space 回收入口收敛为 queued/dead_letter（PG）；
20. 四对 storage-only 转换经任何公共入口均 typed 拒绝且零字段变更（对持有
    有效 lease、`attempt=0` 的 `leased` 行逐一尝试全部错误分类）；接受侧：
    合法 `running → dead_letter` 仍成功且 attempt 正确（unit）；
21. 领域写句柄：回调内结束/提交完成事务被 typed 拒绝并整体回滚（零领域行、
    零 outbox、任务不 succeeded）；写 `wiki_` 自有表（含其他 Space 终态行与
    `lease_generation`）被 typed 拒绝；接受侧：诚实领域写仍原子提交（PG）；
22. 事件追加边界：调用方事务内的公共追加入口不存在；受支持路径下重放恰好
    一份领域行 + 一条事件（unit + PG）；
23. 瞬时消费端不可用后收敛：连续失败超过任何退避档位后恢复，健康事件仍被
    投递并标记；接受侧：单条失败不阻塞同轮后续事件（unit + PG）；
24. 指标暴露过期 lease 计数与最老过期 lease 年龄，使"全 Space 卡在过期
    lease"与健康可区分；接受侧：健康分布读数仍精确（unit + PG）；
25. Decision duplicate 判据经历回收/失败覆写后仍返回 duplicate；接受侧：真正
    从未 awaiting 的行仍返回 not_awaiting（unit）；
26. 只读入口（指标、outbox 读、投递、标记）输入合同与写路径一致：typed
    输入错误、不泄漏驱动异常、`limit` 非正被拒（unit）；
27. dispatcher at-least-once 的 PG 覆盖（补齐第 11 项标注的 (PG)）：投递成功
    未标记即崩溃 → 重投 → event_id 幂等收敛（PG）；
28. 迁移降级 crossing 分支覆盖：空库相对目的地 `-2`（跨 0006）成功；存在
    存量 lifecycle 行时 `-2` 在零 DDL 前拒绝；`dead_letter` 取证行存在时
    降级同样拒绝；offline `--sql` 模式显式 typed 拒绝（PG）。

PG 项全部使用 `integration_postgres` marker，在 PostgreSQL 16 lane 执行且
JUnit `skipped=0`；默认 deterministic lane 如实记 NOT RUN。新增 PG 节点必须
注册进 `tests/test_ci_lanes_022.py` 的精确集合断言。

### 存量资产处置引用（D-2026-07-26-3 义务）

按 [24 · 存量资产处置清单](../../../docs/insurance-kb/24-legacy-asset-disposition.md)
§2，本 PR 对应两行，声明如下：

- **`runtime`（028b + S1）→ 冻结审计**：本 PR 取代其作为 033 §12 任务运行时
  的地位。该包转为冻结审计资产、零生产消费者，本 PR 不读取、不导入、不复用
  其任何表或模块。
- **`compiler` → 废弃部分**：本 PR 取代其 LangGraph 管线编排与
  `attempts.py` 的 SQLite attempt ledger（033 §12 固定 Job Store 取代）。
- **表权威切换：无**。24 号 §3 的表权威切换表中不存在任何 job/outbox 表，
  因此本 PR **零旧表停写、零读路径切换、零旧数据导入**；`wiki_jobs` 与
  `wiki_outbox_events` 是新建表，不外键任何遗留域表。
- **迁移台账**：0007–0011 旧预分配与 superseded 0013/0014 按 22 号 §4 /
  24 号 §3 永不复用（D-2026-07-27-10）；本 PR 独占 0015。

### 路径预算

- logical files ≤ 13：生产约 7（唯一迁移 1、states、models、store、outbox
  dispatcher、metrics 查询、配置接线），tests 约 5–6；
- 生产代码目标 500–700 行；超过约 900 行触发重新切分评审（033 §16.2）；
  单文件 400/700（测试 500/800）行仅作警报线；
- **实测（第二轮双评审闭环后）**：raw 2150 / 有效 1497 行（store 550、
  outbox 210、迁移 214、models 187、metrics 111、tables 91、`__init__` 导出面
  90、errors 44），超过 ~900 触发线。边界冻结的修复（两道防线、持久退避、
  过期 lease 指标、两个新列）是本轮增量。**已按
  [D-2026-07-27-17](../../../docs/insurance-kb/23-mvp-control-board.md#d-2026-07-27-17--035-实现的-162-行数触发线豁免)
  裁决不拆分**：拆分在算术上仍不能带来预算合规——可分离的只有 metrics(111)
  与 dispatcher 观测面(约 162)共约 273 行，拆后仍约 1224 > 900，且会产生
  "outbox 无人 drain"的半成品。豁免仅限本窗口，不构成后续 Pn 先例。
  本行不留 TBD。
- 恰好 1 个新 Alembic 迁移，只建 `wiki_jobs`/`wiki_outbox_events`（含其列、
  索引与约束；边界修订新增的列属于这两张表，不产生第二个迁移）。

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
- [x] T13 独立 Spec/质量复审。**已执行（2026-07-27，PR #53，两支互不知晓的
  独立评审 + 各自独立 worktree/PostgreSQL）**：Spec `not compliant`（1C/6I/5m）、
  Quality `not approved`（2C/6I/4m），**双方独立复现同一破口** ⇒ 按 033 §18
  停止补丁循环、回到边界设计。裁决与冻结条款见
  [D-2026-07-27-16](../../../docs/insurance-kb/23-mvp-control-board.md#d-2026-07-27-16--p1-18-停线与-lease-写权威边界冻结)；
  行数豁免见 D-2026-07-27-17。

### 边界修订后的实现任务（D-16 后新增，严格 RED-first）

- [x] T14 RED：回收 `leased` 行时 `attempt += 1` 再路由（清单第 18 项，含
  crash-after-start 接受侧不回归）。GREEN：`_reclaim_locked`。
  节点：`test_q14_reclaiming_a_leased_row_counts_one_attempt`、
  `test_q14_crash_between_claim_and_start_is_bounded_by_max_attempts`、
  `test_q14_crash_after_start_keeps_its_existing_bound`。
- [x] T15 RED：写权威 = generation ∧ lease 未过期，四条写路径对称 typed
  `lease_expired`（清单第 15 项，含未过期接受侧）。GREEN：四个入口共用
  `require_active_lease` 单一原语，不各自 if。节点：
  `test_q15_expired_lease_holder_has_no_write_authority_on_any_path`、
  `test_q15_unexpired_lease_still_writes_on_every_path`。
  次序裁决：先判转换合法性再判 lease 权威——对 queued/终态行
  `illegal_transition` 比 `lease_expired` 更精确。
- [x] T16 RED：限额计入全部 `leased | running`；饱和且存在过期行时先做一次
  无 Space 过滤的有界回收再重算（清单第 16、17 项）。GREEN：`claim` 限额段
  + `_count_active`/`_reclaim_saturated`。节点：
  `test_q16_stalled_expired_leases_never_exceed_configured_limits`、
  `test_q16_single_space_saturation_is_not_bypassed_by_expired_rows`、
  `test_q16_saturation_triggers_scope_free_bounded_reclaim`、
  `test_q16_unexpired_leases_still_consume_the_limit`。
  **契约收紧**：C1 节点（det + PG）原断言"scope 外零变更"已按冻结边界迁移为
  "回收后放行 + 调用方拿不到跨 Space 内容 + 过期持有者即刻失去写权威"。
- [x] T17 RED：显式命名的跨 Space 回收入口（清单第 19 项）。GREEN：
  `reclaim_expired_leases_all_spaces()`，与 `global_job_metrics` 同形；
  `claim` 的 scope 语义未改。节点：
  `test_q17_unenumerated_space_converges_via_explicit_global_entry`、
  `test_q17_global_reclaim_leaves_unexpired_rows_untouched`。
- [x] T18 RED：storage-only 转换无调用方入口 + 失败上报要求源状态 `running`
  （清单第 20 项，含合法 `running → dead_letter` 接受侧）。GREEN：
  `ensure_transition(..., storage_layer=False)` 使常量成为可执行护栏，只有
  `_reclaim_locked`/`_promote_due_retries` 传 `True`。节点：
  `test_q18_storage_only_transitions_have_no_caller_entry`、
  `test_q18_ensure_transition_refuses_storage_only_pairs_for_callers`、
  `test_q18_running_to_dead_letter_still_works`；穷举节点
  `test_p1_1_exhaustive_pairs_split_between_legal_and_typed_illegal`
  已迁移为三分（调用方可达/storage-only/非法）。
- [x] T-cfg RED：`lease_seconds` 严格为正且大于 heartbeat 间隔（Quality F11）。
  GREEN：`JobRuntimeConfig`（`gt=0` + `model_post_init` 一致性校验）与
  `config.py` 的 `job_lease_seconds`。节点：
  `test_q11_zero_or_sub_heartbeat_lease_is_rejected_by_config`（4 参数化）、
  `test_q11_positive_lease_above_heartbeat_is_still_accepted`。
  12 处 `lease_seconds=0.0` 过期脚手架全部迁移为 `force_expire`/`_force_expire`
  （只回拨 lease，不改 state/attempt/generation）。
- [x] T19 RED：领域写句柄的事务身份不变式 + 禁写 `wiki_` 自有表（清单第 21
  项，含诚实领域写接受侧）。GREEN：**两道独立防线**——句柄 `execute` 的语句
  面校验（拒绝事务控制语句与 `wiki_` 目标表；Core 语句走元数据、`text()` 走
  保守标识符扫描）+ 完成事务在回调返回后校验 SAVEPOINT/外层事务仍 active。
  安全冗余是特性，不因已有语句面校验而删掉提交点校验。新 typed
  `DomainWriteViolationError`。节点：
  `test_q19_domain_write_cannot_end_the_completion_transaction`、
  `test_q19_domain_write_cannot_touch_p1_owned_tables`（4 参数化）、
  `test_q19_honest_domain_write_still_commits_atomically`、
  PG `test_q19_domain_write_cannot_escape_its_channel_on_postgres`。
- [x] T20 RED：事件只能在完成事务内追加（清单第 22 项）。GREEN：
  `append_job_event` 从 `insurance_harness.jobs` 公共出口移除（降级为内部
  函数，测试直接引 `jobs.outbox` 验证内部合同）。节点：
  `test_q20_append_job_event_is_not_a_public_entry`。
- [x] T21 RED：投递改持久化退避，瞬时不可用后收敛；单条失败不阻塞同轮
  （清单第 23 项）。GREEN：0015 增列 `next_dispatch_at`（NOT NULL，新事件
  立即可投）+ 索引改 `(next_dispatch_at, id)` 部分索引 +
  `JobRuntimeConfig.dispatch_backoff_seconds`；**删除** `max_dispatch_attempts`
  硬上限、`parked_event_ids` 与 `read_parked`，新增运维视图
  `read_backed_off`（仍在扫描集合内，不是坟墓）。`OutboxDispatcher` 构造签名
  改为接收 `JobRuntimeConfig`（退避参数不得硬编码于构造函数）。节点：
  `test_q21_transient_consumer_outage_recovers_at_least_once`、
  `test_q21_dispatch_backoff_delay_comes_from_configuration`；
  `test_i10_*` 已迁移为 `test_i10_poison_event_yields_via_backoff_without_blocking_later_events`
  （断言"退避让位 + 不阻塞后续 + 行仍在库内待投"）。
- [x] T22 RED：过期 lease 指标（清单第 24 项，含健康分布接受侧）。GREEN：
  `SpaceJobMetrics`/`GlobalJobMetrics` 增 `expired_lease_count` 与
  `oldest_expired_lease_age_seconds`，与既有字段同一事务、同一数据库时钟
  （`_collect` 重构为 `_Collected` + `_age_seconds` 单一规范化原语）。节点：
  `test_q22_metrics_expose_expired_lease_wedge`、
  `test_q22_healthy_distribution_metrics_stay_exact`。
  **TDD 次序偏差如实记录**：本项实现先于 RED 落地（metrics 改动与 T24 的
  `validated_text` 接线同一处），验收节点随后补齐并全绿。
- [x] T23 RED：Decision duplicate 判据经回收后仍正确（清单第 25 项，含真正
  never-awaiting 接受侧）。GREEN：0015 增列 `human_decision_resumed_at`
  （首次唤醒写入、此后不改），判据由可变 `error_class` 改读该列。节点：
  `test_q23_decision_duplicate_label_survives_a_reclaim`（覆盖"唤醒→再失败"
  与"唤醒→租约过期回收"两种覆写路径）、
  `test_q23_never_awaiting_row_is_still_not_awaiting`。
- [x] T24 RED：只读入口输入合同与写路径一致、`limit` 非正被拒（清单第 26
  项）。GREEN：`space_job_metrics` 改走 `validated_text`；新增
  `validated_limit` 原语，`read_pending`/`read_pending_all_spaces`/
  `read_backed_off`/`dispatch_pending` 统一使用。节点：
  `test_q24_read_path_input_contract_is_typed`（3 参数化）、
  `test_q24_non_positive_limit_is_typed_on_read_entries`（2 参数化）、
  `test_q24_default_limits_still_work`。
- [x] T25 RED：dispatcher at-least-once 的 PG 节点（清单第 27 项，补齐第 11
  项标注的 (PG)）。GREEN：无生产改动，仅补覆盖。节点：
  PG `test_q25_delivered_but_unmarked_crash_converges_on_postgres`
  （投递成功→标记前崩溃→重投→同一 event_id 两次投递、消费端可折叠→最终标记）。
- [x] T26 RED：迁移降级 crossing 分支 + `dead_letter` 取证保护 + offline
  `--sql` 显式拒绝（清单第 28 项）。GREEN：`_validate_own_rows_before_ddl`
  纳入 `dead_letter`（P1.4 要求保留取证；`succeeded` 仍可丢弃）；
  `_validate_downgrade_before_ddl` 首行判 `context.is_offline_mode()` 抛显式
  `RuntimeError`（把偶然的 `AttributeError` fail-closed 变成声明的）。节点：
  PG `test_q26_downgrade_relative_destination_crossing_0006_is_resolved`
  （空库 `-2` 真实走到 M13 的解析分支——原 `test_i9_*` 因 live-row 预检先抛，
  该分支从未被触达）、`test_q26_downgrade_refuses_while_dead_letter_forensics_exist`
  （含只有 `succeeded` 时仍可降级的接受侧）、
  `test_q26_offline_sql_downgrade_is_explicitly_refused`。
- [x] T27 收尾复跑：035 deterministic **119 passed**（78 → 119）；存量迁移
  消费者回归 **77 passed**；`test_ci_lanes_022.py` **69 passed**（精确集含新增
  8 个 PG 节点）；PostgreSQL 16 全量 `integration_postgres` **55 passed /
  3879 deselected**，JUnit `tests=55 skipped=0`；`uv run ruff check .` 全绿；
  `uv run mypy src tests` strict **350 files** 全绿；
  `openspec validate 035-p1-job-outbox --strict` valid。validation report 已
  重写为本 head 证据 + 如实 NOT RUN。
- [ ] T28 修复后重新提交双独立评审。若**再次**在 lease 过期/写权威/限额
  会计域出现新的基础不变量，按 §18 不得继续补丁——回到 033 §12 的运行时
  边界设计，由业务方裁决是否重划 P1 范围。

完成 T27 前不得宣称 P1 验收达成；P3 及后续消费方 PR 不得提前开工接线。
