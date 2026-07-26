# 035 · P1 Job + Outbox

> 状态：📋 规格起草（Wave 1，总控窗口）。本 change 是 033 新路线的**第一个
> 实现 PR（P1）**，开工授权：23 号控制板 §8 D-2026-07-26-5（Wave 1）。
>
> 权威设计源：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> §6.2（并发模型）、§12（任务运行时与错误处理）、§16 P1 行、§16.2（PR 颗粒度
> 与 PostgreSQL 16 并发测试义务）、§18（Contract Card）。本 change 不复制、
> 不修改、不重新解释该设计；语义冲突时以 033/权威设计为准。

## 为什么做

033 已冻结：多实例正确性依赖 PostgreSQL 唯一约束、CAS 和 fencing token，
不依赖进程内锁；任务语义是 at-least-once，领域输出必须幂等（§6.2）。
Milestone A 的 Revision Capture、微批、抽取以及后续 Release/投影全部要跑在
同一个可证明并发正确的任务运行时上（§16 DAG：`D0 → P1 → P3`）。旧 031
runtime 已 superseded / history-only，不得重放。没有 P1，后续每个小 PR 都会
被迫各自发明领取、重试和事件外发语义，重蹈旧路线补丁循环的覆辙。

## 本 Change 做什么

按 033 §16 P1 行的单一职责——「PostgreSQL 固定任务状态机、lease、fencing、
幂等、Outbox」——冻结以下合同并交付其实现规格（见
`specs/job-runtime/spec.md`）：

- §12 固定状态机：`queued → leased → running → succeeded`，加
  `running → retry_wait → queued`、`running → awaiting_human → queued`、
  `running → blocked`、`running → dead_letter`；非法转换在存储层拒绝；
- PostgreSQL `FOR UPDATE SKIP LOCKED`（或经测试证明等价）的 claim：多
  worker 并发时每任务每 lease generation 恰好单一领取者；
- lease 到期 + heartbeat + 单调 generation/fencing token：过期 lease 可回收，
  迟到（旧 generation）worker 的一切写入被拒绝；
- attempt 计数、封闭 typed 错误分类、配置化重试/backoff 与 max-attempts →
  `dead_letter`；
- 幂等键：重复 enqueue 去重；at-least-once 重放下同一任务恰好一份领域结果；
- 事务性 Outbox：领域写与 outbox 事件同一 PostgreSQL 事务，dispatcher
  at-least-once 消费 + 消费端幂等，无双写；
- `awaiting_human` 不持有 worker lease，人工 Decision 幂等唤醒原任务；
- 所有行显式绑定 `space_id`，跨 Space fail closed；per-Space 与全局并发上限
  来自配置（数值不是产品上限）；
- 队列深度、最老任务年龄、重试/失败与 dead-letter 计数可查询；
- 崩溃恢复：进程崩溃 → lease 过期 → 更高 generation 接管；
- 恰好一个新 Alembic 迁移，只建 `wiki_jobs` 与 `wiki_outbox_events` 两表，
  `down_revision` 从执行时真实 head 续接（本规格起草时观测为 `0006`）；
- 033 §16.2 要求的 PostgreSQL 16 并发验收测试（`integration_postgres`
  lane，JUnit `skipped=0`）。

## 不做什么（非目标）

以下明确不属于 P1，出现在计划或 diff 中即 scope 违规（依据 033 §12
「近期不实现」与 §16 P1「不包含」列）：

- WeKnora 交互（Source Inbox/polling/投影归 W0/W1/P4a/P12）；
- Compiler（P6a）与任何 Candidate/Release 语义（P2b/P6b/P8）；
- 通用 DAG/DSL、动态 worker 拓扑；
- exactly-once 宣称——P1 只承诺 at-least-once 执行 + 幂等提交；
- Redis、Kafka 或任何第二 broker/队列系统；
- 031 式 SQLite budget ledger、PTU、密钥 ceremony、文件系统 operation store；
- 每次编译创建/领养/删除模型部署；
- 外部 provider 请求的 reconciliation 流程（归消费方 PR；P1 只提供 typed
  状态与幂等提交原语）；
- API/Worker 进程壳与健康检查（P3）。

## 影响面

- 本阶段（spec-only）只新增 `openspec/changes/035-p1-job-outbox/` 并在
  `openspec/changes/README.md` 注册表占号：035 = p1-job-outbox，034 =
  c0-canonical-envelope（C0 正在 sibling worktree 实施，一并登记避免注册表
  合并冲突）；原 planned 的 W0 spike 行按注册表「后者改号」规则由 035 改号
  至 037。不修改 033 的任何文件，不写功能代码、迁移或测试。
- 实现 PR 的文件域：harness 新 `job_runtime` 包（状态机、store、outbox
  dispatcher、指标查询、配置接线）+ 恰好 1 个新 Alembic 迁移 + P1 tests；
  不触碰 WeKnora fork、frontend、既有领域表与历史迁移。
- 迁移编号在实现 PR 开工时按注册表规则先占号，本 change 不预占（033
  D0.11：后续 owner 从执行时真实 `origin/main` Alembic head 重新占号）。

## 依赖与后续

- 依赖：仅 D0（033 治理批准）。按 §16 DAG，P1 不依赖 C0/W0/CAP0 的产物。
- 后续：P3 的 Worker 壳消费 JobStore；P4a/P4c/P5b1 以 P1 任务承载各自事务；
  P8 复用同一 Outbox 合同。per-Space/全局并发数值与 CapacityProfile 的正式
  对接归 CAP0/P4b，P1 只保证上限来自配置且超限任务排队不丢失。
