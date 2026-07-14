# knowledge — S2→S3 主链（Claim 落库、增量合并、审核门禁、页面发布）

change 007 落点；数据模型/权威序/发布契约以 `docs/insurance-kb/03-knowledge-model.md` 为唯一权威。

## 职责与入口

| 模块 | 职责 |
|---|---|
| `tables.py` | 知识域 ORM（claims/claim_evidence/claim_revisions/change_sets/change_items/conflicts/review_items/release_snapshots/snapshot_claims/current_release；基础迁移 `0002`，source lineage 迁移 `0004`） |
| `authority.py` | doc_role → 权威等级（03 §6.1）、离散置信度 → 浮点 |
| `importer.py` | pred JSONL（compiler.PredRecord）→ ProposedClaim → 合并引擎；记录级/批级幂等 |
| `merge.py` | 增量合并引擎：add/enrich/supersede/conflict/retract；裁决序严格 03 §6.2（④=claude-session 队列占位，零模型调用）；审核动作 approve/reject/defer；翻案=新 ChangeSet |
| `source_revision.py` | source revision 通知：同修订 no-op、旧 Evidence 条件标 stale、并发安全地创建或复用 pending recompile ChangeSet |
| `review.py` | ReviewItem 内容稳定 ID（sha256 派生）+ 受限动作集 |
| `pages.py` | published Claims → 产品限定页 Markdown（分组渲染 + 证据角标） |
| `publisher.py` | 经 adapters/weknora 写 wiki 页（03 §7 契约）；ReleaseSnapshot + current_release 指针；回滚=按快照重发布 |

## 与其他包的关系

- 上游：`compiler/`（pred.jsonl 行格式与 judge-queue 形态，只读复用）、`db/`（Base 与产品主数据）、`schemas/`（字段风险级与展示名）；
- 下游：`adapters/weknora`（唯一允许出现 WeKnora API 细节的位置）。

测试：`tests/test_knowledge_*.py`（spec 编号 K1~K6 一一对应）；发布器全 respx mock，live 契约留 `-m live`。

## KnowledgeScope 合同（change 016）

- import、`MergeEngine`、claim helper、review/judgement/retraction、page build、publish/rollback/current/snapshot helper 的 public DB 入口全部显式接收 bound `KnowledgeScope`，并先用 `require_current_scope` 证明它来自当前 Session Engine 且当前数据库仍为相同 bound 行；matching forged、另一 Engine scope 或 dirty Space UoW 在业务查询/I/O/mutation 前拒绝。Claim、ChangeSet、ReviewItem、ReleaseSnapshot 与 CurrentRelease 直接按 `space_id` 隔离。
- ChangeItem/Conflict/ClaimEvidence/ClaimRevision 等 child 表通过先行 scoped 父聚合 guard 继承作用域。JSON proposal/reference 还会闭合同一 ChangeSet/Claim 与 canonical proposal；不能靠协调篡改两份 JSON 绕过。
- release label 与 current pointer 按 Space 唯一。publisher 不接受 free-form `kb_id`，只把页面写入 `scope.wiki_kb_id`；current pointer 还会闭合指向的 scoped ReleaseSnapshot。
- Claim 的 `superseded_by` 由 `(space_id, superseded_by)` 复合 self-FK 保证只能指向同 Space Claim，nullable 语义不变。
- publish/rollback 会先校验 scope、聚合、frozen revision/evidence 和页面 metadata，再执行 Wiki I/O/数据库 pointer mutation。016 只保证本进程路径失败时指针不移动；跨进程串行化、部分外部写补偿、SnapshotFact/reconciliation 属于 018。
- 完全 unscoped 的 ExtractionPipeline 仅保留给本地回放/Golden legacy run；scoped run 的 fresh/resume/checkpoint/manifest 必须一致，live 来源链由 017 强制。

## Source-aware import（change 017）

- `import_pred_records()` / `import_pred_jsonl()` 默认是生产 source-aware 路径。调用方必须提供冻结的 `SourceImportContext`：scope 三元身份与 `doc → SourceImportIdentity` 映射；每个 identity 固定 `knowledge_id/raw_kb_id/source_revision/file_hash/original_digest/parser_version`。`knowledge_id` 沿用 WeKnora 单路径段契约（1–128 位字母、数字、`_`、`-`），导入边界会重新验证已有模型实例，不能用 `model_construct()` 绕过。Evidence 审计字段是事实来源，并逐条与 context 及 bound `scope.raw_kb_id` 对照。unknown 无 Evidence 也只从该 context 取得来源，禁止以文件名猜 `knowledge_id`。
- 历史 pred/fixture 只能显式传 `legacy_replay=True`。此时才保留旧 `knowledge_ids`、文件名 placeholder 与 JSONL 内容 revision 语义；生产模式若收到这些 legacy 参数会拒绝。两种模式不能混用，legacy 路径也拒绝携带 source-aware Evidence，以免静默丢审计字段。
- 生产导入按完整 `(knowledge_id, source_revision)` 分区，每区一个 ChangeSet。所有分区先完成无副作用状态预检，再在同一 savepoint 内创建、merge 与 flush；任一分区失败会撤销本次导入的全部副作用，外层 Session 仍可继续使用。优先填充同 key、零 ChangeItem 的 pending `recompile`，也允许恢复零 ChangeItem 的 pending `document`；已有条目的 pending/partially-applied、跨 source_kind 多候选或其他不确定状态 fail closed。已 applied 同 key 是 duplicate/no-op，不新增 ChangeItem。
- `ClaimEvidence` 无损持久化 source/chunk audit；导入的新 Evidence 的 `stale_at` 恒为 `NULL`。enrich 去重键包含 revision 与 chunk lineage，避免同一 quote 的新修订证据被吞掉。
- 页面正文仍可保留证据脚注，但生产 `source_refs/chunk_refs` 只来自完整、已验证且 `stale_at IS NULL` 的 lineage。`page_only/ambiguous` 可贡献 source ref，只有 `linked` 可贡献 chunk ref。历史 placeholder ref 仅在显式 `build_page_claims(..., legacy_replay=True)` 回放路径开放。

## Source lifecycle（change 017 T7）

- `notify_source_revision(session, scope, identity)` 只接受与 bound `scope.raw_kb_id` 一致且经过深度重校验的 `SourceImportIdentity`。同一 active revision 完全 no-op；新 revision 只把相同 Space、`knowledge_id`、raw KB 的旧 source-aware active Evidence 以单条条件更新从 `stale_at IS NULL` 改为首个观测时间，不触碰其他来源、legacy Evidence、其他 Space 或已有 stale 时间。
- 每次新 revision 使用精确键 `(space_id, "recompile", knowledge_id, source_revision)` 创建或复用零 ChangeItem 的 pending ChangeSet。创建依赖数据库 `uq_changeset_source` 和嵌套 savepoint 捕获唯一冲突后精确回读；非 pending、已有条目、document/recompile 歧义均 fail closed。T6 importer 会填充该 recompile，而不另建 document ChangeSet。
- 通知返回冻结、拒绝额外字段的 `SourceRevisionReport(same_revision, created, reused, stale_count, change_set_id)`。通知、stale mutation 和 ChangeSet 创建处于调用方事务内；失败不留下部分 stale 或 ChangeSet，且不改变 `ReleaseSnapshot`、`SnapshotClaim`、`CurrentRelease` 或已物化页面。
- `retract_source` 的生产入口传完整 source identity；`SourceImportIdentity + legacy_replay=True` 在任何 SQL 前拒绝。历史字符串只允许显式 `legacy_replay=True`，并用哈希 sentinel，绝不把文件名猜成可信来源身份。legacy retract 只能删除 audit 全 NULL 的 legacy Evidence；若同一 Space/knowledge 已存在 source-aware Evidence，或存在带真实 64 位 source revision 的 `document`/`recompile` ChangeSet，则在 mutation 前 fail closed，防止 legacy 路径删掉生产 lineage 后又被 applied import 幂等键永久挡住。生产删除按 `space_id + knowledge_id` 移除该来源的全部 Evidence（包括 stale），仅以其他 `stale_at IS NULL` Evidence 决定 Claim 是否保留。
- retract 继续记录 `source_kind="document"`，但 `source_revision` 使用固定 64 字符的 `retract:` 事件键；同一 knowledge/revision 删除事件精确复用原 applied ChangeSet，不新增 ChangeItem，重新上传的新 source revision 会形成新事件键。即使首次删除时 scoped Evidence 为零，也会记录零 ChangeItem 的 applied tombstone；replay/import 在复用前共同校验 tombstone 的 scoped parent/child aggregate，包括唯一 Claim、`retract + auto_applied`、dict proposal 与严格正整数 `removed_evidence`。T6 source-aware importer 在任何分区写入前拒绝同 source revision 的迟到导入，防止旧数据复活。整个操作使用 savepoint，且不改发布快照或 current pointer。
- pending/applied source ChangeSet 不能只凭唯一键复用：共享 parent aggregate validator 还要求 Space、source kind、external record、source revision 与 `knowledge_ids == [identity.knowledge_id]` 精确闭合；调用方再分别约束 state 与 ChangeItem 数量。applied duplicate 返回 no-op 前还会遍历全部 ChangeItem，并复用 merge 层 action-aware scoped aggregate guard 校验 item 的 claim、existing/placeholder、proposal、Conflict 与 product-version 引用；合法零 item 及 winner-existing `claim_id=NULL` conflict 保持可重放。不完整、跨 knowledge 或任一 child 跨 Space 均在写入前 fail closed。
- **顺序边界**：017 T7 的唯一键只解决“同一 revision”幂等，不提供不同 revision 的新旧排序；SHA-256 revision 不可比较，也不得按 hash 排序。当前 tombstone preflight 与 import/delete 也分属不同数据库 key。因此在后续 source-head/代际 CAS 方案落地前，生产只允许同一 Space/source 的 lifecycle 串行执行，且 notification 必须来自当次实时读取的当前 metadata；禁止并发 B/C revision、缓存/延迟旧 metadata 回放及 import/delete 竞争。该残余风险由 change 021 的 durable SourceHead、`processed_at`/generation 与统一 per-source lock/CAS 方案承接。
