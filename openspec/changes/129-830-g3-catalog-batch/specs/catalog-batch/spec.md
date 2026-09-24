# G3 · 目录与批次合同

## ADDED Requirements

### Requirement: G3-R1 工作簿无损目录
系统 MUST 从 B0 持久 v5 工作簿实测 hash 编译 11/11 版本化 pack；字段计数 67/70/62/67/66/75/79/82/74/83/76，按工作簿字段名统计 154 去重、47 全产品共有。统计同名不等于共享语义身份。各 pack 保留 11 列原值及 sheet/row；字段 key 使用原英文名，身份由 pack+key 限定，语义 hash 包含说明/取值/来源等，不仅按名字合并。必选意味着 attempt 及三态独立页，绝不补造非空事实。

#### Scenario: 真实工作簿导入与重算
- WHEN 编译 exact v5 输入及冻结映射配置两次
- THEN 每包数据及 Catalog hash 一致，11 包计数及全部元数据可回放，错 hash 或遗漏/重复字段拒绝。

### Requirement: G3-R2 独立展示 Profile
系统 MUST 复用 presentation-profile.v1 的有序 sections/fields 合同，每 pack 独立 id/version/hash；FieldDefinition 不保存 presentation_section。映射只由 Profile 拥有，业务分类不直接用作 UI 目录；每字段恰好一次主映射、空 section/孤儿/重复为零。Catalog entry 绑定 exact pack 和 Profile，包内容 hash 不循环依赖 Profile hash。所有 Profile 先为 PENDING_PRODUCT_OWNER_CONFIRMATION；结构生成不伪造具名产品负责人整包确认，质量持续 DEFERRED_TO_Q0。

#### Scenario: 多节点及重排
- WHEN 使用非医疗可变节点配置或重排展示
- THEN 通过同一 Profile validator，字段 key 和语义 hash 不变；孤儿/重复/空节点确定性拒绝。

### Requirement: G3-R3 既有平台目录接线
系统 MUST 用既有 WeKnora 目录/页面/审核链读取 Catalog/Profile 及同版字段值、条件、来源；保持 legacy 医疗链，禁止第二 Wiki。注册目录不得冒充内容 Release 或质量准入。

#### Scenario: 目录与隔离知识分层
- WHEN 打开 11 包目录及已选 pack 样本映射
- THEN 可核对 pack/profile identity；未质量准入知识不得发布生产；未发布 Candidate 不进入正式搜索。

#### Scenario: 多产品候选复用同一发布链
- WHEN 批次自动身份结果进入 G3 候选编译
- THEN 按 `docs/insurance-kb/evidence/830-g3/lane-d-consolidated-contract-v2.md`（SHA-256 `75c81f582b2ace94efba6d016f0d24c00eb3e10a836f6673612bb7aaa3bfb94d`）严格验证完整 Catalog、确认回执、C 输入及结果、每实体 binding、原 G2 base request、模型 delta/机械合成/独立审核记录与同一 page manifest。
- THEN 反序列化请求必须逐一绑定 exact C child 的身份 anchors、entity/version key公式和所选证据；确认回执同时锁定真实文件及语义hash；C/base同 SourceBlock identity 不同完整内容必须拒绝，即使调用方重算全部外层hash（集中修复合同 `lane-d-python-repair-1.md`）。
- THEN D source集合严格为全部已选C材料blocks与actual base carry证据blocks的canonical并集；owner字段校验允许其所选材料、其自身carry及实际关联concept的证据来源，拒绝跨owner借用。按 `lane-d-source-coverage-design-2.md`（SHA-256 `ec64c6b90d2504b481686fc071ce1f6ed2bcf218339efafff8119aa6f7e21716`）同时校验请求与delta，主342样例包含身份块外的保障正文块及对应字段Evidence。
- THEN 所有既有实体必须有实际 C 自动 MATCH；新实体必须有实际 C 自动 CREATE，不增加主数据注册前置；缺失资格在编译及 Draft 前拒绝。
- THEN 首切片正向和容量 fixture 使用 actual G2 base 两医疗实体与重疾、两全、意外三新实体，合计 342 个标准字段页；完整 POST 使用真实 serializer 测量且不得超过现有 8 MiB，容量闭合前不得实施 handler/service/UI。
- THEN 旧 134 行 existing input 原样进入 request；132 行事实逐字继承，仅按修订6冻结的两行 exact unknown-only lineage 对齐旧单数 key 到新 Profile key，旧 Release 不变；每医疗仍恰好 67 页，禁止额外 legacy 页或删 base 压缩容量。
- THEN Active概念页复用现有concept-page-read.830.g2.v1 envelope；G3 overview related从sections字段引用严格构造同版同owner集合，G3服务端拒绝冲突查询。按 `d-active-page-transport-clarification-1.md`（SHA-256 `26189ef0159da209926d24d14b59939b0688924febd55c221b2e6b9b1536ed26`）分派，旧G2行为不变，Preparation仍用独立冻结响应。
- THEN 按独立复核的 `lane-d-downstream-execution-plan-1.md`（SHA-256 `a5cbf39c74f2bd26d52590580b7d2a059858d2951577614ad1cae3ed8727f3ab`），G3在落Draft前调用同一source verifier；仅G3允许create-draft operation且此时PreparationDigest为空/非存储权威；Review/Activate使用真实存储digest，G2 operation集合不变。
- THEN 按 `d-preparation-alignment-display-clarification-1.md`（SHA-256 `5e12a1e0f81677986aa8483c79e6376f9266b410655564be8ee96ec858b0daab`），前端不内联租户entity/release/member标识；在鉴权preparation后从expected base pin经现有双KB ACL historical search派生旧成员，并与当前manifest验证两行展示绑定。完整14字段lineage仍由服务端重验，不扩响应DTO，不以当前Head替代历史pin。
- THEN 使用既有 Draft/Ready/Review/Activate 和唯一 Head CAS；preparation 与 active 读取分开，真实 source authority 在 Draft/Review/Activate 按原 G1/C5 链重开；fixture 不替代实际模型、来源或业务验收。

### Requirement: G3-R4 批量身份与材料采信
系统 MUST 在后续同 G3 切片冻结 10–15 真实材料/revisions 和 Seed 标签来源，分别冻结 identity/classification 阈值，证明 MATCH/CREATE/MULTI/NEEDS_CONFIRM/QUARANTINE 真实场景。明确高置信自动 Candidate，歧义/版本冲突隔离；配置式 TrustPolicy 按来源、字段、版本、作用域、有效期求值，不以上传次序或模型自信提权。

#### Scenario: 自动与隔离
- WHEN exact 身份及依据满足独立阈值
- THEN 幂等 Candidate 沿唯一链形成；多实体有独立 Evidence，低置信/冲突不静默 MATCH。

#### Scenario: 真实多行正文与结构化身份分离
- WHEN C Corpus/Evidence 或 D 内联旧 G2 正文含 TAB、LF、CR
- THEN 按 `cd-multiline-canonical-amendment-7-v2.md`（SHA-256 `975ae956c2c851b8f8fffffbffd5bbbebb6b4051fa031237db3c0afb224f9380`）复用既有 G2 正文 canonical，保持 G3 domain/prefix 与合法旧向量 hash；不清洗原文、不改变 Catalog/G2 shared helper。
- THEN C 构造/重验在 typed 对象转字典前递归拒绝全部嵌套结构化字符串的控制字符，唯 exact SourceBlock.text/Evidence.quote 为正文豁免；D 沿该修订的 G2 正文与 control-free 身份边界，Python/Go 同时拒绝非 ASCII 域。

#### Scenario: 直接消费当前来源登记回执
- WHEN 真实来源已通过现有 knowledge-revision-source.v1 HTTP 登记
- THEN 按 `c-source-registration-amendment-8.md`（SHA-256 `0b2e924174e4ea31143f369dcf9ec2479a1f01e003b29e0f84cf188ddaf7dc66`）接入 exact 14-key 镜像，与原 LiveReceipt 组成严格 contract discriminated union；不伪造 admission/resource/self-hash 字段，不新增历史 admission 前置。
- THEN Registered scope 由实际 authenticated acquisition 与 BatchCorpus 绑定；来源校验、信任规则、候选 key 与重复来源 key 同步使用明确分支；Legacy 校验不变，D 继续重开服务端完整 source authority 与旧 G1/C5 carryover 链。

### Requirement: G3-R5 分类稳定与真实隔离验收
系统 MUST 保持重分类前后实体/字段/Evidence/历史身份，复用 G2 概念/free_wiki 与原始质量记录。G3 PASS 只由全卡真实批次、11 包注册、对应独立字段页与来源/搜索、具名结构确认和独立复核共同产生；QUALITY=DEFERRED_TO_Q0。

#### Scenario: 完整结果门
- WHEN 只通过本地 Catalog 测试或只生成 Profile Candidate
- THEN G3 仍 WIP；真实批次、具名确认、平台/隔离 Release 未执行项明确 NOT RUN。

## 2026-09-12 用户批准的有限修复

G3-P1：已发布读取复用既有不可变成员与固定来源定位，正常GET不重验整批候选、不调用DocReader；完整校验留在准入/发布及一次历史补建。缓存/投影绑定发布及来源版本，当前权限与目标身份逐请求检查。旧第6版保持不变。验证同字段/引用首读、重复读、进程重启复用及拒绝越权/版本漂移。root独占release/schema读取与repository/types必要小适配，g3_source_reuse独占concept_source_authority与来源复用小文件。

G3-P2：已有代码+备案号版本不因version_label缺项误挡，m07/08分别保留；m02/04/18利用现有证据关联，m09不同公司隔离，m19不确定适用性保留待办；m21完整多实体识别。只重跑受影响任务。

G3-P3：复用现有状态/检查点/幂等机制实跑小批与一次中断恢复，已完成任务不重复模型调用、不损坏第6版，结果不明调用先对账。Q0质量、大规模长稳和G4不在本轮范围。

用户已批准上述顺序和本机修复/部署，不另建Mission、冻结包或再次申请授权。测试与必要独立审查后推进实际验证，状态随实际结果填写。

### 2026-09-12 收尾接续授权

用户确认执行容量、恢复、读取、启动、歧义处置及修订发布六项遗留处理。既有第6版作为不可变历史保留，允许通过现有 Candidate/Review/Activate 形成新的隔离版；此前“第6版保持不变”不再解释为禁止新的授权发布。具体写域、验证与原卡完成边界见 `docs/superpowers/plans/2026-09-12-g3-final-closeout.md`。继续复用原 P1—P3 与 R1—R5，不新增产品 Goal 或生产验收门槛。

### 2026-09-13 用户授权的两款增量验证

用户要求从原始产品目录另挑两款新产品跑流程，并优先按首页完整产品名定位Schema。本次选择福满分1820年金与爱满分1818两全，执行计划见 `docs/superpowers/plans/2026-09-13-g3-two-new-products.md`。G3-INC1—4补齐实际发现的增量base、可组合分类复用及清单执行接线；旧第9版与493字段完整保留，新增材料才发模型。此前G3原固定批次FLOW PASS保留为历史真实结论，不能扩大为新增任意产品入口已通过。


## 2026-09-13 G3 platform-independent closeout amendment

G3-AUTO-3/4/6 compilation durability clarification (2026-09-15, Task3as): workflow v2 MUST commit the platform-generated canonical candidate as a successful compilation artifact before the separate preparation submission stage. A rejected submission MUST retain that exact candidate for inspection and dependency-scoped recovery; recovery MUST NOT regenerate it or resend completed model work. Existing v1 run/plan contracts retain their stage order and combined compilation semantics. Run workflow versions are explicit, immutable after creation, and bound to checkpoint contract; legacy successful compilation may be recovered without inventing a new completed stage. New workflow publication requires the preparation stage in its barrier. Original source/field/raw evidence and platform authority checks remain mandatory; no Codex-created candidate or continuation qualifies as acceptance.

G3-AUTO-3/5/6 cold-read clarification (2026-09-15, Task3ar): the existing published-base comparison MUST accept equivalent empty optional collections after signed cache deserialization, including definition aliases; field evidence/concept_ids/conditions/exceptions; page concept_ids/conditions/exceptions. Member counts/order, nonempty collections, scalar values, required evidence, locators, source/version authority and signed history MUST remain exact. Comparison must not mutate original candidates, signed projections or hashes. Both a cold persisted projection followed by incremental base validation and the existing transfer-to-draft entry require coverage; a cold read of member indexes alone is insufficient. This fixes compatibility within the existing authority, not a new approval or publication path.

G3-AUTO-3/4/6 checkpoint clarification (2026-09-15, Task3aq): enqueue control inputs have producer_generation=0 and MUST NOT count as completed stage outputs. Both locally selected and inherited references in a newly admitted checkpoint must be actual executed outputs (producer_generation>0); required output coverage, scope, digest, dependency and producer fence checks remain mandatory. Existing plans and failed terminals remain immutable. Recovery from a failed verifier must apply the same selection boundary. A required artifact available only as zero-generation control input cannot satisfy a completed stage. Validation and deployment remain separate from the failed Task3ap real webpage trial.

User replaces Codex-assisted closeout with G3-AUTO-1 through G3-AUTO-6 in `docs/superpowers/specs/2026-09-13-g3-platform-independent-design.md`. These stable Requirements are normative for this closeout: platform-only orchestration; nonblocking ordinary field failures with raw retention; persistent dependency-scoped reuse; durable observable tasks with terminals and field retry; real deployment plus scoped system-policy review/publish; original/page/evidence custody. The earlier ban on additional service/store implementation is superseded only as necessary to extend the existing Harness service shell and job persistence within the sole WeKnora serving authority. No production release or second authority is authorized. New acceptance is one untouched platform product, three webpage uploads; no Codex processing/continuation, and measured upload-to-search/evidence time. Existing fixed-batch/assisted evidence remains historical and cannot prove this requirement.

### Task3at amendment (2026-09-15, G3-AUTO-1/3/5/6)
Incremental platform compilation SHALL preserve the published parent's navigation assignments byte-for-byte in their typed values, including assignment version and hashes, and include them in the new page manifest/candidate hash. It SHALL NOT recreate classification or silently erase navigation. Artifact producer contract revision changes SHALL invalidate only that stage and its descendants at recovery admission, using the existing metadata fields; unchanged earlier extraction/source results SHALL remain immutable and reusable. Current candidate artifacts use product-candidate.v2/version2; old v1 candidates are audit-only inputs for this corrected compiler. No new database/environment or manual real-candidate repair is authorized or required.


### Task3au amendment — G3-AUTO-1/3/5/6
The source authority must select live corpus materials using the existing current-resolution binding contract, including current MATCH/refresh on existing entities. Carried published bindings do not require retransmitting their materials in the current corpus. All existing source/evidence revocation, exact published-base and custody checks remain mandatory; missing current materials fail closed. Source selection must reuse the same types decision used by candidate validation. No historic candidate mutation or model replay is permitted.


### Task3av bounded configuration — G3-AUTO-3/4/5/6
The existing isolated platform connection may use its supported timeout_seconds=300 for one configuration verification after the 120-second transport failures reach terminal state. No source gate or model policy changes; no build or database migration. Preserve the existing three-attempt job policy and report it explicitly. Exact one-scalar configuration diff, unchanged images, terminal/no-active-work guard and normal webpage recovery are required. This is not a performance acceptance pass.

### Task3aw recent G3 evidence baseline — G3-AUTO-3/4/5/6
An incremental candidate shall reuse the latest exact published G3 projection and its already sealed legacy evidence occurrences when available, without replaying complete G3/G2/G1/815 ancestors. The existing release authority validates scoped release/epoch/preparation/member identities and the existing derived-artifact owner verifies the parent proof signature/key. Only unchanged factual fields and exact source/evidence occurrences may inherit proofs; existing navigation extension and optional-empty semantics remain valid. Live deletion, revision/resource/retention and source revocation checks remain mandatory. Missing baseline artifacts may use the established preparation path; corrupt or foreign artifacts must fail closed without replacement. Existing files, model outputs, candidates, proof bytes and the single serving Release authority remain preserved. This amendment changes neither provider policy nor ordinary-field completeness requirements.


### Task3ax — 普通字段定位验证与有效状态（G3-AUTO-2/3/4/5/6）

字段文本校验成功不代表单页定位成功。平台在编译前消费原签名解析快照的页范围与字符定位，复用815/G3已有一字段多证据结构，将可精确映射的跨页引文投影为多条单页引用；原文和页间空白完整保留在原记录及映射审计中。跨页本身不是字段失败。只有无法满足精确来源/定位要求的普通字段持久记录为抽取失败，不保留未经验证的有效值；原响应与原字段记录不变。有效字段读取、统计、重试与发布消费同一验证产物。验证合同变化仅使相关派生产物失效，恢复不得重新外发已完成抽取或为普通字段触发发现模型。具体冻结范围与验证队列见2026-09-13实施计划Task3ax。
# Task3ay：G3-AUTO-3/5 激活已验证结果复用（2026-09-15）

自动激活在当前来源与权限校验后，必须复用同一 Ready preparation 已验证并签名的投影，
不得在原子发布前重复完整语义编译。投影须绑定原scope/preparation/manifest全部字节及成员；
缺失或损坏不能作为跳过校验的理由。现有签名、来源撤销、当前双KB权限、策略有效期、
expected Head和CAS/幂等回执保持有效。验收区分重复校验计数器测试与真实部署网页恢复；
失败任务不得以代码通过或临时发布脚本冒充完成。

### Task3az — 已发布阅读结果复用（G3-AUTO-3/5/6）
同一页面会话、同一确切发布版本内切换字段，平台 MUST 复用已验证目录和 Schema，仍通过当前权限检查读取目标字段；不得每次重新下载整批目录。切换版本、读取失败或页面销毁 MUST 清理对应复用状态，异步旧响应不得覆盖新页面。
原文阅读 MAY 在当前页面内保留单个有界、已校验摘要和页数的 PDF 文档，但每条引用 MUST 重新核对当前引用权威和来源；仅当完整scope、发布、候选、来源版本、文件摘要及绑定一致时复用。错误、过大文件、替换及卸载 MUST 正确释放资源，未经验证的字节不得进入可复用状态。此能力不引入模型调用、重新解析、发布或新环境。首次读取和重复读取分别实测；前端缓存不能替代对后端冷读异常的定位。

### G3-AUTO-3 Task3ba checkpoint effective validation view
Checkpoint delta comparison MUST use the authenticated persisted field_validation effective view when synthesis is reused, including nonempty validation changes. Report input identities and original row digests MUST be validated by the existing apply_field_validation function. Checkpoint receipts MUST retain original immutable field digests. Invalid reports MUST fail closed; recovery MUST NOT reextract or rewrite completed data. Regression uses a completed real fixture pipeline and a nonempty ordinary-field validation failure, then resumes unchanged candidate with zero new model calls.

Task3az deployment artifact invariant: public frontend static output MUST be readable/traversable by the nginx worker regardless of the builder's umask. Enforce modes only for /usr/share/nginx/html in existing Dockerfile. Verify actual runtime user read before replacement; reuse byte-identical previously compiled assets, no new Vite compilation.

### Task3bb — G3-AUTO-3/4 bounded reconciliation selection

The repair scan MUST exclude authoritative terminal run history before hydrating material/field/artifact payloads and return only scoped run identities and keyset timestamps. Current progression validation, outbox and lease recovery remain mandatory. Failed child stages without a terminal run/root/finalization MUST remain discoverable for finalization. Explicit history reads/recovery, original results and states MUST remain unchanged. This reduces idle work; live read latency requires separate measurement and cannot be inferred from fixture success.

### Task3be — G3-AUTO-1 explicit identity extraction guidance

The identity prompt MUST distinguish full legal issuers from abbreviations when both are locally evidenced, and MUST recognise explicit edition tokens in formal product names as version labels with offered version evidence. It MUST NOT invent missing issuer/version values or bypass genuine conflict decisions. Existing raw response, evidence and deterministic admission contracts remain unchanged. Real provider recovery and uninterrupted fresh-upload acceptance are separate outcomes.

### Task3bf G3-AUTO-3/6: resident source proof reuse

A citation reader SHALL reuse complete first-parse binding validation only for the same owned resident record and exact authenticated first payload. Every warm read SHALL reopen the artifact and verify current signature authority and payload bytes; missing/changed artifacts, revoked keys and newly appearing first artifacts for legacy entries remain failures. Cold/unproved/copied records retain full semantic validation. No read-triggered parsing or model call is introduced. Allocation and real webpage timing evidence are reported separately.


### Requirement: G3-AUTO-1/3/4/6 Task3bg offered issuer and explicit recorded identity retry

The existing first-page identity selector MUST prefer an available legal-company block within the same material and existing page<=3 allowance over generic first-page company language. It MUST keep page-local locators, one auxiliary block, and the existing broad fallback when no legal-company candidate exists; no issuer aliasing or raw-result rewriting.

The existing public checkpoint mechanism MUST allow explicit webpage recovery of a fully recorded terminal semantic identity failure after successful uploads/source/routing, without re-parsing or embedding completed sources. Checkpoint v3 separates the failed identity call proof from reused-success calls; workflow remains2. The worker MUST revalidate original request/raw bytes and producer/scope/dependency/source proofs, then the existing identity handler makes one fresh recorded call. Unknown/interrupted/corrupt calls, active or foreign producers and unrelated later work remain ineligible. Polling never initiates retries. Expected-version and idempotent child creation remain mandatory.

Checkpoint v1/v2 encoded bytes and hashes MUST remain exact; v3 metadata uses revision3, rejects duplicate/intersecting references and retains the128KiB bound. Failed checkpoint recovery carries its verified retry reference; failed identity is not counted as reused model success. Existing artifacts and failed-run terminal state remain immutable. Recovery is a separate result and cannot convert the failed fresh acceptance into uninterrupted PASS.
# G3-AUTO-6 clarification — partial native PDF locations (2026-09-16)

Readable text MUST NOT be discarded because individual glyph geometry is invalid or unavailable. Complete captures retain v1 identity and bytes. Partial v2 captures preserve exact text, pages, hashes and valid boxes, plus explicit unavailable non-whitespace ranges with reasons; transport, persisted evidence indexing and Harness must verify complete, disjoint box/gap coverage. Normal quotations remain eligible; quotes touching missing geometry are not issued a fabricated highlight, and ordinary fields use existing extraction_failed handling. Parser-returned deterministic failure remains a terminal document outcome; transport failure retains bounded retries. Source integrity/unreadable content errors remain explicit. This is an authorized G3 repair, not a page-only publication contract or a new processing service. Actual fresh acceptance failures remain failures.

# G3-AUTO-3/4/6 clarification — consolidated recovery and bounded reuse (2026-09-16)

Within the existing authorized G3 task, successful immutable parse/field/candidate artifacts MUST survive later failures. Recovery MUST validate only the successful prefix it reuses, reconcile uncertain native reparse submissions and reprocess only failed bound documents. Each wait has a terminal deadline; completed siblings remain unchanged. Call statistics must retain failures and reuse independently of source-stage success. Current successful document status must not expose a previous attempt's error as its current failure.

Canonical text validation and allowed-source routing MAY share validated work within one input boundary without changing bytes, identifiers or evidence. Source-authority checks MAY reuse a fully verified immutable artifact/index within one verification operation; current scope, ACL, source lifecycle and binding checks remain mandatory. New requests cannot inherit unchecked first-parse file proofs. Worker diagnostics distinguish event-loop delay, executor wait, heartbeat database duration and lease reclamation; generation fencing and unknown external-call protection remain mandatory. No ordinary missing field triggers automatic supplementary calls.

The current Codex-assisted diagnostic run is not independent-platform acceptance. All identified in-scope fixes are locally tested/reviewed as one batch before rebuilding affected components; native parsing and unaffected services are reused. Review/publication/search remain NOT RUN until their real prerequisites and live checks succeed.


## 2026-09-16 Task3bm — 用户确认的六项集中收尾（G3-AUTO-1—6）

执行边界与Owner见docs/superpowers/plans/2026-09-16-g3-consolidated-closeout.md。正常新产品3186网页全链实测PASS不关闭技术恢复、增量和性能缺口。重复上传须有先持久的输入指纹/数量及existing ProductMaterial关联，不覆盖历史metadata；未知保存由exact-scope lookup核对。故障恢复由durable job/call状态和依赖判定，不以人类错误消息前缀决定；已记录HTTP失败的显式重试与自动重试区分，未知发送禁止盲重试。原生失败单文件恢复沿Task3bk原子expected-attempt/receipt边界完成。来源/成员与已验证已发布投影完全相同时可复用不可变证明，所有新请求仍核当前权限、来源生命周期/修订/资源绑定，变更走完整校验；不删校验换性能。discovery按实际序列化预算分窗，原响应/覆盖审计保留，最终审查绑定最终输出。状态以finalization为权威、wall历时包含重试并分开最后attempt；统计未知不得记零。集中RED/GREEN/独立复核后统一部署受影响组件，再网页重验正常、增量和恢复三类；普通字段缺失不补抽、不作为发布阻断。


### Task3bm 用户追加：独立自由发现（2026-09-16）

**G3-DISC-1**：Schema字段抽取和自由发现具有独立任务、输入、结果、状态及恢复。自由发现基于原文、实体身份、紧凑已有知识索引发现有证据的新增概念/知识及页面关联；不得依赖field_delta或以Schema字段清单选择原文覆盖范围。编译汇合后仍经既有审核和唯一Release发布；独立review绑定最终真实输出hash。

**G3-DISC-2**：Schema已有字段及同义概念（即使当前字段未提供/抽取失败）不得生成重复自由页面。模型排除和服务端准入均执行该规则；已有概念可以被关系链接引用，不能复制正文。语义无法确定的候选保留待审处置及证据，不发布未经验证的重复页。

### 2026-09-17 Task3bn — 本轮真实网页验收发现的同批修复

沿用 G3-AUTO-1—6/G3-DISC-1/2，无新环境或发布权威。2648-1 三份材料正常网页链路已由平台独立发布（faf5182c，845.414秒），不覆盖随后重复上传、身份恢复和独立发现的失败。

- 生产组合适配器必须暴露既有 exact-scope 文件指纹查询；重复上传通过真实组合路径关联原有成功来源，不改旧 metadata、不重新解析。确定的本地接口/参数错误不得按远端暂态盲重试至一小时。
- 模型语义 JSON 边界允许整个响应为单一 json Markdown 代码块，仍拒绝额外 prose、多块、重复键及非有限数字。字段、发现生成、独立审核及已记录回放共用严格解析；原始响应、hash和调用记录不变。
- 发现统计区分实际已发送覆盖与通过投影覆盖，失败不能把已发送字数写成零；Schema字段同名、既有概念别名及模型审核认定的同义概念均不得重复发布，包括unknown/failed字段。
- 已终态且发现技术失败的 workflow3 任务具有单独的网页恢复操作；持久child复用有效 uploads→synthesis前缀与已记录窗口响应，从discovery继续。不得要求补抽普通字段、复用未知调用或直接使用过期发布基线；当前Head变化按已有增量合成校验，不手工拼候选。
- 任务列表和频繁轮询不得重装所有历史任务的完整审计；详细阶段/字段/来源/回放记录按任务按需读取。调用数未知必须显示未知。保留原详情与证据能力，不能以裁掉审计换取正确性。
- 1835恢复的已记录归并响应与原来源先离线复现，身份歧义必须绑定真正冲突证据；材料缺少保险公司或代码时可依据同批唯一且经验证的完整产品名/版本关联主体，真正同名多主体/版本冲突继续待确认。不以产品硬编码或手工结果接续。

本轮先完成正常、重复、恢复边界观察，再统一RED/实现/复核并仅部署受影响组件。5～10分钟仍仅是优化目标；当前发布阶段耗时和规模限制如实记录，不为追求时长删除校验。
### Task3bn 恢复中父响应的有效性（G3-AUTO-3/4、G3-DISC-1，2026-09-19）

显式恢复的发现任务 SHALL 先按当前相同解码及投影规则核验已记录父响应；合法结果复用，仍属技术格式/证据结构失败的单元才允许一次新的子调用。原响应与失败原因 SHALL 保留，新调用失败 SHALL NOT 在同阶段无限重试。未知发送仍阻断，合法PENDING/REJECTED不是技术失败。Schema字段成功结果不重抽，单json围栏经软件修复后合法的父响应仍可直接复用。


### 2026-09-22 recovery lifecycle clarification — G3-AUTO-3/4/6

Append-only source processing audits can be saved before the source stage's final successful execution. They MUST remain retained and readable, but MUST NOT be selected as final stage outputs in a recovery checkpoint. Reusable final outputs retain exact producer/dependency/final-generation checks; this change does not relax job fencing.

Checkpoint validation has one service entry responsible for stored proof, current source, Catalog/Schema and current published-base dependencies, returning drafts for the existing fenced stage adapter. Its safe failure code identifies the failed boundary without exposing provider, configuration or raw exception text.

A recovery of a historical G3 workflow2 run after an unrelated Head change MUST preserve workflow2 and reuse validated fields without adding discovery or new field calls. A new versioned checkpoint may explicitly record this execution workflow; v1–v6 wire bytes and original rows remain immutable. Only after a validated rebase receipt may the execution view select the rebased field-only request/delta and exclude historical discovery-derived outputs/reviews; the original records remain audit evidence. Unchanged-base recovery preserves prior semantics. Changed-base recovery invalidates compilation and subsequent outputs, with all four rebased inputs and the receipt persisted under one fence. A subsequent recovery validates and reuses that same chain. Unknown model sends still block relevant redispatch. No new database, service, migration or serving authority is added.

Validation uses the actual generation3/4 audit failure and workflow2 epoch11→13 failure as representative boundaries, first repository/worker RED→GREEN and read-only stored-record checks, then one consolidated deployment and real webpage acceptance. Offline diagnostics cannot count as platform execution or G3 completion.

### 2026-09-22 公司确认归并（G3-AUTO-1/3/6，root唯一写者）

复用现有可信ResolutionPolicy、v3联合身份解析和Go发布复核；缺口为有原文支持的公司简称与正式名称缺少可审计等价声明。新增可选issuer_aliases策略项（canonical_name、aliases、space_ids、confirmation_ref），精确归一比较且限定Space，声明和策略SHA持久进入现有resolution inputs。用户2026-09-22确认“这些都是平安人寿的产品”作为本批声明出处；原文、模型值、原响应及每份材料的证据归属均不改写。派生决定可使用规范名称，不能把声明伪装成PDF证据。未配置时省略字段并保持历史策略原字节/哈希，显式空/null配置拒绝；禁止同Space重叠别名或链式映射。无新表、权限系统或审批入口。

现有名称/代码/版本/来源校验仍生效，不能通过公司声明补造产品身份。Python解析与Go发布重放采用同一策略等价语义，v3联合决定消费规范名称，旧无映射策略结果保持不变。唯一Owner=root：batch_entity_resolution_830_g3.py、g3_evidence_identity_v3.py、新增issuer_aliases窄合同模块，Go对应types/identity v3及必要测试/固定跨语言向量；配置仅在原Space现有trusted policy更新。先真实同响应离线贯穿，核实旧发布和恢复兼容，再同引用规范化合并一次APP/Harness部署，UI/DB不变。网页恢复才计业务结果。

验证：原文支持的简称/正式名称互补→同一候选；未声明/跨Space/真实公司或版本冲突→不自动归并；原proposal原字节不变；旧policy哈希不变、新声明篡改拒绝；Python生成输入/决定/绑定由Go完整重放；已有模型与来源复用，失败原记录不删除。

策略语义明确化：非空issuer_aliases产生新的policy identity，其精确等价比较适用于消费该新policy的解析；v3联合归并才生成canonical issuer的共享anchors/candidate。旧无映射policy和旧v1/v2结果原字节不变，不要求新策略在旧编译器忽略自己声明。已有compile_request的旧checkpoint对不同policy保持fail closed；本次368c在identity失败，无compile_request，可复用原模型raw和来源。

### 2026-09-23 G3.5 — 自由发现与知识准入（用户新授权）

#### Requirement: G35-R1/R3/R5 原生候选交接（2026-09-23 用户选择）

补充G35-R3（用户随后明确）：原生实际补充生成的信息MAY保留，但MUST显式标注“模型生成”；有原文依据的内容MUST保留可点击的原文证据定位。混合页面MUST按内容片段区分，页面级/候选级chunk引用不得冒充所有内容的事实依据；不得编造引用。该要求覆盖此前把所有无原文支持补充一律拒绝的表述，不放宽需要原文确认的产品字段事实及唯一发布审核。

内容合同的可省略content_provenance扩展MUST采用knowledge-content-provenance.830.v1。segments的text顺序拼接等于完整展示内容：定义为body；自由页为既有统一renderer的body及条件、例外、有效期；SOURCE_SUPPORTED片段引用同对象顶层evidence的合法非空索引，MODEL_GENERATED片段不得伪造引用。全部evidence须有片段归属。显式扩展允许纯模型生成补充无evidence，省略时旧证据必需规则及canonical字节不变。来源标注参与内容和审核hash；字段事实/受保护定义/唯一Active门禁保持。页面按片段展示并通过完整Evidence身份定位原文，禁止仅按quote猜引用。

原生producer的PreviousSlugs MUST为空（以后如使用正式身份须独立版本化并绑定依赖）；MUST NOT查询native wiki_pages或调用原生deduplicateExtractedBatch。已提交StageCall raw必须可恢复，响应尚未落库的未知发送必须阻断重发，不声称网络调用与数据库提交原子。

原生候选producer MUST复用已有候选发现及chunk引用能力，通过版本化REST输出签名计划和候选快照；不得进入原生写页/发布路径。Harness MUST复用既有持久模型执行器保留每段raw及请求/模型身份，未知发送不可重发，成功段不可因兄弟失败丢失。签名快照绑定scope、来源版本/hash、全窗口覆盖、原始响应hash、提示词和引用映射；它不是语义真实性或审核授权。未知引用/重复身份/来源漂移 MUST拒绝，不能用原生description/details替代原文。无引用候选保留为unsupported，不直接晋升。Harness只对候选做知识准入及最终审核，不再重复自由发现。显式产品候选策略阻止原生直写；未声明策略的旧协议/行为保持。软件验证不代表已部署或真实知识准入。

本次Goal与完整G35-R1—7、非目标和真实选材冻结于
`docs/superpowers/plans/2026-09-23-830-g35-knowledge-admission.md`。
旧G3 FLOW PASS保留，不能代替G3.5非空知识准入；沿既有G2-R1/R3及G3-DISC-1/2扩展。

#### Requirement: G35-R2/G35-R5 已有知识语义参与准入及真实依赖

发现与独立审核MUST能够比较已有页/概念的正文、主体/义项、版本、条件和例外；
仅有名称索引不足以判断语义重复与更新。已有自由页正文/作用域/证据修订MUST改变本次
生成输入identity；不能只因page_id/title/stable_key未变就复用旧发现。无关实体页不应
扩大当前实体输入，原Schema字段结果变化仍不使独立发现失效。

第一软件切片采用显式v5 generation context与v4 review context；v3/v4 generation历史
输入保留原renderer及原字节语义，当前运行默认v5，不把新增语义输入变化伪装为零调用。
已有知识比较视图只带语义正文/作用域/稳定身份和revision摘要，不展开历史来源巨大审计
对象；来源Evidence真实性继续由现有验证边界承担。超出原有序列化预算明确失败，不静默
截正文。此切片不自行执行模型、部署、Candidate或发布；尚不意味着更新、新实体和局部
失败合同已完成。

- GIVEN已有页稳定身份/标题未变，正文或条件/例外/版本/证据被修订
- WHEN构建当前发现或审核输入
- THEN视图呈现真实语义且identity改变；历史v3/v4 renderer仍保留原形
- AND同名字段实例与通用概念由各自类型、义项及主体区分，不依据名称直接合并

#### Scenario: G35-R2 原生准入投影不得用同名替代语义审核（2026-09-24）

- GIVEN 原生候选已绑定可信来源窗口，提出与Schema字段同名、但具有独立义项或解释用途的概念/页面
- WHEN title、canonical_key或aliases与Schema字段短标题/field_key相同
- THEN 原生投影 MUST NOT 仅据名称碰撞拒绝整份响应；保留完整正文、义项、来源片段及处置，交既有独立审核对照完整Schema描述判断语义。投影成功不代表质量通过或发布授权。
- AND 字段值复述即使换名也须由独立审核拒绝；REJECT/NEEDS_HUMAN不得组合为通过审核。原生响应仍不得包含fields，合并后既有字段增量保持原值；身份/版本/精确引文/来源标记/审核hash与唯一Active门禁不变。
- AND 准入仍可选取已绑定窗口内但不在候选source_chunks子集中的原文；candidate chunk关联不构成正文证据白名单，窗口外或错误offset/quote仍拒绝。

本切片唯一写者root，写域为native_admission.py及对应准入/独立审核测试、此Spec与既有执行证据。旧独立发现v3/v4路径合同不改；不新增正文生成阶段、模型调用或发布入口。先以同名不同义投影反例记录RED，再验证字段防护与审核拒绝；真实模型语义质量仍须P1/P2实测。

审核v4 MUST 保留候选的类型身份：概念的canonical_key/sense_key/aliases/origin，页面的entity_id/stable_key/entity_version/concept_ids；审核v3显式renderer保持历史字节。历史版本只供原合同回放，不能替代当前v4审核授权。Schema绑定必须唯一匹配id/version/hash，否则稳定拒绝。


### G35-R2/R3/R5：显式同身份更新的增量编译

G3增量输入MUST复用G2既有update处置：仅已存在的同类型稳定身份可更新，必须显式update且对象实际发生变化。新id假称update、旧id伪装新页/新义项、同批重复身份或重复审计MUST拒绝；字段增量覆盖合同不变。Schema/专家来源的定义正文仍受保护，来源/实体版本校验不放宽。

组合器MUST让每个update替换最终候选中的对应旧成员，并且只保留一条该成员update处置。其他旧成员及历史request/release保持原值；失败不得产生部分覆盖。Python与Go MUST重放同样的组合及最终审核hash，旧内容或旧集合审核不得用于新正文。旧无update向量的canonical与hash MUST保持不变。该子项不代表模型UPDATE_PROPOSAL已接线或发布成功。

更新能力通过可省略的request.knowledge_update_policy=`explicit-same-identity.830.v1`显式声明并进入request hash；只有该请求的compiler context使用NEW_AND_UPDATED_MEMBERS。缺省旧请求保持NEW_MEMBERS_ONLY及禁止update，省略值维持旧canonical字节；空值/未知策略拒绝。当前producer不自动启用该能力。

显式更新策略的Candidate MUST在Python/Go准入边界重验所有新建/变化自由知识的评分覆盖：每项>=60、60—79恰好进入pending，显式update（含只改别名）必须参与；>=80仍保留既有整批发布授权。实际bounded模型display context必须反映同一output_mode，旧请求不新增空扩展键。不能仅依赖正常runner曾调用审核来代替边界校验。

G35-R3来源一致性：含MODEL_GENERATED的定义必须origin=MODEL_COMPILE；含生成片段的CompileOutput必须transformation=SYNTHESIZE。主正文及相关知识预览使用同一片段展示。仅新来源合同的citation增加可省略evidence_index，绑定完整Evidence派生的citation_id；排序位置和quote不得代替身份。G2仅新合同自由页采用完整renderer，旧对象正文/hash保持。

#### Requirement: G35-R1 已有产品唯一身份关联（2026-09-23 用户澄清）

已有产品的材料 MUST 可以凭原文支持的公司、完整正式名称（或已批准别名）和明确年款唯一关联其已有版本；说明书未给出编码/备案不构成实际歧义。明确提供的编码/备案与目标冲突、多个候选或证据不足 MUST 阻断。MATCH 的派生anchors MAY消费绑定的ExistingEntitySnapshot，原proposal和证据归属 MUST 不变，不能补造本次材料引用。编译及Go发布重放 MUST 核对相同关联与已有版本身份，不要求每次重复上传原条款；CREATE及来源真实性/信任/置信度门禁保持。成功模型记录按既有依赖验证复用。

#### Scenario: G35-R1 既有产品新增材料的字段规划（2026-09-23 真实恢复补充）

- GIVEN 已唯一匹配既有产品，新增材料需要刷新已有字段，Schema字段显示顺序与协议排序不同
- WHEN product_ingestion适配器构造完整增量编译请求
- THEN MUST验证更新项结构，并按(entity_id,field_key)排序；请求身份和refresh_fields采用同一规范集合顺序。相同更新项的不同输入顺序产生相同请求。重复项、非已有字段、非当前实体仍由既有编译校验拒绝；不得静默删项或放松证据/发布合同。

#### Scenario: G35-R2 当前产品实体的只读引用

- GIVEN 原生候选指向当前已解析产品，准入context已提供经编译请求绑定的entity_id
- WHEN 准入返回REFERENCE且existing_target等于该当前entity_id
- THEN MUST保留为只读引用处置，不要求为实体重复建立free page；不得生成实体/关系或修改已有成员。非当前实体引用仍拒绝，NEW/UPDATE的成员、版本、Schema及来源校验保持。
- AND 当前实体REFERENCE MUST仅接收kind=entity且name等于可信context.entity.display_name的候选；概念及其他产品名称不得因返回当前entity_id被静默吞并，模型自报alias不能授予身份。

#### Scenario: G35-R1/R3 字段响应空值的限定兼容

- GIVEN 模型已返回并持久保存原始字段响应，外部协议出现valid_time显式null或present行遗漏nullable unknown_reason
- WHEN product-field-outcome.v2在适配边界解释该响应
- THEN MAY仅将显式null有效期转空字符串、仅为present缺失原因补None，再走原有严格结构/字段状态/引用原文校验；MUST不改原raw，不补缺失有效期，不补unknown原因，不修改引用或事实。缓存/窗口身份MUST绑定新验证版本及实际prompt；未知发送不补发，已成功结果保持，失败恢复复用现有字段重试入口。

#### Scenario: G35-R2/R5 保险场景知识覆盖与语义去重

- GIVEN 原生发现面对完整保险材料，Schema已声明字段用途
- WHEN 发现并准入候选知识
- THEN MUST关注各节实际权利义务、后果/对象/时限/条件/例外和演示适用边界；不得以篇幅短或规则通用作为唯一删除理由。Schema去重MUST比较完整定义与语义职责，不得只按主题名称推断覆盖。独立规则/解释可准入，字段值仍由Schema流程承接，禁止因字段技术失败复制同名free page。完整原文输入不等于语义覆盖PASS，真实质量验证MUST逐项核对原文和有效产物。

#### Scenario: G35-R1/R3/R7 PDF 数字表格保真（2026-09-24 P0-1）

- GIVEN 原生 builtin PDF 解析产生连续数字表格行，既有文本清理将其误判为坐标轴杂字
- WHEN 解析器清理正文
- THEN MUST保留没有相邻图表标题边界的数字块；同页别处出现Figure标题不足以授权删除。已有相邻Figure标题的图表标签清理继续工作，原始定位捕获合同和原字节不改。
- AND 本切片唯一Owner=root，写域限docreader/parser/pdf_parser.py、docreader/tests/test_pdf_router.py及本任务证据/入口；先以无标题数字表和异处标题反例证明RED，再实测原PDF。复杂性归解析模块，不在Harness或提示词重建丢失内容，不引入新解析器/开关。

用户已批准按2026-09-24清单执行，并要求tracer bullet与deep modules：以同一真实材料贯穿已有上传、解析、发现、准入、审核和发布形成最小纵切；各边界由原有责任模块提供窄接口并封装状态/校验，不横向新建平行流程。P0-1离线证明不代表正常网页输入与后续生成验收完成。

#### Scenario: G35-R1/R5/R7 原生对照结果不冒充成功（2026-09-24 P0-2）

- GIVEN 原生候选发现成功，但某个引用批调用或响应解析失败，或者某个页面正文生成失败
- WHEN 原生Wiki聚合阶段结果
- THEN MUST返回可区分的单元结果，保存成功兄弟引用结果及失败位置；引用批不完整时MUST NOT用候选短说明继续生成带原文支持的正文。页面生成失败MUST保留错误，不能标为no_change或健康完成。
- AND 文档结果结算由既有ProcessWikiIngest统一拥有，COMPLETE仅可从全部必需阶段成功推导；PARTIAL/NEEDS_ATTENTION沿既有失败追踪与任务处置展示，不新增第二队列。已写成功页保持，原生实验不宣称exact断点恢复；正式G3.5继续复用Harness StageCall的raw/依赖/恢复合同。
- AND 外部调用失败与响应格式失败须区分；缺少完整响应的发送结果不可推断为未发送。禁止以新增EOF字符串匹配触发重发。任何未知发送须在原生内层、fallback及任务重排之间统一阻断自动重发；没有可核验持久边界时保持未验收，不用局部单元测试声明跨崩溃恢复通过。

本切片写Owner=root，先收口wiki_ingest_cite.go、wiki_ingest_batch.go、wiki_ingest.go及对应测试/本任务证据；涉及持久调用记录或任务结算接口的新增写域必须先补窄合同与反例。不得把最佳努力span日志当作exact恢复权威，或让Go直接访问Harness私有表。

P0-2结算澄清：source parse与可选Wiki enrichment独立；已成功解析的source不得因Wiki失败改成failed。Wiki失败/部分成功须在原trace和持久失败处置中明确，排空slot继续使用原revision binding。原生未知或格式失败不自动整文重跑，成功页保持。调用结果类型封装在同责任的wiki_ingest_outcome.go；不保留旧字符串瞬态重试分类器。主Wiki必须展示待处理生成失败，不能把页面数或source completed当作健康完成。

P0-2最小持久隔离补充（同Owner，不新增执行器/表）：原生文档op在首次模型调用前，MUST用现有pending行的tenant/task/scope/dedup/op/payload和claimed_at作CAS，持久写入execution_id。恢复发现execution_id非空时MUST隔离为OUTCOME_UNKNOWN，不整文重发；marker写入失败则不得调用模型。此文档级marker不声称单元raw恢复或exact执行，已写成功页保持。原TaskPendingOpsRepository的可选窄扩展负责payload CAS与同库事务archive/delete；消费者缺少该能力时发送前fail closed。归档必须锁定并校验原行身份，insert失败不得delete，delete失败不得留下归档；原行已不在时不推断归档成功，不排空source slot。slot仅在确认本次归档成功后沿原revision接口结算；提交回执未知可能保留待清理slot，不能用再次模型调用消除此不确定性。WikiStats沿既有队列仓储查询当前KB/tenant的原生归档失败数量，前端只显示生成未完整、可查看文档处理记录；不得把查失败当0。

必要新增写域限internal/types/interfaces/task_queue.go、internal/application/repository/task_queue.go及测试（上述CAS/事务/计数），internal/types/wiki_page.go、internal/application/service/wiki_page.go及测试（独立生成失败计数），frontend/src/api/wiki/index.ts、frontend/src/views/knowledge/wiki/WikiBrowser.vue及中英文locale（失败可见）。原生业务逻辑仍只在wiki_ingest*.go；不改通用parse状态机/数据库schema。先用现有实现缺少guard的运行时接口反例及事务回滚/身份隔离反例建立RED，再实现。

上述CAS具体化：Begin只在execution_id缺省/空且claim身份匹配时原子设置该JSON字段，保持payload其他未知字段，不能重新marshal整段覆盖。Complete同样按claim+execution_id删除，旧worker不能删除新claim。解码去重前检查同dedup_key所有已领取行；任何marker使整组隔离，空marker兄弟也须先持久标记，标记任一步失败不得先归档其他兄弟后遗留可发送行。marker只约束同一queue operation及其已存在兄弟，不授权同revision自动重新入队；恢复器只可触发既有pending，不得重新造op。预发送CAS RED已获得，扩展同反例覆盖marked sibling、旧claim complete和payload未知字段保持。

P0-2独立复核收口（2026-09-24）：原生草稿发布是文档完成的必需阶段。页面读取失败/缺失、状态持久写入失败MUST逐slug返回失败并关联所有贡献文档；已发布兄弟页保持。失败页面不得进入成功日志、后续交叉链接输入或健康完成统计。锁/读取/写入失败与模型失败消费同一页结果账本，不能只清理模型失败。任一Complete/Archive CAS未确认MUST返回结算错误且不排空slot。该原生draft状态切换不是正式Active发布，不改变正式审核权威。

P0-2 revision隔离澄清：上一段按knowledge全组marker隔离收窄为tenant/task/scope/op/knowledge/exact RevisionCommitBinding；旧版本未知操作不能阻断真正的新版本。已归档同版本失败通过现有dead-letter在Begin前核对，迟到同版本行必须先mark再隔离，不能重发模型。ClaimBatch仍按knowledge串行，当前持有者Archive与删除同事务后迟到行才可领取；Lite继续使用现有scope锁。已领取旧marker版本单独归档，不能被最新未开始版本覆盖或当成功清理。不增加成功tombstone；本切片不承诺成功删除后任意未来重复提交的exactly-once。

P0-2复核设计边界：最终发送门在标记后、任何模型调用前，按现有dead-letter锁内保存的payload核对op+exact revision，命中者沿原恢复归档而非release重试。重解析/删除的单文档Wiki ingest scrub只能删除未领取且execution_id为空的行；不能抹掉在途/未知操作marker。该窄保护落在原TaskPendingOpsRepository.DeleteByDedupKey，不改变其他任务的清理或整库失活清理。不引入新enqueue协议、成功回执表或后台恢复器。

P0-2代次选择设计重审（0设计BLOCKER后冻结）：queue row ID/到达次序不是文件版本。输入选择责任集中在原生operation模块：对同knowledge合法显式Revision按既有单调ParseAttempt取最高代，legacy nil不得覆盖显式版本；畸形显式高代次单独隔离，不压住合法版本；同代次不同file/parser身份整组冲突，双方不得发送。最高代失败/未知不得回退发送较低代。任一已领取retract为该knowledge顶层删除栅栏，不被迟到ingest越过；原已开始组仍按自身identity结算。未开始较低代可作为superseded行随选中操作结算；已开始/冲突组独立保留。provider发送前查DL；允许先CAS marker后零provider归档。反例覆盖marked R1→R2→late R1、DL后[R2,late R1]、非法高代、同代冲突、最高代未知不回退及R2→retract→late R1。该规则替换已有latest-row选择，不新增调度器/成功journal。

### G3-AUTO-5 / P0-3 · 一次操作内验证复用与取消（2026-09-24）

在已批准的发布性能切片内，先修复已证实的同包重复完整验证和取消后继续进入昂贵阶段，不把当前18.2/25.0秒读取A/B扩大为历史400秒根因已闭合。唯一写者root；写域限Go `internal/types/concept_free_wiki_830_g3.go`、service同名文件、`wiki_release.go`、`wiki_release_automated.go`、`concept_source_authority_830_g2.go`、`g3_published_read_reuse.go`及定向测试，不改Harness/handler/DB/签名格式。

- types提供一个窄的context-aware完整验证/投影入口：精确decode、完整semantic validation一次、旧canonical编码、已验证member snapshots。各阶段前后和member循环检查取消；旧Parse/Canonical/Snapshot公开入口保持原安全语义。不得删除Unicode、重复JSON key、精确key、candidate/compile/review/member约束。
- service在一次ActivateAutomated请求内持有私有验证结果，封装decoded bundle、canonical/raw身份、members与完整preparation身份；只由成功的完整验证构造。源验证借读它、既有signed projection消费它，不再次全量解析/语义验证。该对象不持久化、不上HTTP、不跨请求复用，不建立新的发布授权或缓存协议；Go嵌套集合靠私有所有权保持只读，不宣称语言级不可变。
- 当前来源验证接口的已有独立调用仍可无该结果并执行完整验证；如传入结果，则MUST精确核对scope/preparation/candidate/raw identity，失配不得静默回落。仍重读数据库Draft/Ready，保留live来源版本/撤销、当前双KB ACL及每项evidence核验；source循环和projection构建前检查取消。
- 系统决策、policy/expiry、nonce、expected Head及private CAS数据库重读/成员检查不变；私有验证对象不能替代最终权威门禁。
- 取消在稳定阶段边界生效，不能通过启动无人等待的goroutine假装终止；当前JSON或semantic primitive可能运行至该阶段末尾，必须如实记录该限制。检查到取消后source/projection/activation后续effects为0。
- RED包括：取消后仍进入source/写边界；一次operation重复semantic validation；错误复用身份。另验证canonical/member逐字一致、context各阶段取消、当前权限/来源变更和validation后成员遗漏仍拒绝。真实发布仅沿P2当前有效候选；旧失败候选继续只读。

### G35-R5/R6：显式候选依赖隔离首切片（2026-09-24 用户确认先R6）

用户确认先隔离未决候选并验证完整流程，再接R4正式关系。root唯一写者；复用现有原生准入、StageCall、增量组合器、独立审核和唯一Release，不新建队列/表/发布权威。

运行配置可显式启用dependency_policy=`candidate-dependencies.830.v1`；缺省省略该键并保持旧配置/请求语义。启用时使用显式v2准入context/response及对应新prompt身份，每条decision MUST提供depends_on（引用同窗口candidate_ref，可显式空数组）；必须完整覆盖候选，无重复、未知、自引用。旧v1不推断独立，继续原整组围栏；v1/v2响应不得跨请求投影，新prompt/context不可冒充旧raw exact复用。

投影先验证完整响应的成员/身份/版本/来源合同，然后按依赖隔离：PENDING、REQUIRES_ENTITY_RESOLUTION和REJECT不能满足依赖；REFERENCE可满足只读依赖。共享同一成员的候选共同进退，引用本响应新定义的页面依赖该定义的所有提供候选；依赖闭环可整体保留，但任一节点未决则其依赖者全部隔离。裁剪后无页面使用的新定义连同其提供候选隔离，不能残留悬空引用。独立的合法候选保留；失败UPDATE不进入增量，既有组合器仍保留旧正文。原完整response/raw与逐候选隔离回执都保存，最终审核只对裁剪后的成员与对应dispositions评分，但必须只读看到完整已验证v2响应、原候选语义与有效依赖/隔离计划，检查未声明的依赖；采用独立v6审核context和新prompt身份。

首条tracer仅当整次运行恰好一个完整有效admission response（单窗口、单实体依赖域）时允许候选级隔离；所有多窗口/多实体输入即使调用成功也保留整组围栏。isolation_enabled必须进入请求身份。窗口原始结果未知/响应结构不合法、来源未绑定或跨窗口同身份冲突仍保守隔离整组，不能推断未知窗口没有依赖。此限制不等于全部R6完成；跨窗口故障和审核失败后的二次最小裁剪是后续独立切片，须另冻结边界。审核仍基于裁剪后真实最终composition hash独立执行，未通过不发布，不复用裁剪前审核授权。可审核成员存在不把未决候选状态改为全部成功：用户摘要保留PENDING与隔离原因，同时保留已通过成员计数。

写域：product_ingestion/native_admission.py、native_admission_stage.py、native_pipeline.py、configuration.py、discovery_replay_metrics.py、api.py、discovery.py、discovery_stage.py、discovery_composition.py、checkpoints.py及新增native_dependency_selection.py纯依赖模块；对应tests与本Spec/既有计划/证据。先记录新版依赖协议及独立候选保留的RED，再实现；模板/配置只离线准备，部署和真实质量分别验收。

反例：A未决、独立B保留、依赖A的C隔离；共享定义/环、无效依赖、旧v1不放宽；失败更新保持旧页；裁剪结果与旧审核hash不匹配；未知窗口/冲突仍隔离；新协议调用记录可复用且输入改变不误复用；最终审核通过部分成员时摘要仍可见未决。

隔离算法求确定性不动点：显式边、共享member原子组、页面→新定义结构边取并集；结构自身可闭环（显式候选自引用仍非法），传播失效及孤定义直到稳定，输出/原因/图稳定排序。receipt绑定policy、context/raw hash、snapshot/entity/windows、完整已验证响应、有效图、保留/隔离候选和成员及selection hash；注册native_dependency_selection版本化artifact，与discovery_candidates内同一receipt共同持久化，policy变更拒绝旧checkpoint。审核上下文读取并验证receipt身份与保留成员，完整计划变化使审核input hash变化。摘要在存在隔离项时保留PENDING与原因，accepted_member_count仅统计独立审核通过成员；发布验证前published=0，exact release验证后允许PENDING + published_confirmed + published=N并存。

### G35-R6 展示纵切补齐（2026-09-24）

沿用户已确认 tracer bullet/deep modules 继续推进：新后端摘要已支持 PENDING + verified partial publication，但 Go bridge 白名单丢弃 dependency_policy/pending_candidate_count/accepted_member_count，前端仅 ACCEPTED 才显示已发布，必须在部署前补齐同一纵切。

唯一 Owner=root；追加写域 internal/application/service/product_ingestion_bridge.go 及对应测试，frontend/src/api/product-ingestion.ts、frontend/src/components/knowledge-base/product-ingestion-status.vue 及对应组件测试。Harness 保持唯一摘要计算责任；Go bridge 仅透传受限可选字段，不传 raw/candidate/依赖图、不重算语义状态；前端仅展示已验证发布和待处理数量，不依赖 candidate 细节或触发第二工作流。

旧摘要缺省三个新字段必须维持原输出；已声明依赖策略的 PENDING 在 published_confirmed=true、终态及 verify 成功时可显示已发布数量，同时明确未决数。未验证、尚未完成、未知策略或无正数未决时不得仅凭 PENDING 显示发布。REJECTED/FAILED 仍非发布完成。RED 必须贯穿 bridge HTTP序列化和组件用户可见输出，保留旧状态/敏感字段防泄漏回归。

### G35-R5/R6：原生准入确定性预检（2026-09-24 真实失败回执驱动）

root唯一写者。按已批准质量计划，继续单材料tracer：当前真实raw的三层结构错误必须完整识别，不能以修正offset宣称业务通过。复用原生发现/StageCall及严格投影、既有定位和唯一发布。新增纯native admission preflight不做I/O、不调用模型、不授权发布；阶段适配器只持久记录与调用。写域为product_ingestion/native_admission_preflight.py（新增）、native_admission_stage.py、checkpoints.py及对应测试；共享精确匹配原语仅涉及knowledge_compiler/evidence_occurrences.py（新增）和g3_bounded_model_execution.py既有枚举循环。场景提示澄清位于native_admission.py的v2服务端member_contract上下文，系统prompt/template/完整配置保持原值，通过新context输入身份与旧raw区分。本Spec/计划/HANDOFF/既有证据允许对应状态记录。

- 输入为原始decoded响应和绑定的request/context/snapshot/source。仅v2允许确定性归位：正确start原样保留；错误start仅当同一source_ref的offered span内quote逐字唯一出现时修正。Unicode按Python码点，保留CRLF/emoji；零/多命中、空白归一化、模糊匹配或跨源推断均拒绝。共享原语只枚举精确occurrence，D字段保留原有多命中策略。
- concept_refs只允许既有合法identity或本响应definition.member_ref；错填canonical_key时，必须逐字唯一指向一个definition，且不与既有identity/任何member_ref冲突才归位。不得改正文、provenance、decisions、候选/成员集合或自动造页/删孤定义。重复canonical_key（不同sense）不可猜测。旧v1完全保持严格原行为。
- 原provider raw、native_admission_response和调用身份不可变。RULE预检回执记录版本、原始/归位raw及context/source/snapshot hash、JSON pointer旧/新值、原因、quote hash/命中数、strict projection成功或结构化失败。只有完整严格投影（含R6闭包）通过才输出投影；几何定位保持其后原门禁。归位后的字节保存在独立RULE产物，与原始MODEL产物分离；任何失败仍保存审计但无projection。
- native_admission_projection派生产物升版，旧完成阶段因旧投影版本必须重新预检；原调用请求/模板不变时记录可复用，未知仍不重发。升级不得使身份/字段/来源成功步骤一并失效。提示/schema改变必须单独改变模型请求身份，不能假称同raw可响应新提示。
- RED涵盖两类归位贯穿真实stage journal；v1拒绝、Unicode/重叠/正确offset重复quote、0/多命中/外源/篡改context、引用碰撞/重复sense、孤定义保持失败、原始响应及回执不可变、旧投影截断但成功模型raw保持可恢复。真实失败raw离线预检必须最终停在孤定义；没有最终审核/发布即BUSINESS仍BLOCKED。

本切片同时澄清v2成员生成合同：response context新增版本化member_contract（独立概念以有用Wiki page承接；definitions仅为至少一个页面使用的术语义项；concept_refs用member_ref/现有concept_id及最小样例；无新定义可合法空引用）。该显式输入改变必须使operation/input SHA变化，旧准入raw不能作为新场景输入的输出复用；来源/原生候选调用身份不变。v1提示与context保持字节语义。新增changed_contract RED已观察旧实现把旧上下文响应复用而没有执行新请求；实现后只允许新准入响应，不能扩大为整文件重算。完整运行配置与系统模板SHA/id保持不变；此前修改系统模板的方案已由下段收窄设计取代。

预检切片设计收窄（同日独立设计复核后，取代上段system prompt/模板变更方案）：成员职责、保险覆盖及引用样例全部放入服务端生成的版本化member_contract上下文；保持既有v2 system prompt、template ID/SHA和完整运行配置不变。变化只进入admission context/input/operation身份，旧admission raw不能命中新输入，其他阶段仍按原完整policy与请求验证复用。无需跨策略兼容或policy history，不删除任何既有校验。写域追加test_native_runtime.py，用真实完整配置和持久worker恢复验证来源/身份/字段/发现/引用调用计数不增加、仅新admission增加1；旧成功/未知/过期调用保持既有规则。先观察当前system prompt改动拒绝已批准配置的RED，再移回场景上下文；该软件恢复纵切不等同于真实模型质量。

### G35-R5/R6：后续阶段失败不得遮蔽发现失败（2026-09-24 恢复实测）

真实恢复16452cbb复用了33dd1349的FAILED discovery_summary而从compilation继续；模型新增0、字段发布到epoch18，自由发现仍FAILED。这不是准入质量验证。根因在既有checkpoint_store仅对顶层PARTIAL_SUCCESS检查技术发现失败，顶层FAILED会遗漏更早的失败结果。

root唯一写者；追加写域仅product_ingestion/checkpoint_store.py、test_checkpoint_artifact_version.py、test_native_runtime.py及本Spec/既有计划/证据/HANDOFF。恢复选择仍由原checkpoint深模块负责，公开接口、配置、队列、审核及发布合同不变。

- workflow3所有原本可恢复的终态均检查已有绑定的discovery_summary/discovery_final_summary；更晚阶段失败不得遮蔽较早的FAILED + partial_success技术失败。按有效前缀与最早失败边界恢复，不能越过已有更早的失效边界；REJECTED/PENDING等语义结果不得因该修复重发。
- 原产物、stage/job代次和raw custody证明、未知发送阻断及全policy检查保持。有效source/identity/fields和原生发现/引用继续复用，新member_contract仅重做准入；不删除旧结果、不改历史任务状态。
- RED包含真实worker中准入失败后compilation故障的FAILED父任务，以及最终审核失败后更晚故障的恢复边界；覆盖更早产物失效优先、非FAILED摘要和旧workflow。完整worker恢复证明只有必要admission新增，不能以metadata测试替代接线。
- 本轮已冻结的真实窗口一次UI恢复已用完，不追加点击；先完成上述离线反例/验证/独审，再单独记录后续有限交付窗口。G3.5、非空质量/点击与R4仍未完成。

### G35-R5/R6：服务端证据编号准入（2026-09-24，四项质量阻断首切片）

root唯一写者；继续用户已批准质量任务。既有原生候选/引用、精确source_options、严格v2投影、R6、几何定位和StageCall全部复用。缺口是模型重复抄写原文/计算offset/维护独立证据索引导致完整响应非法。新增纯wire适配，不新增发现、执行、审核或发布平台。

- **G35-R5-WIRE-1**：显式wire v3及新系统模板；旧v1/v2字节语义不变。服务端按已验证source_options顺序给既有完整span分配短编号，保留Unicode/CRLF精确字节；首切片不另作分句或清洗。模型逐段返回text、origin、evidence_refs；不再独立返回evidence/offset/quote。按catalog固定顺序展开为既有v2 evidence和segment indexes，正文、决策、来源标签不得修改。重复/未知ref、MODEL带引用、SOURCE无引用、非法正文覆盖均拒绝；同一引用可被不同段使用。原始wire、context与展开后的v2及回执分别留存，继续完整strict/R6/geometry/review。该接口避免未被段使用的孤立evidence，但不能自动判断模型来源标签的语义真伪。
- **G35-R5-WIRE-2**：top-level可选native_admission绑定仅包含protocol和完整ModelTemplatePolicy；仅依赖策略v1可启用。保留base model与native_discovery配置/哈希，派生设置仅替换exact旧admission模板，新purpose g3-native-admission-v3，连接、凭据、模型、容量继承。不改变generic replay校验。composition复用同一ConfiguredModelExecutor类，只有准入使用派生实例；旧准入请求失配，其他成功调用仍须通过原exact校验。兼容Owner=root；旧配置默认保留，后续正常配置迁移再移除旧模板，不引入policy history。
- **G35-R5-WIRE-3**：执行回执升版，绑定protocol/template/prompt/derived policy/input/request/raw身份；旧完成阶段旧产物版本必须重验。完整discovery checkpoint复用前按当前准入配置复核回执；改变/移除override不得沿用旧完整阶段。缺失/失配fail closed，FAILED discovery恢复仍可使用原成功调用索引按exact请求选择。新协议自身后续亦可exact复用，不放宽未知调用围栏。
- **G35-R5-WIRE-4**：新提示明确逐段SOURCE_SUPPORTED包括原文改述；补充解释独立MODEL_GENERATED。Schema比较必须保留subject/recipient/trigger/condition/exception/consequence，不能用触发条件覆盖独立后果，告知对象须完整。提示变化不是质量验收；当前v6 review只查retained dispositions，Schema误拒与对象遗漏仍BLOCKED，下一切片另冻结所有decision的disposition检查协议，不能冒称已独立覆盖全部REJECT。

新增写域限product_ingestion/native_admission_wire.py、native_admission_policy.py及既有configuration.py/composition.py/native_admission_stage.py/native_admission_preflight.py/checkpoint_validation.py/checkpoints.py；相关定向tests、本Spec、原计划/任务/HANDOFF/证据。原native_admission.py领域投影不改协议。RED覆盖精确CRLF/Unicode、逐段引用和来源不自动改写、篡改catalog/context、未知/重复ref、v2语义仍严格、旧配置哈希不变/非法新模板拒绝、完整阶段恢复身份、真实worker仅准入新增。先软件/离线证据，集中交付和新有限真实窗口另记，旧窗口保持关闭。
