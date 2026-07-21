# 021 Source Lifecycle Ordering 验收规格

## ADDED Requirements

### Requirement: L1 可排序 identity 必须规范化且 fail closed

生产 source-aware identity SHALL 携带一个显式判别的 ordering：timezone-aware
`processed_at` 或来源服务端签发的严格单调 `generation`。`processed_at` SHALL 按实际 instant
归一为 UTC canonical value 后比较；naive datetime、无法解析的 offset SHALL 被拒绝。
`generation` SHALL 为非负 integer，bool、float、字符串数字 SHALL 被拒绝。ordering SHALL
从 WeKnora metadata/`SourceRevision` 无损贯穿 source revision canonical input、
`SourceImportIdentity`、manifest、import context、`SourceHead` 与 `SourceEvent`；系统 SHALL NOT
按 SHA-256 revision 的字典序或提交时间推断新旧。

同一 `(space_id, knowledge_id)` 的 ordering kind SHALL 固定；kind 混用、identity/scope/ordering
缺失或矛盾、相同 revision 携带不同 ordering，或相同 ordering 携带不同 revision，均 SHALL
在任何 lifecycle 业务写入前 fail closed。测试名 SHALL 以 `test_l1_` 开头并引用本条款。

#### Scenario: processed_at 跨时区归一为同一 instant

- **WHEN** 同一 source revision 分别携带等价的 `+08:00` 与 `Z` timezone-aware processed_at
- **THEN** 两者生成相同 UTC ordering canonical value 与相同 revision canonical input
- **AND** manifest、import identity、head/event 中的 ordering 可逐层复核

#### Scenario: generation 类型不严格或 ordering 碰撞

- **WHEN** generation 是 bool/float/string，或相同 ordering 对应不同 revision
- **THEN** source-aware 入口在 SourceHead、SourceEvent、Evidence、ChangeSet 写入前 fail closed
- **AND** 不得降级按 revision hash 或 legacy 路径裁决

### Requirement: L2 SourceHead 与 SourceEvent 必须 durable、唯一且支持首次并发创建

每个 `(space_id, knowledge_id)` SHALL 最多存在一个 durable `SourceHead`，并以复合约束闭合
其 `tenant_id`、`raw_kb_id` 与 KnowledgeSpace 归属。head SHALL 保存当前 revision、归一化
ordering kind/value、`active|deleted` state、CAS version、最后 event 与审计 actor/time。
每个 identity/scope 已通过 L1/L4 校验并进入 ordering 裁决的 notify/import/delete/reactivate
（包括 accepted、idempotent 与 stale）SHALL 形成 append-only `SourceEvent`，保存归一化输入、decision、before/after head、
causation/actor 及可空 ChangeSet 关联；event SHALL 足以按 source 顺序重建 head。

已有 head SHALL 在 PostgreSQL per-source transaction-scoped lock 下读取并以 version CAS 更新。
首次 head 不存在时也 SHALL 使用同一 source key 的稳定锁，或等价的唯一插入 + nested
savepoint/CAS 协议串行化创建；并发唯一冲突 loser SHALL 重读 winner 并重新裁决，SHALL NOT
泄漏随机 IntegrityError、遗留失败事务或创建两个 head/event business outcome。无法可靠判定
历史 latest 的数据 SHALL 写入 durable、Space-scoped `SourceLifecycleBackfillIssue`，至少保存
knowledge/raw-KB 身份、观测到的 revision 集、原因、`open|resolved` 状态与人工裁决审计；
SHALL NOT 猜测 head。存在 open issue 的 source SHALL 在正常 notify/import/delete/reactivate
入口写入 SourceHead、SourceEvent、Evidence、ChangeSet 或 tombstone 前 fail closed，且不得
fallback 到 legacy。只有显式管理入口在 bound Space 内以可审计 actor/reason、完整合法 ordering
identity 与期望 state 解析 issue 后，正常 lifecycle 才可继续；issue 解析、初始 head/event 与
必要的旧 Evidence stale/retraction SHALL 在一个 caller-owned unit-of-work 中完成，失败全回滚。
测试名 SHALL 以 `test_l2_` 开头并引用本条款。

#### Scenario: 两会话并发创建首个 head

- **WHEN** 两个真实 PostgreSQL Session 对同一 Space/source 同时提交首个相同 identity
- **THEN** 恰有一个 SourceHead，loser 重读后得到 idempotent 结果
- **AND** head version、SourceEvent 与关联业务结果满足唯一约束且 caller Session 可继续使用

#### Scenario: 首个事件 revision 不同

- **WHEN** head 尚不存在且两个 Session 并发提交 ordering 为 B、C 的不同 revision
- **THEN** 两次裁决均在同一 per-source 临界区完成，最终 head 为 C
- **AND** 结果不依赖哪个 transaction 先取得 insert 或先 commit

#### Scenario: 历史 source 没有可证明 ordering

- **WHEN** 迁移发现同一 Space/source 的 017 Evidence 或 ChangeSet 只有 revision hash 而没有 ordering
- **THEN** 创建唯一 open SourceLifecycleBackfillIssue，不创建或猜测 SourceHead
- **AND** 正常 notify/import/delete/reactivate 在零业务写入下 fail closed，直到显式管理入口原子解析

### Requirement: L3 notify、import、delete 与 reactivate 必须共用原子状态机

notify、source-aware import 与 delete/retract SHALL 先取得同一 `(space_id, knowledge_id)`
per-source lock，再在一次 caller-owned unit-of-work 内读取 head、比较 ordering、写
SourceEvent，并按入口原子写 head、Evidence stale/retraction、ChangeSet/ChangeItem、recompile
或 tombstone。所有 head 更新 SHALL 使用 CAS；CAS loser SHALL 重读最新 head 并重新裁决，
SHALL NOT 盲重放原写集。

状态机 SHALL 遵守以下规则：

- 相同 revision、ordering 与 desired state 是 idempotent replay，复用既有结果；
- 低于 head 的事件是 stale，只可追加审计型 SourceEvent，head/Evidence/ChangeSet/
  ChangeItem/tombstone/可消费 recompile 均零新增或修改；
- 严格更新的 active revision 原子推进 head、将旧 active Evidence 标 stale，并创建或复用
  该 identity 唯一的 recompile/import aggregate；
- delete 携带可校验 identity；旧 delete 是 stale，相同 revision/ordering 的 delete 胜过
  active 并原子写 `deleted` head、tombstone 与 scoped Evidence retraction；重复 delete 幂等；
- `deleted` 后同代或更旧 notify/import 不得复活；只有 ordering 严格更新的 active identity
  可原子 reactivate，并留下独立 reactivate event；
- 相同 ordering 但 revision 不同属于 L1 碰撞并 fail closed，不能以到达/提交顺序裁决。

完整转移矩阵 SHALL 如下；`equal` 均先要求 revision 相同，否则按 L1 碰撞 fail closed：

| 当前 head | incoming ordering | desired active | desired deleted |
|---|---|---|---|
| absent | first | 创建 active head；按入口创建 recompile/import aggregate | 创建 deleted head 与该 identity 的唯一空 tombstone |
| active | older | `stale` 审计型 no-op | `stale` 审计型 no-op，旧 delete 不撤新 Evidence |
| active | equal | `idempotent`，复用既有业务结果 | `accepted_delete`，同代 delete 胜出并撤回 Evidence |
| active | newer | `accepted_advance`，推进 head、stale 旧 Evidence | `accepted_delete`，推进 deleted head、写新 tombstone并撤回 Evidence |
| deleted | older | `stale` 审计型 no-op | `stale` 审计型 no-op |
| deleted | equal | `blocked_deleted` 审计型 no-op，不复活 | `idempotent`，复用同 identity tombstone |
| deleted | newer | `accepted_reactivate`，推进 active head | `accepted_delete`，推进 deleted ordering 并写新 identity tombstone |

每个 accepted delete SHALL 将 head ordering/revision 设为 incoming identity，并为该 identity
创建或复用恰一个 tombstone；首次即 delete 和 deleted→newer delete 即使没有 Evidence 也 SHALL
持久化空 tombstone。重复/竞争路径可追加各自审计 event，但 SHALL NOT 重复业务 tombstone、
ChangeItem 或 Evidence mutation。SourceEvent decision SHALL 使用上述稳定枚举，确保可重建结果。

服务 SHALL NOT commit 或 rollback caller 的 outer transaction。lifecycle unit 的持久化失败
SHALL 回滚自身 nested savepoint 中的 head/event/Evidence/ChangeSet/ChangeItem/tombstone 全部
写入，保留 caller 在调用前已完成的合法工作；预期 stale/idempotent/CAS loser 路径与异常被
调用方捕获后，Session SHALL 可继续查询、flush 并由 caller 决定 commit/rollback。测试名
SHALL 以 `test_l3_` 开头并引用本条款。

#### Scenario: C active 后迟到 B

- **WHEN** revision C 已为 active head，随后 notify 或 import 收到 ordering 更旧的 B
- **THEN** B 记录 stale decision，但不改变 head、不 stale C Evidence
- **AND** 不创建或唤醒 B 的可消费 recompile、ChangeSet 或 tombstone

#### Scenario: delete 与同代 import 竞争

- **WHEN** 当前 active revision 的 delete 与相同或更旧 revision import 在两 Session 并发
- **THEN** 两者经同一 lock/CAS 重裁决后最终 head 为 deleted
- **AND** import 不得复活 Evidence，delete/tombstone/事件业务结果恰一份

#### Scenario: 首个 lifecycle 事件就是 delete

- **WHEN** source 尚无 head/Evidence，合法 delete identity 是首个事件
- **THEN** 原子创建 deleted head、该 identity 的唯一空 tombstone 与 accepted_delete event
- **AND** 同代或更旧 active 事件随后只能得到 blocked_deleted/stale 审计 no-op

#### Scenario: active 或 deleted head 收到严格更新 delete

- **WHEN** active 或 deleted head 收到 ordering 严格更新的合法 delete identity
- **THEN** head revision/ordering 原子推进并保持/变为 deleted，创建该新 identity 的唯一 tombstone
- **AND** active 情形撤回 scoped Evidence，deleted 情形不得重复旧 tombstone/ChangeItem

#### Scenario: delete 后严格更新 revision 重新激活

- **WHEN** deleted head 收到 ordering 严格更新且 identity 合法的 active revision
- **THEN** head 原子变为 active 并关联独立 reactivate SourceEvent
- **AND** 同代或旧 revision 的 notify/import 重放仍为 no-op

#### Scenario: 持久化失败不接管 caller transaction

- **WHEN** caller 已 flush 合法工作，lifecycle unit 在 event 与 ChangeSet 之间注入失败并捕获
- **THEN** 本 unit 的 head/event/Evidence/ChangeSet/tombstone 全部回滚，caller 既有工作保留
- **AND** 同一 Session 仍可执行新查询/flush，outer commit/rollback 仍由 caller 决定

### Requirement: L4 Space、legacy 与 Snapshot 边界必须保持隔离

全部 source lifecycle 读写 SHALL 强制按 bound `KnowledgeScope` 隔离。
SourceHead、SourceEvent、Evidence、ChangeSet/ChangeItem 与 tombstone 的全部读取、锁、CAS 和
写入 SHALL 由 bound `KnowledgeScope` 闭合 `space_id/tenant_id/raw_kb_id`；child aggregate
SHALL 经 scoped parent join/复合约束校验。相同 knowledge_id 在不同 Space SHALL 拥有独立
lock、head、events 与 lifecycle 结果，任何畸形、歧义或跨 Scope aggregate SHALL 在业务写入
前 fail closed，错误不得泄漏他租户 payload，caller-owned Session 按 L3 保持可用。

legacy replay 与 source-aware lifecycle SHALL 严格互斥：legacy 入口 SHALL NOT 读取、创建、
删除、推进或恢复生产 SourceHead；source-aware identity 无效时 SHALL NOT fallback 到 legacy。
任何 notify/import/delete/reactivate/stale/recompile 状态变化 SHALL NOT 创建、修改或删除
`ReleaseSnapshot`/`SnapshotFact`，也 SHALL NOT 移动 `CurrentRelease`；发布仍只由 018 审核后
snapshot 流程完成。测试名 SHALL 以 `test_l4_` 开头并引用本条款。

#### Scenario: 两个 Space 使用相同 knowledge_id

- **WHEN** Space A 的 source 已推进或删除，Space B 使用相同 knowledge_id 导入自己的 revision
- **THEN** B 只读取和更新自己的 head/event/Evidence/ChangeSet
- **AND** A 的 head、events、Evidence、Snapshot 与 CurrentRelease 均不变化

#### Scenario: legacy replay 试图命中生产 source

- **WHEN** legacy payload 使用与生产 SourceHead 相同的 knowledge/revision 字符串
- **THEN** legacy 路径不得推进、删除或重新激活该 head
- **AND** source-aware 路径也不得把非法 identity 降级为 legacy 成功

#### Scenario: lifecycle 推进不发布 Snapshot

- **WHEN** active head 推进、delete 或 reactivate 成功
- **THEN** ReleaseSnapshot/SnapshotFact 行与内容均零变化
- **AND** CurrentRelease 仍指向调用前 snapshot

### Requirement: L5 迁移 0006 必须链级预检且有条件 downgrade

本变更 SHALL 使用注册表预分配的 Alembic revision id `0006`，SHALL NOT 占用或重排 018 的
`0005`。数字编号 SHALL NOT 被当作链拓扑；实现 PR SHALL 将 `down_revision` 指向合入时
`main` 的唯一实际 head，upgrade 前 SHALL 拒绝意外 base/multiple heads，并由 migration/test
证明 `upgrade head` 后仍只有一个 head。

任何跨多 revision 的 downgrade SHALL 在首个破坏性 DDL 前完成目标链级数据兼容预检，
而不是等走到较老 migration 才发现不可降级。直接跨过 `0006` 时，若存在任一 SourceHead、
SourceEvent、无法由旧 schema 保真的 ordering/source lifecycle provenance，downgrade SHALL
fail closed；失败时 schema、数据和 `alembic_version` SHALL 全部保持调用前状态。空 lifecycle
数据时 SHALL 可 downgrade 并干净移除 0006 对象；随后 roll-forward SHALL 可重建等价 schema。
无法证明 latest 的历史 source-aware 数据（包括只有一个 revision hash）SHALL NOT 被
hash、Evidence.extracted_at、ChangeSet.created_at 或文件时间猜测回填；upgrade SHALL 为每个
受影响的 Space/source 写入 L2 定义的唯一 open SourceLifecycleBackfillIssue。迁移测试名 SHALL
以 `test_l5_` 开头并引用本条款，并同时覆盖 SQLite 与 PostgreSQL 支持的合同。

#### Scenario: 0006 绑定实际单 head

- **WHEN** 在实现基线的实际 Alembic head 上执行 upgrade 到 `0006`
- **THEN** `0006.down_revision` 精确指向该 base 且 upgrade 后仍只有一个 head
- **AND** SourceHead/SourceEvent 的 scope、唯一、CAS 与 append-only 数据库约束已建立

#### Scenario: 非空 lifecycle 数据拒绝链式 downgrade

- **WHEN** 数据库在 `0006` 或其后且存在 SourceHead/SourceEvent/BackfillIssue/provenance，再请求 downgrade 到 0006 之前
- **THEN** 在任何表、列、constraint 或 trigger 被删除前 fail closed
- **AND** schema、业务数据与 alembic_version 均保持调用前状态

#### Scenario: 空数据 downgrade 与 roll-forward

- **WHEN** 0006 lifecycle 数据为空并执行允许的 downgrade 后再次 upgrade
- **THEN** downgrade 干净移除 0006 对象，roll-forward 恢复等价 schema
- **AND** Alembic 全程维持单 head

#### Scenario: 017 历史数据只生成 unresolved ledger

- **WHEN** upgrade 读取只有 revision hash、没有可信 ordering 的既有 source-aware Evidence/ChangeSet
- **THEN** 按 `(space_id, knowledge_id)` 幂等生成 open BackfillIssue，且不创建 active/deleted head
- **AND** 重跑 upgrade/backfill 不重复 issue，任何时间戳或 revision 字典序都不参与 latest 裁决

### Requirement: L6 验收必须包含真实 PostgreSQL 双会话与零 skip 证据

deterministic lane SHALL 覆盖 L1 归一/深校验、纯状态机、Space/legacy/Snapshot 隔离、
caller-owned transaction、迁移形状与失败回滚。PostgreSQL integration lane SHALL 使用两个
真实独立 connection/Session（SHALL NOT 用 mock、SQLite 或同 connection nested Session
代替），至少覆盖：首次并发创建、同 revision create/reuse、B/C 逆序与并发、C 后迟到 B、
首事件 delete、active/deleted 上的严格更新 delete、delete-vs-import、delete-vs-notify、严格
更新 reactivate、CAS loser 重读以及失败回滚。
结果 SHALL 由 ordering/state machine 唯一决定且可由 SourceEvent 重建。

integration harness SHALL 为 connection、statement、lock 与 future/join 设置有限 timeout，
为每次运行使用隔离且可清理的数据库 scope，并输出 JUnit。缺 PostgreSQL 前置条件的本地运行
MAY 显式 skip 并记录 `NOT RUN`，但 SHALL NOT 计作验收成功；实施完成必须有受信真实
PostgreSQL run 的 `tests>0` 且 `skipped=0` 证据。最终还 SHALL 通过 OpenSpec strict、Ruff、
mypy strict、非 live/非 integration_postgres pytest、Alembic upgrade/downgrade/check 与
`git diff --check`。所有新增/修改的行为测试名 SHALL 以 `test_l1_`～`test_l6_` 引用所证条款；
characterization SHALL 明示 baseline GREEN，行为变更 SHALL 保存正确原因的 RED→GREEN。

#### Scenario: 真实 PostgreSQL lane 完成

- **WHEN** 021 申请 implementation complete
- **THEN** JUnit 证明本 lane tests 大于零、skipped 等于零且双会话竞争节点全部通过
- **AND** 报告记录 exact SHA、数据库版本、node identities、timeout 与 sanitized run identity

#### Scenario: 本机没有 PostgreSQL URL

- **WHEN** 开发者只运行 deterministic lane 且未配置 PostgreSQL fixture
- **THEN** integration node 显式 skip/NOT RUN，不以 mock 或 SQLite 替代
- **AND** change 状态不得描述为 PostgreSQL ordering verified 或 implementation complete
