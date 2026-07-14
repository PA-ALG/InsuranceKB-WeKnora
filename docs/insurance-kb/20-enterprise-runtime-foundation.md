# 20 · 企业运行基础：作用域、来源桥接、发布快照与质量闸门

> 状态：设计已形成，按 OpenSpec 016～020 分段实施。016 已完成并通过规格/质量双审与主代理验收；017 T1–T6 已完成并进入 T7，018～020 尚未完成。本文是方案 A 的总设计；各 change 的 `specs/` 是验收权威。

## 1. 目标与结论

当前方向保持不变：WeKnora 是企业知识平台，Insurance Harness 是寿险领域知识编译器。需要修正的不是“两者是否共存”，而是两者尚未形成同一条受治理的生产数据链。

本阶段建立五个不可绕过的运行约束：

1. 每次读写都属于显式 `KnowledgeSpace`，不得依赖进程级默认租户或默认 KB；
2. 生产编译输入来自 WeKnora `knowledge`，本地目录只保留为开发、回放与金标评测入口；
3. Evidence 同时记录原文页锚点、WeKnora chunk 锚点和来源修订；
4. Wiki、MCP 与 Agent 只消费当前 `ReleaseSnapshot` 的不可变事实投影；
5. Golden Set 不只是离线报告，而是抽取策略和自动发布策略的质量闸门。

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

同一 tenant 可以有多个 KnowledgeSpace；一个 Space 固定映射一个 KB-RAW 和一个 KB-WIKI。Harness 内部使用 `space_id`，避免把“哪个 kb_id”混成一个不明确字段。

以下聚合根必须直接带 `space_id`：Product、ProductDocument、UnassignedItem、Claim、ChangeSet、ReviewItem、ReleaseSnapshot、CurrentRelease。子表通过父表外键继承作用域，但任何服务入口仍必须接收 `KnowledgeScope` 并在查询中校验。

所有原全局唯一约束改为空间内唯一，包括：

- `(space_id, product_code)`；
- `(space_id, source_kind, external_record_id, source_revision)`；
- `(space_id, review_key)`；
- `(space_id, release_label)`；
- `CurrentRelease(space_id)` 每空间一行。

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
- `WeKnoraDocumentSource`：生产模式，唯一允许进入在线编译的实现。

PDF 页码来自下载的原文件；chunk 引用通过 evidence quote 与 chunk 内容归一化匹配得到。唯一命中写 `chunk_id`；零命中或多命中保留页锚点，并记录 `lineage_status=page_only|ambiguous`，不得伪造 chunk 关联。

Evidence 额外冻结 `source_revision`、`file_hash`、`parser_version` 与可选的 `chunk_hash`。同一 `knowledge_id` 修订变化时，旧 Evidence 标记 stale 并产生 recompile ChangeSet，不静默覆盖。

017 T5 已实现纯 whitespace-only quote→chunk 映射、同 `SourceDocument` 来源校验，以及 `linked|page_only|ambiguous` 三态 lineage；T6 已以 0004 迁移持久化完整 audit/stale 字段，并交付生产 `SourceImportContext`、显式 legacy replay、按 source revision 分区、pending recompile 复用、全分区 savepoint 与 validated non-stale refs。来源变化后的 stale mutation、并发 recompile get-or-create 和 scoped retract 仍属于 T7。

## 5. ReleaseSnapshot：单一在线事实视图

现有 Snapshot 只保存 claim/revision 会员关系，不足以冻结当时的 Evidence。新增不可变 `SnapshotFact`，在发布时复制：

- Claim 的值、三态、有效期、置信度与 schema 版本；
- 当时的 Evidence 全量投影；
- product/version 与 scope；
- claim_id/revision_no 用于审计回链。

Wiki 渲染器和未来 MCP 查询都只读取 `SnapshotFact`。不得绕过当前快照直接查询 `claims.status='published'` 作为在线答案。

发布采用可恢复状态机：

```text
building → publishing → published
                    ↘ failed
```

先在数据库内构建 SnapshotFact、页面物化结果和完整 PublishPlan（upsert/delete 写集及补偿动作），再向 WeKnora 幂等执行；全部成功后才移动该 Space 的 CurrentRelease。外部写入部分失败时指针不动，记录 PublishAttempt。failed snapshot 可用同一冻结 plan 显式重试；放弃时 reconciliation 按 current snapshot 精确 upsert 旧页面，并删除失败 plan 触及但 current 不拥有的全部 Harness managed slug，消除半发布状态。若目标 slug 是非 Harness 管理页面，发布前直接拒绝覆盖。

回滚同样先重放旧快照页面，再移动该 Space 指针。MCP 和 Wiki 页面因此引用同一个 snapshot_id。

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
4. **自动化资格**：只有低风险字段且质量画像满足最小样本数、值准确率、幻觉率和证据准确率阈值，才可能自动 add/enrich/supersede。

默认安全策略：`auto_apply_supersede_low_risk=false`。即使配置开启，也必须同时存在匹配 schema/model/prompt/source-profile 的已批准 `QualityProfile`。高风险字段始终人工审核。

首版保守资格阈值可配置，默认：样本支持数 ≥10、值准确率 ≥0.98、幻觉率 ≤0.01、证据准确率 =1.0。阈值不足只意味着“禁止自动发布”，不阻止候选事实进入审核队列。

## 8. 失败处理与可观测性

| 失败 | 行为 |
|---|---|
| WeKnora scope 不匹配 | 立即拒绝并记录 security event |
| knowledge 未完成解析 | 可重试，不开始 Compiler |
| 原件下载或页解析失败 | dead letter；不使用 chunks 猜页码 |
| quote 无 chunk 唯一匹配 | 保留 page evidence，标 lineage 状态 |
| source revision 变化 | Evidence stale + recompile ChangeSet |
| 质量画像缺失或过期 | 自动发布关闭，进入审核 |
| Wiki 部分发布失败 | CurrentRelease 不移动；记录 attempt 并 reconciliation |
| 回滚失败 | 指针不移动，当前在线快照保持 |

所有 run manifest 记录 `space_id/tenant_id/raw_kb_id/knowledge_id/source_revision/schema/model/prompt`，使一次错误可以重放并定位到来源版本。

## 9. 实施拆分与依赖

| Change | 内容 | 依赖 |
|---|---|---|
| 016 | KnowledgeSpace、作用域强制、两阶段迁移 | 007 |
| 017 | WeKnora SourceDocument Bridge、Evidence lineage | 016、004 |
| 018 | SnapshotFact、统一读取、发布/回滚一致性 | 007、016、017（硬依赖） |
| 019 | Golden 工具、QualityProfile 与发布闸门（确定性软件） | 002、004、005、007；merge 接入在 016 后 |
| 020 | gs-v0.1 收尾、13 产品 baseline、judge/dead-letter/keypoints（真实数据运行） | 002、019；运行准入记录 |

016 是所有后续企业能力的前置，现已完成；本地实现证据见 `openspec/changes/016-enterprise-knowledge-scope/validation-report.md`。017 T1～T6 已完成并进入 T7，整体仍在实施；018 硬依赖 016+017。019 的 Golden 工具部分可独立推进，merge gate 接入的 016 前置已满足；020 是受模型环境与预算约束的可恢复数据运行。018、019 和必要的 020 质量画像完成后再启用生产自动发布。B10 的 live WeKnora 部署与契约测试作为 017/018 的最终验收，不再只是演示附加项。

## 10. 非目标

- 本阶段不实现 008 工作台、009 概念层、012 QA、013 MCP UI 或 014 批量控制台；
- 不修改 WeKnora Go/Vue 核心业务代码，除非 live 契约证明现有 API 无法满足且先形成独立上游提案；
- 不宣称当前 Golden F1 已达到无人审核发布水平；本阶段首先让低质量结果无法越过治理边界。
