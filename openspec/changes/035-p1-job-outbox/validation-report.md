# 035 验证报告 — P1 Job Store + 事务性 Outbox

> 单一领域不变量：**at-least-once 任务执行在 PostgreSQL 权威下收敛为恰好
> 一次领域提交**。本报告记录实现 PR 的实际验证结果与未运行项。
>
> **2026-07-27 重落地**：旧实现 PR #44（分支 `feat/035-p1-job-outbox-impl`）
> 已关闭、**零代码合入**，归档于 tag
> `archive/pr44-p1-job-outbox-20260727-a6cdc9ae`。本 PR（分支
> `feat/035-p1-job-outbox-reland`）从最新 `main=70740334` 的干净 worktree
> 重落地**同一份代码**：首个重落地提交 `f8bb24c7` 时 `git diff` 对归档 tag
> 在 P1 全部代码路径下为空（main 侧自 merge-base `dedbbafb` 起从未触碰这些
> 文件），只按最新 main 重写了治理文档。
>
> **该「逐字节一致」表述自 `5d663004` 起不再成立**：其后按下文 D-2026-07-27-16
> 边界冻结做了实质代码修复。**旧 #44 head、以及本 PR 早期 head 的门禁结果
> 一律不作当前证据**；下文「已运行门禁」是在本 PR 当前 head 重跑的结果。
> 迁移链前置已复核：最新 main（`caf05fac`，含 W1 #55——只动 WeKnora Go 侧，
> 未引入新 Alembic revision）的真实 alembic head 仍为 `0006`，`0015` 的
> `down_revision="0006"` 无需改动，单 head。
>
> **2026-07-27 双评审闭环（在归档代码内完成，随本 PR 一并交付）**：PR #44
> 规格评审 Approved-with-findings（minor）、对抗评审 REJECTED（2 Critical /
> 10 Important / 7 Minor）；全部 finding 已按 RED-first 关闭并重跑评审
> probe 验证，见下文「双评审 finding 闭环」节。这 19 条及其 16 个以 finding
> 编号命名的测试节点是本 PR 验收清单的**强制项**，后续重构不得删除。
>
> **2026-07-27 §18 停线与边界冻结（第二轮双独立评审后）**：PR #53 提交
> 双独立评审（Spec / Quality，互不知晓对方结论、各自独立 worktree +
> 独立 PostgreSQL 实例），结果 `Spec compliant: no`（1C/6I/5m）与
> `Quality approved: no`（2C/6I/4m），且**两侧独立复现了同一破口**——过期
> 未回收的 lease 既不计入并发限额、又保有完整写权威。按 033 §18「根因是
> 错误架构边界时替换边界而不是把补丁堆叠到旧实现」，先冻结规格再实现：
> 035 spec 344 → 536 行（8 条边界合同，纯澄清、不新增状态/异常分支），
> 裁决记入 23 号 §8 `D-2026-07-27-16`，行数触发线豁免记入 `D-2026-07-27-17`。
> 修复见 tasks T14–T27，验收清单由 14 项扩为 **28 项**。
>
> **2026-07-27 第二轮双评审 → P1.5 边界替换**：修复后重新提交双独立评审。
> lease 过期 / 写权威 / 限额会计域经 live 验证**真正闭合**（Spec 侧用探针反转
> 了自己上轮 F1 的原始场景），13 条上轮 findings 中 12 条 CLOSED。但
> **P1.5 领域写通道判定停线**：第一版修法（可执行回调 + 语句面校验 + 提交点
> 校验）被公共属性一行击破——`handle.execute(...).connection.execute(COMMIT)`
> ⇒ 领域行落库、任务仍 `running`、outbox 空，重放产生第二份领域结果；同时
> SQL 文本扫描误杀 P6a/P2b 自己的 `wiki_` 表与含关键字的字符串字面量。
> 既可绕过又会误杀 ⇒ 方法错误而非补得不够。业务方裁决取**方案 A：完成事务
> 收数据不收代码**（见 tasks T29）。规格 P1.5 条款随之修订（536 → 556 行），
> 四个 Scenario 重写为"接口层面不可构造 + 前缀不误拦"。

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

## 边界冻结后的修复面（D-2026-07-27-16）

```text
写权威    require_active_lease 单一过期门 → start / report_success /
          report_failure / append_job_event 四路对称执法（+heartbeat）
限额会计  _count_active 计全部 leased|running（不按过期缩小分母）
          → 饱和且存在过期行时 _reclaim_saturated 做无 Space 过滤的有界回收
回收的界  _reclaim_locked 对 leased 行先 attempt +1 再路由（修无界重排队）
          + reclaim_expired_leases_all_spaces() 显式跨 Space 入口
状态机    ensure_transition(storage_layer=False) 使 STORAGE_ONLY_TRANSITIONS
          成为可执行护栏；report_failure 要求源状态 running
领域写    完成事务收数据不收代码：DomainWriteSpec(table, values) 由存储层执行
          目标表在数据上比对 OWNED_TABLES 精确两张（不按 wiki_ 前缀封杀）
          调用方不持有任何 DB 句柄 ⇒ 提交外层事务在接口层面不可构造
事件边界  append_job_event 收回公共出口（只经 report_success 追加）
投递      next_dispatch_at 持久退避 + 配置化 dispatch_backoff_seconds
          取代 max_dispatch_attempts 硬上限与永久 park
可观测    expired_lease_count / oldest_expired_lease_age_seconds
判据      human_decision_resumed_at 不可变列取代可变 error_class 代理
输入合同  validated_limit 原语 + 只读入口统一走 validated_text
迁移      dead_letter 纳入降级拒绝；offline --sql 显式 typed 拒绝
配置      lease_seconds 严格为正且 > heartbeat_interval_seconds
```

迁移 `0015` 新增两列（`wiki_outbox_events.next_dispatch_at`、
`wiki_jobs.human_decision_resumed_at`）与索引调整
（`ix_wiki_outbox_events_undispatched` → `(next_dispatch_at, id)`）。0015 未
合入，属"合入前原位修订"，**不产生第二个 migration**（与 I5 索引同一处理）。

## 已运行门禁（2026-07-27，本 PR head 在 `main=0cb7beff` 上全新重跑）

> 以下全部是重落地 + 边界冻结修复后在本分支重跑的结果；旧 #44 head 与
> 本 PR 早期 head 的门禁结果均不作当前证据。

- focused deterministic（SQLite lane）：
  `tests/test_job_state_machine_035.py` + `tests/test_job_store_035.py` +
  `tests/test_job_outbox_035.py` + `tests/test_config.py` → **135 passed**
  （重落地时 78 → 边界冻结后 119 → P1.5 边界替换与其两轮修复后 135）。
- 存量迁移消费者回归（deterministic）：`test_scope_migration_016.py`、
  `test_source_lifecycle_migration_021.py`、
  `test_release_snapshot_migration_018.py`（含 SQLite `alembic check`）、
  `test_knowledge_db.py`、`test_flywheel_migration_015.py`、
  `test_product_db.py`、`test_config.py` → **80 passed**（0015 降级
  preflight 保持「被拒绝的降级零 DDL」全链不变量）。
- CI lane 合同：`test_ci_lanes_022.py` 全文件 → **71 passed**（integration
  集合与注册表精确一致）；PG 节点 22 → **32** 全部注册且 no-URL fail-fast
  （store 18 → 25、migration 4 → 7）。
- **PostgreSQL 16 lane（全量 `integration_postgres`）**：本机受控
  `postgres:16` 全新容器（`127.0.0.1:5942`，全新 volume，零遗留状态；DSN
  经 `HARNESS_TEST_POSTGRES_URL` 运行时注入，密码不入库不入日志）→
  **57 passed / 3897 deselected**（重落地时 47 → 边界冻结后 55 → P1.5 替换后
  57）；JUnit（`harness/scripts/check_junit.py`）`tests=57 skipped=0`。每组测试创建随机
  临时 database（migration 测试与独立全局限额测试）或经真实 Alembic
  `upgrade head` 的模块级随机 database（store 测试），结束即 drop。
- **CI 门禁原样命令**：`uv run ruff check .` → **All checks passed**；
  `uv run mypy src tests`（strict）→ **Success: no issues found in 350
  source files**（不再只查触碰文件，按 `.github/workflows/harness-ci.yml`
  的实际命令全量运行）。
- `openspec validate 035-p1-job-outbox --strict` → **valid**；
  `openspec validate --all --strict` → 27 passed / 12 failed，12 项失败为
  001～022 存量轻量规格，与最新 main 的基线完全同集（main 上同样 12 项），
  非本 PR 引入。
- **finding 派生测试节点在本 PR head 全部通过**：`test_c1_*`（2）、
  `test_c2_*`（2）、`test_i3/i4/i6/i7/i8/i9/i10_*`、`test_m14/m15/m16/m17/
  m19_*`，共 16 个节点随上述 focused 与 PG lane 一并绿。它们是 19 条
  findings 的可持续回归载体。

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
+ 回拨 `enqueued_at` 的精确最老可调度年龄 + 全局按增量精确）、advisory
等待不吞噬 lease、并发 dispatcher 零双投递、活跃数据降级拒绝等 PG 节点。

**D-2026-07-27-16 边界冻结新增的 8 个 PG 节点**（tasks 清单 15/16/19/21/
27/28）：`test_q15_expired_lease_holder_has_no_write_authority_on_postgres`、
`test_q16_stalled_expired_leases_never_exceed_limits_on_postgres`、
`test_q17_unenumerated_space_converges_via_global_reclaim_on_postgres`、
`test_q19_domain_write_cannot_escape_its_channel_on_postgres`、
`test_q25_delivered_but_unmarked_crash_converges_on_postgres`、
`test_q26_downgrade_relative_destination_crossing_0006_is_resolved`、
`test_q26_downgrade_refuses_while_dead_letter_forensics_exist`、
`test_q26_offline_sql_downgrade_is_explicitly_refused`。

**P1.5 边界替换新增的 2 个 PG 节点**：
`test_q30_owned_table_check_is_normalized_on_postgres`（表名规范化在两方言上
给同族拒绝）、`test_q31_values_may_not_smuggle_sql_on_postgres`（列值不得夹带
SQL，含泄漏计数为 0 与接受侧）。

PG 节点合计 **32 个**（22 → 30 → 32），全部在 `test_ci_lanes_022.py` 精确集注册。

**契约收紧（刻意，两处）**：① C1 节点（det + PG）原断言"scope 外零变更"
已迁移为"回收后放行 + 调用方拿不到跨 Space 内容 + 过期持有者即刻失去写
权威"——冻结的边界选择了"限额分母含过期行 + 饱和时无 Space 过滤的有界
回收"，与"claim 不触碰 scope 外行"不可兼得，取前者因其同时消灭过度准入与
永久饥饿；② 转换穷举节点由二分改三分（调用方可达 / storage-only / 非法）。
另有 12 处 `lease_seconds=0.0` 过期脚手架迁移为只回拨 lease 的
`force_expire`/`_force_expire`（配置层已禁止 `lease_seconds = 0`）。

## NOT RUN（如实记录）

- **WeKnora `live` lane：NOT RUN**（P1 无 WeKnora 交互，无需运行）。
- **完整 deterministic 全量套件：NOT RUN**（按 PR 约定由 controller 在
  PR-ready 阶段运行；本 PR 只运行 focused + 受影响存量文件 + 全量
  `integration_postgres`）。
- **CI PostgreSQL 16 service job：NOT RUN**（本机 PG lane 已全量通过；
  CI 覆核在本 PR 流水线执行）。
- **对抗评审 probe 脚本（`p1review/probe_a..h`）：本 PR NOT RE-RUN**。
  这些脚本当时在会话 scratchpad、从未入库，重落地时已不存在，因此**不能
  声称在本 PR head 重跑过**。19 条 findings 的持久回归证据是入库的 16 个
  finding 编号测试节点（见「已运行门禁」末条），它们在本 PR head 全绿；
  probe 的历史结论保留在「双评审 finding 闭环」节，仅作旧 head 的审计记录。

## 四轮评审收口与 BACKLOG 转出（D-2026-07-27-19）

035 共经四轮独立评审（规格 1 + 对抗 3）+ 总控窗口 2 次自攻，最终**零 BLOCKER**。

第四轮定向覆盖此前从未被独立验证的五个面：`attempt` 计数 **no finding**；
`human_decision_resumed_at` **no finding（攻不动）**；`_reclaim_saturated` 的
越限/饥饿/跨 Space 泄漏**全部攻不动**（15s 6 并发压测 2310 次采样零越限）；
多 spec 领域写原子性**成立**；`next_dispatch_at` 3 条 BACKLOG **已在本 PR 修完**
（非有限/荒谬退避档位通过配置门致 dispatcher 在失败处理内崩溃并卡死整个 Space
的 outbox、模型默认 `(0.0,)` 热循环、退避基准在 deliver 之前读致超时失败无
实际让位）。

**5 条 BACKLOG 转 042**（号已占、目录未开，比照 026 惯例；完整清单含 live
证据与建议修法见 23 号 §8 D-2026-07-27-19），不在本 change 内修：领域写失败驱动异常穿透 typed 面；反射占第二条连接（并发上限
≥ 池容量时完成路径自我死锁）；反射无缓存；有界回收触发条件宽于 spec；
`_execute_domain_writes` docstring 与实际次序不符（行为正确、声明不准）。
五条均 live 证明不损坏数据、不越 Space、不产生第二份领域结果，符合
`AGENTS.md` 的 BACKLOG 定义。

## 已知边界与待复审项

- 生产代码量超过 tasks Contract Card 的 ~900 触发线（边界冻结前实测
  raw 1781 / 有效 1300）。该裁决已由
  [D-2026-07-27-17](../../../docs/insurance-kb/23-mvp-control-board.md)
  **闭合为不拆分**：拆分在算术上不能带来预算合规（可分离的 metrics +
  dispatcher 约 225 行，拆后仍约 1075 > 900），且会产生"outbox 无人 drain"
  的半成品，正是 §16.2 禁止的为数字拆坏原子不变量。豁免仅限本窗口，不构成
  后续 Pn 先例。边界冻结的修复使行数进一步增加（新增两道防线、退避、指标与
  两个列），仍在同一豁免范围内。
- 领域写通道的越权问题**由边界替换关闭，不是由检测关闭**（见 tasks T29）。
  我在第一版曾把它报告为"已关闭（两道防线）"，**该结论被第二轮评审用 live
  证据推翻**，此处如实更正：进程内沙箱化一个持有 DB 句柄的可执行回调是不可
  完成的。现在调用方交 `DomainWriteSpec`、不持任何句柄，"提交外层事务"在
  接口层面无从下手。DB 权限级隔离仍归 P3 principal 模型（属纵深防御的下一层，
  不是本条的前提）。
- **声明式通道的已声明功能收窄**：不支持完成事务内先读后写（先 SELECT 中间值
  再据以写入）。当前全部用法是单条 INSERT，不受影响；需要该形态的领域逻辑
  须把读与计算移到完成事务之外，或由后续 PR 以显式合同新开入口，**不得恢复
  可执行回调**（规格已明文）。
- `_execute_domain_writes` 每次调用按表名 `autoload_with` 反射表结构，未做
  缓存：单次完成事务内的领域写数量很小（当前用法 1–2 条），但高频路径下值得
  由消费方 PR 评估是否引入 `MetaData` 复用。列为 BACKLOG，不影响正确性。
- SQLite 仅 deterministic 测试用：`claim` 的 advisory 串行化与
  `FOR UPDATE SKIP LOCKED` 在 SQLite 为 no-op（单写者），并发证据只以
  PG lane 为准（P1.12 明文）。
- T9 dispatcher 的 deterministic 测试先于 RED 实现（dispatcher 随
  outbox.py 在 T6 GREEN 一并落地），属 TDD 次序偏差，已在交付记录中
  如实说明；PG 侧 at-least-once/无跳过证据按 RED→GREEN 正常闭环。
- **T22（过期 lease 指标）同样属 TDD 次序偏差**：其实现与 T24 的
  `validated_text` 接线在同一处，先落 GREEN 后补验收节点；节点在本 head
  全绿，如实记录不粉饰。
- 并发限额仍由执行 claim 的实例按其自身配置执行（review M18 的既有边界
  未变）：多实例配置漂移会弱化限额，部署必须共享单一配置来源；数据库
  支撑的集中限额策略是显式后续项。
- `claim` 在单一 advisory key 上全局串行化（`_CLAIM_LOCK_KEY`），且生产
  engine 未设 `lock_timeout`：任一持锁事务卡住会阻塞全部 Space 的 claim。
  I3 节点证明 lease 时长不被等待吞噬，但未证明等待有界。`lock_timeout`
  接线归 P3 worker 壳（本 PR 不改 `make_engine`，避免夹带无关改动）。
- `heartbeat_interval_seconds` 在 P1 内无消费者（heartbeat 调度归 P3
  worker 壳）；本 PR 只用它校验 `lease_seconds` 的下界一致性。
- `read_backed_off` 是运维**可观测面**，不是隔离终态：这些行仍在扫描集合
  内、退避到期后继续重投。毒性事件的熔断/人工处置属消费方 reconciliation
  （proposal 非目标）。
