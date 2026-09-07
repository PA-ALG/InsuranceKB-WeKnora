# G3 D：多 SchemaPack Candidate / Review / Release 合同（私有合并稿）

状态：`PRIVATE_CONSOLIDATION_READY_FOR_LOSSLESS_REVIEW`。本文只把已存在的 D 原设计与修订 1、2、4、5、6 合成一份可复核文本；修订 6 撤销修订 3 的 legacy/344 方案。本文不新增协议，也不授权 D 代码、真实模型、数据库、构建、Draft、Review、发布或 Active 变更。在 Root 冻结最终合同前，本文不是实施 authority。冻结 Catalog、C 合同和用户结构确认的原字节均不改变。

本文合并以下输入，冲突按修订序号由新到旧覆盖：

- `lane-d-contract-design.md`，SHA-256 `415742f61d443ddeb5b00d13fcdddd8dae97ddc370bd8f61a42000f7c8924512`；
- `lane-d-contract-review-amendment-1.md`，SHA-256 `d70fc9ad4385921e018ca8c76e2ee7dc8e9cbbe9b5c2cb2b05c28c870c4eb309`；
- `lane-d-base-binding-amendment-2.md`，SHA-256 `7c71873a7af9017276f61942bc51b2a0b318e1fbd492deb8153122473466ad08`；
- `lane-d-legacy-field-preservation-amendment-3.md`，SHA-256 `dc9c8804183c9fb2c539f0d99559b03a646a8caa1ac964d8a8ee9b0070be4abe`；
- `lane-d-compile-record-amendment-4.md`，SHA-256 `ac46c90d91bce1133c9f7c4991b079cc721defda2050c4f9f06a73e64537fb8a`；
- `lane-d-base-pack-compatibility-amendment-5.md`，SHA-256 `408326eb72c966b60c30c7edf4293777913c385f47cd28cd06ae4e6adf816d75`；
- `lane-d-unknown-key-alignment-amendment-6.md`，SHA-256 `8673c257c493020262de418c03eb789d2569909e008b2feb0b0ccf5fd640c9dd`，独立复核 `BLOCKER0`。

## 1. 结论、边界与身份

D 使用新的 G3 外层合同承接完整 Catalog、C 的输入闭包与批次决定、逐实体 pack/profile/classification 绑定。内部继续复用 G2 的 exact `CompileRequest`、`CompileOutput`、`ReviewOutput`、`ExecutionRecord`、`FieldAssertion`、`FreeWikiPage`、`ConceptDefinition`、`Evidence`、`PageMember` 和 `AuditDisposition`。不得把 G3 字段塞进 G2 subclass；Python `concept_compile_830_g2.validate_output()` 会重新强转 exact G2 request/output，Go 也使用 exact-key strict decode。旧 G2 v1/v2 DTO、hash、raw-output 校验与 fixture 原字节必须保持不变。

G3 外层始终形成 `human_batch` Candidate。高置信 `CREATE` 可以提出稳定逻辑实体并与 `MATCH` 一起编译，但只能进入同一份既有 Draft、具名整包 Review、Ready、`ActivateReviewed` 与 CAS 链。C 的 `EntityCandidateV1.status=NOT_ACTIVE` 不是 serving 状态；C Candidate、Draft 和 Ready 都不能直接写唯一 Active Head、实体主数据表或 serving search。

CREATE 的逻辑身份固定为：

```text
entity_id      = "entity_" + entity_key_sha256
entity_version = entity_id + "@" + version_candidate_key_sha256
```

两个 key 必须取 C 已验证 Candidate 的原值并按 C 公式重算。MATCH 原样使用 C 的 `matched_entity_id` 和 `matched_entity_version`。分类、Profile、短标题、材料顺序和模型运行 ID 都不进入实体身份。

G3 Candidate 只允许 `REGISTERED_NOT_QUALITY_ADMITTED / ISOLATED_NOT_FOR_PRODUCTION`。它可在隔离 scope 走完真实 Review、Activate 与 PinnedRead 来验证 FLOW，但不能因此升级为 Q0 质量准入或生产发布。

本切片不新增实体主数据注册服务、数据库表、第二 Wiki/Head、第二审核链、签名体系、表格 parser、Q0 质量模型或生产发布开关；不按产品拆 KB，不让分类改变实体身份，不让 Catalog schema 文本冒充事实。

## 2. Python 公共合同

建议唯一新增 Harness 生产文件为 `harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py`。DTO 必须 frozen、strict、`extra="forbid"`。新 G3 对象使用各节明确给出的 `schema_wiki_sha256` 域；嵌套 G2 DTO 保留原 `digest()` 和 wire，不重哈希成新的 G2 identity。

### 2.1 Profile 确认绑定

`CatalogProfileConfirmationReceipt830G3V1` 精确描述现有 `830-g3-profile-user-confirmation.v1` 的全部键：

- `confirmed_at_recorded`、`decision=CONFIRMED`、`user_reply_verbatim`、`actor`、`confirmation_channel`、`review_document`、`review_document_sha256`；
- `catalog_sha256`、`catalog_wire_sha256`；
- `profiles[]`，每项 exact `profile_id/profile_version/profile_sha256`；
- `scope`、`not_included[]`、`identity_metadata_note`；
- `actor_display_name: Text | None`、`queue_owner: Text | None`。类型允许具名字符串或 null；当前实例为 null，但类型不得写死为 null，也不得虚构姓名或队列负责人。

`CatalogProfileConfirmationBinding830G3V1` exact wire：

```text
contract = catalog-profile-confirmation-binding.830.g3.v1
receipt
receipt_file_sha256
receipt_semantic_sha256
```

`receipt_semantic_sha256 = schema_wiki_sha256(receipt.contract, receipt)`。当前实例 file SHA 为 `7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863`，semantic SHA 为 `cd40072b3c4c32c3ed9440c7ff1ff5effc502c506b4ab11c86bbe438c7649b66`。Receipt 的 Catalog content/wire hash 和 11 个 Profile identity/hash 必须与内联 Catalog 完全一致；确认 receipt 不修改 Catalog 内原 `PENDING_PRODUCT_OWNER_CONFIRMATION` 字节。

### 2.2 C 输入闭包

`BatchResolutionInputs830G3V1` 是 `BatchConceptCompileRequest830G3V1.resolution_inputs` 的唯一 exact DTO：

```text
contract = batch-resolution-inputs.830.g3.v1
corpus = exact BatchCorpusV1
proposals = exact ProposalBatchV1
existing_entities = exact ExistingEntitySnapshotV1
policy = exact BatchResolutionPolicyV1
inputs_sha256
```

各 C 输入只内联一次；Catalog 不进入该对象；嵌套输入的原 hash 不变。`inputs_sha256 = schema_wiki_sha256(contract, payload_without_inputs_sha256)`。Outer resolution 的 corpus/proposals/existing_snapshot/policy SHA 必须逐一匹配；scope 与 base request、route 逐项相等；C existing snapshot 的 base release/epoch 与唯一 Head 的预期值一致。Python builder 必须从这些 exact inputs 重跑完整 C 输出。

Go strict decoder 必须解析并重算相同的 C 输入及各级 hash，不能只相信 resolution self-hash。对所有选中 child，Go 机械重验 source/proposal/PolicyReceipt/model 用途绑定、身份与 classification 两个阈值、精确 pack、name/code/version/issuer 依据、对应 TrustRule、parent gate，以及 CREATE key 或 MATCH existing key。此过程不重新分类、不生成 Evidence、不解释条款、不新增 PolicyReceipt 或模型服务。Policy snapshot 仅供审计，不冒充远端模型授权；source 真值仍由现有 REST source authority 重开。

C parent 为 `NEEDS_CONFIRM` 或 `QUARANTINE` 时，任何 child 均不可选择；parent 为 `MULTI` 时，只能选择自动合格 `MATCH/CREATE` child。调用方提供的 `policy_sha256` 不授予自动发布能力。G3 无条件 `human_batch`，结构确认和 classifier 结论均不赋予 Active 能力。

### 2.3 C 决定引用、Evidence 与实体绑定

`ResolutionDecisionRef830G3V1` exact wire：

```text
material_id
proposal_ref
decision_sha256
classification_assignment_sha256
```

引用按 `(material_id, proposal_ref)` 排序且唯一。每个 ref 必须在内联 `BatchEntityResolutionV1` 中唯一命中同一 child；child 必须为满足 C 自动资格的 `MATCH` 或 `CREATE`。父材料只能为 MATCH、CREATE 或 MULTI；父 `NEEDS_CONFIRM/QUARANTINE` 的 child 与 child 自身 `NEEDS_CONFIRM/QUARANTINE` 永远不能进入编译。父 `MULTI` 的身份成立不授予 child 自动编译资格。最终 C 中每个 child 的最小 name/code Evidence ID 集合由原 decision/batch hash 覆盖；所选自动 child 的两个集合必须各自为 child evidence 的非空子集，覆盖 name 与 product_code，并全部进入绑定 Evidence 与 source authority 重开。

`BoundResolutionEvidence830G3V1` exact wire：

```text
material_id
proposal_ref
evidence_id
purpose = issuer | product_code | name | version | classification
evidence = exact G2 Evidence
```

它从 exact `ProposalBatchV1` 提取，必须被对应 child 的 `evidence_ids` 引用；purpose、proposal_ref、quote、offset 和 source identity 不得改写。按 `(material_id,evidence_id)` 排序。

区分性的 name/code/version occurrence 与 C design2 完全一致：使用完整 `SourceIdentity + block/page/start/end/quote_hash`，忽略 `evidence_id/purpose/proposal_ref`。不同 ID 或 purpose 不能把同一真实 span 伪装成独立产品依据；不同产品在同一 block 的不同精确 span 可以独立；共同 issuer/classification/通用条款在 owner/ref 关联明确且来源有效时允许共享。禁止使用另一个 child 的 Evidence ID/proposal_ref 或另一个实体的独立身份/事实 Evidence 代替本实体依据。FieldAssertion Evidence 必须属于 owner binding 的 source allowlist。协议不以“整 SourceBlock 独占”冒充语义证明。

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

`binding_sha256 = schema_wiki_sha256(contract, payload_without_binding_sha256)`。

MATCH 的 `candidate_id/entity_candidate_sha256` 必须显式 null；`entity_id/entity_version` 与所有 ref 的 matched IDs 原样相等。MATCH 仍重算 entity/version key 供审计，但不得用它替代 serving ID。CREATE 的所有 ref 必须指向同一 C Candidate；`candidate_id` 和 candidate SHA 完整，D 的 entity ID/version 按固定公式生成。所有 ref 必须具有一致的 normalized issuer/name/code/version anchor、primary classification 和 pack 三元组，否则 D 拒绝。

Pack 必须从内联、已严格验证的 Catalog exact 取包；Profile 必须是该 entry 的 exact Profile。`required_fields` 逐项逐序等于 `profile.ordered_field_keys`，不能只比较 set。每个选中 pack 的 FieldDefinition 数必须与该实体最终独立 FieldAssertion 页数完全相等。

实体显示名使用 C Candidate/MATCH anchors 的来源原文，normalized 值必须一致。`source_material_ids` 是 refs 的 material_id 去重排序集合。Owner source allowlist 是所选 refs 的 source materials 与该实体全部 base carryover Evidence source closure 的并集。

### 2.4 外层编译请求

`BatchConceptCompileRequest830G3V1` exact wire：

```text
contract = batch-concept-compile-request.830.g3.v1
base_request = exact G2 CompileRequest
catalog = exact SchemaPackCatalogV1（完整实例，仅此一份）
catalog_wire_sha256
profile_confirmation
resolution_inputs = exact BatchResolutionInputs830G3V1
resolution = exact BatchEntityResolutionV1
entity_bindings[]
unknown_field_key_alignments[]
quality_status = REGISTERED_NOT_QUALITY_ADMITTED
release_lane = ISOLATED_NOT_FOR_PRODUCTION
request_sha256
```

`request_sha256 = schema_wiki_sha256(contract, payload_without_request_sha256)`。

`catalog_wire_sha256` 是 Catalog 对象按 UTF-8、NFC、对象键排序、紧凑 JSON 序列化后的普通 SHA-256；当前值为 `0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9`。Catalog content hash 是内部 `catalog_sha256=b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd`，两者不得互换。

请求必须同时满足：

- `resolution.catalog_sha256 == catalog.catalog_sha256`，且 `resolution.space_id == base_request.space_id`；C resolution 本身没有 tenant/raw/wiki 字段，不能读取不存在的 scope；
- `resolution_inputs` 的四个原 hash 与 resolution 对应 hash 逐项相等；Python 与 Go 均从 exact inputs 重跑/重验 C；
- `corpus.tenant_id/space_id/raw_kb_id/wiki_kb_id` 与 base request 和 route scope 逐项相等；所有 binding Evidence 的 source receipt/block scope 同样相等；
- entity binding 的 entity 集合逐一等于 `base_request.required_fields` 和 `base_request.entity_versions` 的 key 集合；
- `base_request.required_fields[entity] == binding.required_fields == profile.ordered_field_keys`，逐项逐序完全相等；
- `base_request.existing_fields` 保留 actual G2 base 的原 134 行，包括两个旧单数 key；`unknown_field_key_alignments` 必须恰好是修订 6 冻结 fixture 的两行，按 `entity_id` 排序并进入 request hash；
- `base_request.entity_versions[entity] == binding.entity_version`；
- `base_request.schema_identity = "catalog:" + catalog_id + "@" + catalog_version + "#" + catalog_sha256`；
- `base_request.profile_identity = "profile-set:" + schema_wiki_sha256("batch-profile-bindings.830.g3.v1", profile-set payload)`；
- profile-set payload 是按 entity_id 排序、拒绝重复的数组，每项 exact keys 为 `entity_id/profile_id/profile_version/profile_sha256`；
- `base_request.policy_identity = "g3-resolution-policy:" + resolution.policy_sha256`；
- `base_request.sources` 是新选中材料所需 SourceBlock 与全部 carryover Evidence 所需 SourceBlock 的 canonical 并集，按 `(revision_id,block_id)` 去重；同 identity 不同 bytes 拒绝；共享 block 只内联一次；
- base request 的 existing definitions/fields/pages/entity versions 与 base release/epoch 必须从当前 exact base Head 全部成员重开，由 Go 与库内 base 核对，调用方不得少传或缩小集合；
- C existing snapshot 的 base release/epoch 与 base request、route 预期 Head 完全一致。

建议纯函数入口：

```python
build_batch_compile_request(
    *,
    base_request: CompileRequest,
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

入口先重跑 C 并要求结果逐字等于传入 resolution，再提取 Evidence 和 bindings；不接受调用方手填 entity ID、pack/Profile 或 Evidence。函数纯内存，不调用 provider/DB。

### 2.5 完整 base MATCH 与既有 pack 兼容

首切片采用完整 base MATCH 前置。当前 base Head 中每个 existing entity/version 都必须在本批 exact C inputs 和最终 resolution 中至少有一个自动合格 MATCH child，且 D binding 实际选择该 ref。此条件在 compiler/provider 调用和 Draft 创建前验证；不能默认批次恰好覆盖。

- actual base entity 集合从唯一 base Head 全成员和原 base request 重开；
- 每个 base entity 恰有一个 D binding，`resolution_disposition=MATCH`，原 entity ID/version 逐字保留；refs 满足完整 C 自动门槛、parent gate、同一身份/分类/pack/Profile；
- 缺 ref、只有 NEEDS_CONFIRM/QUARANTINE、parent 不合格、版本不同、用 CREATE 替代、或 MATCH 指向别的 entity，均返回 `BASE_ENTITY_MATCH_REQUIRED`，不生成半包，也不删除 base entity；
- source material IDs 仍来自所选 MATCH refs；owner allowlist 另加入真实 carryover Evidence source closure；base field 事实不要求重新提案，但 identity MATCH 资格和旧事实完整保留均必需；
- 当前 v4 选中 01—04 是两个 base 医疗实体的既有条款/说明书；此事实不授权重传或重解析，也不表示真实 MATCH 已完成。actual C 模型执行仍为 `NOT RUN`。

本切片只支持以下唯一 base compatibility mapping，常量必须从已发布 G2 持久化 bundle 和已确认 Catalog 核对，不能从字段数猜分类：

```json
{
  "base_contract": "concept-candidate-bundle.830.g2.v1",
  "base_schema_identity": "medical-schema67.v1@fe3b390222108614d3ff07409fbd81d17e915e066eb9c25c03d3268bc49ef7ac",
  "base_profile_identity": "medical-schema67.presentation.v1@d83a3b38e3b72bd986823d373b86fe1077e0baa6333a27dc74a2545f58bfd3e9",
  "catalog_sha256": "b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd",
  "classification": "medical_insurance",
  "schema_pack_id": "schemapack_medical_insurance",
  "schema_version": "2026-08-12-v5",
  "schema_pack_sha256": "5a7938dcb86327f12dbff6e3056271e03c63842ba34904eefebb5bcdc8694079",
  "profile_id": "profile_medical_insurance",
  "profile_version": "1.0.0-candidate",
  "profile_sha256": "61595e9b2fec127dfca4c31ef95f161d55a9b0939211316b4508ccc4b7d21cf3"
}
```

服务端从 actual base Head 重开原 candidate request，核 base contract/schema/profile identity；每个 base MATCH binding 必须使用上述 exact medical classification、pack 与 Profile，同时匹配 Catalog content hash。Python 对冻结 base 输入执行同一断言，Go 不得仅相信调用方。

Base MATCH 若被分到重疾、两全或其他 pack，即使 identity/version 匹配、置信高、旧字段全保留，也必须在 delta 编译/provider/Draft 前返回 `BASE_PACK_MIGRATION_REQUIRED`。旧 base contract/schema/profile 不在唯一映射内则返回 `BASE_PACK_AUTHORITY_UNSUPPORTED`，不能现场推断第二映射。本映射只支持首切片继承的 G2 医疗 base；未来 G3 多 pack base 或 pack migration 必须另行设计。

首切片不提供“本批无旧实体 MATCH 仍自动迁移旧目录”的通用能力。缺 MATCH 时应保持 base 并记 `BLOCKED`，不得另建身份 authority、前置平台或伪造模型结果。

## 3. 模型 delta、机械组合、校验与执行记录

### 3.1 两份编译结果和审核结果

`BatchConceptCandidateBundle830G3V1` exact 顶层：

```text
contract = batch-concept-candidate-bundle.830.g3.v1
request = exact BatchConceptCompileRequest830G3V1
model_compile_result = exact G2 CompileResult
compile_result = exact G2 CompileResult
review_result = exact G2 ReviewResult
page_manifest = exact BatchConceptPageManifest830G3V1
admission = exact G2 HumanBatchAdmission（必须存在）
candidate_hash
```

`model_compile_result.output` 是模型对本次新增成员的原始 delta 提案；其 execution raw 是实际 completion content 的逐字文本。`compile_result.output` 是固定机械组合后的最终逻辑输出；其 execution raw 是 final output 的 canonical JSON，不得伪称模型原文。两份 compile result 与 review result 全部进入 `candidate_hash = schema_wiki_sha256(contract, payload_without_candidate_hash)`。

Candidate 只允许 human admission。即使 reviewer PASS 且所有评分达到阈值，`admission.status` 仍是 `NEEDS_HUMAN`，`pending_page_ids` 可以为空。Outer candidate hash 是 Draft/Review/Activate 使用的 CandidateDigest；旧 G2 candidate hash 不变。

### 3.2 模型上下文和 delta 边界

`compiler_context_g3` exact keys：

```text
request = full G3 request
request_sha256
base_request_hash
output_mode = NEW_MEMBERS_ONLY
```

`model_compile_result.execution.context_hash = schema_wiki_sha256("batch-concept-compile-context.830.g3.v1", compiler_context_g3)`。模型仍看到完整 G3 request、base members、Catalog、C bindings 和 sources。run ID/implementation 必须是真实 execution identity；fixture 明确标为 fixture，不能制造实际模型 receipt。受控执行器另存 provider HTTP request/response；completion raw 不冒充整个 HTTP body。

Delta output 复用 exact G2 `CompileOutput` 和原 G2 `output_hash`，其 `request_hash` 等于 `base_request.request_hash`，但合并前不要求满足 G2 的全字段 coverage。组合前先按 §4 构造 `aligned_existing_fields`。G3 delta validator 必须执行：

- 每个实体的 delta field keys 恰好等于 `base_request.required_fields[entity] - aligned_existing_fields[entity] keys`；每项 attempted，entity/version 与 request 一致；不得输出任何旧 field key、已经对齐的 plural key 或旧 singular key；
- 新 definition 不得与 existing concept ID 重复；新 free page 不得与 existing free page ID 重复；新 field 可以引用 existing definition；
- delta audit 精确覆盖 delta objects；field 只能 `field_rule`；新 definition/page 只允许 `new_page` 或满足 G2 条件的 `sense`；不夹带旧 object audit 或额外 audit；
- raw 无重复 JSON key，逐字段语义等于 delta output；`raw_output_hash` 是原始 UTF-8 bytes SHA；不得用重序列化文本替换实际 completion；
- delta 的 owner/source/Evidence、conditions/exceptions/valid_time 与 request 约束全部有效。

### 3.3 唯一机械组合公式

`compose_batch_output(request, model_compile_result)` 是纯内存函数，不调用 provider/DB：

- `request_hash` 使用原 base hash；`transformation` 逐字沿用 delta，不能擅自提升为 EXTRACT 或消除转换标记；
- definitions 是 exact existing definitions 与 delta new definitions 的并集，按 concept_id 排序；
- fields 是 `aligned_existing_fields` 与 delta new fields 的无碰撞并集，按 `(entity_id,field_key)` 排序；
- pages 是 exact existing pages 与 delta new pages 的并集，按 free page ID 排序；
- 任一 identity collision 均拒绝，不采用先到或后到覆盖；
- audit 是 delta audit 加所有 carry objects 的确定性 audit，再按 key 排序：旧 definition/page 为 `alias_link, reason="BASE_CARRYOVER"`；其余 132 个旧 field 为 `field_rule, reason="BASE_CARRYOVER"`；两个新 plural assertion ID 为 `field_rule, reason="BASE_UNKNOWN_KEY_ALIGNMENT"`；delta reason 原样保留；最终 promoted objects 与 audit 一一对应；
- final output 必须通过原 G2 `validate_output(base_request, final)`，再通过全部 G3 base 完备、unknown-only alignment、逐字 carry、owner/source、Profile、pack compatibility 与 manifest 约束。

除 §4 冻结的两个 unknown-only key alignment 外，所有 existing FieldAssertion 按 entity/field key 逐字保留 payload 与 Evidence；所有 existing ConceptDefinition 按 concept ID/definition hash 保留；所有 existing FreeWikiPage 按 free page ID 保留 payload/Evidence。旧 known 不得变 unknown；新产品可引用旧 definition，但不得替换旧 definition 或删除旧 free page。其余 132 个旧 FieldAssertion 只能机械 carry，不能由模型新建、删改、变 unknown 或替换 Evidence。两个对齐项也不能改变 unknown_reason 或任何事实载荷。任何其他旧事实修订属于后续独立设计。

`compile_result.output` 必须逐字等于机械重算结果，Go 同样复算。Final execution：

- `implementation = base-carry-compiler.830.g3.v1`；
- run ID 与 model compile、review 两个 run ID 各不相同；
- raw 是 final G2 CompileOutput 的 schema-wiki canonical JSON，恰好等于 canonical 字符串并通过 G2 raw semantic binding；
- `context_hash = schema_wiki_sha256("batch-concept-carry-context.830.g3.v1", carry_context)`；
- `model_compile_output_hash = model_compile_result.output.output_hash`；
- carry context exact keys 为 `request_sha256`、`model_compile_output_hash`、`model_compile_execution_sha256`；最后一项等于 `schema_wiki_sha256("batch-concept-model-execution.830.g3.v1", model_compile_result.execution)`；
- 新 G3 recorder 直接构造原 G2 `ExecutionRecord` 形状并重验，不能调用固定 G2 `execution-context` 域后伪称 G3 hash，也不修改旧 `record_output`。

### 3.4 Reviewer 和输出约束

`review_context_g3` exact keys：

```text
request = full G3 request
candidate = exact final G2 CompileOutput
request_sha256
base_request_hash
output_hash = final G2 output_hash
```

`review_result.execution.context_hash = schema_wiki_sha256("batch-concept-review-context.830.g3.v1", review_context_g3)`。ReviewOutput 绑定 base request hash 与 final output hash；raw 是真实 review completion；review run ID 与两次 compile run ID 均不同。审核看到 final output 与 full G3 request。G3 审计 hash 不授予网络权限、模型额度或 Active 能力。

`validate_g3_output()` 先运行 G2 `validate_output`，再验证：

- 所有 known FieldAssertion 和 FreeWikiPage 的 Evidence source key 属于 owner binding allowlist；
- unknown 字段 attempted、无 value、无 Evidence且有 unknown_reason；
- ConceptDefinition 可使用 request 内 admitted source，因为 definition 可跨实体共享；
- source closure、C child/ref membership 与区分性 occurrence 规则防止跨实体借据；共同 issuer/classification/通用条款可以按规则共享；
- `conditions/exceptions/valid_time/evidence` 保持原数组及顺序，并进入原 G2 payload/member digest；
- final output 对 existing definitions/pages 和其余 132 个 fields 是完整、逐字、无遗漏的机械 carry；两个冻结 unknown-only fields 只能发生 §4 的 key/identity 重建；
- model delta、final logical raw 和 review raw 分属其明确 identity，不能互相替换。

## 4. Unknown-only key alignment 与页面 manifest

### 4.1 唯一允许的两行对齐

Actual base 固定为 release `release-9cb493e3-8d27-4a0f-8f29-93e2a078725b`、epoch `5`、candidate `bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684`。两个医疗实体的旧 `social_insurance_requirement` 都必须逐字满足：`attempted=true`、`state=unknown`、`value=null`，Evidence、conditions、exceptions、concept_ids 均为 `[]`，`valid_time=""`，且分别保留原 `unknown_reason`。

唯一允许的对齐是这两个 exact entity/version 的 `social_insurance_requirement` → `social_insurance_requirements`，从旧 medical schema/profile 指向 §2.5 的 exact confirmed v5 medical pack/profile。它不是一般 alias，不证明两个 key 的事实等价，也不允许已知值或任何 Evidence/条件/例外/concept/time 的迁移。旧 release、旧 member ID/URL/payload 和历史 source 保持不可变；新 release 的每个医疗实体只有 Profile 的 67 个字段页。

`BatchConceptCompileRequest830G3V1.unknown_field_key_alignments` 是必传数组，按 `entity_id` 排序，由 builder 从 actual base payload 和上述唯一映射机械生成，不接受手填。当前 base 必须恰好两行并逐字等于 `unknown-field-key-alignment-exact-fixture.json`（SHA-256 `89eda07c37c8e0859bc97d121bf9e5e067123afc3f1b19d04d5c96f95b1960d4`，状态 `EXACT_LOCAL_DERIVATION_NOT_APPLIED`）。每行 exact wire：

```text
contract = unknown-field-key-alignment.830.g3.v1
source_release_id
source_activation_epoch
source_candidate_sha256
entity_id
entity_version
old_field_key
new_field_key
old_member_id
old_member_digest
new_member_id
new_member_digest
alignment_sha256
```

`alignment_sha256 = schema_wiki_sha256(contract, payload_without_alignment_sha256)`。`old_member_digest` 使用 G2 `digest("concept-member", exact old PageMember)`；`new_member_digest` 使用 D `schema_wiki_sha256("batch-concept-member.830.g3.v1", exact new PageMember)`。两行进入 request hash、compiler/review context 和 candidate hash。

Python 与 Go 都必须从 exact base Head 重开原 candidate/member，验证 source release/epoch/candidate、entity/version、old digest、旧 member 存在、新 key 在 base 不存在，以及上述全空资格。遗漏、伪造或漂移返回 `BASE_UNKNOWN_KEY_MIGRATION_REQUIRED`；任一 known/value/Evidence/condition/exception/concept/time 非空、unknown_reason 不符或企图清空旧值返回 `BASE_UNKNOWN_KEY_MIGRATION_INELIGIBLE`。

组合器先构造 `aligned_existing_fields`：其余 132 行逐字不变；两行只把 field_key 改为 plural，保留 unknown_reason、attempted、entity/version 与所有其他 payload。新 assertion ID 按 G2 field identity 公式重算，新 PageMember 按 D 标准 Profile title/content 投影。这是在新 Candidate 创建两个 unknown 占位，不声称旧 assertion/member hash 未变。历史链接必须带旧 `release_id`；新 release 不能假装旧 member ID 仍存在。

### 4.2 Page manifest exact DTO

`BatchConceptPageManifest830G3V1` 精确四键：

```text
contract = batch-concept-page-manifest.830.g3.v1
members = [exact G2 PageMember]
members_sha256
audit = [exact G2 AuditDisposition]
```

Members 按 `(kind,member_id)` 排序，member ID 全局唯一。G2 PageMember exact keys 为 `kind/member_id/owner_id/title/content/payload`；payload 按 kind 使用原 G2 object 或 G3 entity-directory-entry。`members_sha256 = schema_wiki_sha256("batch-concept-page-members.830.g3.v1", {"members": members})`。Audit 与 final CompileOutput.audit 逐字逐序相等，不另造、不省略。Manifest 不增加 request/output hash 或 self-hash；bundle 同时绑定 request/output/manifest，validator 必须重新 project 后逐字相等。

Go snapshot 使用 G3 manifest：`RevisionID = outer candidate_hash`；`MemberDigest = schema_wiki_sha256("batch-concept-member.830.g3.v1", PageMember)`。同一 Release 的成员共享 outer Candidate identity；这不表示 snapshot bytes 与旧 release 相同。旧 G2 snapshot 算法不变。

成员保持一字段一页：

- `concept`：复用 exact G2 definition payload；
- 标准 `field_assertion`：member ID/owner/payload 是 exact G2 FieldAssertion；title 来自 Catalog Profile `short_title`；content 首行为 present=`值：{value}`、absent_explicitly=`明确不提供：{value}`、unknown=`未知：{unknown_reason}`，再按原序追加每个 `条件：{condition}`、每个 `例外：{exception}`，valid_time 非空时最后加 `有效期：{valid_time}`；UTF-8 LF 连接、无尾换行；
- `free_wiki_item`：payload 原样，content 包含 body/conditions/exceptions/valid_time；
- `entity_overview`：沿 G2 稳定 member ID，title 为来源支持的正式产品名，payload 为 exact G3 directory entry；
- `free_wiki`：沿 G2 稳定 root ID，只链接本实体 free items。

Python outer bundle 不重复内联 base PageMembers。Go 从 actual base Head 核对其余 132 个 field member、全部 definition/free page 与 Evidence；两个对齐 member 则按冻结 lineage 和标准 Profile 投影重建。本首切片只支持现 G2 base。

### 4.3 Entity directory exact 增量

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

每个 section field 为 exact `{field_key,short_title,member_id}`，按 Profile 顺序投影；所有 sections 合计恰好覆盖 `binding.required_fields` 一次。Overview 不含历史额外字段、额外节点或第 8 个医疗 section。

Overview content 确定性包含产品名、分类、pack 名和 Profile section 名。分类重排只改变 binding/navigation/manifest/candidate hash，不改变 entity ID/version 或 FieldAssertion payload/Evidence；unknown key alignment 只由明确的 old-schema→v5 lineage 触发。换 pack 是后续 migration Candidate，首切片不得静默执行。

Human 整包预览必须明确列出两条 unknown key alignment，并显示旧 release lineage；Profile 结构确认不能替代最终 whole-Candidate 批准。Active 目录只显示 Profile sections 和每医疗 67 个当前字段页；旧 member 仅可通过带旧 release ID 的历史链接读取。

## 5. Go、唯一 Release authority 与来源托管

### 5.1 Strict DTO 与向后兼容

新增 `internal/types/concept_free_wiki_830_g3.go`，镜像外层 DTO、C inputs、Catalog wire、selected child、binding、unknown key alignment、三类 context、model/final/review results、manifest 和 candidate hash。它可复用同 package 的 `schemaWikiCanonicalJSON/schemaWikiSHA256` 与 G2 DTO/validators。

Go 必须先严格验证整棵内联 Catalog：NFC、sorted-key compact JSON、wire hash、每个 field semantic hash、pack hash、Profile hash、catalog content hash；再按 exact pack ID/version/hash 取包并核 entry Profile/classification。Catalog 在 outer request 仅出现一次，不得为四个代表 pack 另写硬编码字段表。

所有 G3 wire 字段必传；nullable 字段显式 null。不能用 `omitempty` 混淆 omitted 与 null；若 pointer 表示 null，custom `UnmarshalJSON` 先检查 exact key presence。顶层 contract 分派 G2/G3；unknown contract、extra key、duplicate key、non-NFC、float 与 null/omitted 漂移均拒绝。旧 `ConceptCandidateBundle830G2.Admission omitempty`、`admissionSeen` 和 v1/v2 exact-key 行为不变。

### 5.2 Create、Review、Activate 与 CAS

1. `internal/handler/schema_wiki.go`：create request 新增 `batch_concept_candidate_bundle: json.RawMessage` 的 exact variant，wire 只有 `preparation_id + batch_concept_candidate_bundle`；旧 G2 两键 variant 不变；调用 `SchemaWikiService.CreateBatchConceptDraft830G3`。
2. 新 `internal/application/service/concept_free_wiki_830_g3.go`：human admin 与 dual-KB seal 后 strict parse；重验 scope/base Head/Catalog/confirmation/C inputs/full base MATCH/pack compatibility、两行unknown-only alignment、carry/manifest；生成 G3 snapshots；调用既有 `createDraftAtExpectedHead`。CandidateDigest 为 outer candidate hash，ReadyReceiptDigest 为 G3 reviewer raw-output hash，ReviewPolicyID 仍由 base request policy identity 进入既有 `conceptReviewPolicyHash830G2`。Draft/Ready 重开均重新 canonical parse 并验证 preparation digest/base Head bindings。
3. `internal/application/service/wiki_release.go`：`reviewDraft`、`ActivateReviewed` 和 private `activate` 的 manifest contract switch 增加 G3 validator；review 与 activate 都从 preparation 重开并复算两行 alignment 及 final composition；继续使用具名 whole-batch receipt、PublishAuthorization、nonce idempotency、expected Head 与 repository CAS。
4. `internal/application/service/concept_source_authority_830_g2.go`：现有 `VerifyConceptSources830G2` 顶层按 contract 分派；G3 helper 解包 outer request/final output，重开所有 field/free-page Evidence 与 identity/classification Evidence；每条 Evidence 继续走现有 Knowledge、SourceRevision、manifest digest、revision source binding、chunk list、Unicode quote offsets、fixed PDF/native bbox 全链；review 与 activate 每次从 preparation.Manifest 重新解析并重开来源，不复用 create 时内存结论；base carryover traversal 从 `outer.request.base_request.base_release_id` 沿唯一 release chain；Active citation 用 exact G3 release/preparation 和 outer candidate hash 签既有 release/epoch-bound token。Preparation 只预览 quote/page，不签假 release token。
5. Repository、Draft/Ready/Release/member/Head 表与事务全部复用；不新增 migration/table/service。Generic `/activations`、`/current`、`/releases/:release_id/{pages,payloads,search}` 和 CAS API 原样复用。

只有 `WikiReleaseService` 能经既有 repository 写 Draft/Ready/Release/receipt，并在 activation transaction 内 CAS 唯一 Head。Harness 只生成/验证 canonical bundle bytes；handler 只 strict decode 和调用 service；source authority 只读重开；前端只维护界面状态并调用既有写 API。CREATE entity ID 不形成 repository 之外的第二 serving authority。

### 5.3 Preparation 刷新重开

新增 human-only：

```text
GET .../schema/preparations/:preparation_id/batch-concept
```

Exact response：

```text
contract = batch-concept-preparation-read.830.g3.v1
read_mode = preparation
tenant_id = positive integer
space_id = Text
raw_kb_id = Text
wiki_kb_id = Text
preparation_id = Text
status = DRAFT | READY
candidate_sha256 = Hash
expected_base_release_id = Text
expected_base_activation_epoch = positive integer
page_manifest = exact BatchConceptPageManifest830G3V1
read_sha256 = Hash
```

所有键必传且无 nullable key；首切片继承非空 base Head，不定义空空间 bootstrap。`read_sha256 = schema_wiki_sha256(contract,payload_without_read_sha256)`。Scope 来自已授权 preparation；status 映射实际 DRAFT/READY。Service 按 ID 从 `GetDraftPreparation` 或 `GetReadyPreparation` 读取并重新执行完整 G3 preparation validation；不得读新 Head 替换 expected base，不得切换 candidate。响应不重复 entities 或完整 Catalog；前端从 manifest 的 overview 投影目录，所有 field refs 必须在同一 manifest 唯一命中 owner field assertion。

Preparation 字段页从 frozen members 读取并显示 exact quote/page，无需第二个逐成员 route；激活前不生成 release-bound token。

## 6. Active PinnedRead 与前端

Active 后先 generic `/current` pin 唯一 Head，再以 exact release ID 读取 `/releases/:release_id/search?q=`。字段页 transport 继续使用 scoped schema `/concept-pages/:member_id?release_id=:release_id`；服务只从该 pinned release 组装页面与引用。Generic `/pages/:logical_slug` 和 `/payloads/:logical_slug` 仍是底层 PinnedRead。G3 前端不读 Harness Candidate、不读 RAW chunk、不接受任意 release 替换。

建议新增 `frontend/src/api/schema-wiki/batchConcept830G3.ts`：strict parse active snapshots 和 preparation response；用 G3 overview payload 分派；验证 snapshot revision、member digest、owner/ref、pack/Profile、sections、Profile coverage 和两条 alignment lineage；preparation 只接受 preparation ID，active 只接受 release ID，两种 query 互斥；Active Evidence 点击复用既有 citation authority，candidate identity 使用 outer hash。

`SchemaWikiCatalogEntry830G2.vue` 在 exact preparation query 下读取 human preparation并显示“待审核/已审核但未发布”，否则 Catalog 与 active directory 并行；旧 G1/G2 mode 不变。

`ConceptDirectory830G2.vue` 的 G3 mode 显示正式产品名、primary classification、pack/Profile identity 和质量状态；按分类分组实体，实体内只按 Profile sections 顺序显示字段。旧 G2 输入仍显示原 entity ID 卡片；human preparation 另列两条 unknown key alignment 供整包审核。

`ConceptFreeWiki830G2.vue` 和 API parser 的 G3 mode 显示 short title、value/unknown、conditions、exceptions、valid_time 和同版 Evidence。Active 可点击来源；preparation 只显示 frozen quote/page 与“激活后可打开原件”。路由名可保留 `conceptPage830G2`；query parser 增加互斥 preparation mode。

## 7. Fixture、容量和最小纵向切片

### 7.1 代表 fixture 与 actual shape

标准跨语言 fixture 固定使用 Catalog 的四类：

1. medical：`schemapack_medical_insurance`，67 fields，7 sections；
2. critical illness：`schemapack_critical_illness_insurance`，67 fields，8 sections；
3. endowment：`schemapack_endowment_insurance`，79 fields，8 sections，对应 corpus material11；
4. accident：`schemapack_accident_insurance`，62 fields，7 sections，对应 corpus material13。

四个 pack 的字段数算术/投影统计为 `67+67+79+62=275`。它只用于验证 Catalog/Profile 投影和“删除任一 actual base MATCH 必须拒绝”的负例；不得构造为缺少一个现有医疗实体的合法当前-base Candidate，也不是容量或正向跨语言 fixture。

唯一正向跨语言和 capacity fixture 使用 actual frozen base：两个既有医疗 MATCH 和三个新 CREATE（重疾、两全、意外），字段数为 `67+67+67+79+62=342`。它必须包含完整旧 134-row `base_request.existing_fields`、两行 exact unknown key alignment、对齐后的 132-row exact carry、两个仅 key/identity 变化的 unknown 占位、原 definitions/free pages、导航、base-only sources、C 输入闭包、model delta raw、final logical raw、review raw 与 page manifest。

每个 fixture 必须满足其声明 base 的完整 MATCH 覆盖。真实 preflight 若判材料没有冻结 C 自动资格，协议 fixture仍可验证 serializer，但现场 Candidate 必须保持 `NOT RUN/NEEDS_CONFIRM`，不得伪造锚点、registration 或模型结果。

### 7.2 8 MiB 容量先行

Handler 现有 8 MiB 上限保持。Handler/service/UI 实现前，必须先用真实 serializers 生成完整 actual 342 canonical POST 容量向量；保存总 bytes、各组成部分 bytes 和所有输入 SHA。向量包含 Catalog、C resolution inputs/output、model_compile_result、final compile_result、review_result、完整旧 base request及成员/source closure、两行 alignment 和 manifest。未上传 source receipt 只能作为明确 fixture，不能冒充真实来源/模型/业务结果。275 子集和历史撤销的 344 口径均不得用于容量验收。

任一完整向量超过 8 MiB 时，D 状态保持 `BLOCKED`，先提出有界协议去重或明确 capacity 修订；不得删字段、C 输入、raw、来源、旧成员或 base 来压容量。未经测量不得推断可通过。先冻结 Harness strict DTO/projection、跨语言 fixture 和 Go types，使用其真实 serializer 测量；容量闭合后才派 handler/service/UI 接线。

### 7.3 最小可跑纵向路径

1. Python builder 重跑 C、验证完整 base MATCH 与医疗 compatibility mapping，构建 exact G3 request；受控一次新增编译生成 model delta，机械组合器生成 final output；独立 reviewer 审 final output；G3 projector 生成一个 human outer Candidate。
2. 既有执行者 POST `.../schema/preparations`，body 为 `preparation_id + batch_concept_candidate_bundle`；服务重验 Catalog/C/base Head/source custody并写现有 Draft repository。
3. UI 打开 `/platform/knowledge-bases/:kbId?tab=schema&preparation_id=:preparationId`；刷新调用 preparation GET，从 Draft/Ready 重开同一 frozen Candidate、完整目录与字段。
4. 具名整包 review 调用现有 review endpoint进入 Ready；source authority 在审核时重开 field/free-page/identity/classification Evidence。Ready 不出现在 `/current` 或 `/search`。
5. 现有发布界面提交同一具名 decision 与 PublishAuthorization 到 `/activations`；既有 `ActivateReviewed`、nonce、expected Head 与 CAS 原子切换唯一 Head。Activate 前再次重开全部来源。
6. 激活后 UI 先读 `/current`，再以返回的 exact release ID 读 search；overview 驱动按分类、产品名和 Profile sections 展示 actual 五实体，每个医疗恰好 67 个字段页。
7. Active 字段页读取 scoped concept page/citation preview；preparation 字段页读取 frozen member且不生成 Active citation token。

验收必须证明浏览器刷新后仍能重开 DRAFT/READY，Review 前后 Head 不变；Activate CAS 后完整实体、342 个 Profile 字段、conditions/exceptions/valid_time/Evidence 可从同一 pinned release 读取与检索，且两条 alignment lineage 可审核、历史旧页仍可按旧 release ID 读取。至少一个 CREATE 走完整链，且不存在第二次主数据注册前置。真实材料未达 C 自动资格时，该业务 DoD 保持 `NOT RUN/NEEDS_CONFIRM`。

## 8. 真实代码边界

原设计识别至少以下生产路径；合并稿不缩减其职责，也不预先锁死五文件：

1. `harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py`；
2. `internal/types/concept_free_wiki_830_g3.go`；
3. `internal/application/service/concept_free_wiki_830_g3.go`；
4. `internal/application/service/concept_free_wiki_830_g2.go`，只抽取/分派共享 base-chain 与 active citation read，旧分支不改语义；
5. `internal/application/service/concept_source_authority_830_g2.go`；
6. `internal/application/service/wiki_release.go`；
7. `internal/handler/schema_wiki.go`；
8. `internal/router/routes_schema_wiki.go`；
9. `frontend/src/api/schema-wiki/batchConcept830G3.ts`；
10. `frontend/src/views/knowledge/schema-wiki/SchemaWikiCatalogEntry830G2.vue`、`ConceptDirectory830G2.vue`、`ConceptFreeWiki830G2.vue`。

测试边界：Harness DTO/composition/projection test与canonical fixture；Go strict/cross-language parser；G3 service；现 source authority/wiki release分派反例；handler/router ACL/reopen；新 API spec和三个 Vue G3 mode specs。无需 repository migration、agent tool 或新后台 service。

## 9. 强制 RED / GREEN 向量

### 9.1 Python 与跨语言合同

1. G2 exact validator拒绝 G3 extra/subclass；G3 validator接受四 pack exact vector。
2. Catalog重复、wire/content hash互换、confirmation缺 Profile/改 hash、actor omitted/null 漂移拒绝；合法具名非 null通过。
3. C inputs任一 hash/scope/policy/model/source binding漂移、调用方只改 resolution self-hash、Go不重验C均拒绝。
4. CREATE entity/version公式漂移、Candidate NOT_ACTIVE/sha/key漂移、MATCH改 serving ID拒绝。
5. 选择 NEEDS_CONFIRM/QUARANTINE child、parent gate失败、不同 key/version/pack混为binding拒绝；MULTI中自动合格children可分别选择。
6. 删除任一 base entity proposal/ref、base只有待审 child、CREATE或错误entity/version替代 MATCH、caller少传 Existing*，返回 `BASE_ENTITY_MATCH_REQUIRED`。
7. Base MATCH改为 critical/endowment pack、旧base contract/schema/profile漂移，分别返回 `BASE_PACK_MIGRATION_REQUIRED` 或 `BASE_PACK_AUTHORITY_UNSUPPORTED`；两个base MATCH使用exact医疗映射通过。
8. Standard required fields少/多/乱序、只set相等、short title/section伪映射拒绝；四 pack严格为67/67/79/62。
9. 保留 68 个历史额外页、让新 plural key 复用旧 singular member、遗漏任一 alignment、改 source release/epoch/candidate/entity/version/key/digest/hash、或传入非冻结第三行，分别以 `BASE_UNKNOWN_KEY_MIGRATION_REQUIRED` / `BASE_UNKNOWN_KEY_MIGRATION_INELIGIBLE` 拒绝。
10. 两个旧 singular 占位任一变 known、有 value/Evidence/condition/exception/concept/time、unknown_reason 漂移，或调用方先清空旧值再对齐，均拒绝；正向每个医疗恰为 67 页。
11. 删除第二医疗、任一旧free page/definition/base-only source，或把旧known变unknown、改旧value/Evidence，均拒绝；正向保持完整旧 134-row input、132-row exact carry 和两条仅 key/identity 变化的 unknown alignment。
12. Model delta夹带旧field/definition/page、singular key、已 aligned plural field，缺新增required field、raw/context伪造、delta identity collision或audit错配拒绝。
13. Final组合删改旧object、缺/重复carry audit、改变delta transformation、以final raw替model raw、使用G2 context域、三类run ID重复均拒绝；真实model raw与canonical logical raw分开且组合一致通过。
14. 同block不同name/code span通过；共同issuer/classification/通用条款按owner/ref共享通过；同一实际span换ID/purpose/proposal_ref伪装独立、跨material/scope/revision/attempt/manifest/offset失败。
15. 每字段恰好一个attempted assertion；known无Evidence、unknown有Evidence、entity version或owner source漂移失败。
16. conditions/exceptions/valid_time经final output、manifest、Go snapshot逐字roundtrip；改任一值使hash失败。
17. 同pack重分类只改变classification/navigation/candidate hash；entity identity与原FieldAssertion/Evidence不变。
18. Python/Go重算 request、三类context、model execution、manifest、candidate与member hash相同；Go unknown/duplicate/non-NFC/float/omitted-null均拒绝。
19. 旧G2 fixture raw SHA、candidate hash与snapshot不变：v1 `d36546179939a4fdc8e1a53e4dacbe9ce1aaf2313f07f280c42dd8ff44b291aa`；v2 human `c864fcd359f76c3ba708acd28009fb4e567a45e37ec4816c69eabfc46a40a700`；canonical vector `02787ba2c17af49078349d37ac024f5e9e1bb06ab0b23c0640278adcba86d795`。

### 9.2 Go service、authority 与 UI

20. Create Draft使用outer CandidateDigest和expected Head；CREATE不查实体主数据表且不改Active。
21. Review前来源撤销/manifest/quote漂移失败且Draft保留；恢复后同一Draft可Review。
22. Review后、Activate前来源漂移使Activate失败且Head/CAS/receipt零写；恢复后exact authorization只激活一次，nonce retry幂等。
23. Stale release/epoch导致CAS失败，不覆盖并发Head。
24. Preparation GET在进程/页面刷新后按exact ID重开DRAFT/READY；ACL、dual-KB seal、scope、manifest/member漂移反例拒绝，且不读取serving Head替代base。
25. Active directory先pin current，actual五实体按正式名/分类分组，字段按Profile 7/8 section顺序显示，每医疗恰为67页且无额外历史节点；未发布preparation不进入current/search。
26. 产品名、分类、section、field value、condition、exception均命中同一active release member，不命中RAW或其他release。
27. Active source click重开exact SourceRevision并返回同版quote/page；release/candidate/member/citation任一identity漂移失败。
28. Catalog/Profile质量状态始终为 `REGISTERED_NOT_QUALITY_ADMITTED`；UI/service不能把结构确认写成quality PASS或production admitted。
29. 唯一正向与容量 fixture 为 actual342；275只用于四-pack投影统计和删除base负例，历史344必须拒绝作为验收口径；容量必须先于handler写入闭合。

## 10. 验收与非目标

D software GREEN 只表示协议和接线可用。真实 15/15 模型尝试、四代表 pack Candidate、具名 human Review、隔离 Activate、PinnedRead、source click和搜索问题都必须分别保存 exact execution/preparation/review/activation/source receipts；未运行保持 `NOT RUN`。

真实 `source21` 只证明材料中出现多组独立产品 name/code，尚未证明两个完整 filing/registration version anchors。Parent 可为身份级 MULTI而children因version待核保持 NEEDS_CONFIRM；D不能选择这些children。真实preflight只读核验锚点，缺失时不得补造材料、标签或registration。

本切片不支持base-only自动迁移、静默pack migration、一般字段 alias、冻结两行之外的 key alignment、G3作为未来base的通用迁移、旧事实修订、额外模型调用、新authority或第二 serving Head。实际模型/provider/DB/build/deploy均需后续明确授权。

## 11. 追溯表

| 合并稿章节 | 原设计 | 修订1 | 修订2 | 修订3 | 修订4 | 修订5 | 修订6 | 合并结果 |
|---|---|---|---|---|---|---|---|---|
| 1 边界/身份 | §1 | 保留 | 保留 | 被撤销 | 保留 | 保留 | 明确撤销3 | 原边界完整保留；状态不自动升级 |
| 2.1 confirmation | §2.1 | 保留 | — | — | — | — | 保留 | 原exact receipt/binding保留 |
| 2.2 C输入 | §2.3仅函数参数 | D1 | — | — | — | — | 保留 | `resolution_inputs`变为outer唯一必传闭包 |
| 2.3 binding/Evidence | §2.2 | D1、D3 | 完整base MATCH引用 | 新增字段被撤销 | — | base医疗pack约束 | 删除legacy DTO | occurrence去掉purpose；binding只保留Profile字段 |
| 2.4 outer request | §2.3 | D1 | base Head绑定 | 连接公式被撤销 | — | compatibility | 新增exact alignment数组 | required逐序等于Profile；旧134 existing原样内联 |
| 2.5 base前置 | 原base snapshot泛称 | D2完整保留 | 全base MATCH | 被撤销 | — | 唯一pack映射 | exact base lineage | 编译/provider/Draft前重开base、mapping及两行资格 |
| 3 output/record | §2.4单compile_result | D2提出raw分离 | — | 部分carry被替换 | 完整替换 | — | aligned view先行 | model delta + mechanical final + review三身份；132 carry、2 alignment |
| 4 manifest | §3 | D4 | — | 历史额外节点被撤销 | final audit来源 | — | 每医疗67 | exact四键manifest；只有Profile sections；对齐页使用新identity |
| 5 authority | §4 | D1/D2/D4 | base MATCH重开 | — | 三execution复算 | pack mapping重开 | review/activate重开alignment | 唯一Head/source custody/CAS全部保留 |
| 6 UI | §5 | D4 read DTO | — | 历史折叠组被撤销 | — | — | 预览alignment lineage | preparation/active互斥；当前目录只显示Profile页 |
| 7 fixture/capacity | §6.1 | 8MiB前置 | 两base全覆盖 | 344被撤销 | 三结果均计容量 | actual mapping | actual342唯一正向 | 275仅投影/负例；342正向与容量；344历史拒绝 |
| 8路径 | §6.2 | 写域顺序 | — | UI/parser增量被撤销部分 | G3 wrapper/composer | strict mapping | alignment职责加入既有路径 | 未新增表、服务或第二Head |
| 9 RED | §7 | 新闭包/base/DTO向量 | BASE_ENTITY_MATCH | legacy向量被替换 | dual raw/context向量 | pack向量 | unknown-only反例 | 合并去重且保留1/2/4/5强制反例 |
| 10验收 | §8 | 保留 | actual MATCH未运行 | 计数被撤销 | model权限不推导 | migration非目标 | full342/每医疗67 | 保持业务状态分层和Goal页数等式 |

## 12. 无法机械整合、需最终复核冻结的事项

以下不是本合并稿新增方案，只是源文件状态或文字无法由机械合并自行裁决：

1. **受控执行器另存provider HTTP request/response的持久化位置和exact DTO未在输入合同中定义。** 修订4只冻结bundle内completion raw、model/final/review execution identities，并明确HTTP envelope另存。合并稿不能自行发明仓库、表或hash合同；D实现计划若要求该envelope进入同一可移植artifact，需Root另行冻结其既有承载方式。
2. **未来G3 release作为base不在首切片兼容范围。** 修订5只冻结现G2医疗mapping，修订6只冻结actual G2 base的两行unknown-only alignment；不能机械推广为registry、一般alias或第二mapping。

除以上两项外，修订1、2、4、5、6对原设计的明确替换可以机械闭合：修订3的legacy DTO/额外页/344口径全部撤销；actual正向恢复342并要求每医疗67页；旧134-row existing input原样内联后机械形成132-row exact carry和两行unknown-only alignment；单一compile result变为model delta与final logical双结果；原purpose参与occurrence被删除；泛化base snapshot前置变为全base MATCH、唯一医疗pack mapping与exact alignment lineage。
