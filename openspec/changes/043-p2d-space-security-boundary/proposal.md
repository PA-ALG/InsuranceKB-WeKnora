# 043 · P2d Space Security Boundary

> 状态：`SPEC-ONLY / IMPLEMENTATION BLOCKED ON P3 + P1 READ-ONLY FENCE`
> （2026-07-28）。
> 本窗口只冻结 Contract Card、验收规格与未来实施计划；零生产代码、零
> Alembic migration、零测试实现。P3（OpenSpec 039）目前只有规格，实现在
> main 尚未合入；P2d 实现不得据本 change 提前开工。
>
> 权威设计：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> §6.3、§8、§11.1、§13、§16/§16.2/§17，
> `docs/superpowers/specs/2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md`
> §7，OpenSpec 033/C0（034）/P3（039），以及
> `docs/insurance-kb/24-legacy-asset-disposition.md` 的 `db`、
> `model_policy` 与 migration `0003` 处置行。冲突时以上述生产架构设计和
> 修正案为准。

## 为什么做

当前 `knowledge_spaces` 只有 `bound | unbound` 与 tenant/RAW/Wiki 三元组，
不能证明 RAW/Wiki 两端当前 ACL 在受支持角色映射下等价，也不能在 ACL
收窄、tenant/KB 移动或验证不可得时形成可审计的 fail-closed 状态。现行
change 027 `model_policy` 又是硬编码、进程内的过渡 gate：它能拒绝未知/
rolling/强模型，却没有按 Space 版本化的数据分类、provider/model、脱敏、
留存、驻留、工具网络、日志与 renderer 安全合同，更没有数据库 current
pointer 和 ABA-safe epoch。

P2d 是 P3 后的主线安全边界：它必须把「当前可用 Space binding」和「当前
CompilationSecurityProfile」变成 PostgreSQL 中可精确读取、可并发重验的
权威，并给 provider 调用、Candidate 形成与 promotion 提供同一份 exact
snapshot 合同。没有该边界，caller 可以借历史 `bound`、历史 ACL 快照或
旧 profile 在权限撤销/轮转后继续运行。

## 本 Change 冻结什么

1. **KnowledgeSpaceBinding admission 与状态**：每次 admission、
   reconciliation、rebind 或 disable 产生一个 append-only、C0
   content-addressed `KnowledgeSpaceBinding` 版本；Space 保存 current
   pointer + 单调 `binding_epoch`。版本冻结 tenant、RAW KB、managed Wiki
   KB、RAW/Wiki ACL canonical digest、ACL role-mapping version/hash、
   typed state/reason 与 supersedes 链。每个成功/no-op/deactivate mutation
   另写 append-only `SecurityBoundaryMutationReceipt`，使所有幂等结果都可
   持久重放；receipt/request hash 还精确绑定 P3 actor 或 P1 Worker
   authority snapshot，避免跨 principal/job 复用同一幂等结果。
2. **ACL 等价与漂移**：ACL authority 来自当前 WeKnora KB ACL 读取面；
   identity/role/service-principal 类型只消费 P3。两端 digest 在 code-owned
   版本化角色映射下等价才可 `active`；不等价、
   Source/File 出现比 KB 更窄 ACL、无法稳定读取或未知角色分别进入 typed
   fail-closed 状态。发布时快照不构成持续授权。
3. **不可变 CompilationSecurityProfile registry**：每个 profile version
   为 append-only、C0 content-addressed、Space-scoped 记录；Space 只保存
   current pointer + 单调 `security_profile_epoch`。profile rotation/
   deactivation 只改 pointer/epoch，不更新历史版本。
4. **provider pre-call gate 合同**：每次外部模型调用的最后一道同步 gate
   从数据库重读 current binding/profile，并从 WeKnora 重验当前 RAW/Wiki
   ACL digest/freshness，不接受 caller 自报 authority；校验 exact
   provider/model/deployment、资料分类、由 code-owned adapter verifier
   签发的不透明脱敏/标记化/DLP/KMS attestation、retention/no-training、
   residency、fallback、tools/network、prompt/document-instruction、
   renderer 与 logging policy。gate 还必须经 P1-owned **只读**
   active-fence verifier 以数据库时钟重验 job 当前 generation、`running`
   state、attempt 与未过期 lease；授权检查不得续租、推进 job 或写 Outbox。
   constructible `ClaimedJob` snapshot 本身不授予权限。
   DENY 时 transport 零调用；ALLOW 只产生绑定已重验 P1 fence 与 exact call
   scope 的不透明、短期、单次 authorization 和 secret-free decision
   receipt。
5. **Candidate/promotion exact recheck 合同**：P6b Candidate 必须冻结
   binding/profile 的 id/hash/epoch 与组合 snapshot hash；P8 promotion
   在自身 Space 串行事务内重读并逐字段 exact 比较。任何 ACL/profile
   变动（包括 A→B→A）使旧 Candidate `stale/superseded` 并 requeue，绝不
   发布。
6. **单一事务/并发边界**：binding pointer 与 profile pointer 的所有变更
   都锁同一 `knowledge_spaces` 行、以 caller 的 expected pointer/epoch 做
   CAS、在同一 PostgreSQL 事务中插入不可变版本并递增对应 epoch。跨 Space
   pointer 由 composite FK/约束在数据库拒绝。
7. **唯一 migration 所有权**：未来 P2d 实现独占 migration id `0016`，
   恰好一个 migration 文件；`down_revision` 在实现时必须指向当时 main 的
   真实 single head。当前 spec 窗口只在台账占号，不创建 migration。

## 关键裁决

采用「append-only 版本 + Space current pointer/epoch」而不是：

- 把 ACL/profile JSON 原地写进 `knowledge_spaces`：会丢失历史内容身份，
  无法做 Candidate/promotion exact replay；
- 只信任外部 IAM/DLP/provider 配置：无法给本地事务、Candidate digest 与
  promotion 提供一致的 current authority；
- 为每个 Claim/Evidence/Page 传播 visibility label：WeKnora 当前证据证明
  ACL 粒度为 KB × capability，本轮按已批准 MVP 方案对更窄 ACL 直接
  `acl_scope_unsupported` quarantine，不扩成逐 Claim ACL 系统。

线性化点冻结为：Space current pointer/epoch 变更在 PostgreSQL 提交时生效；
provider call 以 transport dispatch 前最后一次数据库 authority + 当前
WeKnora ACL/freshness recheck 为 pre-call 线性化点。该点之后才提交的
profile rotation/ACL 变化不追杀已 dispatch 的网络请求，但会使其后续
Candidate/promotion exact recheck 失败；receipt 必须记录实际使用的旧
epoch/profile/ACL digest。实现不得为了跨外部网络持有长事务锁。

## 依赖与阻断

- **P3 contract + implementation 硬依赖未满足**：P2d 只消费 P3 的五个
  人类角色、两个 scoped service principals、唯一 principal 铸造/能力检查
  入口；不得复制身份模型或建立 principal 表。当前 OpenSpec 039 的
  `source_reader` 只读 RAW Source/chunk/artifact，`wiki_projector` 只写
  managed Wiki，**没有可读取 RAW+Wiki 两端 ACL 的 authority**。P2d 实现
  必须继续 `BLOCKED`，直到单独的 P3 amendment 冻结并实现一个 P3-owned、
  least-privilege ACL-inspection authority（或等价 authenticated human
  delegation）；P2d 不在本 change 发明第三个 service principal/capability。
  provider 调用本身使用 P1 fenced claimed-job context，不把
  `source_reader/wiki_projector` 权限放大为模型调用权限。
- **P1 read-only fence contract 未满足**：当前 P1 public `heartbeat` 会在
  成功时续租，不能作为“授权失败零写”的 verifier。P2d 实现继续
  `BLOCKED`，直到 P1-owned public contract 提供只读、DB-clock、current-row
  的 active-fence verification；P2d 不得自行读写 `wiki_jobs`，也不得把
  heartbeat/状态推进包装成授权检查。
- C0 已在 main：binding/profile/snapshot/decision digest 全部使用
  `CanonicalEnvelopeV1` + `canonical_hash`，不得另造 JSON/hash。
- P1 已在本 spec base `40f3ae9e` 合入；P2d 正确性采用 pull-based exact
  recheck，不依赖新增 Outbox 或 Candidate 表。
- W0 证明当前 ACL 是 KB × capability，且无 Source/knowledge 级 ACL；
  W1 实现尚非本 change 前置。P2d 不解决 W1/Tencent 上游债务。

## 与存量资产的切换

- `knowledge_spaces.tenant_id/raw_kb_id/wiki_kb_id` 与既有唯一约束保留为
  current mapping 的兼容镜像；新路线的 security authority 唯一来自
  current `KnowledgeSpaceBinding` 指针/epoch。镜像只允许在同一 pointer
  CAS 事务中同步，不能单独铸造 active authority。
- migration 不把现有 `binding_status=bound` 自动提升为 `active`，也不把
  存量 ACL 猜成等价。没有 current active binding 的旧行对新生产入口
  fail closed，必须显式 admission。
- change 027 的 provider deny-only 安全核按
  `docs/insurance-kb/24-legacy-asset-disposition.md` 记录 provenance 后
  移植为 P2d adapter；P2d current profile 成为唯一 allow authority。
  旧入口不得继续独立签发 allow。物理删除和历史数据清理另立 change。

## 明确非目标

- provider/transport SDK 实现、真实模型调用或 provider live 验收；
- 逐 Claim/Evidence/Page ACL、visibility label 与交集传播；
- 通用 DLP/KMS/secret/residency 平台；只定义版本化 adapter contract；
- P11 managed-page Go patch、managed GET/search/cache RAW ACL guard；
- Candidate、ReviewDecision、promotion、Release、requeue 的生产实现；
- principal/role/service-account 定义、持久化或身份联邦（唯一归 P3）；
  本 change 只记录 P3 ACL-inspection authority 缺口，不替 P3 定义它；
- P1 job 状态、lease、heartbeat 或 active-fence 的实现（唯一归 P1）；
- 历史 binding/profile 数据清理、旧表/旧模块物理删除；
- W1 或任何 Tencent/WeKnora 上游债务、UI/MCP/业务查询面。

## 影响面与预算

本窗口只新增 OpenSpec 043、一个 spec-only plan、validation report 与
README 台账行。未来实现限制：

- logical files **≤15**（包含 migration、测试和实现期文档回写）；
- 生产代码目标 500–800 行；**超过约 900 行必须停止并重新切分**；
- 恰好一个 Alembic migration `0016`；出现第二 migration、第二身份模型、
  provider SDK 或 Candidate/Release 表即 scope 违规；
- P2d 属 033 §16.2 强制 PostgreSQL 并发面，未来实现必须通过 PostgreSQL
  16 lane；SQLite/deterministic 单测不能替代 PG16。P2d 的 read 交付只到
  current RAW ACL guard/verifier；P11/P9a/P9b/P13 各自负责在 managed
  GET/search/cache/API/MCP/UX 入口接线并做端到端零泄漏验收。
