# 035 验证报告 — P1 Job Store + 事务性 Outbox

> 单一领域不变量：**at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
> 一次领域提交**。本报告记录实现 PR（分支 `feat/035-p1-job-outbox-impl`）
> 的实际验证结果与未运行项；T13 独立复审尚未进行。

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
- 存量测试适配：`test_ci_lanes_022.py`（新增 17 个 PG 节点注册 + 021 节点
  改名）、`test_source_lifecycle_migration_021.py` / `..._postgres_021.py`
  （单 head 断言随链前移至 0015，0012→0006 拓扑断言保留）。

## 已运行门禁（2026-07-27，本机）

- focused deterministic（SQLite lane）：
  `tests/test_job_state_machine_035.py` + `tests/test_job_store_035.py` +
  `tests/test_job_outbox_035.py` → **64 passed**。
- 存量迁移消费者回归（deterministic）：`test_scope_migration_016.py`、
  `test_source_lifecycle_migration_021.py`、
  `test_release_snapshot_migration_018.py`（含 SQLite `alembic check`）、
  `test_knowledge_db.py`、`test_flywheel_migration_015.py`、
  `test_product_db.py` → **77 passed**。
- CI lane 合同：`test_p0_4_three_collections_are_disjoint_exhaustive_and_precise`
  → **1 passed**（integration 集合与注册表精确一致）；17 个新 PG 节点的
  no-URL fail-fast 参数化 → **17 passed**。
- **PostgreSQL 16 lane（全量 `integration_postgres`）**：本机受控
  `postgres:16`（docker-compose.harness.yml，127.0.0.1:5442；DSN 经
  `HARNESS_TEST_POSTGRES_URL` 运行时注入，密码不入库不入日志）→
  **42 passed / 3741 deselected**；JUnit（`scripts/check_junit.py`）
  `tests=42 skipped=0 failures=0 errors=0`。每组测试创建随机临时
  database（migration 测试）或经真实 Alembic `upgrade head` 的模块级
  随机 database（store 测试），结束即 drop。
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

另有限额（两组配置值并发生效）、跨 Space fail closed、Decision 并发幂等、
retry/backoff 配置驱动、P1.9 指标分布（per-Space 精确 + 全局按增量精确）
等 PG 节点，共 17 个新节点，全部在 `test_ci_lanes_022.py` 注册。

## NOT RUN（如实记录）

- **WeKnora `live` lane：NOT RUN**（P1 无 WeKnora 交互，无需运行）。
- **完整 deterministic 全量套件：NOT RUN**（按 PR 约定由 controller 在
  PR-ready 阶段运行；本 PR 只运行 focused + 受影响存量文件）。
- **CI PostgreSQL 16 service job：NOT RUN**（本地 PG lane 已全量通过；
  CI 覆核在 PR 流水线执行）。

## 已知边界与待复审项

- 生产代码量：raw 1392 行 / 有效代码行（去空行/注释/docstring）1040 行
  （其中唯一迁移 135、`__init__` 导出面 82、store 366），超过 tasks
  Contract Card 的 ~900 触发线 → 按 033 §16.2 需重新切分评审裁决；
  P1 是单一原子不变量（单领/fencing/outbox 收敛），拆分候选仅有
  metrics/dispatcher 观测面，等 T13 复审裁决，不自行拆半成品。
- SQLite 仅 deterministic 测试用：`claim` 的 advisory 串行化与
  `FOR UPDATE SKIP LOCKED` 在 SQLite 为 no-op（单写者），并发证据只以
  PG lane 为准（P1.12 明文）。
- T9 dispatcher 的 deterministic 测试先于 RED 实现（dispatcher 随
  outbox.py 在 T6 GREEN 一并落地），属 TDD 次序偏差，已在交付记录中
  如实说明；PG 侧 at-least-once/无跳过证据按 RED→GREEN 正常闭环。
