# D 合同评审修订 1（实现前）

状态：ROOT_DESIGN_REVIEW_PENDING。补充 `lane-d-contract-design.md` SHA415742f61d443ddeb5b00d13fcdddd8dae97ddc370bd8f61a42000f7c8924512，若冲突以下为准。原设计4项BLOCKER和容量前置保留，不授权实现或环境执行。范围仍G3-R3/R4/R5同一Candidate/Review/Release链，无新表、服务、签名体系或第二Head。

## D1：持久化C输入闭包

`BatchConceptCompileRequest830G3V1`在原exact字段中新增唯一必传字段 `resolution_inputs`，其exact DTO为：

```
contract = batch-resolution-inputs.830.g3.v1
corpus = exact BatchCorpusV1
proposals = exact ProposalBatchV1
existing_entities = exact ExistingEntitySnapshotV1
policy = exact BatchResolutionPolicyV1
inputs_sha256
```

各C输入只内联一次，不把Catalog放进该对象；各自原hash不变。`inputs_sha256=schema_wiki_sha256(contract, payload_without_inputs_sha256)`。outer resolution的corpus/proposals/existing_snapshot/policy SHA必须逐一匹配，scope与base_request/route精确相等，C existing snapshot base release/epoch与唯一Head预期一致。Python builder仍按exact inputs重算完整C输出。

Go strict decoder持久解析相同C输入和各级hash，不得只相信输出的self-hash。对所有选中child机械重验source/proposal/PolicyReceipt/model用途绑定、身份和classification两个阈值、精确pack、name/code/version/issuer依据、对应TrustRule资格、parent gate及CREATE key或MATCH existing key。这不是另一个模型推断器：不重新分类、生成Evidence或解释条款，不新增PolicyReceipt或模型服务。纯C结构/资格的跨语言拒绝向量需与最终C输出同步；source真值仍经现有REST来源authority重开，policy snapshot可审计但不冒充远端模型授权证明。

C parent处置NEEDS_CONFIRM/QUARANTINE禁止选择任何child；MULTI只可选择自动合格MATCH/CREATE。Go不能把单个调用者声明的policy_sha256当作已被服务授权的自动发布策略：G3无条件human_batch，结构确认和classifier结论均不赋予Active能力。现有具名整包Review/PublishAuthorization/CAS不变。

## D2：完整base保留

现有G2 validate_output不足以保证旧definition/free page不消失，D必须增加明确保留规则。

D本首实现切片只新增产品字段、目录/Profile标签，不对base知识进行事实修订：

- base_request.existing_fields/definitions/pages/entity_versions必须从当前exact base Head全部成员重开，由Go与库内base核对，不能由caller少传。
- 生成的CompileOutput必须逐实体/field_key保留全部existing FieldAssertion原payload与Evidence，逐concept_id/definition_hash保留全部existing ConceptDefinition，逐free_page_id保留全部existing FreeWikiPage原payload/Evidence。不得unknown覆盖旧known，也不得让LLM遗漏旧page。
- 旧对象由既有执行适配器在完成输出前机械carry，作为最终compiler output和execution record的一部分；实际模型原始响应仍另存，不伪称机械carry文本是上游逐字输出。最终执行context含完整G3输入；G2 DTO和raw-output一致性规则仍按最终逻辑compiler output验证，不改G2历史回执。
- 新产品可以引用现有definition；不得替换旧definition或删掉旧free page。本切片若要改旧事实，返回单独变更设计，不能借“新增产品”悄悄更新。
- base_request.sources是新选中材料所需SourceBlock与全部carryover Evidence所需SourceBlock的canonical并集（revision_id/block_id去重，重复identity不同bytes拒绝），由actual base/member Evidence闭包推导，不限于新C材料。每实体owner source allowlist同时含该实体的selected sources及base carryover sources。共享definition来源按已有引用关系保留。
- 必须保留当前第二医疗实体和原free page；当前base2医疗+新增重疾/两全/意外为5实体342字段，另加旧共享定义、页面和导航成员。275仅四实体最小fixture，不是线上真实计数或硬上限。

追加RED：删第二医疗实体、删旧free page/definition、删base-only source、旧known变unknown、改旧Evidence或value、caller少传Existing*均拒绝；合法新增三类并逐字carry base通过。

## D3：统一Evidence occurrence

原设计包含purpose的occurrence公式废弃。与C设计2一致，区分性name/code/version occurrence使用完整SourceIdentity+block/page/start/end/quote_hash，忽略evidence_id/purpose/proposal_ref。不同ID或purpose不能将同一实际span伪装为独立产品依据。共同issuer/classification/通用条款在明确owner/ref关联且来源有效时允许共享；不同产品在同一block的各自精确span允许。exact-input和服务端来源复验负责该事实，单参wire不声称从ID证明locator独立。

## D4：exact DTO、顺序、hash

`BatchConceptPageManifest830G3V1`精确四键：

```
contract = batch-concept-page-manifest.830.g3.v1
members = [exact G2 PageMember shape]
members_sha256
audit = [exact G2 AuditDisposition shape]
```

成员按 `(kind,member_id)`排序，member_id全局唯一；G2 PageMember exact keys为kind/member_id/owner_id/title/content/payload。payload按kind使用原G2对象或G3 entity-directory-entry。`members_sha256=schema_wiki_sha256("batch-concept-page-members.830.g3.v1", {"members": members})`。audit逐字逐序等于CompileOutput.audit，不另外生成或省略。manifest不另加request/output hash或自hash；bundle同时绑定request/output/manifest，validator必须重新project并逐字等于manifest。snapshot MemberDigest按原设计`schema_wiki_sha256("batch-concept-member.830.g3.v1", PageMember)`，RevisionID为outer candidate_hash。

profile-set hash payload精确为排序数组，每项exact keys：`entity_id,profile_id,profile_version,profile_sha256`；按entity_id排序、拒重复，domain=`batch-profile-bindings.830.g3.v1`。Go通过sections/fields顺序展开ordered field keys；ordered_field_keys是Python派生property，不存在于Catalog wire，不能期待wire带该键。

preparation GET响应DTO精确如下，不重复另存entities或完整Catalog：

```
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

所有键必传，无nullable键；G3本范围继承已有非空base Head，不定义空空间bootstrap。`read_sha256=schema_wiki_sha256(contract,payload_without_read_sha256)`。scope来自已授权preparation；status是实际存储draft/ready映射。重开不能读取新Head替换expected base，不能切換candidate。前端从page_manifest里的entity_overview投影产品目录，section顺序不重排；全部field refs必须在同一manifest内唯一命中对应owner的field_assertion。

## 容量与写域前置

handler现有8 MiB上限保持。派handler实现前，用当前实际Catalog、已有base完整G2 bundle及最终C fixture生成完整275/342字段的canonical POST容量向量，包含新增C输入闭包、raw compile/review和page_manifest；保存实测字节、各组成项字节与输入SHA。容量向量可用明确标注fixture的未上传source receipt，不当实际来源/模型/业务结果。

若任一完整向量超过8 MiB，本设计维持BLOCKED，先提出有界协议去重或明确capacity修订，不通过删字段、删C输入、删来源或遗漏base规避。未经测量不得推断通过。本容量检查只为冻结交付形状，产品字段数/数量保持数据驱动。

设计复核后，可先冻结Harness严格DTO/投影及跨语言fixture/Go类型的合同写域，用这些真实serializer生成容量向量；容量闭合后才派handler/service/UI接线。同一D切片内按依赖串行，不另建Goal或平台前置。最终仍为C/Harness+跨语言类型与B/backend/UI两个互斥实现域，最多两个产品写lane。评审只读。D实现前不得向现有G2类型塞extra字段或改旧fixture。
