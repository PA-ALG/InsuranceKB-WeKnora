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
