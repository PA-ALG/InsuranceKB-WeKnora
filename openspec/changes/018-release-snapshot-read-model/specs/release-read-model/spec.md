# 018 ReleaseSnapshot 统一读模型验收规格

## ADDED Requirements

### Requirement: R1.1 SnapshotFact 必须冻结完整在线事实

SnapshotFact SHALL 包含 space/snapshot/claim/revision、product/product version ID 与展示身份、predicate、发布时 field name/group、value state/value、有效期、confidence、schema version 与完整 017 Evidence JSON。

#### Scenario: 构建完整 Space 快照

- **WHEN** 一个 Space 中多个产品版本具有可发布事实
- **THEN** 新 snapshot 为每个 published、非 unknown Claim 生成 SnapshotFact
- **AND** 每条事实冻结产品 code/name/version label、field name/group 及 Evidence 来源审计与展示字段

### Requirement: R1.2 事实、计划与发布页面必须不可变

SnapshotFact 插入后及 building 事务提交后的 PublishPlan/页面 SHALL 不可修改；published snapshot 的 rendered_pages SHALL 不可修改，数据库与服务层均 SHALL 拒绝越界 UPDATE/DELETE。

#### Scenario: 绕过服务直接修改冻结数据

- **WHEN** 调用方直接 UPDATE/DELETE SnapshotFact 或修改已冻结 plan/published rendered_pages
- **THEN** SQLite 与 PostgreSQL 数据库边界拒绝写入
- **AND** 服务层不暴露等价修改路径

#### Scenario: building 事务提交后追加投影成员

- **WHEN** snapshot.projection_frozen_at 与 operation.plan_frozen_at 已在 building 事务内设置并提交
- **AND** 调用方尝试 INSERT 新 SnapshotFact 或向 frozen pages/plan 追加 action
- **THEN** SQLite 与 PostgreSQL 数据库边界拒绝写入
- **AND** 原事实、页面和 plan digest 保持不变

### Requirement: R1.3 快照不得依赖后续可变实体

同一 snapshot/claim/revision SHALL 唯一；Evidence、产品展示内容和值 SHALL 与发布时一致，不受后续 enrich/retract/rename 影响。新发布 SHALL 拒绝 placeholder、legacy-null-lineage 与 stale Evidence。

#### Scenario: 发布后修改来源事实和产品名称

- **WHEN** snapshot 发布后 Claim/Evidence/Product 被 enrich、retract 或 rename
- **THEN** SnapshotFact、Reader 结果和回放页面仍返回发布时内容

#### Scenario: 待发布事实含不完整或 stale Evidence

- **WHEN** 完整 Space 投影中任一参与事实的 Evidence 缺少 017 lineage 或 stale_at 非空
- **THEN** 发布在任何 Wiki mutation 前失败

### Requirement: R1.4 旧快照迁移不得伪造历史事实

`0005` SHALL 将既有快照保留为 `published/read_model_version=0`，不得从当前 mutable Claim 回填历史 SnapshotFact；原 CurrentRelease SHALL 保留。

#### Scenario: 0004 数据库带 current snapshot 升级

- **WHEN** 含旧 ReleaseSnapshot 和 CurrentRelease 的数据库升级到 0005
- **THEN** 原 snapshot/pointer 仍可审计且旧 snapshot 标为 read_model_version 0
- **AND** Reader 返回 `coverage_gap=legacy_release`，直至首次 018 完整重发布

#### Scenario: version-1 发布后尝试回滚 legacy snapshot

- **WHEN** current 已是 read_model_version 1 且目标 snapshot 为 version 0
- **THEN** rollback 在 Wiki mutation 前拒绝目标

#### Scenario: 0005 安全降级与 PostgreSQL DDL

- **WHEN** 数据库仅含迁移继承的 version-0 rows
- **THEN** 0005→0004 downgrade 保留旧 snapshot/pointer 并移除 018 表、列和 trigger
- **AND** PostgreSQL offline DDL 包含等价约束与 trigger
- **WHEN** 已存在 version-1 snapshot/fact/operation/attempt/job
- **THEN** downgrade fail closed，不静默丢弃 018 数据

### Requirement: R2.1 Reader 必须只沿当前已发布快照读取

`SnapshotReader.current(scope)` SHALL 校验数据库加载的 KnowledgeScope，并只沿该 Space 的 CurrentRelease 读取 published SnapshotFact。除 `0005` 原样保留的既有 version-0 pointer 外，migration 完成后的 CurrentRelease INSERT/UPDATE SHALL 只能指向同 Space 的 published、read_model_version=1 snapshot。

#### Scenario: 两个 Space 各有 current

- **WHEN** 使用 Space A 的 attested scope 调用 Reader
- **THEN** 只返回 A 的 current snapshot facts
- **AND** 不读取 A/B 的 mutable published Claims 或 Space B 的 snapshot

#### Scenario: 数据库直接把 pointer 指向不可用 snapshot

- **WHEN** 调用方直接令 CurrentRelease 指向跨 Space、非 published 或 read_model_version 0 snapshot
- **THEN** 数据库约束或 trigger 拒绝写入

### Requirement: R2.2 Reader 过滤必须确定且可追溯

Reader SHALL 支持按 product_id/product_version_id/predicate/effective_on 组合查询并返回 snapshot_id 与完整 Evidence；effective_from/effective_to SHALL 均为包含边界，NULL 起点/终点 SHALL 分别表示负/正无穷。重叠命中 SHALL 全部按 `(product_id, product_version_id, predicate, effective_from-or-date.min, effective_to-or-date.max, claim_id, revision_no)` 排序。

#### Scenario: 日期命中首尾边界与重叠区间

- **WHEN** effective_on 等于区间首日、末日或同时命中两个事实
- **THEN** 首尾事实均视为有效
- **AND** 重叠事实全部按稳定键返回，不静默选择单一赢家

### Requirement: R2.3 Wiki 与未来 MCP 必须复用快照读模型

Wiki renderer SHALL 只从 SnapshotFact 构建页面；013 MCP 后续 SHALL 复用 SnapshotReader，不得直接查询 `Claim.status=published` 作为在线答案。

#### Scenario: mutable Claim 与 current snapshot 不同

- **WHEN** current snapshot 发布后 mutable Claim 已发生变化
- **THEN** Wiki renderer 仍生成 current snapshot 的值、Evidence 和 snapshot metadata

### Requirement: R2.4 Reader 必须返回固定 typed gap 并 fail closed

gap code SHALL 固定为 `no_release/legacy_release/product_not_found/predicate_not_found/effective_date_miss`；scope 不一致 SHALL 抛 ScopeViolation，不得包装为 gap 或跨 scope 回退。

#### Scenario: 依次查询无发布、无产品、无字段和日期未命中

- **WHEN** 查询分别缺少 current、使用 legacy current、缺少产品版本、缺少 predicate 或日期未命中
- **THEN** Reader 返回对应固定 gap code 和 current snapshot_id（如存在）

#### Scenario: 复合过滤的 gap 优先级

- **WHEN** scope/current/read_model 校验通过并依次应用 product/product_version、predicate、effective_on
- **THEN** 第一个把候选集合降为零的阶段分别返回 product_not_found、predicate_not_found 或 effective_date_miss
- **AND** 合法零事实 current 的无过滤查询返回 product_not_found

#### Scenario: scope provenance 或实体 scope 不一致

- **WHEN** scope 非数据库 attested、来自不同 Engine 或查询实体属于另一 Space
- **THEN** Reader 抛出不泄漏数据的 ScopeViolation
- **AND** 不调用任何 RAW fallback

### Requirement: R3.1 发布状态机必须冻结计划并保护 base current

snapshot SHALL 只允许 building→publishing→published 或 failed；failed 仅在 base current 未变化时由显式 retry 使用同一冻结 PublishPlan 回到 publishing；只有 published 可成为 current。

#### Scenario: failed snapshot 在相同 base 上重试

- **WHEN** 外部写失败且 CurrentRelease 仍等于 plan 的 base current
- **THEN** retry 复用相同 snapshot_id 和 PublishPlan
- **AND** 不创建新业务快照

#### Scenario: failed plan 之后 current 已变化

- **WHEN** retry 时 CurrentRelease 不再等于 plan 的 base current
- **THEN** 系统拒绝执行旧 plan
- **AND** 要求 reconcile 后重新构建 release

#### Scenario: 进程终止留下过期 running operation

- **WHEN** operation 为 running 或 attempt 为 started 且 lease_expires_at 已过期
- **THEN** recovery 在 Space 锁内把 source operation 与正常发布 snapshot 标为 failed
- **AND** 创建或复用唯一 ReconciliationJob，current 保持不变

#### Scenario: building plan 提交后、running 前进程终止

- **WHEN** frozen building operation 的初始 lease 已过期且没有 running/started attempt
- **THEN** recovery 将 operation 与正常发布 snapshot 标为 failed，current 保持不变
- **AND** 因协议保证 running commit 前零 Wiki mutation，不创建 reconciliation 工单
- **AND** base current 未变化时可复用同 operation/plan retry

### Requirement: R3.2 单产品入口必须生成完整 Space 发布

兼容的单产品发布入口 SHALL 构建该 Space 全部可发布产品事实与页面；系统 SHALL 先提交 SnapshotFact/页面/计划，再执行 WeKnora，全部成功且 base current 未变化后才在 DB 事务内移动该 Space 指针。

#### Scenario: 先发布产品 A 再以产品 B 发起发布

- **WHEN** 产品 A、B 均有可发布事实且第二次调用入口参数为 B
- **THEN** 第二个 snapshot 与 Wiki 目标投影同时包含 A、B
- **AND** 指针只在全部页面成功后移动

#### Scenario: 完整候选集合含坏 Evidence

- **WHEN** 候选集合先选出该 Space 全部 published、product_version 非空、非 unknown Claims
- **AND** 任一候选缺少 current revision 或含 legacy-null/stale Evidence
- **THEN** 整个 release 在 Wiki mutation 前失败，不得静默漏掉该候选

#### Scenario: 撤销最后一条在线事实

- **WHEN** Space 中已无 published、product_version 非空、非 unknown Claim
- **THEN** 可发布合法零事实 snapshot，并计划删除旧 current 的 managed pages
- **AND** 成功后 Reader 对无过滤查询返回 product_not_found

### Requirement: R3.3 每次 saga 必须有冻结 operation 与 attempt

发布前 SHALL 冻结包含 base current、目标 upsert、旧 managed slug delete 和补偿动作的 PublishPlan；每个 plan SHALL 只属于一个 ReleaseOperation。publish/rollback/reconcile SHALL 各有独立 ReleaseOperation，每个动作 SHALL 形成 PublishAttempt，键为 operation_id/retry_no/action_no，并记录 operation/status/error/snapshot/slug/nullable created_new。

#### Scenario: 第二页 POST 响应丢失

- **WHEN** 第一页成功而第二页请求可能已创建远端页但客户端未收到响应
- **THEN** attempt 持久化失败与 `created_new=null`
- **AND** frozen plan 足以支持 retry 或 reconciliation

#### Scenario: failed operation retry 与 reconcile identity

- **WHEN** publish 或 rollback operation 失败后在相同 base 上 retry
- **THEN** 复用同一 operation/plan 并递增 retry_no
- **WHEN** ReconciliationJob 执行
- **THEN** job 通过 source_operation_id/source plan digest 指向失败来源
- **AND** 新 reconcile operation 通过 parent_operation_id 回链来源，job 记录 reconcile_operation_id

#### Scenario: failed reconciliation 显式 requeue

- **WHEN** reconcile child operation 失败且执行时 current 未变化
- **THEN** job 从 failed 显式 requeue，并复用同一 child/plan、递增 retry_no
- **WHEN** reconcile child 失败后 current 已变化
- **THEN** 同一 job 创建带 previous_operation_id 的 successor child，冻结最新 current 恢复计划
- **AND** 原 child 与 attempts 保持可审计

### Requirement: R3.4 外部失败不得前移真相指针

任一外部写入失败时 CurrentRelease SHALL 不移动，operation 及正常发布的新 snapshot SHALL 记为 failed，并 SHALL 产生以 source_operation_id 唯一的 ReconciliationJob；rollback target snapshot SHALL 保持 published。非 Harness 管理的同 slug 页面 SHALL 在覆盖前触发 collision。

#### Scenario: 多页发布第二页失败

- **WHEN** 第一个页面已成功而第二个页面 mutation 失败
- **THEN** current 仍指向旧 published snapshot
- **AND** failed snapshot、attempt 和 pending reconciliation 工单均可持久查询

#### Scenario: 目标 slug 属于第三方页面

- **WHEN** ownership preflight 发现同 slug 页面没有合法 Harness scope metadata
- **THEN** operation 以 collision 失败
- **AND** 该页面从未被更新或删除

#### Scenario: Wiki 写完但最终 DB commit 失败

- **WHEN** 全部外部 action 成功但 published/pointer/succeeded 原子事务 commit 失败
- **THEN** current 仍保持 base snapshot
- **AND** 新 Session recovery 或过期 lease 将 durable running operation 转为 failed 并创建 reconciliation 工单

### Requirement: R3.5 Wiki 请求必须绑定 Scope 并写后验证

Publisher SHALL 只使用 `scope.wiki_kb_id`，调用方不得另传 kb_id；每次 upsert SHALL 写后回读验证目标 snapshot metadata。

#### Scenario: 两个 Space 使用相同 slug

- **WHEN** Space A/B 的发布计划含相同 slug
- **THEN** 每次 REST 请求分别使用各自 scope.wiki_kb_id
- **AND** 回读 metadata 的 space_id/snapshot_id 必须匹配计划

### Requirement: R3.6 saga 服务必须拥有独立 Session

ReleasePublisher SHALL 由应用注入 SessionFactory，并为每个 DB 阶段创建、提交和关闭自己的 Session；public publish/rollback/retry/reconcile API SHALL NOT 接收调用方 Session，因此不得提交调用方已 flush 或未 flush 的业务事务。

#### Scenario: 调用方另有已 flush 未提交事务

- **WHEN** 调用方 Session 已 flush 业务写入但尚未 commit，并另行调用 ReleasePublisher
- **THEN** 无论 saga 成功或因数据库并发隔离失败，都不得 commit 调用方事务
- **AND** 调用方 rollback 后其业务写入不存在；PostgreSQL integration 证明成功 saga 只提交 service-owned Session 的 release 状态

### Requirement: R4.1 回滚必须使用独立 operation 且 pointer-last

回滚 SHALL 只允许该 Space 的 published snapshot；系统 SHALL 冻结 base current 和目标计划，先重放目标页面，成功且 base current 未变化后移动指针，不得改变目标 snapshot 的 published 状态。

#### Scenario: 从 V2 回滚 V1

- **WHEN** V1/V2 均为同 Space 的 published snapshot 且 current=V2
- **THEN** rollback operation 重放 V1 页面后才把 current 切到 V1
- **AND** V1/V2 状态均保持 published

- **WHEN** rollback 目标是 read_model_version 0 legacy snapshot
- **THEN** 在 Wiki mutation 前拒绝目标

### Requirement: R4.2 回滚失败不得留下成功状态

回滚任一 Wiki action 失败时 CurrentRelease SHALL 保持原值，系统 SHALL 持久化 failed operation、attempt 和 reconciliation 工单，不得留下成功 rollback audit。

#### Scenario: 回滚第二页失败

- **WHEN** 回滚已重放第一页但第二页失败
- **THEN** current 仍指向回滚前 snapshot
- **AND** operation/audit 不得显示 succeeded/applied

### Requirement: R4.3 Reconciliation 必须恢复执行时 current 的精确投影

Reconciliation SHALL 在取得 Space 锁后重新读取执行时 current：幂等重放 current 拥有的全部 slug，并删除失败 plan 触及但 current 不拥有的全部 Harness managed slug；DELETE 404 SHALL 视为成功。

#### Scenario: 失败计划新增 slug 并覆盖历史非 current managed slug

- **WHEN** failed plan 触及一个 current 不拥有的新 slug 和一个历史 managed slug
- **THEN** reconciliation 重放 current 全部页面
- **AND** 删除两个非 current slug，重复执行结果不变

#### Scenario: 首次 018 发布收养 legacy 页后失败

- **WHEN** current 是 version-0 legacy snapshot，publisher 合法收养其旧页后在后续 action 失败
- **THEN** reconciliation 可从 legacy rendered_pages 精确重放旧 current 页面
- **AND** 不因此允许覆盖任一不满足 legacy 双重匹配的第三方页面

### Requirement: R4.4 页面 ownership 与 legacy 收养必须严格

新 managed page metadata SHALL 同时包含 `managed_by=insurance-harness`、space_id 和 snapshot_id。Legacy 页面只在 slug 属于 current legacy rendered_pages 且远端 snapshot_id 与 current 一致时 SHALL 允许收养。

#### Scenario: 首次 018 发布遇到旧 Harness 页面

- **WHEN** 远端旧页没有新 managed_by/space_id，但其 slug 与 snapshot_id 同时匹配 current legacy snapshot
- **THEN** publisher 可将其更新为新 metadata
- **AND** 任一不匹配旧页仍按第三方 collision 处理

### Requirement: R4.5 Space 操作必须局部串行

发布、回滚、retry 和 reconcile SHALL 按 `(Engine, space_id)` 进程内串行，不同 Space SHALL 可并行。018 SHALL NOT 宣称多实例互斥；014 将以 PostgreSQL advisory lock 替换此边界。

#### Scenario: 同 Space 与跨 Space 并发

- **WHEN** 两个同 Space operation 和一个另一 Space operation 同时启动
- **THEN** 同 Space operation 不得交错执行 Wiki plan
- **AND** 另一 Space operation 不被该局部锁阻塞

### Requirement: R5.1 RAW fallback 只能由 typed gap 触发

SnapshotReader SHALL 只在无匹配事实或无可信 release 时返回 R2.4 typed gap；RAW fallback policy SHALL 只消费这些 gap。

#### Scenario: Reader 已返回 SnapshotFact

- **WHEN** curated 查询存在一个或多个 facts
- **THEN** fallback provider 调用次数为零

### Requirement: R5.2 RAW fallback 必须限定同一 Scope 并标记未审核

RAW fallback SHALL 验证每个结果的 space_id/raw_kb_id 与 scope 完全一致，并 SHALL 标记 `unreviewed_raw`；不得写回或覆盖 SnapshotFact。

#### Scenario: provider 返回跨 Scope 命中

- **WHEN** typed gap 触发 provider 但任一结果的 space_id 或 raw_kb_id 不匹配
- **THEN** policy 抛 ScopeViolation 且不返回部分结果
- **AND** 数据库没有 SnapshotFact mutation

### Requirement: R5.3 RAW 冲突文本不得替代 curated 答案

已存在 SnapshotFact 时，系统 SHALL 禁止以 RAW 冲突文本替换或合并成同权答案。

#### Scenario: RAW 文本与 curated fact 冲突

- **WHEN** curated facts 已存在且 provider 可返回不同值
- **THEN** 结果只保留 curated facts
- **AND** RAW provider 不被调用

### Requirement: R6.1 完整 Space 两快照回滚必须端到端一致

验收 SHALL 覆盖完整 Space 的 V1→V2→rollback V1，并同时验证 Reader、Evidence、产品 A/B 完整性与 Wiki metadata.snapshot_id。

#### Scenario: 两产品两快照后回滚

- **WHEN** Space 中产品 A/B 发布 V1、变更事实后发布 V2，再回滚 V1
- **THEN** Reader 返回 V1 的值与 Evidence 且 A/B 均存在
- **AND** 全部 Wiki managed page metadata.snapshot_id 均为 V1

### Requirement: R6.2 部分发布与补偿必须可恢复

验收 SHALL 覆盖多页第二页失败、same-plan retry、失败新增 slug 和覆盖历史非 current managed slug，并证明 current 不动且 reconciliation 精确恢复。

#### Scenario: 第二页失败后先补偿再重试

- **WHEN** 多页 publish 的第二页失败
- **THEN** reconciliation 可重复恢复 current 精确投影
- **AND** base current 未变化时相同 snapshot/plan 可重试成功

### Requirement: R6.3 双 Space 相同 label 与 slug 必须隔离

验收 SHALL 证明两个 Space 使用相同 label/slug 时，快照、pointer、attempt、job 与 Wiki 请求互不影响。

#### Scenario: 双 Space 同名发布及回滚

- **WHEN** A/B 分别发布相同 label/slug 并只回滚 A
- **THEN** A 的状态按计划变化
- **AND** B 的 current、页面、attempt 与 job 均不变化

### Requirement: R6.4 软件、PostgreSQL 与 WeKnora 门禁必须分层

OpenSpec strict、Ruff、mypy strict、非 live/非 integration_postgres pytest SHALL 全绿；PostgreSQL integration 与真实 Wiki live SHALL 独立报告，live SHALL 验证真实 upsert/rollback，skip/NOT RUN 不得描述为成功。

PostgreSQL integration SHALL 将每次运行的对象和数据限制在本次随机 schema；测试连接的 `search_path` SHALL NOT 回退到 `public`，否则已迁移的公共表会造成伪隔离、跨运行污染和假绿。测试结束 SHALL 只清理其拥有的随机 schema。

#### Scenario: PostgreSQL 随机 schema 不回退公共表

- **WHEN** PostgreSQL lane 为 017/018 集成节点创建本次运行的随机 schema
- **THEN** 建表、约束、触发器与业务数据均位于该随机 schema
- **AND** 测试连接的 `search_path` 不包含 `public`
- **AND** 失败或成功后的清理均只删除本次随机 schema

#### Scenario: deterministic 通过但没有受控 live run

- **WHEN** 本地 deterministic 门禁通过但没有 protected WeKnora workflow 的零 skip 证据
- **THEN** change 可报告 software complete
- **AND** live 状态仍必须为 NOT RUN
