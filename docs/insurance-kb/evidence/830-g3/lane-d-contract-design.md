# G3 D：多 SchemaPack Candidate / Review / Release 接线合同草案

状态：`ROOT_DESIGN_REVIEW_PENDING`。Root保留私有原稿SHA 8800da6ecd189391a1fd1f7c8a2e163e8ce2a838252184acdbc5dc3a37d55457；持久副本纠正代表pack缺意外类别、fixture与真实base计数、避免用户手填JSON。本稿只做设计，不授权实现、真实模型、数据库、构建、发布或 Active 变更。C 两个冻结文件保持不变。

A+C 已有集成提交，但 C 复审随后撤回 B2：原合同允许父 `MULTI` 表示多个 name/code 身份已独立成立而子版本仍 `NEEDS_CONFIRM`，当前实现错误地把 MULTI 身份资格收紧成自动 Candidate 资格。C 正在单独冻结“MULTI 身份资格/自动 Candidate 资格分离”及每个 child 的最小 name/code Evidence ID 集合；D 不改变该设计，只消费最终 C 中仍具自动资格的 `MATCH/CREATE` child。D 可直接复用冻结 Catalog、最终 C DTO和既有 G2 唯一 Candidate 链，不要求重新进行已经接受的“结构确认”。

## 1. 结论与边界

D 使用一个新的外层合同承接 G3 Catalog、C 批次决定和逐实体 pack/profile/classification 绑定；内部继续复用 G2 的 `CompileRequest`、`CompileOutput`、`ReviewOutput`、`ExecutionRecord`、`FieldAssertion`、`FreeWikiPage`、`ConceptDefinition` 与 Evidence。不能把 G3 字段塞进 G2 subclass：`concept_compile_830_g2.validate_output()` 会重新强转 exact `CompileRequest` / `CompileOutput`，Go 侧也用 exact-key strict decode。

新外层始终形成 `human_batch` Candidate：高置信 `CREATE` 可以直接提出稳定逻辑实体并编译页面，但仍与 `MATCH` 一起进入现有同一份 Draft、具名整包 Review、Ready、`ActivateReviewed` 和 CAS。C 的 `EntityCandidateV1.status=NOT_ACTIVE` 不是 serving 状态，不能直接写 Head、DB 实体表或搜索。

CREATE 的 D 逻辑身份固定为：

```text
entity_id      = "entity_" + entity_key_sha256
entity_version = entity_id + "@" + version_candidate_key_sha256
```

其中两个 key 必须是 C 已验证 Candidate 的原值并按 C 公式重算。MATCH 原样使用 C 的 `matched_entity_id` 和 `matched_entity_version`。分类、Profile、短标题、材料顺序和模型运行 ID 都不进入实体身份。

G3 Candidate 只允许 `REGISTERED_NOT_QUALITY_ADMITTED / ISOLATED_NOT_FOR_PRODUCTION`。它可以在隔离 scope 走完真实 Review/Activate/PinnedRead 以验证 FLOW，不得据此写成 Q0 质量准入或生产发布。

## 2. Python 公共合同

建议新增 `harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py`，公开以下严格、frozen、`extra="forbid"` DTO。新对象 hash 统一使用 `schema_wiki_sha256(object_type, payload_without_own_hash)`；嵌套的 G2 DTO 继续使用其原 `digest()`，不得重哈希或改变已有字节。

### 2.1 Profile 确认绑定

`CatalogProfileConfirmationReceipt830G3V1` 精确描述现有 `830-g3-profile-user-confirmation.v1` 的全部键：

- `confirmed_at_recorded`, `decision=CONFIRMED`, `user_reply_verbatim`, `actor`, `confirmation_channel`, `review_document`, `review_document_sha256`；
- `catalog_sha256`, `catalog_wire_sha256`；
- `profiles[]`，每项为 `profile_id/profile_version/profile_sha256`；
- `scope`, `not_included[]`, `identity_metadata_note`；
- `actor_display_name: Text | None`、`queue_owner: Text | None`。类型允许具名字符串或 null；当前实例为 null，不得把 null 写死进类型，也不得虚构姓名或队列负责人。

`CatalogProfileConfirmationBinding830G3V1`：

```text
contract = catalog-profile-confirmation-binding.830.g3.v1
receipt
receipt_file_sha256
receipt_semantic_sha256
```

`receipt_semantic_sha256 = schema_wiki_sha256(receipt.contract, receipt)`。当前实例 file SHA 为 `7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863`，semantic SHA 为 `cd40072b3c4c32c3ed9440c7ff1ff5effc502c506b4ab11c86bbe438c7649b66`。验证时要求 receipt 的 Catalog content/wire hash 和 11 个 Profile identity/hash 与内联 Catalog 完全一致；确认 receipt 不改变 Catalog 内原 `PENDING_PRODUCT_OWNER_CONFIRMATION` 字节。

### 2.2 C 决定、Evidence 与实体绑定

`ResolutionDecisionRef830G3V1`：

```text
material_id
proposal_ref
decision_sha256
classification_assignment_sha256
```

按 `(material_id, proposal_ref)` 排序、拒绝重复。每个 ref 必须在内联 `BatchEntityResolutionV1` 中唯一命中同一个 child，且 child 必须是满足 C 自动资格的 `MATCH` 或 `CREATE`，父材料处置必须为 MATCH/CREATE/MULTI；父 NEEDS_CONFIRM/QUARANTINE 的任何 child 都不得选入。父材料为 `MULTI` 时可选择其中资格完整的自动 child；`NEEDS_CONFIRM` / `QUARANTINE` child 永远不能进入编译。D 外层仍整体人工审核，因此没有新增“先注册主数据”的第二队列。

D 不复制或重新命名 C 即将增加的两个 wire 字段：outer request 内联 exact、最终冻结的 `BatchEntityResolutionV1`，因此 MULTI 身份资格和 child 最小 name/code Evidence ID 集合均由原 C decision/batch hash覆盖，Go 按最终 C exact key set镜像。父 MULTI 的“身份已成立”标记不授予 child 自动编译资格；D 仍只选 C 自动 `MATCH/CREATE`。若所选自动 child 带最小 name/code Evidence ID 集合，该集合必须恰好是 child evidence 的非空子集、同时覆盖 `name` 与 `product_code` purpose，并全部进入下述 `resolution_evidence` 与 source authority 重开。

`BoundResolutionEvidence830G3V1`：

```text
material_id
proposal_ref
evidence_id
purpose = issuer | product_code | name | version | classification
evidence = G2 Evidence 原类
```

它从 C 的 exact `ProposalBatchV1` 提取，必须被对应 child 的 `evidence_ids` 引用；值、purpose、proposal_ref 和原 quote/offset/source identity 不得改写。按 `(material_id,evidence_id)` 排序。不同实体可共享同一 `SourceBlock`，发行人、分类或通用条款也可以共享同一真实 quote；禁止的是把另一个 child 的 Evidence ID/proposal_ref 或另一个实体的独立事实当成本实体依据。具区分性的 `product_code/name/version` occurrence 以 `(revision_id, block_id, start, end, quote_hash, purpose)` 判定，不得跨不同 entity binding 复用。每条 identity Evidence 都必须由 owner binding 所选 child 明确引用；FieldAssertion Evidence 必须属于 owner binding 允许的 source material。语义上仍不支持本实体的 quote 属于 human whole-batch review 的拒绝条件，协议不以“整 block 独占”伪装成语义证明。

`EntityCompileBinding830G3V1` 必填：

```text
contract = entity-compile-binding.830.g3.v1
entity_id
entity_version
resolution_disposition = MATCH | CREATE
resolution_refs[]
entity_key_sha256
version_candidate_key_sha256
candidate_id: Text | None
entity_candidate_sha256: Hash | None
display_name
issuer
product_code
version_label
version_anchor {kind, observed_value, normalized_value}
primary_classification
schema_pack_id / schema_version / schema_pack_sha256
profile_id / profile_version / profile_sha256
required_fields[]
source_material_ids[]
resolution_evidence[]
binding_sha256
```

MATCH 要求 `candidate_id/entity_candidate_sha256` 为 null，`entity_id/entity_version` 与所有 ref 的 matched IDs 原样相等；其 entity/version key 仍按 anchors 重算，用于审计但不替代 serving ID。CREATE 要求所有 ref 指向同一 C Candidate，`candidate_id` 与 candidate SHA 完整，且 D 的 entity ID/version 按本稿公式生成。所有 ref 必须具有相同 normalized issuer/name/code/version anchor、相同 primary classification 和同一 pack 三元组；否则回到 C 人工态，D 拒绝。

pack 必须从内联 Catalog exact 取包；Profile 必须是该 entry 的 exact Profile。`required_fields` 必须逐项、逐序等于 `profile.ordered_field_keys`，不能只比较 set。实体显示名使用 C Candidate/MATCH anchors 的来源原文，normalized 值必须一致。`source_material_ids` 是 refs 的 material_id 去重排序集合。

### 2.3 外层编译请求

`BatchConceptCompileRequest830G3V1`：

```text
contract = batch-concept-compile-request.830.g3.v1
base_request = exact G2 CompileRequest
catalog = exact SchemaPackCatalogV1（完整实例，仅此一份）
catalog_wire_sha256
profile_confirmation
resolution = exact BatchEntityResolutionV1
entity_bindings[]
quality_status = REGISTERED_NOT_QUALITY_ADMITTED
release_lane = ISOLATED_NOT_FOR_PRODUCTION
request_sha256
```

`catalog_wire_sha256` 是 Catalog 对象按 UTF-8、NFC、对象键排序、紧凑 JSON 序列化后的普通 SHA-256；当前值 `0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9`。Catalog content hash 仍是内部 `catalog_sha256=b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd`，两者不能互换。

请求闭包：

- `resolution.catalog_sha256 == catalog.catalog_sha256`，且 `resolution.space_id == base_request.space_id`；C resolution 本身没有 tenant/raw/wiki 字段，不能读取不存在的 scope；
- builder 对 exact `corpus/proposals/existing/policy` 重跑 C，并要求 `resolution.corpus_sha256/proposals_sha256/existing_snapshot_sha256/policy_sha256` 逐项等于这些输入；`corpus.tenant_id/space_id/raw_kb_id/wiki_kb_id` 必须逐项等于 base request scope；
- Go 收到持久化 outer request 后重验它实际拥有的闭包：所有 binding Evidence 的 source receipt/block scope、base request sources、outer resolution.space_id 和 route scope 必须逐项一致；不能声称从 resolution 单独恢复 tenant/raw/wiki；
- `entity_bindings` 的 entity 集合必须逐一等于 `base_request.required_fields` 与 `base_request.entity_versions` 的 key；
- 每个 `base_request.required_fields[entity]` 逐序等于对应 binding.required_fields，`base_request.entity_versions[entity]` 等于 binding.entity_version；
- `base_request.schema_identity = "catalog:" + catalog_id + "@" + catalog_version + "#" + catalog_sha256`；
- `base_request.profile_identity = "profile-set:" + schema_wiki_sha256("batch-profile-bindings.830.g3.v1", 按entity_id排序的profile三元组)`；
- `base_request.policy_identity = "g3-resolution-policy:" + resolution.policy_sha256`；
- base request sources 必须是所选 source materials 的 SourceBlock 精确并集，按 `(revision_id,block_id)` canonical；允许一个 block 出现在多个实体的允许集合，但 request 内只存一次；
- Existing definitions/fields/pages/entity versions 和 base release/epoch 继续由 G2 现有 base snapshot 规则验证；CREATE 不要求先出现在 existing snapshot。

建议的纯函数入口：

```python
build_batch_compile_request(
    *, base_request: CompileRequest,
    catalog_json: bytes,
    profile_confirmation_json: bytes,
    corpus: BatchCorpusV1,
    proposals: ProposalBatchV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    resolution: BatchEntityResolutionV1,
    selected_decision_refs: tuple[tuple[str, str], ...],
) -> BatchConceptCompileRequest830G3V1
```

入口先用 exact C inputs 重跑 `resolve_batch()` 并要求结果等于传入 resolution，再提取 Evidence/bindings；不接受调用方手填 entity ID、pack/Profile 或 Evidence。该函数纯内存，不调用 provider/DB。

### 2.4 输出、上下文和 Candidate

模型输出继续是 exact G2 `CompileOutput`：`output.request_hash == base_request.request_hash`，由 G2 `validate_output(base_request, output)` 验证全部 FieldAssertion 覆盖、entity_version、Evidence quote 和 member lint。这样保留 G2 编译器输出协议和 FieldAssertion ID/hash。

不能直接组装 G2 `HumanReviewCandidateBundle`，因为其 execution context 只含 base request，无法证明模型与 reviewer 看过 Catalog 和逐实体绑定。新增：

```text
compiler_context_g3 = {
  request: full G3 request,
  request_sha256: G3 request_sha256,
  base_request_hash: base_request.request_hash
}

review_context_g3 = {
  request: full G3 request,
  candidate: exact G2 CompileOutput,
  request_sha256: G3 request_sha256,
  base_request_hash: base_request.request_hash,
  output_hash: G2 output.output_hash
}
```

compile/review `ExecutionRecord.context_hash` 分别用 `schema_wiki_sha256("batch-concept-compile-context.830.g3.v1", ...)` 与 `schema_wiki_sha256("batch-concept-review-context.830.g3.v1", ...)`。raw output 仍由 G2 exact raw JSON 校验，compile/reviewer run_id 必须不同。ReviewOutput 仍绑定 base request hash 与 G2 output hash。

`BatchConceptCandidateBundle830G3V1`：

```text
contract = batch-concept-candidate-bundle.830.g3.v1
request
compile_result = G2 CompileResult
review_result = G2 ReviewResult
page_manifest = BatchConceptPageManifest830G3V1
admission = G2 HumanBatchAdmission（必须存在）
candidate_hash
```

该合同只允许 human admission；即使 reviewer PASS 且全部评分 >=80，`admission.status` 仍为 `NEEDS_HUMAN`，pending_page_ids 可为空。`candidate_hash = schema_wiki_sha256(contract, payload_without_candidate_hash)`，是 Draft/Review/Activate 使用的 CandidateDigest。G2 v1/v2 candidate hash 算法完全不改。

`validate_g3_output()` 先执行 G2 `validate_output`，再执行实体 Evidence scope：

- 每个 known FieldAssertion 和 FreeWikiPage 的每条 Evidence，source key 必须属于该 owner entity binding 的 source materials；
- unknown 字段仍必须 attempted、无值、无 Evidence、有 unknown_reason；
- ConceptDefinition 可引用请求内任一 admitted source，因为定义可跨实体共享；
- 不要求整个 SourceBlock 实体独占；按 owner binding、C child/ref membership 和具区分性的 product_code/name/version occurrence 防跨实体借据，共同 issuer/classification/通用条款 quote 可共享；
- `conditions/exceptions/valid_time/evidence` 保持 FieldAssertion 原数组及原顺序，全部进入原 G2 payload/member digest；不得因 UI 分组丢失或另造弱 claim hash。

## 3. G3 页面投影与可检索目录

`BatchConceptPageManifest830G3V1` 使用 G2 `PageMember` 形状，但由 G3 投影器重建并用自己的 `members_sha256`。不能直接使用 G2 `PageManifest`，因为 G3 需要短标题、产品名、分类和 Profile 分组，且 MinimalSearch 必须能命中条件/例外。

成员保持一字段一页：

- `concept`：复用 G2 definition payload；
- `field_assertion`：member_id/owner_id 和 payload 仍是 exact G2 FieldAssertion；title 改为 Catalog Profile 的 `short_title`；content 按下述精确行序拼接，使现有 release search 可检索值、条件和例外：首行为 present=`值：{value}`、absent_explicitly=`明确不提供：{value}`、unknown=`未知：{unknown_reason}`，随后依原数组顺序加入每个 `条件：{condition}`、每个 `例外：{exception}`，`valid_time` 非空时最后加入 `有效期：{valid_time}`，UTF-8 LF 连接且无尾换行；
- `free_wiki_item`：payload 原样，content 同样包含 body/conditions/exceptions/valid_time；
- `entity_overview`：沿 G2 稳定 member_id，但 title 为来源支持的产品正式名，payload 改为 `entity-directory-entry.830.g3.v1`；
- `free_wiki`：沿 G2 稳定 root ID，继续只链接本实体 free items。

`entity-directory-entry.830.g3.v1` 必含：

```text
entity_id / entity_version
display_name / issuer / product_code
primary_classification
schema_pack_id / schema_version / schema_pack_sha256 / schema_pack_display_name
profile_id / profile_version / profile_sha256
quality_status / release_lane
sections[] = {section_key, display_name, fields[]}
```

每个 section.fields 按 Profile 顺序投影 `{field_key, short_title, member_id}`，恰好覆盖 binding.required_fields 一次。overview content 确定性包含产品名、分类、pack 名和 section 显示名，使现有 `SearchPinned` 无需新索引即可按产品名、分类、分组命中。分类重排只改变 binding/navigation/page-manifest/candidate hash；entity ID、version key、原 FieldAssertion payload/Evidence/历史 release 不变。换 pack 属后续迁移 Candidate，不能在 D 静默改字段集合。

Go `SnapshotMembers()` 使用 G3 page manifest，所有 snapshot `RevisionID = outer candidate_hash`，`MemberDigest = schema_wiki_sha256("batch-concept-member.830.g3.v1", PageMember)`。因此同一 Release 的所有成员共享 outer Candidate identity；旧 G2 snapshot 算法不变。

代表性跨语言正向 fixture 固定从真实 Catalog 选四个 entry：

1. `schemapack_medical_insurance` / 67 fields / 7 sections；
2. `schemapack_critical_illness_insurance` / 67 fields / 8 sections；
3. `schemapack_endowment_insurance` / 79 fields / 8 sections，对应当前 corpus 的 material11；
4. `schemapack_accident_insurance` / 62 fields / 7 sections，对应当前 corpus 的 material13。

前两项同样从当前 corpus 的医疗/重疾材料选 exact child。fixture 至少含一个 CREATE 和一个 MATCH，全部 required field 都有一个 attempted 三态 FieldAssertion；不能用缩减字段集冒充代表 pack。若真实 preflight 判某材料尚无冻结 C 自动资格，fixture 仍先验证协议，但现场 Candidate 必须保持 `NOT RUN/NEEDS_CONFIRM`，不得伪造锚点补齐。

## 4. Go 与唯一 Release authority 接线

### 4.1 严格解析和向后兼容

新增 `internal/types/concept_free_wiki_830_g3.go`：镜像外层 DTO、schema-wiki hash、Catalog wire hash、resolution selected child、entity binding、G3 context、manifest 和 candidate hash。该文件可直接调用同 package 已有 `schemaWikiCanonicalJSON/schemaWikiSHA256`，并复用 G2 Go DTO/validators。

Go 必须把内联 Catalog 当作一份完整的受版本约束输入校验，而不是只核对 binding 中调用方给出的 pack/profile 三元组：先对 Catalog 子树做 NFC、sorted-key compact JSON 并核 `catalog_wire_sha256`，再重算每个 field semantic hash、pack hash、Profile hash和 `catalog_sha256`；最后只能从这棵已验 Catalog 按 exact `(schema_pack_id,schema_version,schema_pack_sha256)` 取 pack，并核对应 entry 的 Profile 与 classification。当前 v1 的 wire/content hash 可进入 G3 合同常量或只读 registry；不得为四个代表 pack另写一套硬编码字段表。Catalog 在 outer request 中仍只出现一次。

新 G3 struct 的所有 wire 字段都必传；nullable 字段必须显式 `null`。不能依赖 `omitempty` 区分“未出现”和 null；如 Go 指针需要表达 null，custom `UnmarshalJSON` 必须先检查 exact key set/presence。旧 `ConceptCandidateBundle830G2.Admission omitempty`、`admissionSeen` 和 v1/v2 exact-key 行为保持原样。

旧 fixture `concept_free_wiki_830_g2_*` 必须逐字 SHA 不变，并继续通过 `ParseConceptCandidateBundle830G2`。G3 只按顶层 contract 分派；未知 contract、额外键、重复键、非 NFC、float、null/omitted 漂移全部拒绝。

### 4.2 Create / Review / Activate

1. `internal/handler/schema_wiki.go`
   - `schemaWikiCreateDraftRequest` 新增 `batch_concept_candidate_bundle: json.RawMessage`；
   - `decodeSchemaWikiCreateDraftRequest` 新 exact-key variant `preparation_id + batch_concept_candidate_bundle`；旧两键 G2 variant 不变；
   - 调用 `SchemaWikiService.CreateBatchConceptDraft830G3`。

2. 新增 `internal/application/service/concept_free_wiki_830_g3.go`
   - `CreateBatchConceptDraft830G3`：human admin/dual KB seal 后 strict parse outer bundle、校验 scope/base Head/Catalog/confirmation、生成 G3 snapshots，再调用现有 `createDraftAtExpectedHead`；
   - CandidateDigest=outer candidate hash；ReadyReceiptDigest=G3 reviewer raw-output hash；ReviewPolicyID 仍由 base request policy identity 进入现有 `conceptReviewPolicyHash830G2`；
   - `validateBatchConceptPreparation830G3` 对 Draft/Ready 重新 canonical parse、重算 manifest/snapshots/preparation digest/base Head bindings。

3. `internal/application/service/wiki_release.go`
   - `reviewDraft`、`ActivateReviewed`、private `activate` 的 manifest contract switch 增加 G3 validator；
   - review 和 activation 都调用同一个既有 `verifyConceptSourceAuthority830G2` port，但 port 实现按 manifest contract 分派到 G3；
   - 保留 named-human whole-batch receipt、PublishAuthorization、nonce idempotency、expected Head 和 repository CAS，绝不新增第二 Head 或直改 pointer。

4. `internal/application/service/concept_source_authority_830_g2.go`
   - 在现 `VerifyConceptSources830G2` 顶层按 contract 分派；G2 原路径不动；G3 helper 解包 outer request/output，重开全部 field/free-page Evidence 和 entity binding 的 identity/classification Evidence；
   - 每条 Evidence 继续走现 `verifyEvidence`：Knowledge、SourceRevision、manifest digest、revision source binding、chunk list、Unicode quote offsets、fixed PDF、native bbox 全链；
   - review 与 activate 每次都从 preparation.Manifest 重新解析并重开来源，不能复用 create 时内存结论；
   - legacy carryover traversal 增加 G3 case，取 `outer.request.base_request.base_release_id` 继续沿唯一 release chain；
   - Active citation helper加载 exact G3 release/preparation，使用 outer candidate hash 计算 citation identity并签现有 release/epoch-bound token。Preparation 预览只展示 exact quote/page，不签假 release token。

5. repository 与路由保持同一套 Draft/Ready/Release/member/Head 表和事务；不新增 migration/table/service。现有 generic `/activations`、`/current`、`/releases/:release_id/{pages,payloads,search}` 和 CAS API 原样复用。

### 4.3 刷新后重开 Preparation

当前 G2 没有列出 concept Draft 全成员的 HTTP 入口，只有内部 `ReadDraftMember`；仅靠前端内存不能满足刷新重开。因此必须新增一个 human-only read surface，而不是假称现有接口已覆盖：

```text
GET .../schema/preparations/:preparation_id/batch-concept
```

响应 `batch-concept-preparation-read.830.g3.v1`：`read_mode=preparation`、scope、preparation_id、status `DRAFT|READY`、outer candidate hash、expected base Head、G3 page manifest members、entity directory entries。service 按 ID 从 `GetDraftPreparation` 或 `GetReadyPreparation` 读取并重新执行 `validateBatchConceptPreparation830G3`；不读或改变 Head。URL 的 `preparation_id` 是唯一恢复键，前端刷新后重新加载同一不可变 Candidate。

若用户从 Preparation 打开成员，前端可从该响应中的完整 frozen members 读取；无需第二个逐成员 route。它显示 quote/page 与 exact source identity。PDF source click 只在隔离 Active 后使用既有 release-bound authority，避免为未激活 Candidate 伪造 release_id/activation_epoch。

## 5. Active PinnedRead、目录与前端

Active 后继续先 generic `/current` pin 唯一 Head，再用 exact release ID读 generic `/releases/:release_id/search?q=`。现有真实字段页 transport 走 scoped schema `/concept-pages/:member_id?release_id=:release_id`，其服务端只从该 pinned release 组装页面和引用；generic `/pages/:logical_slug`、`/payloads/:logical_slug` 仍保留为底层 PinnedRead API，不要求 UI 改走另一条页面链。G3 前端不读 Harness Candidate、不读 RAW chunk、不接受任意 release 替换。

建议新增 `frontend/src/api/schema-wiki/batchConcept830G3.ts`：

- strict 解析 active generic snapshots 与 preparation response；
- 以 G3 overview payload 为分派信号，验证所有 snapshot revision=outer candidate hash、member digest/owner/ref、pack/profile/sections/field coverage；
- preparation 只允许 `preparation_id`，active/pinned 只允许 `release_id`，两种 query 互斥；
- active 点击 Evidence 继续调用已有 concept citation authority transport，但 candidate identity 使用 outer hash。

修改 `SchemaWikiCatalogEntry830G2.vue`：若 URL 有 exact `preparation_id`，走 human preparation API并显示“待审核/已审核但未发布”；否则保持 Catalog 与 active directory 并行读取。旧 G1/G2/legacy mode 不变。

修改/泛化 `ConceptDirectory830G2.vue`：G3 entity 卡片显示正式产品名、primary classification、pack identity、Profile identity、质量状态；按分类分组实体，实体内按 Profile sections 顺序显示字段。旧 G2 输入仍显示原 entity ID 卡片。

修改/泛化 `ConceptFreeWiki830G2.vue` 和 API parser：G3 field 页面显示 short title、值/unknown、conditions、exceptions、valid_time、同版 Evidence；active 时允许 source click，preparation 时展示 frozen quote/page 和“激活后可打开原件”。路由名称可保留 `conceptPage830G2` 以免迁移书签，query parser 增加互斥 preparation mode；后续若命名清晰度要求再改 UI 文件名，不是合同前置。

## 6. 实际最小路径（不预设 5 文件）

### 6.1 最小可跑纵向切片

第一条实现切片覆盖完整用户路径。最小跨语言fixture含上述四个真实pack各一实体，共 `67+67+79+62=275` 个 required field；至少一个 entity binding 为 CREATE，其余可为 MATCH，且 275 个字段全部各有一个 attempted 三态 FieldAssertion。输入直接来自冻结 Catalog、最终冻结的 C corpus/proposals/existing/policy/resolution 和现有 G2 compile/review adapter。CREATE 在 bundle 内使用本稿稳定逻辑 ID，既不查也不写新实体主数据表。

可运行顺序与真实接口如下：

1. 纯 Python `build_batch_compile_request` 重跑 C 并构建 exact G3 request；现有 G2 compile/review adapter产出并验证 `CompileOutput/ReviewOutput`，G3 投影器生成一个 human outer Candidate。
2. 既有执行者用冻结完整 bundle 提交 `POST /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations`，body 只有 `preparation_id + batch_concept_candidate_bundle` 这一 G3 exact variant。服务严格重验 Catalog/C/base Head/source custody并写现有 Draft repository。
3. 创建后 UI 使用 `/platform/knowledge-bases/:kbId?tab=schema&preparation_id=:preparationId`；刷新时调用新增 `GET /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema/preparations/:preparation_id/batch-concept`，从现有 Draft/Ready 恢复同一个 frozen Candidate、完整实体目录和按各Profile计数的全部字段。
4. 具名整包审核继续调用 `POST .../schema/preparations/:preparation_id/review`，进入现有 Ready；来源 authority 在审核时重开 FieldAssertion、free-page 和 identity/classification Evidence。刷新同一路径应显示 READY，但不出现在 serving `/current` 或 `/search`。
5. 现有发布界面用 `POST /api/v1/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/activations` 提交同一 named-human decision 与 publish authorization；既有 `ActivateReviewed`、nonce、expected Head 和 CAS 原子切换唯一 Head。C Candidate 与 Draft/Ready 均不能直接进入 Head。
6. 激活后 `/platform/knowledge-bases/:kbId?tab=schema` 先读 `GET .../current`，再只用返回的 exact `release_id` 读 `GET .../releases/:release_id/search?q=`；G3 overview payload驱动按分类、产品名、Profile section 展示四实体目录。
7. Active 字段页继续使用 `/platform/knowledge-bases/:kbId/schema-wiki/concept-pages/:memberId?release_id=:releaseId`，前端调用真实 scoped schema `GET .../schema/concept-pages/:member_id?release_id=:release_id` 与 `GET .../schema/concept-pages/:member_id/citations/:citation_id/preview?release_id=:release_id`；服务端只从同一 pinned release 组装页面并签 release-bound citation。Preparation 字段页使用同一路由的 `?preparation_id=:preparationId`，内容来自步骤 3 的 frozen members，只能预览 exact quote/page，不生成 Active citation token。

真实执行必须保留全部base实体。当前G2 base含两个医疗实体；若各新增重疾、两全、意外各一实体，则实际为5实体/342字段，四类pack。275只是最小fixture数，不是产品硬上限或真实batch已验事实；实际数量按base ExistingFields/EntityVersions及最终自动绑定集合重算。不得丢弃第二个既有医疗实体来凑275。

用户无需手填或粘贴技术JSON；冻结bundle的POST由既有执行者完成，用户打开不可变preparation查看整包。页面新增范围是可读、可重开与现有审核入口的接线，不追加手动JSON导入产品流程。

该切片的验收必须在真实浏览器刷新后仍可重开 Draft/Ready，审核前后 `/current` 不变；激活 CAS 成功后完整实体集合及所有字段、条件、例外、有效期和同版 Evidence 都能从 exact pinned release 读取和搜索。至少对一个 CREATE 产品完成整条路径，证明新增逻辑实体可进入同一 Candidate/Release，而无第二次主数据注册前置。这里的“完整用户路径”是软件最小切片；真实材料未达到 C 自动资格时，现场运行不得用测试 fixture 替代来源，DoD 仍为 `NOT RUN/NEEDS_CONFIRM`。

### 6.2 真实代码边界

生产路径至少需要以下 10 组、共 12 个文件；缺任何一类都会留下真实链路断点：

1. `harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py` — 外层 DTO/build/validate/project。
2. `internal/types/concept_free_wiki_830_g3.go` — Go strict/canonical/cross-language parser。
3. `internal/application/service/concept_free_wiki_830_g3.go` — create、base snapshot、preparation reopen、active G3 bundle/member helpers。
4. `internal/application/service/concept_free_wiki_830_g2.go` — 仅抽取/分派共享 G2/G3 base-chain 与 active citation读取；旧分支不改语义。
5. `internal/application/service/concept_source_authority_830_g2.go` — review/activate/active citation 对 G3 manifest 解包并真实重开。
6. `internal/application/service/wiki_release.go` — 三处 manifest contract switch 接 G3，继续同一 review/CAS。
7. `internal/handler/schema_wiki.go` — Create variant 与 preparation GET handler。
8. `internal/router/routes_schema_wiki.go` — human-only preparation reopen route；现 activation/current/search routes复用。
9. `frontend/src/api/schema-wiki/batchConcept830G3.ts` — strict active/preparation client。
10. `frontend/src/views/knowledge/schema-wiki/SchemaWikiCatalogEntry830G2.vue`、`ConceptDirectory830G2.vue`、`ConceptFreeWiki830G2.vue` — 现有三个页面的 G3 mode 增量。

写入所有权保持单一且可审计：Python harness 只生成/验证 canonical bundle bytes，不持久化；`schema_wiki` handler 只做 strict transport decode 和调用 service；`SchemaWikiService` 只能经既有 release authority 创建 Draft、提交 Review，并通过现有 repository 接口读回 Draft/Ready；source authority 全程只读重开；只有 `WikiReleaseService` 能经现有 repository 写 Draft/Ready/Release/receipt，并在 activation transaction 内 CAS 唯一 Head。前端只写本地界面状态并调用上述既有写 API。D 不写冻结 Catalog/C 文件、不写实体主数据表，也不让 CREATE entity ID 成为 repository 之外的第二 serving authority。

测试路径对应上述边界，不应塞回一个巨型测试：

- `harness/tests/test_batch_concept_compile_830_g3.py`；
- `harness/tests/fixtures/batch_concept_compile_830_g3_contract_vector.json`；
- `internal/types/concept_free_wiki_830_g3_test.go`；
- `internal/application/service/concept_free_wiki_830_g3_test.go`；
- 现 `concept_source_authority_830_g2_test.go`、`wiki_release_test.go` 增加 G3 分派反例；
- 现 handler/router tests 增 Create variant、preparation ACL/reopen；
- 新 API spec 加三个现有 Vue spec 的 G3 mode 用例。

不需要 repository、migration、agent tool 或新后台 service。现有 `schemaWikiHTTPService` 只增加 preparation read/create 所需方法，现有 source authority port 保持同一方法并按顶层 contract 分派。Agent/Search 已消费唯一 Active member snapshots；只需用真实问题验证字段 content 已包含值/条件/例外且来源仍由 exact release citation authority 打开。

## 7. RED 向量

### Python / 跨语言

1. G2 validator 对 G3 外层失败，证明不能 subclass/塞 extra；新 validator 接受四 pack exact vector。
2. Catalog 出现两份、wire/content hash互换、confirmation少一个 Profile/改 hash、actor 字段 omitted/null 漂移均拒绝；具名非 null实例可通过。
3. CREATE 的 entity/version 公式任一字符漂移、C Candidate NOT_ACTIVE/sha/key 漂移拒绝；MATCH 改写原 serving ID拒绝。
4. 选择 NEEDS_CONFIRM/QUARANTINE child、不同 key/version/pack 混为一个 binding拒绝；MULTI 中两个合法自动 child可分别进入同一外层 human Candidate。
5. required_fields 与 Profile 少一项、多一项、只排序后相等、短标题/section 伪映射均拒绝；四 pack分别严格为 67/67/79/62（若冻结替代 pack则用其真实数）。
6. 同 SourceBlock 两实体各有独立 name/code quote通过；共同 issuer/classification/通用条款 quote 在各 owner/ref 明确绑定时通过；复用另一实体的 product_code/name/version occurrence、跨 material、跨 scope、错 revision/attempt/manifest/offset失败。
7. 每字段恰好一个 attempted FieldAssertion；known 无Evidence、unknown有Evidence、entity version漂移、owner source scope漂移失败。
8. conditions/exceptions/valid_time 在 compile output→G3 manifest→Go snapshot roundtrip逐字相等；修改任一值导致 member/candidate hash不匹配。
9. reclassification（同 pack）只改变分类/navigation/candidate hash，entity ID/version、FieldAssertion ID/payload Evidence 不变。
10. Python生成 canonical fixture，Go重算 request/context/manifest/candidate/member hashes完全相同；Go unknown key、duplicate key、non-NFC、float、omitted-vs-null反例失败。
11. 旧 G2 fixture raw SHA、candidate hash、snapshot members逐字不变。冻结基线：v1 `concept_free_wiki_830_g2_contract_vector.json`=`d36546179939a4fdc8e1a53e4dacbe9ce1aaf2313f07f280c42dd8ff44b291aa`；v2 human=`c864fcd359f76c3ba708acd28009fb4e567a45e37ec4816c69eabfc46a40a700`；canonical vector=`02787ba2c17af49078349d37ac024f5e9e1bb06ab0b23c0640278adcba86d795`。

### Go service / UI

12. Create Draft 使用 outer CandidateDigest、existing expected Head；CREATE entity不查主数据表、不变 Active。
13. Review 前真实来源被撤销/manifest或quote漂移失败，Draft保持；修复来源后同 exact Draft可Review。
14. Review 后、Activate 前再次漂移时 Activate失败且 Head/CAS/receipt零写；恢复后 exact authorization激活一次，nonce retry幂等。
15. stale expected release/epoch CAS失败，不覆盖并发 Head。
16. preparation GET 在进程/页面刷新后按 exact ID重开 DRAFT 与 READY；无管理员/双KB seal、外域ID、manifest/member漂移失败；不读取 serving Head。
17. Active directory先 pin current，四实体按正式产品名/分类分组，字段按各Profile 7/8 section顺序；未发布 preparation永不出现在 generic current/search。
18. 搜索产品名、分类、section名、字段值、condition、exception都命中同一 active release成员；不命中 RAW 或其他 release。
19. Active field source click重开 exact SourceRevision并返回同版 quote/page；换 release/candidate/member/citation 任一身份失败。
20. Catalog/profile质量状态始终显示 REGISTERED_NOT_QUALITY_ADMITTED；UI或服务不得把结构确认改写成 QUALITY PASS/production admitted。

## 8. 验收与非目标

D software GREEN 只说明协议/接线可用。真实 15/15模型尝试、四代表 pack Candidate、具名 human Review、隔离 Activate、PinnedRead、来源点击、搜索问题都要各自保留 exact execution/preparation/review/activation/source receipts；未运行项继续 `NOT RUN`。

当前真实 `source21` 只证明材料中有多组独立产品名称/code，尚未证明存在两个完整 filing/registration 版本锚点；因此 D 不把其 children 预写为自动 `MATCH/CREATE`，也不承诺真实五种 disposition 已全部可达。按 C 复审裁决，父材料可以是身份级 `MULTI`，同时各 child 因版本待核而保持 `NEEDS_CONFIRM`；这些 child 不能被 D 选择。实现后的真实 preflight 必须只读核验版本锚点，缺失时不得补造材料、标签或 registration。

本切片不新增实体主数据注册服务、数据库表、第二 Wiki/Head、第二审核链、表格 parser、Q0 质量模型或生产发布开关；不把 C Candidate 当 Active，不按产品拆 KB，不让分类更改身份或让 Catalog schema 文本冒充事实。
