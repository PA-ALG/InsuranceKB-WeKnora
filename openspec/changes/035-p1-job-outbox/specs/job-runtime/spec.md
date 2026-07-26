# 035 P1 Job + Outbox 验收规格

## ADDED Requirements

### Requirement: P1.1 固定任务状态机

任务状态 SHALL 是封闭枚举
`queued | leased | running | succeeded | retry_wait | awaiting_human | blocked | dead_letter`。
合法转换 SHALL 只有以下列出的转换：

1. `queued → leased`：claim 成功，lease generation 单调 +1；
2. `leased → running`：同一 generation 的 worker 开始执行，attempt +1；
3. `running → succeeded`：完成事务提交；
4. `running → retry_wait`：typed `retryable` 错误且 attempt 未达配置上限；
5. `retry_wait → queued`：仅限存储层在以数据库时钟验证配置化 backoff 已
   到期（`available_at <= 数据库当前时间`）后执行；
6. `running → awaiting_human`：typed `human_required` 结果，同事务释放 lease；
7. `awaiting_human → queued`：人工 Decision 幂等唤醒；
8. `running → blocked`：typed `capacity_blocked` 阻断（含
   `candidate_capacity_exceeded` 一类合同性阻断原因）；
9. `running → dead_letter`：typed `non_retryable` 错误，或 `retryable` 但
   attempt 已达配置上限；
10. `leased → queued | dead_letter` 与 `running → queued | dead_letter`：
    仅限存储层在以数据库时钟验证 lease 已过期后执行的回收转换。回收 SHALL
    把该次过期记录为 typed `retryable` 失败（错误摘要 `lease_expired`），并
    按 P1.4 的 `max_attempts` 条件路由：attempt 已达上限转 `dead_letter`，
    否则回 `queued`。

系统 SHALL NOT 定义其他状态或其他转换；`succeeded`、`blocked`、
`dead_letter` 在本状态机内 SHALL 是终态（无出边）。任何非法转换请求 SHALL
在存储层被拒绝并返回 typed `illegal_transition` 错误，目标行零字段变更；
转换合法性 SHALL 由存储层单一入口执行，SHALL NOT 依赖调用方自律或进程内
检查。

#### Scenario: 非法转换在存储层拒绝

- **WHEN** 调用方尝试 `queued → running`、`succeeded → queued`、
  `blocked → running` 或任何未列入上表的转换
- **THEN** 存储层返回 typed `illegal_transition` 错误，任务行的
  state/attempt/generation/lease 字段逐一保持不变

#### Scenario: 终态不再流转

- **WHEN** 对处于 `succeeded`、`blocked` 或 `dead_letter` 的任务提交任何
  状态转换请求（包括重复完成）
- **THEN** 请求被 typed 拒绝，不产生领域写、不追加 outbox 行

### Requirement: P1.2 PostgreSQL claim 单一领取

claim SHALL 在单个 PostgreSQL 事务内使用
`SELECT ... FOR UPDATE SKIP LOCKED`（或提供等价「跳过已锁行」行级锁语义并
在 P1.12 并发测试中证明等价）选中可领取任务，写入 `leased` 状态、worker
身份、lease 到期时间并把 lease generation 单调 +1。可领取 SHALL 定义为
`state = queued AND available_at <= 数据库当前时间`，或满足 P1.3 的过期回收
条件。对同一任务，同一 lease generation SHALL 恰好有一个 claim 成功；并发
claim SHALL NOT 因其他连接持有行锁而阻塞领取其余任务。无可领取任务时
claim SHALL 返回 typed 空结果，SHALL NOT 抛出异常或在事务内等待。

#### Scenario: 多 worker 并发单领

- **WHEN** 至少 8 个并发数据库连接对同一批 queued 任务同时执行 claim，
  直至队列耗尽
- **THEN** 每个任务在其当次 lease generation 内恰好被一个连接领取一次，
  没有任务被两个连接同时领取，也没有连接因他人行锁而无法领取其余任务

#### Scenario: 空队列返回 typed 空结果

- **WHEN** 目标 scope 内不存在可领取任务时执行 claim
- **THEN** claim 返回 typed「无任务」结果，零行变更，不阻塞等待

### Requirement: P1.3 lease、heartbeat 与 fencing token

每个 lease SHALL 持久化 `lease_expires_at`（过期判定只使用 PostgreSQL
数据库时钟）与每任务单调递增的 `lease_generation`（fencing token）。
heartbeat SHALL 仅当携带的 generation 等于任务当前 generation 且状态为
`leased | running` 时延长 `lease_expires_at`，否则 typed 拒绝、零行变更。
lease 过期后任务 SHALL 只能按 P1.1 第 10 条回收（记 `lease_expired` 的
typed `retryable` 失败并按 `max_attempts` 路由至 `queued` 或
`dead_letter`）；回收后再次成功 claim SHALL 取得严格更大的 generation。携带小于当前 generation 的任何写入——
heartbeat、状态转换、领域结果提交、outbox 追加——SHALL 在存储层被 typed
`stale_generation` 拒绝且零行变更。lease 有效期与 heartbeat 间隔 SHALL
来自配置，SHALL NOT 硬编码。过期判定与写入权威 SHALL NOT 参考 worker
本地时钟。

#### Scenario: lease 过期接管

- **WHEN** 任务在 generation g 被领取后 worker 停止 heartbeat，
  `lease_expires_at` 按数据库时钟过去，另一个 worker 执行 claim
- **THEN** 任务先被回收再被领取，新 lease 的 generation 严格大于 g，任务
  可继续执行

#### Scenario: 迟到 worker 写入被 fencing 拒绝

- **WHEN** 持有 generation g 的原 worker 在任务已被 generation g+1 接管后
  苏醒，依次尝试 heartbeat、状态转换与结果提交
- **THEN** 三类写入全部返回 typed `stale_generation`，零领域写、零 outbox
  追加，g+1 的 lease 与任务状态不受影响

#### Scenario: 时钟漂移不产生双写权威

- **WHEN** 某 worker 本地时钟快于或慢于数据库时钟任意幅度
- **THEN** 过期判定仍只由数据库时钟决定，写入权威仍只由 generation 决定，
  任意时刻至多一个 generation 的写入会被接受

### Requirement: P1.4 attempt、typed 错误分类与重试策略

每次 `leased → running` SHALL 使任务 attempt 计数 +1。执行失败 SHALL 归入
封闭 typed 枚举 `retryable | non_retryable | capacity_blocked |
human_required`，并分别确定性映射到 `retry_wait`、`dead_letter`、
`blocked`、`awaiting_human`；无法分类的异常 SHALL 记为 `retryable` 的一次
attempt 并保留原始错误摘要，SHALL NOT 被静默吞掉或伪装成功。`retryable`
失败且 attempt 已达 `max_attempts` 时 SHALL 转入 `dead_letter`。
`max_attempts` 与每次重试的 backoff 序列 SHALL 来自配置（可按 job_type
覆盖），SHALL NOT 硬编码于转换代码。lease 过期回收（P1.1 第 10 条）SHALL
复用同一分类与路由：记 typed `retryable` 失败（错误摘要
`lease_expired`），attempt 已达上限即转 `dead_letter`。`dead_letter` 行
SHALL 保留 space_id、幂等键、attempt、错误分类与最后错误摘要。

#### Scenario: 达到重试上限进入 dead_letter

- **WHEN** 配置 `max_attempts = 3`，同一任务连续三次以 `retryable` 失败
- **THEN** 前两次转入 `retry_wait` 并按配置 backoff 重新排队，第三次转入
  `dead_letter`，行内保留 attempt=3、错误分类与最后错误摘要

#### Scenario: backoff 只由配置决定

- **WHEN** 同一失败序列分别在 backoff 配置 `[1s, 5s]` 与 `[10s, 60s]` 下运行
- **THEN** `retry_wait` 写入的 `available_at` 分别按两组配置计算，无代码
  变更即生效

#### Scenario: 未分类异常不静默

- **WHEN** worker 抛出未归类的异常
- **THEN** 该次执行按 `retryable` 记一次 attempt、保留错误摘要并进入
  `retry_wait` 或（达上限时）`dead_letter`；任务不会停留在 `running`，也
  不会被标记 `succeeded`

### Requirement: P1.5 幂等键与单一领域结果

每个任务 SHALL 携带调用方提供的幂等键，`(space_id, job_type,
idempotency_key)` SHALL 由数据库唯一约束保证唯一；重复 enqueue SHALL 返回
既有任务的 typed dedup 结果，SHALL NOT 创建第二行。任务的领域结果 SHALL
只能通过存储层完成事务提交；对同一任务，完成事务 SHALL 至多成功一次（由
P1.1 状态机与 P1.3 fencing 共同保证）。在 at-least-once 重投/重放下，同一
任务 SHALL 恰好持久化一份领域结果；后续完成尝试 SHALL 被 typed 拒绝且零
领域写、零 outbox 追加。系统 SHALL NOT 宣称 exactly-once execution；对外
合同是 at-least-once 执行 + 幂等提交。

幂等键 SHALL 由消费方按显式批次/重试裁决铸造，键 SHALL 编码该次批次/裁决
身份：对同一逻辑工作的新一次授权处理 SHALL 使用新幂等键创建新任务行，
而不是改写既有行。终态行（`succeeded | blocked | dead_letter`）与其唯一键
SHALL 保持不变；P1 SHALL NOT 提供对终态行的 replay/重新处理入口——受治理
的 replay 入口是显式后置非目标，SHALL NOT 被当作 P1 的隐含能力实现。

#### Scenario: 重复 enqueue 幂等去重

- **WHEN** 同一 `(space_id, job_type, idempotency_key)` 被并发或先后
  enqueue 多次（如同一 SourceRevision 的重复事件）
- **THEN** 表中恰好存在一行任务，后续 enqueue 均返回 typed dedup 结果并
  指向同一任务

#### Scenario: 重复执行不产生第二份领域结果

- **WHEN** 因确认丢失同一任务被完整执行两次，两次都尝试提交完成事务
- **THEN** 只有第一次提交写入领域结果与 outbox 事件；第二次被 typed 拒绝，
  领域结果全表计数不变

### Requirement: P1.6 事务性 Outbox

需要对外发布事件的领域写 SHALL 在同一个 PostgreSQL 事务中同时写入领域行与
`wiki_outbox_events` 行；事务中断或回滚时二者 SHALL 都不存在。存储层
SHALL NOT 提供绕过该事务、在领域写路径上直接向外部系统发布的入口（无
双写）。每条 outbox 行 SHALL 携带单调分配的有序 id、稳定 event_id（投递
幂等键）、NOT NULL `space_id`、事件类型与负载。有序 id SHALL 只表示分配
顺序：较小 id 的行可能在较大 id 的行已投递之后才随其事务提交而可见，因此
系统 SHALL NOT 提供跨事务的投递顺序保证；消费端 SHALL 只依赖 event_id
幂等去重及其自身的 epoch/fencing 语义，SHALL NOT 把 id 顺序当作语义顺序。
dispatcher SHALL 按有序 id
升序扫描未标记投递的行、投递成功后持久标记 `dispatched_at`；投递语义
SHALL 是 at-least-once：投递与标记之间崩溃时该行 SHALL 被重投，消费端
SHALL 以 event_id 幂等去重。已提交的 outbox 行 SHALL NOT 因内存
offset/水位丢失而永不投递；扫描 SHALL 基于持久化投递标记。

#### Scenario: 领域写与 outbox 同事务原子

- **WHEN** 完成事务在写入领域行与 outbox 行之后、提交之前被注入中断
- **THEN** 领域行与 outbox 行都不存在；任务重放后二者各恰好出现一次

#### Scenario: 投递后未标记的崩溃收敛

- **WHEN** dispatcher 投递某行成功但在写入 `dispatched_at` 前崩溃后重启
- **THEN** 该行被再次投递，消费端按 event_id 幂等，最终恰好产生一次可观测
  效果，且该行最终被持久标记为已投递

#### Scenario: 外发不可用不影响领域事务

- **WHEN** 领域写提交时外部消费方不可用
- **THEN** 领域事务照常提交，事件停留在 outbox 等待投递；不存在同步双写
  造成的半提交状态

### Requirement: P1.7 awaiting_human 不持有 lease

`running → awaiting_human` SHALL 在同一存储事务中释放 worker lease：该
任务 SHALL 立即不再计入其 Space 与全局的已领并发（P1.8），worker SHALL 可
随即领取其他任务。人工 Decision SHALL 通过唯一存储层入口幂等唤醒原任务：
当且仅当任务当前处于 `awaiting_human` 时执行 `awaiting_human → queued`；
对同一任务的重复 Decision 提交 SHALL 返回 typed duplicate 且零行变更。
系统 SHALL NOT 为人工等待建立第二套工作流/任务系统；Decision 只作用于原
任务行，唤醒后的执行仍走同一状态机。

#### Scenario: 等待人工不占用并发额度

- **WHEN** 某 Space 并发上限为 C 且已满，其中一个任务进入 `awaiting_human`
- **THEN** 该 Space 已领并发立即减一，下一个 queued 任务可被 claim

#### Scenario: 重复 Decision 幂等

- **WHEN** 同一任务的人工 Decision 因重试被提交两次
- **THEN** 任务恰好被 requeue 一次；第二次提交返回 typed duplicate，任务
  最终仍只产生一份领域结果

### Requirement: P1.8 Space 绑定与配置化并发限额

`wiki_jobs` 与 `wiki_outbox_events` 的每一行 SHALL 携带 NOT NULL
`space_id`。enqueue、claim、heartbeat、状态转换、完成、Decision、outbox
读取与指标查询 SHALL 校验调用方声明的 Space scope 与目标行一致，不一致
SHALL fail closed：typed 拒绝、零行返回、零行变更。claim SHALL 执行
per-Space 与全局并发上限：某 Space 处于 `leased | running` 的任务数达到其
配置上限时，该 Space 的任务 SHALL NOT 被继续领取，其他 Space 不受影响；
全局上限同理。两类上限 SHALL 来自配置；任何具体数值 SHALL 只是环境默认值
而非产品上限，SHALL NOT 硬编码于领取逻辑。超限任务 SHALL 保持排队等待，
SHALL NOT 被拒绝、丢弃或无限创建执行协程。

#### Scenario: 跨 Space 操作 fail closed

- **WHEN** 以 Space A 的 scope 尝试 claim、读取、heartbeat 或完成 Space B
  的任务，或读取 Space B 的 outbox 行
- **THEN** 请求被 typed 拒绝或返回零行，Space B 的任何行零变更

#### Scenario: per-Space 限额只影响本 Space

- **WHEN** Space A 已达配置并发上限而 Space B 未达，两个 Space 均有 queued
  任务
- **THEN** claim 跳过 Space A 的任务并继续领取 Space B 的任务；Space A 的
  任务保持 queued，不丢失、不报错

#### Scenario: 限额只由配置决定

- **WHEN** 同一数据分别以 per-Space 上限 2 与 4 两组配置运行
- **THEN** 同时处于 `leased | running` 的任务数分别至多为 2 与 4，无代码
  变更即生效

### Requirement: P1.9 可观测性查询

存储层 SHALL 提供只读、确定性的指标查询接口，至少可返回：per-Space 与
全局的各状态任务计数（含 queued 队列深度与 dead_letter 计数）、最老
**可调度**任务年龄（覆盖 `state ∈ {queued, retry_wait}` 的行，以数据库
时钟按 `enqueued_at` 计算——停留在 `retry_wait` 的任务 SHALL 同样可见，
而不仅是最老 queued）、attempt 累计与当前 `retry_wait` 计数（失败率/
重试率 SHALL 可由这些计数在采样间隔内推导）。`wiki_jobs` 每行 SHALL
持久化 `enqueued_at`、最近一次 `started_at`（`leased → running`）与
`finished_at`（进入终态）时间戳，供时长类指标推导；编译/审核/发布时长与
投影延迟指标本身归消费方 PR（见 proposal 非目标）。指标查询 SHALL
遵守 P1.8 的 Space scope 规则；全局聚合 SHALL 是显式命名的独立入口。P1
SHALL NOT 建设独立 metrics 平台或引入第二存储。

#### Scenario: 指标与已知数据分布一致

- **WHEN** 测试预置已知分布（如 Space A：3 queued/1 running/1 retry_wait/
  2 dead_letter，Space B：1 queued），且最老的可调度行处于 `retry_wait`，
  随后执行指标查询
- **THEN** per-Space 与全局的各状态计数、队列深度、dead_letter 计数与最老
  可调度年龄与预置分布精确一致；最老可调度年龄由该 `retry_wait` 行决定，
  每行的 `enqueued_at/started_at/finished_at` 已持久化可查

### Requirement: P1.10 崩溃恢复与接管

worker 进程被强制终止（不执行任何清理）后，其持有的 lease SHALL 按数据库
时钟自然过期；过期任务 SHALL 可被任何存活实例回收并以严格更大的
generation 重新领取执行。接管 SHALL NOT 依赖崩溃 worker 的任何配合、进程
内锁或单一 reaper 实例——回收逻辑 SHALL 只依赖 PostgreSQL 持久状态，任何
实例都可执行。崩溃 worker 苏醒后的一切写入按 P1.3 被 fencing 拒绝；整个
崩溃-接管-重放过程 SHALL 恰好产生一份领域结果。

#### Scenario: 崩溃后接管且单一结果

- **WHEN** worker A 在 `running` 中被强制终止，lease 过期后 worker B 以
  generation g+1 接管并完成任务，随后 A 恢复并尝试提交其结果
- **THEN** 领域结果恰好是 B 提交的一份；A 的提交被 typed
  `stale_generation` 拒绝，outbox 中该任务的完成事件恰好一条

#### Scenario: 重复崩溃循环有界

- **WHEN** 配置 `max_attempts = 3`，同一（毒性）任务每次被领取进入
  `running` 后都使 worker 崩溃，lease 反复过期并被回收
- **THEN** 每次回收都记录 `lease_expired` 的 typed `retryable` 失败；
  attempt 达到 3 后回收把任务路由进 `dead_letter`（保留 attempt、错误分类
  与摘要），任务不会被无限次重新排队

### Requirement: P1.11 唯一迁移与表所有权

P1 实现 SHALL 恰好包含一个新 Alembic 迁移；该迁移 SHALL 只创建
`wiki_jobs` 与 `wiki_outbox_events` 两张表及其索引与约束，SHALL NOT
创建、修改或删除任何其他表或历史迁移文件。表名 SHALL 使用 `wiki_` 前缀，
与既有 harness 遗留表（product/knowledge/source/release/flywheel 域）明确
区分。迁移 revision 编号 SHALL 在实现 PR 开工时先在
`openspec/changes/README.md` 迁移台账占号，本规格 SHALL NOT 预占具体编号；
`down_revision` SHALL 指向合入时 `origin/main` 的真实 Alembic head（本
规格起草时观测为 `0006`，exact id 以执行时真实 head 为准），SHALL NOT
产生 multi-head，SHALL NOT 复用 superseded 的 `0013/0014`。

#### Scenario: 单迁移单所有权

- **WHEN** 审查 P1 实现 PR 的 diff
- **THEN** 恰好一个新迁移文件，其 upgrade 只创建
  `wiki_jobs`/`wiki_outbox_events` 及其索引/约束，历史迁移文件零修改

#### Scenario: 从真实 head 续接

- **WHEN** 在干净数据库对合入后的迁移链执行 `alembic upgrade head`
- **THEN** 迁移链无 multi-head，P1 迁移的 `down_revision` 等于其合入时
  `origin/main` 的真实 head，全链执行成功

### Requirement: P1.12 PostgreSQL 16 并发验收测试

P1 SHALL 按 033 §16.2 对其事务边界提供 PostgreSQL 16 并发/一致性测试，
至少覆盖四类场景：多 worker 并发单领（P1.2）、lease 过期接管（P1.3/
P1.10）、迟到（旧 generation）worker 写拒绝（P1.3）、完成事务 + outbox
原子性含崩溃/中断模拟（P1.6）。这些测试 SHALL 使用 `integration_postgres`
marker 并在 PG lane 对真实 PostgreSQL 16 执行；PG lane 的 JUnit 报告
SHALL 满足 `skipped=0`。默认 deterministic lane 缺少 PostgreSQL 时，这些
测试 SHALL 显式跳过并在 validation report 记为 NOT RUN；SHALL NOT 以
SQLite 或进程内模拟的结果冒充 PostgreSQL 并发证据。

#### Scenario: PG lane 全量执行

- **WHEN** 在 PostgreSQL 16 lane 运行全部 `integration_postgres` 测试
- **THEN** 四类并发场景全部执行且通过，JUnit 报告 `skipped=0`

#### Scenario: 无 PG 环境如实记录 NOT RUN

- **WHEN** 仅有 SQLite/无数据库环境运行测试
- **THEN** 并发合同测试不被标记为通过，validation report 将 PG lane 记为
  NOT RUN，PR 不得据此宣称并发验收完成
