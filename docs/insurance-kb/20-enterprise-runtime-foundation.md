# 20 · 企业运行基础：作用域、来源桥接、发布快照与质量闸门

> 状态（2026-07-21）：016/017/018/019/021 软件均已合入；018 已取得 PostgreSQL 与真实 WeKnora 5-node 零 skip 证据，但只是 SnapshotFact/历史逐页发布地基，不含 NS-C/P-1 全制品 seal/原子 serving alias。`NS-RIGHTS=recorded` 已确认 LLM-wiki-black 第一方权利；020 canonical admission 仍 `BLOCKED`，027 生产模型入口尚未硬封，030 MVP admission 也未 READY。027 与适用 admission 缺一时，真实编译/merge/release 均禁止。

## 1. 目标与结论

当前方向保持不变：WeKnora 是企业知识平台，Insurance Harness 是寿险领域知识编译器。需要修正的不是“两者是否共存”，而是两者尚未形成同一条受治理的生产数据链。

本阶段建立五个不可绕过的运行约束：

1. 每次读写都属于显式 `KnowledgeSpace`，不得依赖进程级默认租户或默认 KB；
2. 生产编译输入来自 WeKnora `knowledge`，本地目录只保留为开发、回放与金标评测入口；
3. Evidence 同时记录原文页锚点、WeKnora chunk 锚点和来源修订；
4. Wiki、MCP 与 Agent 只消费 WeKnora active alias 指向、且与已批准 `ReleaseSnapshot` 及本地 CurrentRelease activation-receipt 镜像核对一致的不可变投影；P-1 前仅 Harness reader 可服务批准快照；
5. Golden Set 不只是离线报告，而是抽取与低风险候选自动化策略的质量闸门；不能替代 release 级真人最终批准。

## 2. 模块分工

| 模块 | 负责 | 不负责 |
|---|---|---|
| WeKnora | 租户与 KB ACL、原始文件、docreader、chunks、原始检索、Wiki 页面存储、Agent 接入 | 寿险字段语义、权威序、冲突裁决、Claim 生命周期 |
| Insurance Compiler | 读取来源文档、页面切分、寿险字段抽取、三态判断、证据回验 | 企业用户体系、原始文件主存储 |
| Knowledge Domain | Claim/Evidence、ChangeSet、审核、版本、发布快照 | 原始向量检索 |
| Golden/Eval | 可复现的金标 release、指标、字段质量画像、回归判定 | 在线事实主存储 |

“双抽取”不是两套事实系统：WeKnora docreader 产生原始检索材料；Insurance Compiler 产生候选结构化事实。只有通过 ChangeSet、审核和 ReleaseSnapshot 的内容才是 Agent 可依赖的已发布知识。

## 3. KnowledgeSpace：企业隔离边界

新增 `knowledge_spaces` 聚合根：

```text
KnowledgeSpace
  id
  tenant_id       # unbound 时 NULL
  raw_kb_id       # unbound 时 NULL
  wiki_kb_id      # unbound 时 NULL
  name
  binding_status: bound | unbound
```

同一 tenant 可以有多个 KnowledgeSpace；一个 Space 固定映射一个 KB-RAW 和一个**独占的目标** KB-WIKI。数据库对 bound Space 强制 `UQ(tenant_id, wiki_kb_id)`，禁止两个 Space 共享同一 target Wiki KB；P-1 active alias 的地址就是 `(tenant_id, target_wiki_kb_id)`。Harness 内部使用 `space_id`，避免把“哪个 kb_id”混成一个不明确字段。

P-1 前的隔离 staging 不是 Space 的消费目标，不复用 `wiki_kb_id`。NS-C 新增可撤销、可审计的 `WikiPublicationCapability`：`{space_id, tenant_id, target_wiki_kb_id, staging_wiki_kb_id, mode, acl_probe_hash, retrieval_probe_hash, issued_by, expires_at}`。`staging_wiki_kb_id` 必须与 target 不同，并对有效 capability 强制 `UQ(tenant_id, staging_wiki_kb_id)`，两类 KB 均不可跨 Space 复用；`mode=isolated_staging` 时 publisher 只能写 staging，普通用户/Agent/RAG 探针必须证明不可达。P-1 后 capability 切为 `mode=release_namespace`，target 通过 active alias 激活；签发及每次写/seal/activate/query 前都复验 tenant/Space/KB 一一绑定，任何缺失、过期或 ID/ACL 漂移均 fail closed。

以下聚合根必须直接带 `space_id`：Product、ProductDocument、UnassignedItem、Claim、ChangeSet、ReviewItem、ReleaseSnapshot、CurrentRelease。子表通过父表外键继承作用域，但任何服务入口仍必须接收 `KnowledgeScope` 并在查询中校验。

所有原全局唯一约束改为空间内唯一，包括：

- `(space_id, product_code)`；
- ChangeSet `(space_id, source_kind, idempotency_key)`，其中 key 对所有来源类型非空；structured SourceRevision 另以 branch CHECK 保证 external record/revision 非空后建立作用域唯一键；
- `(space_id, review_key)`；
- `(space_id, release_label)`；
- `CurrentRelease(space_id)` 每空间一行，且 bound Space 的 `(tenant_id, wiki_kb_id)` 唯一。

迁移采用兼容的两阶段策略：历史数据先进入 `legacy-default` 且状态为 `unbound`，三个外部绑定字段均为 NULL；只有 bound Space 能构造 `KnowledgeScope`。测试和离线迁移工具可以按 `space_id` 检查 unbound 数据，但生产桥接、发布和在线读取必须拒绝。管理员在单事务内校验并写入 tenant/raw/wiki 三项后切换为 bound。

运行时 `KnowledgeScope` 不是仅凭四个字符串成立的 DTO，而是当前数据库 capability：private attestation 以弱引用绑定进程内 Engine object identity，deep copy 保持 provenance，但 scope 不延长 Engine 生命周期；Engine 被释放后 capability 自动 fail closed。Engine 身份按 `KnowledgeSpace` mapper 解析，因此 mapper-only Session 可用，而默认 Engine 相同、mapper Engine 不同仍会在查询前拒绝。所有 public 产品/知识/发布 DB 入口还会绕过 identity map、禁止 autoflush，以纯列查询重查 bound 行；目标 Space 处于 new/dirty/deleted UoW，或刚由 public `bind_space` 写入而 caller outer transaction 尚未结束时，均拒绝签发/使用 capability。共享同一 Engine 的 Session 可以复用；跨 Engine（即使 URL/数据相同）、序列化和 matching forged 均要求 reload/fail closed。Engine/token 不序列化、不入日志。

这里的纯列查询不是“任意 committed-only”隔离承诺：同一 Session/事务中，直接 raw SQL 或手工 flush 的低层写入仍可能对 SELECT 可见。绕过 admin service 的这类写入不属于 capability API 保证；public `bind_space` 路径则通过 caller outer `SessionTransaction` marker 关闭了 commit/rollback 前的加载窗口。

DB 可表达的 child 关系使用 scoped composite FK，包括 ProductDocument→Product/ProductVersion、Claim→ProductVersion/superseded Claim、SnapshotClaim→Snapshot/Claim、CurrentRelease→Snapshot；JSON/nullable child 仍由 service aggregate guard 闭合。

## 4. SourceDocument Bridge

生产入口定义为不可变 `SourceDocument`：

```text
SourceDocument
  scope
  knowledge_id
  title / file_name / file_type
  source_revision = file_hash + processed_at + parser fingerprint
  original_file
  pages[{page_no, text}]
  chunks[{chunk_id, chunk_index, start_at, end_at, content}]
```

WeKnora adapter 通过受 ACL 保护的接口读取 knowledge 元数据、下载原文件并列出 chunks。Bridge 校验返回的 `tenant_id`、`knowledge_base_id` 与调用 scope 一致，任何不一致都 fail closed。SourceDocument 只在 metadata、完整下载、hash 校验和全部 chunk 分页均成功后一次性构造；任何中途失败都清理临时文件并丢弃内存中的部分 chunks。

Compiler 改为依赖 `DocumentSource` 协议：

- `DirectoryDocumentSource`：本地回放、Golden Set、单元测试；
- `WeKnoraDocumentSource`：目标态在线来源 adapter；它只解决来源真实性，不解除 027/适用 admission，也不使当前 004 编译器获得生产资格。

PDF 页码来自下载的原文件；chunk 引用通过 evidence quote 与 chunk 内容归一化匹配得到。唯一命中写 `chunk_id`；零命中或多命中保留页锚点，并记录 `lineage_status=page_only|ambiguous`，不得伪造 chunk 关联。

Evidence 额外冻结 `source_revision`、`file_hash`、`parser_version` 与可选的 `chunk_hash`。同一 `knowledge_id` 修订变化时，旧 Evidence 标记 stale 并产生 recompile ChangeSet，不静默覆盖。

017 T5 已实现纯 whitespace-only quote→chunk 映射、同 `SourceDocument` 来源校验，以及 `linked|page_only|ambiguous` 三态 lineage；T6 已以 0004 迁移持久化完整 audit/stale 字段，并交付生产 `SourceImportContext`、显式 legacy replay、按 source revision 分区、pending recompile 复用、全分区 savepoint 与 validated non-stale refs；T7 已完成 stale mutation、同 revision 并发 recompile get-or-create 与 scoped retract。T8 已交付真实端点 existing-knowledge gate、严格 linked 回链、deterministic Compiler、PostgreSQL import/rollback、Runbook 与双审；由于环境前置缺失，真实 live 运行记录为 `NOT RUN`，且当前不覆盖 upload 创建。

## 5. ReleaseSnapshot：单一在线事实视图

现有 Snapshot 只保存 claim/revision 会员关系，不足以冻结当时的 Evidence。新增不可变 `SnapshotFact`，在发布时复制：

- Claim 的值、三态、有效期、置信度与 schema 版本；
- 当时的 Evidence 全量投影；
- product/version 与 scope；
- claim_id/revision_no 用于审计回链。

Wiki 渲染器和未来 MCP 查询都只读取 `SnapshotFact`。不得绕过当前快照直接查询 `claims.status='published'` 作为在线答案。

发布采用可恢复状态机投影（事件 append-only，snapshot 本体不原地改 status）：

```text
building → publishing → published
                    ↘ failed
```

先在数据库内构建 SnapshotFact、页面物化结果和完整 PublishPlan，再向 WeKnora P-1 的不可见 `release_id` namespace 幂等 staging 并回读验证；之后调用 `seal-release(expected_write_etag, manifest_hash)`，由平台原子重算物理 namespace/index hash 并冻结 PUT/DELETE。随后必须由该 Space 授权人对完整 snapshot content hash 最终批准。只有 seal receipt、仍有效的 approval、target KB 归属和 hash 全匹配时，才调用 `activate-release(expected_alias, release_id, manifest_hash)`；activate 再验 seal/物理 hash 后以 active alias CAS 作为 serving commit。本地 `current_release` 只镜像 verified activation receipt/ETag，不能独立上线。alias/镜像/批准失配时 MCP fail closed + Alert。P-1 前只能写 ACL 隔离、禁生产检索的 staging KB，由 Harness reader 预览，禁止写生产 Wiki。failed snapshot 可用同一冻结 plan 显式重试；任何制品变化都生成新 snapshot并重新批准。

批准撤销/到期、release pin 与 GC 都用 append-only event/receipt 表达。当前 release 和仍具有效 rollback approval/保留资格的 sealed namespace、index generation、内容制品必须 pin，禁止 GC；仅失败未激活 staging，或明确失去回滚资格且过审计保留期的 release，可经授权后 GC 并记录逐项 hash/receipt。回滚先对有效批准、seal、页面/关系/目录/MCP manifest、内容制品和 index generation 做物理 hash preflight，缺一项即阻断；全绿后才执行 active alias CAS，不逐页重放、不重新调用模型。MCP 每次读取并核对同一 alias，所以与 Wiki 页面引用同一个 snapshot_id。

## 6. Curated-first 查询策略

Agent 不直接把 KB-RAW 与 KB-WIKI 作为同权知识源混合检索。在线查询顺序固定为：

1. SnapshotReader 查询已发布结构化事实；
2. 若返回明确 `coverage_gap`，才允许在同一 KnowledgeSpace 的 KB-RAW 检索；
3. RAW 结果必须标记“未经过结构化发布审核”，不能覆盖 SnapshotFact；
4. 若 scope 不一致或当前无已发布快照，拒绝静默跨库回退。

## 7. Golden Set 与质量闸门

现有 002 T8 的 11/13 进度继续保留。软件 change 019 先交付可移植汇总、release validator、QualityProfile 与在线 Gate；真实数据 change 020 再完成两个缺失产品、发布 `gs-v0.1` 并运行 13 产品 baseline。这样普通 CI 不依赖模型凭据，真实运行也不会被伪装成软件测试成功。

Golden 工作拆成四层：

1. **数据集发布**：13/13、schema 固定、每产品 disputed rate ≤5%、自评满分；
2. **全量基线**：13 产品全部跑抽取，完成 judge queue、dead letter 与 long-field keypoints；
3. **回归闸门**：候选版本相对批准基线不得出现指标退化；
4. **低风险候选自动化资格**：只有低风险字段且质量画像满足最小样本数、值准确率、幻觉率和证据准确率阈值，才可能自动形成/推进 add/enrich/supersede 候选；不能直接发布。

默认安全策略：`auto_apply_supersede_low_risk=false`。即使配置开启，也只允许生成 candidate revision，且必须同时存在匹配 schema/model/prompt/source-profile 的已批准 `QualityProfile`。高风险字段始终人工审核；每个生产 snapshot 无论风险都须真人最终批准。

首版保守资格阈值可配置，默认：样本支持数 ≥10、值准确率 ≥0.98、幻觉率 ≤0.01、证据准确率 =1.0。阈值不足意味着禁止低风险候选自动推进，只能进入审核队列；阈值达标也不产生无人批准发布。

## 8. 失败处理与可观测性

| 失败 | 行为 |
|---|---|
| WeKnora scope 不匹配 | 立即拒绝并记录 security event |
| knowledge 未完成解析 | 可重试，不开始 Compiler |
| 原件下载或页解析失败 | dead letter；不使用 chunks 猜页码 |
| quote 无 chunk 唯一匹配 | 保留 page evidence，标 lineage 状态 |
| source revision 变化 | Evidence stale + recompile ChangeSet |
| 质量画像缺失或过期 | 低风险候选自动推进关闭，进入审核 |
| Wiki staging/回读失败 | active alias 不移动；记录 attempt/Alert，staging 对普通 UI/RAG 不可见 |
| active alias CAS/ack 失配 | CAS 失败保持旧 alias；若 alias 已变但本地 ack 丢失，MCP fail closed，凭 provider receipt reconciliation，不猜状态 |
| 回滚失败 | active alias 不移动，当前在线快照保持 |

所有 run manifest 记录 `space_id/tenant_id/raw_kb_id/knowledge_id/source_revision/schema/model/prompt`，使一次错误可以重放并定位到来源版本。

## 9. 实施拆分与依赖

| Change | 内容 | 依赖 |
|---|---|---|
| 016 | KnowledgeSpace、作用域强制、两阶段迁移 | 007 |
| 017 | WeKnora SourceDocument Bridge、Evidence lineage | 历史 change 依赖 016、004；其 live 证据只证明 bridge，不解除 004 的 027/028/030 生产质量门禁 |
| 018 | SnapshotFact、统一读取、发布/回滚一致性 | 007、016、017（硬依赖） |
| 019 | Golden 工具、QualityProfile 与发布闸门（确定性软件） | 历史 change 依赖 002、004、005、007；确定性工具可保留，任何加载 004/merge 的生产用途仍受 027/适用 admission |
| 020 | gs-v0.1 收尾、13 产品 baseline、judge/dead-letter/keypoints（真实数据运行） | 002、019、021 + NS-RIGHTS recorded + NS-0 verified + 020 admission READY |
| 021 | SourceHead、不同 revision ordering 与统一 per-source lock/CAS | 017、018；迁移在 018 `0005` 之后 |

016/017/018/019/021 已合入；018 实现 migration `0005`、统一读模型和旧范围可恢复 saga，021 已在其后补齐 SourceHead/order/lock/CAS。020 T1 run-admission 软件也已合入，但权威工件仍为零模型 `BLOCKED`。当前 MVP 动作是 027→028，并行 029/010 thin、013/032 和独立 030 admission；只有 `NS-RIGHTS=recorded ∧ NS-0=verified ∧ applicable admission=READY` 才执行对应真实 slice。B10 本机 live 环境与受信门禁不替代这些条件；NS-C/P-1 及未来 WeKnora 升级仍须另做同快照 live 验收。

## 10. 非目标

- 本阶段不实现 008 工作台、009 概念层、012 QA、013 MCP UI 或 014 批量控制台；
- 不修改 WeKnora Go/Vue 核心业务代码，除非 live 契约证明现有 API 无法满足且先形成独立上游提案；
- 不宣称当前 Golden F1 已达到无人审核发布水平；本阶段首先让低质量结果无法越过治理边界。
