# G3 批量身份与分类切片（待独立合同审查，未派写）

适用 G3-R4/R5。业务 RED 已实际复现于 `existing-classifier-red.json`：1826 两全主合同因正文提及附加重疾而被旧关键词分类器判为重疾。此探针不冒充 WeKnora 解析或真实批次。

本切片消费实际解析快照和模型提出的分类、材料角色、身份及依据；只生成可审计的实体/分类 Candidate 决定。后续由既有 Candidate/Review/隔离 Release 链承接，不另建存储、服务或 Active。不能把此纯领域模块的单测当成全卡真实 FLOW。

## 拟定唯一写域与公共 API

- 新增 `harness/src/insurance_harness/knowledge_compiler/batch_entity_resolution_830_g3.py`。
- 新增 `harness/tests/test_batch_entity_resolution_830_g3.py`。
- 既有 Catalog、G1/G2、旧 resolver 和模型调用边界均只读。
- `resolve_batch(*, catalog, corpus, proposals, existing_entities, policy) -> BatchEntityResolutionV1`，无网络、DB 或模型调用。
- `validate_batch(payload) -> BatchEntityResolutionV1` 仅检验自洽完整性；外部消费必须同时固定实际 corpus/policy/model receipt/catalog hashes，不能用自洽 hash 冒充来源真实性。
- 所有公开拒绝使用 `BatchEntityResolutionError.reason_code`。冻结严格模型、禁止额外字段、拒绝 bool 伪装数字、NaN、空身份、重复身份/材料/依据、跨作用域或引用漂移。

## 输入与身份约束

1. Catalog 为 A 已冻结完整 catalog；本模块不重建 pack 或字段定义。
2. Corpus 按确定顺序列出材料，每份绑定 Space、RAW KB、knowledge ID、原件 SHA、实际 SourceRevision、parse attempt、manifest SHA、解析 chunk（ID、页、原文及内容 hash）。真实快照必须由既有 WeKnora Source lifecycle 接口捕获；本模块不制造 revision、手写 parse manifest 或直接访问 WeKnora DB。缺少实际快照的材料不能作为成功尝试。
3. 每份 Proposal 必须引用 exact corpus entry/hash 和实际 model receipt identity，提出 material role、一个或多个实体、每实体独立 identity confidence、每标签独立 classification confidence、分类标签及主分类、逐身份字段/分类/角色的 Evidence span。置信度为独立的有限 [0,1] 数值，不由文件名或模型自报角色提升来源权威。
4. Evidence 引用必须落在该材料的 admitted chunk/page 中，quote 为原文精确子串，quote hash、source revision/attempt/manifest 均一致。不能让模型只提交一个任意 hash 声称有依据。标题中的主合同和正文关联实体分别保留 Evidence；仅有泛称的附加合同不能借用主合同的代码/备案号。
5. ExistingEntity 只接收同 scope 已有稳定 entity ID、issuer、product code、正式名称及已知 version/filing anchors 的冻结快照。旧 exact resolver 的既有主数据仅作输入，不在此模块建立另一份在线注册表。
6. 新实体稳定 key 只包含 space_id + product code；版本 key 另包含正式 filing/registration anchor。分类、主导航、短标题、上传顺序、模型置信和 Profile 均不进入实体 key。issuer 只作为有依据的属性和冲突 veto，不进入 key。沿既有 `(space_id, product_code)` 唯一键；版本带 version_label 和 filing/registration(kind,value)。已知实体严格保留原 serving entity_id/entity_version；有已批准产品 UUID 映射时一并保留，不制造主数据 UUID 或要求回填为前置。

## 决定和优先级

- 首先按每实体 proposal_ref 及其独立身份依据分簇；不同子实体的代码/名称不相互构成冲突。
- `QUARANTINE`：整份来源完整性失败时为父处置；单子实体依据完整性不成立或其自身关键 anchors 相互矛盾时为子处置。拒绝原因和实际依据必须可核对；不为了凑五种结果而给正常材料加人为冲突。
- `MULTI`：模型识别至少两个独立实体且各自有对应依据；父决定优先保留 MULTI（来源完整性失败除外），子处置限定 MATCH/CREATE/NEEDS_CONFIRM/QUARANTINE，保留逐子决定，整个混合材料进入具名人工队列，不自动 Active。未识别完整身份的子实体为 `NEEDS_CONFIRM`，不借主实体身份补齐。
- `NEEDS_CONFIRM`：缺关键身份依据、身份或分类低于各自阈值、同名多版本/别名歧义、材料角色或有效作用域尚未确定。明确记录原因。
- `MATCH`：唯一已有 exact identity 和版本匹配、所有关键依据成立、双阈值满足且无冲突。重复运行返回同一个实体及 Candidate identity。
- `CREATE`：无已有匹配，issuer/code/正式名称/版本 anchor 均有实际依据，exact key 唯一、双阈值满足、无同名/版本/别名冲突时自动形成幂等 EntityCandidate。只到 Candidate，不能直接 Active。
- 批次内同 exact key/version 复用首次候选；同 key 不同版本进入人工决定，不因材料顺序覆盖。重排输入不改变各材料和实体的语义决定 hash。
- 一份输入恰好一个父决定；不吞掉失败材料、不改变分母。无 proposal 的材料明确记录 `NEEDS_CONFIRM / MODEL_OUTPUT_MISSING`，不能声称模型成功。

## 分类与材料采信

ClassificationAssignment 包含独立版本、标签集合、一个主导航、pack identity/hash、Evidence 和 model receipt。主分类必须映射到对应 Catalog entry；不同分类无法偷偷替换同一实体版本的 SchemaPack。重分类单独输出 assignment，不改 entity/Evidence/字段历史。

版本化 Policy 明确两项独立阈值（草案 identity=0.95、classification=0.90，尚未冻结批次）、具名人工队列 Owner 及少量 material role 规则。规则匹配可信来源声明、允许字段、scope、产品版本和有效时间；来源可信声明由摄取上下文给出，不能由模型自行声明。字段级采信只允许配置匹配的依据；未知有效期/作用域时降为待确认，不能推断当前有效。上传时间不参与覆盖优先级。同一条件下冲突保留并进入人工队列。

真实 corpus/Seed 标签/model budget 尚未冻结，不能开始真实批次。本次用户新增 1828 条款和说明书已持久化；同目录费率表版本未明，禁止自动挂接 1828。五处置是否存在真实样本仍须在 SourceRevision 捕获后核验，不能先补造标签。官方历史服务手册的7组独立产品名称/代码已获只读审查认可，可作为父MULTI、各子版本NEEDS_CONFIRM的输入候选；已纳入corpus-files-v3.json，但尚非真实执行结果。

## RED/GREEN 与验收边界

最小 RED 覆盖主/附合同混淆、仅名称不能匹配、版本冲突、跨来源伪 Evidence、双阈值相互独立、高置信合法 CREATE、低置信人工、MULTI 子实体不共享身份、批次幂等/重排稳定、分类变更稳定身份、采信不受最后上传影响。测试使用明确 fixture；真实 15 材料全尝试另有独立证据，禁止混记。

在完成独立合同审查和 exact DTO 字段冻结前不派写。若需要额外服务、表、第二权威或超过本模块边界的前置，报告 root 裁决，不能把旧硬编码产品模板整体泛化作为隐性前置。

## 复审版 DTO（本节限定上述 prose，不授权额外模块）

全部新模型严格、extra forbid、冻结。类型 `Text`=非空 NFC 字符串；`Hash`=64位小写hex；`Confidence`=固定六位十进制字符串，正则 `^(0\.[0-9]{6}|1\.000000)$`，用 Decimal 比较，禁止 float/bool/NaN；身份比较复用既有 exact 规范化：NFC 后移除全部 Unicode whitespace；不做casefold或模糊归一，原文quote/offset不变，输出同时保留observed和normalized。数组下述声明为 set 的按稳定键排序并拒绝重复。新 hash 统一 `schema_wiki_sha256(contract, payload_without_own_hash)`，复用既有对象的原生 hash 算法，不重哈希成另一种来源合同。

| 对象 | 必填字段和精确复用 |
|---|---|
| BatchCorpusV1 | contract=`batch-corpus.830.g3.v1`; tenant_id正整数, space_id, raw_kb_id, wiki_kb_id; entries; corpus_sha256 |
| CorpusEntryV1 | material_id; receipt=`LiveRevisionSourceReceiptV1` 原类全量复用; native_capture_sha256; parser_identity_sha256; blocks=`SourceBlock` 原类数组; provenance; entry_sha256 |
| SourceProvenanceV1 | provenance_id; kind=`official_public_document\|user_supplied_document\|internal_document\|unknown`; source_uri; acquisition_receipt_sha256; declared_by; declaration_sha256。声明由冻结摄取上下文提供，Proposal不得含此对象或trusted布尔。 |
| ProposalBatchV1 | contract=`batch-identity-proposals.830.g3.v1`; corpus_sha256; model_receipts（ModelReceiptBindingV1数组，按request_sha256）；proposals（按material_id）；proposals_sha256 |
| ModelReceiptBindingV1 | policy_receipt=`model_policy.models.PolicyReceipt` 原类；material_bindings（非空sorted数组，每项material_id/corpus_entry_sha256）；request_sha256（实际请求原字节审计hash）; input_sha256（下述G3材料绑定hash）; raw_output_sha256; execution_receipt_sha256。ALLOW、scope匹配且permit_digest存在才可用于有效Proposal；此审计对象本身从不授予网络调用权限。 |
| MaterialProposalV1 | material_id; corpus_entry_sha256; model_request_sha256; material_role; material_role_evidence_ids; entities（按proposal_ref）；evidence（按evidence_id）；proposal_sha256 |
| EntityProposalV1 | proposal_ref; issuer/name/product_code/version_label/filing_or_registration（缺失可null，不补值）; identity_confidence; identity_evidence_ids; labels; primary_label; valid_from/valid_through（可null） |
| VersionAnchorV1 | kind=`filing_number\|registration_number`; value |
| LabelProposalV1 | taxonomy_label; confidence; evidence_ids。labels按taxonomy_label、primary_label必须恰好命中一个标签；仅主标签选择pack。 |
| ProposalEvidenceV1 | evidence_id; entity_proposal_ref（材料角色为null，其余必填）; purpose=`issuer\|product_code\|name\|version\|classification\|material_role\|field`; field_key（仅field用途非null）；evidence=`concept_free_wiki_830_g2.Evidence` 原类全量复用。 |
| ExistingEntitySnapshotV1 | contract=`existing-entities.830.g3.v1`; tenant_id/space_id/raw_kb_id/wiki_kb_id; base_release_id; base_activation_epoch正整数; head_receipt_sha256; resolver_version/resolver_policy_sha256; entities; snapshot_sha256 |
| ExistingEntityV1 | entity_id; entity_version; product_id/product_version_id（可null，只保留真实映射）；issuer/name/product_code; version_label; filing_or_registration; approved_aliases（值、approval_receipt_sha256，按值排序）；identity_evidence_sha256s。key碰撞不能创建第二entity。 |
| BatchResolutionPolicyV1 | contract=`batch-resolution-policy.830.g3.v1`; policy_id/version; taxonomy_id/version; identity_threshold; classification_threshold; queue_id/queue_owner; auto_candidate_requires（固定集合 issuer/code/name/version/evidence/unique_key/dual_threshold/no_conflict）；rules; policy_sha256 |
| TrustRuleV1 | rule_id; provenance_kinds; material_roles; purposes; field_keys（空表示不允许field用途）；space_ids; product_version_anchors（允许空，仅identity/classification用途）；validity_mode=`identity_only\|interval`; valid_from/valid_through；priority严格整数。禁止通配符/上传时间优先；交叠同优先冲突返回待确认。 |
| BatchEntityResolutionV1 | contract=`batch-entity-resolution.830.g3.v1`; compiler_version; catalog_sha256/corpus_sha256/proposals_sha256/existing_snapshot_sha256/policy_sha256; model_execution_receipt_sha256s; decisions; material_count/resolution_decision_count/model_attempted_count; disposition_counts（五键完整，允许0）；batch_sha256 |
| MaterialDecisionV1 | material_id; disposition; reason_codes（sorted set）；children；queue_id/queue_owner（人工时必填）；evidence_ids；decision_sha256 |
| EntityDecisionV1 | proposal_ref; disposition（不能MULTI）；matched_entity_id/matched_entity_version（仅MATCH原ID，其他为null）；entity_candidate（仅CREATE为下述EntityCandidateV1，其他null）；anchors（各字段observed_value/normalized_value）；identity_confidence/identity_threshold；classification；evidence_ids；reason_codes；queue_id/queue_owner；decision_sha256 |
| ClassificationAssignmentV1 | taxonomy_id/version; labels（每项label/confidence/evidence_ids）；primary_label; schema_pack_id/schema_version/schema_pack_sha256（无法确定时null）；classification_threshold；assignment_sha256。不修改任何既有字段/Claim。 |

复用 `SourceBlock`/`Evidence`/`verify_evidence` 的完整 Unicode 定位检查：`SourceBlock.revision_id=receipt.revision_source_id`，`parse_attempt=receipt.weknora_parse_attempt`，`source_hash=receipt.file_sha256`，`parse_hash=receipt.weknora_manifest_digest`（**不是** parsed_document_sha256），parser_identity匹配native捕获；tenant/space/raw/knowledge一致，页不超过receipt.page_count。原生捕获hash、parsed_documenthash、manifesthash、chunk manifest digest保持各自域。Corpus传入的是既有平台捕获快照；C不声称替代Review/Activate时重新打开服务端来源。

跨材料/子实体 Evidence join 限制：证据所属material只由corpus material_id决定；identity用途必须带对应proposal_ref。issuer/code/name/version实际值必须出现在其purpose对应quote中。多个标签可引用同一原文，但不能让另一子产品的主体代码充当本子身份依据。MULTI必须至少两个有独立 name+code 依据的簇；无版本可逐子NEEDS_CONFIRM，不假设已有版本。

幂等规则：新Candidate key为canonical hash(`space_id,product_code`)，版本候选key另含`version_label,VersionAnchor`；issuer冲突阻止复用。若同batch同key/version有多份材料，一次预先分组后统一算候选，不采用“先到者赢”。若同key多个版本，全部相关材料一致进入版本待确认，不让输入顺序决定哪份CREATE。既有MATCH保留真实ID；不依据分类创建新实体。语义Candidate/assignment身份不包含run_id/时间；batch审计hash可以绑定不同执行receipt，因此不同模型执行记录不伪装同一运行。

错误边界：合同/全包hash/重复材料或Proposal/分母错误抛 `BatchEntityResolutionError`；结构合法的单材料来源或Evidence join失败、跨scope、关键身份冲突输出QUARANTINE并计入attempted；完全没有Proposal仍输出NEEDS_CONFIRM/MODEL_OUTPUT_MISSING；如有效实际execution binding覆盖该材料，model_attempted增1，否则不增。不把无效整个Corpus当成部分成功。任何同名多版本/别名竞争先人工；独立阈值不足不升级。

最小原因码冻结：`INPUT_CONTRACT_INVALID`, `INPUT_HASH_MISMATCH`, `DUPLICATE_MATERIAL`, `DUPLICATE_PROPOSAL`, `SCOPE_MISMATCH`, `SOURCE_RECEIPT_MISMATCH`, `EVIDENCE_JOIN_FAILED`, `IDENTITY_ANCHOR_CONFLICT`, `MODEL_OUTPUT_MISSING`, `MODEL_RECEIPT_INVALID`, `IDENTITY_EVIDENCE_MISSING`, `VERSION_UNRESOLVED`, `AMBIGUOUS_IDENTITY`, `IDENTITY_BELOW_THRESHOLD`, `CLASSIFICATION_BELOW_THRESHOLD`, `CLASSIFICATION_UNRESOLVED`, `TRUST_POLICY_UNRESOLVED`, `MULTI_ENTITY_REVIEW`, `EXACT_EXISTING_MATCH`, `NEW_ENTITY_CANDIDATE`, `COMPILED_BATCH_INVALID`。源码内部可组合已列原因，不把任意异常文本暴露为协议。

真实Policy/queue_owner/SourceRevisions/Seed尚待具名与执行输入；此DTO不虚构用户确认。单测可用明确fixture和fixture PolicyReceipt，真实执行必须消费已授权调用的实际receipt。C完成只代表领域协议可用，不能推导15/15 FLOW通过。


### 最终集中澄清（只闭合三项复审问题）

1. `EntityCandidateV1` 全字段：`contract=entity-candidate.830.g3.v1, candidate_id, entity_key_sha256, version_candidate_key_sha256, issuer, name, product_code, version_label, version_anchor, evidence_ids, status=NOT_ACTIVE, candidate_sha256`。身份字段同时保留observed/normalized值；CREATE时matched IDs必须null，MATCH必须原样返回已有IDs且entity_candidate=null。C不分配Serving ID、写数据库或激活任何实体。
2. entity key固定 `schema_wiki_sha256("entity-candidate-key.830.g3.v1", {"space_id":space_id,"product_code":normalized_code})`；version key固定 `schema_wiki_sha256("entity-version-candidate-key.830.g3.v1", {"entity_key_sha256":entity_key,"version_label":normalized_version_label,"version_anchor":{"kind":kind,"value":normalized_anchor}})`；`candidate_id="entity_candidate_"+version_key`。candidate_sha256覆盖EntityCandidate全部字段减自身；证据更新可以改变内容hash但不改变这两个key和candidate_id。
3. `input_sha256=schema_wiki_sha256("batch-classifier-input.830.g3.v1", {"corpus_sha256":corpus_sha256,"material_bindings":sorted_material_bindings})`。它绑定送模材料集，不能冒充原始HTTP请求hash；request_sha256/raw_output_sha256/execution_receipt_sha256分别记录实际执行原件，由外层受控执行器保存和冻结，本纯模块不授予或伪造执行权。每个binding的材料必须存在且entry hash相符。每个Proposal选择的model_request_sha256必须唯一命中包含该material_id的有效binding。
4. `material_count=len(corpus.entries)`；`resolution_decision_count=len(decisions)`且必须相等；`model_attempted_count`为有效实际binding覆盖的distinct material数。无Proposal但有效执行覆盖该材料，计model_attempted=1，仍MODEL_OUTPUT_MISSING。整个实际15/15调用验收只看独立实际执行账本与这个数，不能用decision_count冒充。结构合法但DENY/scope/request/input绑定不符的Proposal对应材料为QUARANTINE/MODEL_RECEIPT_INVALID；引用根本不存在的model_request同样处理。有效binding但缺输出不伪造成功。
5. 规范化方程严格沿 `version_resolver.py`：`"".join(unicodedata.normalize("NFC", value).split())`。身份值包含验证在normalized_quote中比较normalized_value，原Evidence仍以未修改原文精确校验Unicode offsets/hash。禁止借此casefold、括号版本猜测或文件名补身份。
6. 集合canonical顺序：entries/material bindings/proposals/decisions按material_id；blocks按(revision_id,block_id)；evidence按evidence_id；entities/children按proposal_ref；model receipts按request_sha256；labels按taxonomy_label；approved_aliases按值；reason/evidence/hash引用集合按值。源正文和Profile字段展示顺序不排序。
