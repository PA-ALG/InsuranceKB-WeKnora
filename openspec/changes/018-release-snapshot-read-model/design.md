# 018 增量设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §5～6。

## 裁决摘要

018 延续“库级 ReleaseSnapshot”而不是引入产品级指针。现有
`ReleasePublisher.publish_product_version(...)` 保留“以单个产品版本触发”的兼容语义，
但每次发布都从该 Space 当前全部可发布事实构建一个**完整 Space 快照**；旧的
caller-Session 模块函数不再从生产包公开。这样连续发布产品 A、B 后，
current snapshot 同时包含 A、B；不会因单产品入口导致其他产品从在线读模型消失。

否决的两个方案：

- 从上一个快照 copy-forward 再替换目标产品：会继承历史坏数据，并使删除、Evidence
  失效和首次 018 接管的语义复杂化；
- 把 CurrentRelease 改为产品级：偏离现有库级发布/回滚语义，且扩大 013/014 接口面。

## SnapshotFact 与迁移

`SnapshotFact` 使用可索引列保存 `space_id/snapshot_id/claim_id/revision_no`、
产品与产品版本 ID、产品 code/name/version label、predicate、发布时 field name/group、value state/value、
effective dates、confidence 和 schema version；Evidence 使用 JSON 冻结 017 的完整
来源审计字段及展示字段。`SnapshotClaim` 保留用于兼容审计，但在线 Reader、Wiki
回放均不依赖 mutable Claim/Evidence/Product 表。

发布构建器读取该 Space 全部 `published`、非 `unknown`、具备当前 ClaimRevision 且
Evidence lineage 完整并未 stale 的产品事实，先复制 SnapshotFact，再只从这些事实生成
rendered pages。任一参与发布的 Evidence 为 placeholder、legacy-null-lineage 或 stale 时，
发布在任何 Wiki I/O 前失败。

候选集合先确定为该 Space 全部 `Claim.status=published`、`product_version_id IS NOT NULL`、
`value_state != unknown` 的 Claim；再对整个集合验证 revision/Evidence。验证失败导致整个
release 失败，不得静默丢弃坏事实。concept/QA 和 unknown 不属于 018 产品事实投影，也不
阻断发布。零候选事实的完整 Space 快照合法，用于撤销最后一条在线事实并计划删除旧
managed pages；Reader 对这种 current 返回 `product_not_found`。

`0005` 将既有 ReleaseSnapshot 标记为 `published` 且 `read_model_version=0`，保留原指针
和 Wiki 连续性；不使用当前 mutable Claim 伪造历史 SnapshotFact。Reader 遇到这种
legacy current 返回 `coverage_gap=legacy_release`。首次 018 完整重发布使用
`read_model_version=1` 后恢复正常。

legacy snapshot 只保留审计与首次接管/补偿能力，不是 018 rollback target；首次 version-1
发布后不得回滚到 version-0，以免 Wiki 回到旧页面而 Reader 只能返回 legacy gap。

Snapshot 带 `projection_frozen_at`，ReleaseOperation 带 `plan_frozen_at`。building 事务先
以空 marker 插入 snapshot/operation，再插入完整 facts/pages/plan，最后在同一事务设置
两个 marker 并 commit。marker 设置后禁止新增、更新或删除 SnapshotFact，禁止改变
rendered_pages 和 PublishPlan；published snapshot 也不得修改 rendered_pages。`0005`
可原样保留既有 version-0 pointer，但 migration 完成后的 CurrentRelease INSERT/UPDATE
只能指向同 Space 的 published、read_model_version=1 snapshot。上述边界同时由服务层和 SQLite/PostgreSQL
数据库 trigger/constraint 验证，而非仅依赖 Python 约定。

## 稳定 Reader

`SnapshotReader.current(scope)` 先校验数据库加载的 KnowledgeScope，再只沿
CurrentRelease → published ReleaseSnapshot → SnapshotFact 查询。过滤器使用稳定 ID
（product_id/product_version_id）并可叠加 predicate/effective_on；结果携带 snapshot_id、
冻结值和完整 Evidence。effective_from/effective_to 均为包含边界；多个有效区间同时命中
时按 `(product_id, product_version_id, predicate, effective_from-or-date.min,
effective_to-or-date.max, claim_id, revision_no)` 返回全部结果，不静默挑选“赢家”。NULL
effective_from 表示负无穷，NULL effective_to 表示正无穷。

typed gap 固定为：

- `no_release`：该 Space 没有 current；
- `legacy_release`：current 是迁移保留、无可信事实投影的旧快照；
- `product_not_found`：给定产品或产品版本不在 current；
- `predicate_not_found`：产品存在但字段不存在；
- `effective_date_miss`：字段存在但指定日期没有命中。

scope 不一致直接 `ScopeViolation`，不包装为 coverage gap，也不跨 Space 猜测。
当查询显式提供 product_id/product_version_id 时，Reader 可对 InsuranceProduct/ProductVersion
执行只返回 ID 的同 Space ownership guard：ID 不属于该 Space（包括不存在）时统一
ScopeViolation；ID 合法但 current snapshot 不含对应事实时返回 product_not_found。该 guard
不得读取可变名称/值/Evidence，在线答案内容仍只来自 SnapshotFact。

过滤与 gap 采用固定顺序：先 scope/current/read_model 校验；随后依次应用 product_id/
product_version_id、predicate、effective_on。某一步把候选降为零，就返回该步对应的
`product_not_found`、`predicate_not_found` 或 `effective_date_miss`；无过滤且 current
为合法零事实快照时返回 `product_not_found`。因此复合查询只产生第一个失败阶段的 gap。

## 外部一致性

PostgreSQL 与 WeKnora HTTP 无法组成原子事务，因此定义明确的 saga：

1. `ReleasePublisher` 由应用注入 SessionFactory 和 Wiki client；每个 DB 阶段只使用服务
   自建 Session，public publish/rollback/retry/reconcile API 不接收调用方 Session，因而
   不可能提交调用方已 flush 或未 flush 的业务事务；
2. DB 创建 snapshot、facts、pages、ReleaseOperation 和完整 PublishPlan，提交为
   building；plan 包含 base current、目标 upsert、应删除的旧 managed slug 及补偿；
3. 标记 publishing，逐项执行 ownership preflight、幂等 upsert/delete、写后回读验证，
   每项持久化 PublishAttempt；
4. 全成功且 base current 未变化后，单 DB 事务标记 published/succeeded 并移动 pointer；
5. 失败则 snapshot/operation=failed、pointer 不动，并产生 ReconciliationJob；显式 retry
   仅在 base current 未变化时复用同 snapshot/plan，否则先 reconcile 后重新构建 release；
6. reconciliation 加载**执行时**的 current，重放其全部页面，并删除失败 plan 触及但
   current 不拥有的 Harness managed slug。

ReleaseOperation 为 publish/rollback/reconcile 提供独立 saga identity。正常发布的 snapshot
有 lifecycle status；rollback 不改变目标 published snapshot 的状态，而在独立 operation
上记录 building/running/succeeded/failed。PublishAttempt 以
`operation_id + retry_no + action_no` 唯一，operation 为 upsert/delete，status 为
started/succeeded/failed/collision；`created_new` 为 nullable bool，以表达 POST 已发送但
响应丢失时的 unknown。

PublishPlan 只属于一个 ReleaseOperation。publish operation 的 target 是新 snapshot；
rollback operation 的 target 是既有 version-1 snapshot。显式 retry 复用同一个 failed
operation、plan 和 snapshot，仅递增 retry_no；不创建 child operation。ReconciliationJob
通过 `source_operation_id` 指向失败 operation，并保存 source plan digest；执行 job 时创建
一个 `kind=reconcile`、`parent_operation_id=source_operation_id` 的 operation，冻结执行时
current 的恢复计划，job 再记录 `reconcile_operation_id`。operation 合法迁移为
building→running→succeeded/failed、failed→running（同 plan retry）；job 为
pending→running→succeeded/failed、failed→pending（显式 requeue）。reconcile 失败后，
若执行时 current 未变化，则复用同一 child operation/plan 并递增 retry_no；若 current 已
变化，则在同一 job 下创建带 `previous_operation_id` 的 successor reconcile operation，
重新冻结最新 current 恢复计划，保留旧 child/attempt 历史。

ReleaseOperation 具有 `lease_expires_at` 和 heartbeat。building commit 同时写入初始 lease；
进入外部 I/O 前必须先持久化 running + 新 lease，每项 attempt started/succeeded/failed
与 heartbeat 分阶段提交。显式 recovery 在 Space 锁内扫描过期 building/running operation
或 started attempt。过期 building 因协议保证零 Wiki I/O，可将 operation（及新 snapshot）
标 failed 而不创建 reconciliation job，并在 base current 未变时复用原 plan retry；过期
running 则将原 operation（及正常发布 snapshot）标 failed 并创建/复用唯一
ReconciliationJob。若全部 Wiki 写成功但最终 DB commit 失败，
服务用新 Session 执行同一 recovery；若进程终止或 DB 暂时不可用，lease 到期后恢复器完成
相同行为。最终 published/pointer/operation succeeded 在一个 DB 事务内提交，因此该事务
成功时无需补偿，失败时 current 仍旧且 durable pre-I/O operation 可被发现。

ReconciliationJob 只表达“远端可能已偏离 current，需要恢复”的事实，而不是所有失败的
通用审计附件。ownership preflight 发现第三方 collision 时，只有检查同一 operation 的全部
retry/attempt 历史后仍能证明从未发生 succeeded、started/结果 unknown mutation，才只持久化
collision attempt 和 failed operation/snapshot 而不创建工单；只要 operation 生命周期内已有
任一可能 mutation 的历史，就仍必须创建工单。rollback operation 因 lease 过期从
running/started 恢复为 failed 时，
对应 ChangeSet 必须与进程内 action 失败保持同一审计语义，统一记为 `partially_applied`，不得
遗留为 `pending`。

Publisher 只管理 metadata 同时包含
`managed_by=insurance-harness`、`space_id`、`snapshot_id` 的 slug；同名非 Harness 页面
在覆盖前触发 collision。首次 018 接管时，只允许收养“slug 在 current legacy snapshot
rendered_pages 中，且远端 metadata.snapshot_id 与该 current 一致”的旧 Harness 页面。
补偿因此无需保存或恢复第三方任意内容。DELETE 遇到 404 视为幂等成功。

这保证 Harness/MCP 真相不前移；WeKnora 短暂半发布通过补偿恢复，不把分布式非原子性伪装成强事务。

发布、回滚、retry 和 reconcile 共享按 `(Engine, space_id)` 的进程内异步锁；不同 Space
可并行。018 明确不宣称多实例互斥，生产多实例锁由 014 PostgreSQL advisory lock 替换。

018 的 pointer-last 规则取代 022 RH1 的函数内部 pointer-before-I/O 顺序；继续保留 RH1
的外部可观察保证：DB preflight/flush 失败时零 Wiki 写，Wiki 失败时 current 和 rollback
审计都不能表现为成功。022 明示留给 018 的 outer commit、进程终止和多页补偿由上述
durable saga 接管。

## Reader 与回退

SnapshotReader 是稳定接口，013 只做协议包装。T6 只实现协议与 policy，不在 018 新建
搜索引擎：调用方提供同 Scope 的 RawFallbackProvider。policy 只有在 Reader 返回 typed
gap 时才调用 provider，并校验每个结果的 `space_id/raw_kb_id` 与 scope 完全一致；输出
统一标记 `unreviewed_raw`。Reader 已返回任何 SnapshotFact 时，RAW 结果不得替换、合并
成同权答案或写回 SnapshotFact。

## 验证策略

- migration：`0004→0005` legacy upgrade、DB immutability、downgrade、PostgreSQL offline DDL；
- Reader：五类 gap、包含式有效期、重叠事实、跨 Space fail-closed；
- renderer：修改/撤回 mutable Claim/Evidence/Product 后，页面仍由 frozen facts 生成；
- saga：多页第二页失败、首动作/后续 collision、response loss、final DB failure、
  same-plan retry，以及 base current 已变化时零副作用拒绝旧 plan；
- rollback/reconcile：V1→V2→rollback V1，新增 slug 与历史非 current managed slug 清理；
- scope：两个 Space 相同 label/slug 隔离，同 Space 串行、跨 Space 可并行；
- schema：deterministic `kb_session` 显式启用 SQLite foreign key，并用复合 FK 失败证明约束
  实际生效；current pointer guard 必须构造真实跨 Space target；
- production boundary：007 legacy characterization support 对三个退休 helper 自包含；已由
  018 淘汰的旧发布 helper 不得继续由 production module 暴露或仅靠测试 import 存活；
- migration/live：`0005` 合约测试固定升级到 `0005`，current-head smoke 才使用 `head`；018
  PostgreSQL/live helper 的随机 schema `search_path` 仅包含该 schema，不得回退 `public`；
- gates：OpenSpec strict、Ruff、mypy strict、deterministic pytest；真实 PostgreSQL 与
  WeKnora 证据分别报告，skip/NOT RUN 不得宣称 live verified。
