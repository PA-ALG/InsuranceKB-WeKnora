# 035 验证报告 — P1 Job Store + 事务性 Outbox

> 单一领域不变量：**at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
> 一次领域提交**。本报告记录实现 PR（分支 `feat/035-p1-job-outbox-impl`）
> 的实际验证结果与未运行项。
>
> **2026-07-27 双评审闭环**：PR #44 规格评审 Approved-with-findings、对抗
> 评审 REJECTED（2 Critical / 10 Important / 7 Minor）；全部 finding 已按
> RED-first 关闭并重跑评审 probe 验证，见下文「双评审 finding 闭环」节。

## 双评审 finding 闭环（2026-07-27）

全部修复先落 RED 测试再实现；对抗评审 probe（scratchpad `p1review/`）全量
重跑，逐项结论：

- **C1**（scope 外过期 lease 永久占用全局限额）：有效并发只统计
  `lease_expires_at > now` 的 leased|running 行；probe A1 由永久
  `global_concurrency_limit` 变为正常领取。新 PG 节点
  `test_c1_expired_foreign_lease_does_not_consume_global_limit`（独立
  数据库）+ deterministic 同名场景。
- **C2**（回收不递增 generation + outbox append 无状态门）：
  `_reclaim_locked` 每次回收 generation +1（被逐出 worker 即刻 stale）；
  `append_job_event` 增加 `state == running` 门。probe B1 → typed
  `illegal_transition`、B2 → typed `stale_generation`。毒性任务 PG 节点
  断言更新为 generations `[1,3,5]`、终值 6，循环仍有界。
- **I3**（advisory 等待吞噬 lease 时长）：`database_now` PostgreSQL 改用
  `clock_timestamp()`，且 claim 在取得 advisory 锁**之后**读钟。probe
  D5：等待 2.79s 后剩余 lease 4.91s（配置 5s）；E1：剩余 0.98s（配置
  1s），无立即接管。新 PG 节点 `test_i3_lease_duration_survives_advisory_lock_wait`。
- **I4**（串行段内无界回收/promote）：维护移至 claim 前的独立事务，批量
  受新配置 `maintenance_batch_size`（默认 128）约束。probe D6：50k 过期
  lease 场景 claim 6.3s → 0.03s。
- **I5**（claim 排序无索引）：新增
  `ix_wiki_jobs_claim_order (space_id, state, enqueued_at, id)`（迁移
  0015 合入前原位修订）。probe D4：200k 行下 Index Scan、0.13ms。
- **I6/M16**（原始 DataError 泄漏、SQLite 方言分歧、空 scope 成员）：
  所有入口前置 `validated_text/validated_payload`（非空/无 NUL/长度/可
  序列化），typed `InvalidJobInputError`（兼容 ValueError 合同）；两方言
  行为一致（probe C1-keys 与 E2）。
- **I7**（event_id 全局唯一误伤跨 Space）：唯一键改
  `(space_id, event_id)`；同 Space 重复 typed `duplicate_event_id`，跨
  Space 允许（probe C5）。
- **I8**（domain_write 拿到裸 Session）：回调签名改为受限
  `DomainWriteHandle`（仅 `execute`），在 SAVEPOINT 内执行；probe H1 的
  「提前 commit」路径消除。残余：句柄仍可执行任意 SQL（含 wiki_ 表），
  以文档合同约束（见已知边界）。
- **I9**（降级默默丢活跃数据）：0015 downgrade 首先执行自有数据
  preflight（存在非终态任务或未投递事件即拒绝、零 DDL）。probe F2/F3。
  新 PG 节点 `test_i9_downgrade_with_live_rows_is_refused_before_any_ddl`。
- **I10**（毒性 outbox 事件永久阻塞）：投递失败不再中止本轮；按持久
  `dispatch_attempts` 计数，达 dispatcher 配置上限 park 出扫描窗口
  （`read_parked` 可见，不伪装已投递）。`DispatchReport` 改为
  `failed_event_ids/parked_event_ids`。
- **I11**（从未 awaiting 的行误报 duplicate）：`DecisionOutcome.status`
  增加 `not_awaiting`（probe C4）。
- **I12**（Space 饱和误报 empty）：`NoClaimableJob.reason` 增加
  `per_space_concurrency_limit`（probe A2）。
- **M13**（相对降级参数绕过 crossing preflight）：目的地经
  ScriptDirectory 解析（`-N` 沿 down_revision 链展开，未知形式保守按
  base 处理）。probe F3b：`-2` 亦在零 DDL 前拒绝。
- **M14**（heartbeat 复活过期 lease）：过期 lease heartbeat typed
  `lease_expired` 拒绝（probe B6）。
- **M15**（成功后错误残留）：report_success 清空
  error_class/error_summary（probe G2）。
- **M17**（终态行 dedup 无提示）：`EnqueueResult.terminal` 标志。
- **M18**（多实例配置漂移弱化限额）：`JobRuntimeConfig`/`JobStore`
  docstring 明确「配置必须单一来源；DB 集中限额为显式后续项」（probe G1
  行为如实保留）。
- **M19**（并发 dispatcher 双投递）：dispatch 逐行「FOR UPDATE SKIP
  LOCKED → 投递 → 持久标记」单事务；probe D2 双 dispatcher 6 投递 0 重复
  （崩溃在标记前仍重投，at-least-once 不变）。新 PG 节点
  `test_m19_concurrent_dispatchers_do_not_double_deliver`。
- **规格评审 minor**：两 lane 回拨 `enqueued_at` 断言最老可调度年龄精确
  区间；新 PG 节点
  `test_p1_8_cross_space_writes_and_outbox_reads_fail_closed_on_postgres`；
  降级拒绝 PG 节点（见 I9）。
- probe D1/D3 引用旧 `DispatchReport.failed_event_id` 属性（I10 有意重
  塑），以等价脚本重跑：崩溃重投收敛、毒性 park 均验证通过。

## 交付面

```text
enqueue（消费方铸造幂等键，DB 唯一去重）
  → claim（FOR UPDATE SKIP LOCKED + advisory 串行化限额，generation +1）
  → start（attempt +1）→ heartbeat（仅当前 generation）
  → report_success（领域写 + outbox + succeeded 同一事务，至多成功一次）
  → report_failure（retryable|non_retryable|capacity_blocked|human_required
      确定性路由 retry_wait|dead_letter|blocked|awaiting_human）
  → reclaim_expired_leases（数据库时钟；记 lease_expired retryable，
      按 max_attempts 路由 queued|dead_letter；任何实例可执行）
  → resume_after_decision（awaiting_human → queued 幂等，重复 typed duplicate）
  → OutboxDispatcher（持久 dispatched_at 标记扫描，at-least-once，
      消费端按 event_id 幂等）
  → space_job_metrics / global_job_metrics（P1.9 只读指标）
```

- 生产文件：`harness/src/insurance_harness/jobs/`（`__init__/errors/models/
  tables/store/outbox/metrics`）+ 唯一迁移
  `harness/migrations/versions/0015_job_store_outbox.py` + `config.py`
  `HARNESS_JOB_*` 接线 + `migrations/env.py` 一行注册。
- 迁移编号 **0015**（`down_revision="0006"`，实际链 `0012 → 0006 → 0015`）；
  0007–0011 旧预分配与 superseded 0013/0014 按 22号 §4/24号 §3 永不复用，
  台账已改记。迁移 upgrade 只建 `wiki_jobs`/`wiki_outbox_events` 两表及其
  索引约束；downgrade 在自身第一条 DDL 之前重放 0006 聚合 preflight
  （跳过其 alembic_version 拓扑自检），保持「被拒绝的降级零 DDL」仓库
  不变量，历史迁移文件零修改。
- 存量测试适配：`test_ci_lanes_022.py`（22 个 PG 节点注册 + 021 节点
  改名）、`test_source_lifecycle_migration_021.py` / `..._postgres_021.py`
  （单 head 断言随链前移至 0015，0012→0006 拓扑断言保留）。

## 已运行门禁（2026-07-27，双评审闭环后，本机）

- focused deterministic（SQLite lane）：
  `tests/test_job_state_machine_035.py` + `tests/test_job_store_035.py` +
  `tests/test_job_outbox_035.py` → **78 passed**。
- 存量迁移消费者回归（deterministic）：`test_scope_migration_016.py`、
  `test_source_lifecycle_migration_021.py`、
  `test_release_snapshot_migration_018.py`（含 SQLite `alembic check`）、
  `test_knowledge_db.py`、`test_flywheel_migration_015.py`、
  `test_product_db.py`、`test_config.py` → **80 passed**（0015 降级
  preflight 保持「被拒绝的降级零 DDL」全链不变量）。
- CI lane 合同：`test_p0_4_three_collections_are_disjoint_exhaustive_and_precise`
  → **1 passed**（integration 集合与注册表精确一致）；22 个 PG 节点全部
  注册且 no-URL fail-fast。
- **PostgreSQL 16 lane（全量 `integration_postgres`）**：本机受控
  `postgres:16`（docker-compose.harness.yml，127.0.0.1:5442；DSN 经
  `HARNESS_TEST_POSTGRES_URL` 运行时注入，密码不入库不入日志）→
  **47 passed / 3760 deselected**；JUnit（`scripts/check_junit.py`）
  `tests=47 skipped=0 failures=0 errors=0`。每组测试创建随机临时
  database（migration 测试与独立全局限额测试）或经真实 Alembic
  `upgrade head` 的模块级随机 database（store 测试），结束即 drop。
- 对抗评审 probe 全量重跑（`p1review/probe_a..h`）：C1/C2/I3-I12/
  M13-M17/M19 对应场景全部转为 typed 拒绝或正确行为；D1/D3 以等价脚本
  验证（旧 DTO 属性已重塑）。
- Ruff：新增/触碰文件 → **All checks passed**。
- mypy（strict）：`jobs/` 全包 + 迁移 + config + 5 个测试文件 + 触碰的
  存量文件 → **Success: no issues found**。
- `openspec validate 035-p1-job-outbox --strict` → **valid**。

## P1.12 四类并发场景 → exact PG 节点

1. 多 worker 并发单领（P1.2）：
   `test_p1_2_eight_workers_claim_each_job_exactly_once_until_typed_empty`
   （8 连接 / 24 任务 / 每任务恰好一次领取）、
   `test_p1_2_claim_skips_externally_locked_row_without_blocking`、
   `test_p1_5_concurrent_duplicate_enqueue_creates_exactly_one_row`；
2. lease 过期接管（P1.3/P1.10）：
   `test_p1_3_expired_lease_is_reclaimed_and_retaken_with_greater_generation`、
   `test_p1_10_forced_kill_takeover_yields_exactly_one_domain_result`
   （pg_terminate_backend 强杀 + 领域结果/完成事件各恰好一份）、
   `test_p1_10_poison_task_crash_loop_is_bounded_by_max_attempts`
   （毒性任务恰好 3 个 generation 后由回收路由进 dead_letter）；
3. 迟到（旧 generation）worker 写拒绝（P1.3）：
   `test_p1_3_late_worker_every_write_path_is_fenced_after_takeover`
   （heartbeat/转换/结果提交/outbox 追加四路全拒、零变更）；
4. 完成事务 + outbox 原子性含崩溃模拟（P1.6）：
   `test_p1_6_completion_interrupt_before_commit_leaves_neither_row`
   （before_commit 注入中断 → 零半写 → 重放各恰好一次 → 重复完成拒绝）、
   `test_p1_6_late_committed_smaller_id_is_still_dispatched`
   （分配序 caveat：小 id 晚提交不被永久跳过）。

另有限额（两组配置值并发生效）、跨 Space fail closed（含 outbox 读）、
Decision 并发幂等、retry/backoff 配置驱动、P1.9 指标分布（per-Space 精确
+ 回拨 `enqueued_at` 的精确最老可调度年龄 + 全局按增量精确）、全局限额
排除过期 lease、advisory 等待不吞噬 lease、并发 dispatcher 零双投递、
活跃数据降级拒绝等 PG 节点，共 **22 个**，全部在 `test_ci_lanes_022.py`
注册。

## NOT RUN（如实记录）

- **WeKnora `live` lane：NOT RUN**（P1 无 WeKnora 交互，无需运行）。
- **完整 deterministic 全量套件：NOT RUN**（按 PR 约定由 controller 在
  PR-ready 阶段运行；本 PR 只运行 focused + 受影响存量文件）。
- **CI PostgreSQL 16 service job：NOT RUN**（本地 PG lane 已全量通过；
  CI 覆核在 PR 流水线执行）。

## 已知边界与待复审项

- 生产代码量：raw 1781 行 / 有效代码行（去空行/注释/docstring）1300 行
  （其中唯一迁移 200、`__init__` 导出面 89、store 445、outbox 196），
  超过 tasks Contract Card 的 ~900 触发线；双评审闭环（输入验证、
  dispatcher 重构、降级 preflight）为主要增量。按 033 §16.2 需重新切分
  评审裁决；P1 是单一原子不变量（单领/fencing/outbox 收敛），拆分候选
  仅有 metrics/dispatcher 观测面，等复审裁决，不自行拆半成品。
- `DomainWriteHandle` 只封锁事务生命周期（无 commit/rollback/close）；
  句柄仍可执行任意 SQL（含越权触碰 `wiki_` 表，评审 H2 残余）。P1 以
  文档合同约束（领域写只写调用方领域表）；SQL 级沙箱不在 P1 范围，
  消费方 PR（P3 worker 壳）接线时按其权限模型收紧。
- SQLite 仅 deterministic 测试用：`claim` 的 advisory 串行化与
  `FOR UPDATE SKIP LOCKED` 在 SQLite 为 no-op（单写者），并发证据只以
  PG lane 为准（P1.12 明文）。
- T9 dispatcher 的 deterministic 测试先于 RED 实现（dispatcher 随
  outbox.py 在 T6 GREEN 一并落地），属 TDD 次序偏差，已在交付记录中
  如实说明；PG 侧 at-least-once/无跳过证据按 RED→GREEN 正常闭环。
