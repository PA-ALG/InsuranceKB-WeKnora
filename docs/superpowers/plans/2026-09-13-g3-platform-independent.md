## 2026-09-15 Task3ba：检查点消费同一有效字段视图

Task3ay已部署APP，但网页恢复15d287e4-d317-587e-87d7-22081517c590在checkpoint终态needs_confirmation/CHECKPOINT_INVALID，未进入publish。只读核对20份引用制品及生产任务身份/hash均匹配，field_validation精确绑定82原行，仅两字段证据3→4、2→3；compile_delta等于派生视图而不等于原行。checkpoint_artifacts.verify_checkpoint目前直接重投影原行，因而误拒。诊断D/task3ay-checkpoint-diagnosis.md。

沿用G3-AUTO-3/4/6，root唯一写者，g3_admission_finish独立只读复核。写域只增加checkpoint_artifacts.py及test_checkpoint_recovery.py、原规格/计划/证据。复用既有FieldValidationReport/apply_field_validation，对已通过scope/producer/generation/hash的by_kind报告验输入绑定并派生有效视图，再比较compile_delta；receipt.field_sha256仍绑定原行，不改存储、候选、报告、模型或来源。缺失/篡改不能回退原值。RED为实际fixture流程生成非空派生报告后恢复，要求同一候选重用、零新增模型，receipt原行摘要不变。增加报告输入摘要损坏拒绝测试，GREEN和冻结复核后仅部署同Harness，与Task3az UI部署复用既有服务，APP不重建。真实网页恢复独立记录；未发布不可宣称完成。

# G3 Platform Independent Processing Implementation Plan

# Task3az: bounded reader reuse within the existing G3 page

User reports field and PDF clicks unreasonably slow. The G3 publication repair Task3ay remains independently queued for deployment; do not delay or interfere with its business recovery. No new environment/database/model or permission policy.

Evidence before implementation: frontend readPinnedBatchConceptPage830G3 always serially reads scope, entire release search, member page and catalog. Parent load clears displayed state and recreates per-load transport; transport deduplicates only within a single load. Recent measured four requests ~4.47s; earlier cold release search70.61s + member80.16s. PDF viewer always fetches fresh authority, whole bytes, hashes bytes, opens a new PDF document, renders one page. Recent preview3.736s + file2.851s. These are server latency samples, excluding frontend parsing/rendering, not total measured UI latency or proof of the entire cold cost.

Scope: root writes UI and narrow tests in existing reader modules. Reuse an already validated exact-release directory in the mounted ConceptFreeWiki830G2 page; repeated field reads use readBatchConceptPage830G3, whose current backend request checks ACL/scope/source and whose parser binds response to release/epoch/candidate/exact member. Cache one directory only, clear on scope/release change or error/unmount. No global/localStorage/cache across authentication sessions. Current selected content remains cleared while a fresh member read is pending. Keep generation fencing so stale completions cannot repopulate a later page. Distinct new-release and preparation paths retain existing reads.

PDF reuse: keep one bounded validated source document per parent reader. Every citation still fetches and verifies fresh authority; reuse bytes/opened document only after current scope/release/candidate/source-file/binding/page-count match. Keys exclude short-lived tokens but include full immutable source identity. On first miss, fetch bytes by current token, check exact SHA256/pagecount and open once; later citations reuse opened document and render the actual referenced page. Bound cached file bytes (16MiB) and one document, release document/worker resources on replacement/unmount; failed fetch/hash/open must never persist a reusable entry. Do not bypass fresh authority or display a failed source. API/protocol/publication remain unchanged. Rendering failure or stale async completion must not leak resources or show old highlights.

Tests: realistic route transitions within same mounted component show first directory load then one member request per next field; version/error invalidation and stale completion reject. Viewer tests assert fresh authority on each citation, same validated PDF fetch/open once, different source/release replacement, bad hash/page count rejects, oversize bypasses cache, and close/dispose. Existing citation/reader tests remain valid. Local targeted tests + independent frozen review before building existing UI, no standalone environment. Deploy UI only once Task3ay APP deployment and active task safety allow. Re-measure real browser clicks, new source first click separately from repeated clicks. Cold backend latency remains a separate measured unresolved item until diagnosed; caching does not prove it fixed.


## 2026-09-15 Task3ay：激活复用已验证 Ready 投影

Task3ax d9d30adac 已部署；网页恢复 1cb14bbf-e098-52db-9c00-c24afb56292d
13:18:52.257Z→13:51:52.456396Z 共1980.199396秒，publish 三次300秒传输超时失败。
source/identity/field_plan/extract复用、synthesis及compilation完成、草稿201及自动审核200；
两字段跨页已保存为4/3条证据，原值/raw不变，21/31/30，0新/10复用模型。
当前Head仍epoch9。只读数据库观察未见活动锁等待；尚未证明所有超时CPU成本。

已核对既有实现：ActivateAutomated先validateSystemPreparation完整校验，再执行来源权威，
rememberValidated保存签名Ready投影，最后private activate却再次完整语义校验。
已存在validatePublishedBatchConceptPreparation830G3及read校验同一Ready的scope、
preparation摘要、完整manifest字节摘要、所有成员内容及签名；read注释已明确支持activation。
本次只把private activate的G3分支接入既有投影读取，不新增缓存/协议/环境、不加长等待、
不跳过调用者签名、当前双KB权限、来源撤销、系统策略、授权有效期与最终CAS检查。
投影缺失/损坏仍拒绝，不隐式重建；原G1/G2路径不变。生产G3调用者在进入activate前
已通过原完整校验及rememberValidated，单请求消除最后一处重复语义编译。

root唯一写者；g3_admission_finish只读独立复核。写域仅wiki_release.go、同目录窄测试、
原规格/本计划/证据。RED以既有batchPreparationValidations830G3计数器验证完整公开
自动激活入口只做一次完整Preparation校验（来源真实检查仍运行，fixture另有范围说明）；
覆盖当前权限/策略/源拒绝、冷重开/篡改投影及manifest/成员、CAS/replay原测试。
GREEN及冻结复核后只构建部署APP，保持Task3ax Harness与配置不变，从网页恢复最新失败任务。
部署前确认平台任务终态；不执行手工发布，不修改候选或原字段。未完成真实发布检索/证据与
全新产品网页验收前，G3仍未完成。

Task3ay GREEN02的4个合法激活用例失败：数据库serializer对原Manifest重新HTML/行分隔符转义，
read的原始bytes摘要与既有canonical摘要不等。复用types已有batchConceptCanonicalWire830G3，
仅暴露JSON规范化wrapper；在private激活校验副本中规范化Manifest后调用原投影reader，
不改变metadata GET原合同、不重做语义编译、不改原始存储。写域据此增加该types文件及窄测试。
已读实现及合法fixture包含原始>/&/U+2028；G3原文允许非NFC，不能误用G2的NFC限定规范化。
在格式误拒修复后重新验证nil成员RED，避免被先前manifest错误掩盖。

Task3ay 冻结01独立复核发现一项边界：published metadata GET允许Members=nil，
activation写边界必须要求完整非空Members。追加公开自动激活测试，仅通过同一SQLite
内存fixture的来源hook把第二次Ready读取成员设为null，要求拒绝且Head/receipt不变。
先验证此反例RED，再在private G3分支补len(Members)>0，不改变GET/helper兼容。
冻结01报告/private/tmp/g3-task3ay-independent-review-01.md；此项关闭后重新冻结复核。

## 2026-09-15 Task3ax：复用多证据结构，跨页定位在编译前收敛

Task3aw d32697067 已构建/烟测/部署同 APP；真实网页恢复3661a372-ae01-5e2f-8ccb-6798b0338668失败，10:53:42.486Z→11:08:41.195356Z，898.709356秒。检查点252.589713秒，0新增/10复用模型，21/31/30字段原行未变。child legacy proof已由平台生成；只读DB/C5比对未发现旧receipt不一致。真实候选+13份既有缓存的离线原函数定位检查，在115项后发现当前产品coverage_responsibilities引用跨3、4页；同一引用也用于death_benefit_rules。quote/块/源身份完全匹配，但单页locator不接受跨页。340条字段证据范围扫描只有该2字段跨页；不将本地probe当完整线上门禁PASS。

沿用G3-AUTO-2/3/4/5/6。用户已允许普通字段失败，不为补齐反复外发。复用已签名source snapshot中的page_spans/native boxes、原FieldAttempt/raw、ProductArtifact、checkpoint合同版本失效和唯一字段读取入口；不增加表、队列、来源版本、签名协议或环境。2026-09-15用户进一步指出815已支持一字段多处证据，因此跨页本身不得判字段失败。已核验815 c7-server-reopen-index中guaranteed_renewal_period有5条引用、位于1/20页；G3证据数组及Viewer的source_locator.actual_page_number均可直接复用。平台按已有原页范围把一条跨页引文确定性映射为多条单页引用，保留原source block起始页身份，由Go locator给出物理页。原文、原attempt/raw不变；每个原码点必须被单页片段或显式gap审计完整覆盖，只有真实页间空白可以放入gap，不得静默strip或删除非空白。只有无法精确分段、缺框等真实定位失败才将普通字段派生为extraction_failed并隐藏有效值。此修订取代此前尚未实现的严格单页降级选择，不扩展引用协议。

唯一Owner=root；g3_admission_finish只读独立复核。写域为harness/src/insurance_harness/product_ingestion下字段验证纯函数/对应artifact存储读取适配、pipeline.py、store.py、checkpoints.py、discovery_stage.py及窄测试/本计划/原规格/证据。必要读取适配须保持Artifact现有scope、hash、checkpoint producer/generation检查；不让UI访问材料大正文。APP/UI无预期行为修改，仅受影响Harness构建部署。

1. 编译前在既有synthesis阶段按原source snapshot及source_geometry既有校验一次构建页范围/字符框索引，逐本产品字段检查来源/块/quote，把可精确映射的跨页quote转换为同字段多条原页证据，保持单页quote原样；identity/版本/签名异常仍是硬错误，普通字段证据问题降为明确失败。只校验当前字段，历史published base复用。
2. 同一阶段持久化版本化field_validation artifact，绑定原attempt identity/digest/raw_ref及source snapshot digest，保存原引文→各片段及页间空白的无损映射、失败原因和有效结果视图；不覆盖82原行或9原响应。project_field_attempts、统一list_field_attempts、最终counts、失败字段重试读取同一有效视图，不能候选unknown而页面仍verified。stage成功提交遵循既有代次/事务。
3. compile_delta合同升版使恢复仅失效synthesis及后续；source/identity/field_plan/extract和原调用记录复用。旧field_validation缺失仍能读历史记录，损坏/跨scope不可回退为verified。
4. 恢复时不得因为validation改变让discovery重新外发。复用既有记录；失败/未执行的发现保留状态。若原未发布发现的复核依赖确实因字段变化失效，保留原始记录并明确待重验，正常普通字段发布继续，不伪造新review或静默消失。新上传仍走原发现策略。本轮恢复必须0新模型。
5. RED覆盖真实跨页多引用保留、同页/页边界/跨页空白完整审计/非空白缺框、scope/源变化、原记录不变、status/count/retry一致、旧contract仅恢复到synthesis、恢复无provider与候选不带失败值。GREEN后独立复核再部署同Harness，从网页恢复，不手工改业务记录或候选。若还有发布错误，保存真实终态继续定位，不宣称G3完成。

## 2026-09-15 Task3aw：直接复用最近已验证 G3 的历史证据基线

用户明确要求参考 WeKnora 原生 Wiki 的增量处理，并指出最近 G3 已统一入库，常规新任务无需重跑 G2/G1/815。沿用已授权 G3-AUTO-3/4/5/6，不删除历史资料或当前字段，不新建环境、发布权威或缓存协议。root 唯一仓库写者；既有 g3_admission_finish 只读复核本计划及冻结实现。

Task3av 网页恢复155a5f45-ca70-59fc-ae24-d426e5edb07a在09:31:24.656Z点击、09:51:13.315343Z失败，总1188.659343s；checkpoint229.020407s，三次草稿请求各约300s，0新/10复用模型，21成功/31未提供/30失败。300秒配置验证已结束，不再增加等待或继续原样恢复。原生wiki_ingest_batch.go已有按需页读取/运行内缓存、受影响页发布、独立失败待办；其直接状态翻转不能替代既有唯一Release合同。

已核实最近父发布链含4层G3全候选，每层约7.4–7.8MB，随后G2/G1/815。同一真实父候选本地单核只读验证23.032305792s、完整验证计数1、516成员，输入原样保留；这是诊断，不冒充RED或Colima耗时。当前父的原sealed legacy proof文件40868B存在；失败child proof不存在，尚未证明父proof已验签。source authority新候选miss直接回溯全链，而普通已发布读取已使用signed published projection。原生first-parse重复读取是另一未测成本，本次不一并修改。

架构：发布权威通过一个窄的内部读取接口提供精确scope/release/epoch下的已签名G3 projection及成员校验结果；复用g3_published_read_reuse原实现，不复制缓存协议。SourceAuthority读取父候选自己的candidate/base/epoch对应原sealed legacy proof，按父field ID和evidence hash逐项核对，只有事实/引用/页码/来源未变且满足既有导航扩展规则的field occurrence可映射到child。仅可选集合nil/empty使用已有语义等价比较。仍逐唯一receipt检查当前知识删除、revision/binding、pinned/active来源及必要旧摘要映射。已有child proof命中行为不变；父projection/proof缺失才走原明确准备路径，存在但损坏/错签名/错scope必须失败，不静默覆盖。新定义/页面/身份引用和变化字段继续原native校验。

写域：internal/application/service/{concept_source_authority_830_g2.go,concept_source_reuse_legacy_830_g3.go,g3_published_read_reuse.go,wiki_release.go}，可新增同目录g3_published_legacy_baseline.go及窄测试文件，复用现有fixture及原规格/证据。无Harness/UI/DB/model变化；仅受影响APP构建部署，旧服务和数据库复用。

- [ ] RED：最近父已封存proof时，新child不调用旧链；冷重开相同；父/child/proof不变。
- [ ] RED/回归：导航扩展及冷projection空集合等价可复用；事实、条件、例外、引文、页码/offset、source/parser变化不能继承；错误成员关联/签名/scope/hash拒绝。
- [ ] 验证发布权威实际读取接线；父缓存缺失与损坏分开；来源撤销在复用后仍阻止发布。
- [ ] 最小实现、bounded GREEN、独立冻结复核，部署同一APP；保存原失败回执。
- [ ] 网页恢复最新失败任务，不重抽普通字段；增量发布/检索/证据通过后，继续已批准新产品三原件网页验收。G3仍未完成。

## 2026-09-15 Task3av：既有平台响应等待上限的有界调整

Task3au APP138028353已部署，网页run6b468cec-402c-5668-a5c9-c70d399483b1在09:02:48.863Z点击、09:13:41.657508Z失败。检查点209.792576s单代成功，candidate-v2直接复用，未重编译；0新/10复用调用，字段21/31/30不变。preparation3次传输失败。首个APP请求120.330171349s后统一返回CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE，与客户端120s读响应等待先超时相容；目前没有phase trace证明具体停在来源链哪层，也不能排除内在来源问题。

沿用G3-AUTO-3/4/5/6及已授权现有环境：仅将该scope platform.timeout_seconds由120改为300（既有PlatformConnectionSettings已允许≤300）。这是一次有界配置验证，不宣称性能解决；httpx标量为网络阶段超时，既有3次job attempts保留，不冒称一次调用或整任务300s硬上限。模型timeout/预算/重试、权限签名、来源校验、响应容量、数据库、应用源码和镜像均不改。当前失败及候选不变。

root唯一写者，只写本计划/现有规格/回执及/private/tmp新私有env和原compose适配；新env逐值对比仅此一个scalar变化，旧env保留回滚。先确认终态、无活动jobs/遗留请求，再复用同一Harness镜像重启原API/worker；APP/UI保持。既有配置模型校验+精确容器env读回、健康检查和独立脚本复核后，从网页恢复并实测。无需源码构建/迁移。若300仍失败，保留平台性能/来源问题，不能继续盲目加时或宣称验收通过。


## 2026-09-15 Task3au：增量来源校验复用既有当前绑定判定

Task3at CODE/DELIVERY已通过，source c37e0813c82c935d6d2f6d600da17662adc34ea1；网页run50e6e0b2-701b-54a2-8081-4a5f0cdb89a3于08:21:11.971Z点击、08:28:44.410085Z失败，452.439085s，0新/10复用模型，21/31/30字段原记录不变。检查点及编译均单代成功，candidate-v2已保存SHA c007b78e0b94e6c8e0fa20c167eb921acfff17c23e8f00779324bb43e35c7903，10,202,320B，原导航已继承。草稿3次返回CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE，不是租约回收。

已证明：source gate对全部8绑定取13份材料，而本次corpus只含3份新增材料，剩10份材料属于逐值不变的7个PublishedBase绑定。types既有currentBindingIDs830G3和source closure早已支持当前resolution/历史carry区分；service未消费同一边界。沿用G3-AUTO-1/3/5/6，复用types当前绑定判定，不按corpus交集忽略缺失，不按旧entity一刀切（当前MATCH/refresh仍要校验）。仅当前绑定材料进入corpus live gate；全部旧新binding/definition/field/page证据与legacy当前撤销检查继续执行。既有发布base身份、来源闭包、导航与权限不放宽，不向current corpus拼入历史材料，不修改真实candidate或重抽。

root唯一写者，范围internal/types/concept_free_wiki_830_g3.go及窄测试、internal/application/service/concept_source_authority_830_g2.go及窄测试。g3_service_inventory仅在/private/tmp准备真实source gate的fixture测试补丁，g3_admission_finish独立只读复核。先RED（完整合法增量候选的当前选集/真实gate到达后续阶段；当前材料缺失及当前MATCH不得跳过），后最小实现、GREEN和独立冻结复核。只构建升级受影响APP，Harness/UI/数据库复用。网页从已保存candidate-v2恢复，不重编译、不重抽。当前只证明选集错误；后续证据校验与发布仍未验收，不预判PASS。


## 2026-09-15 Task3at：增量编译继承已发布导航及产物版本失效

Task3as已部署；网页run16339470-f954-564e-b7ae-60f7515b050b在07:35:46.838Z点击、07:42:31.919412Z失败（405.081412s），candidate成功持久化，preparation HTTP400，0新模型/10复用，字段21/31/30。真实candidate SHA9ebbe5b355d0445683dd87f1f42051ef3b85999be9f8096391007be764f2e16a，10,201,079B，经Go纯types+成员校验PASS且canonical原字节同SHA。只读比对确认：真实已签base保留1条navigation_assignment，新candidate为空；对应旧entity/version仍存在；ValidateBatchNavigationHistory830G3确定拒绝。其他父identity、7旧bindings、493fields/1def/8pages及1822来源一致。不得放松APP历史导航门禁，不得改写该失败候选。

沿用G3-AUTO-1/3/5/6，root唯一写者。修复既有compiler assemble接口可传入严格typed的已发布navigation_assignments，生成manifest/hash时一并继承，空导航时保留旧字节兼容。平台从已验证base_snapshot读取原导航，保持版本/hash/labels不变；不重新分类旧产品、不调用模型、不调用人工导航编辑操作。错误导航或entity/version不符仍拒绝。

编译实现变化使旧candidate失效：复用Artifact现有contract_name/version字段，将新candidate产物版本提升为2，检查点按显式产物合同版本表判可复用；旧candidate及其下游从prefix排除，只重做compilation及之后，sources/identity/field_plan/extract/synthesis继续复用。已验证v2候选仍直接复用；不改历史payload/任务、不新增DB字段/表/工作流版本。历史v1若compiled产物已失效，则从早期前缀进入现有workflow2；仍兼容的v1完整产物按原顺序。

root写域：knowledge_compiler/batch_concept_compile_830_g3.py、product_ingestion/{compilation,pipeline,stages,checkpoints,checkpoint_store}.py及相应tests/原规格证据。先RED覆盖导航在pipeline跨编译保存与hash一致、空导航旧hash兼容、候选版本变化只重编译不重抽取、新版本候选重试原字节复用；后实现、独立复核、只升级现有Harness（复用0018/APP/UI），从网页恢复。全新三材料仍待现有增量通过后执行。Codex不修改真实候选或代执行发布。

## 2026-09-15 Task3as：先保存编译结果，再提交草稿

草稿幂等身份绑定candidate的生产run，而非恢复child；跨恢复保持同一preparation_id、candidate原字节及原内部审查哈希。当前系统审核签名仍使用当前任务和平台回执，不改原候选。提交响应丢失后由平台原幂等接口处理，不产生另一草稿。

Task3ar 真实网页run `dcbc67b3-15a3-588b-b7e7-19df10591cc4` 于06:06:56.478Z点击、06:26:03.161148Z失败。检查点两次租约回收后成功；编译单代失败，APP原接口77秒返回400，未生成草稿。新增模型调用0，复用10，字段21/31/30保持。冷缓存兼容修复CODE/DELIVERY通过不等于BUSINESS通过。当前candidate只在create_preparation成功后持久化，导致失败结果不可查、恢复重算，此处必须修正；未知的实际400细分原因仍不得猜测，待平台留下真实candidate后只读定位。

同G3-AUTO-3/4/5/6，复用现有ProductStage、JobStore、ArtifactStore和唯一APP草稿接口。新增工作流v2：compilation只生成并原子保存candidate；preparation读取其原字节提交原接口并保存metadata；后续review/publish/verify不变。提交失败不得丢弃或重组成功candidate。恢复只引用已完成compilation，经既有来源/摘要/代次边界校验，不改写历史结果，不补抽普通字段。

版本显式冻结：ProductRun增加NOT NULL workflow_version（历史/旧写者server_default=1，新create_run显式2；幂等命中不升级）。v1阶段顺序及combined compilation语义保留。CheckpointPlan旧v1字节/顺序不变，新v2按新顺序；新恢复若旧compilation已成功则保持v1复用candidate+preparation，否则可从已完成早期前缀转v2。child版本绑定plan合同，origin可为旧版本。旧字段重试/旧恢复构造点继承原版本。使用现有数据库单一小迁移，不新建环境、队列或存储。

root唯一仓库写者，写域为product_ingestion的tables/models/store/checkpoints/checkpoint_store/progression/pipeline/composition、对应测试及现有migration目录；仅必要API字段回显（不泄密）与UI阶段名/真实活动阶段展示及对应测试。g3_extraction_finish只在/private/tmp提供版本字段/迁移/构造点的测试与实现分离补丁，root先RED再集成；root负责流程、检查点合同和UI。先验证候选持久化先于HTTP、HTTP失败仍可读取、恢复不再调用assembler/模型、复用原字节/原证据、旧v1及幂等兼容、v2发布屏障必须含preparation，再独立冻结复核和部署受影响Harness/UI。APP保持Task3ar镜像，除非拿到真实候选后证实另一个APP根因。

本轮期间不改运行链路；当前失败已终态，才进入本修复。租约首次过期的直接原因尚未证实，后台线程取消后仍运行的放大机制和重复大对象校验列为待修问题，不能宣称稳定性已通过。之后继续现有产品增量验收，再全新产品三原件网页完整验收。

## 2026-09-15 Task3ar：冷缓存与增量基线的空集合兼容

Task3aq 网页恢复 `baaa5263-75ec-5a4f-b55a-169d3be353cf` 检查点成功，复用10次历史调用，新增调用0；编译提交400，05:14:11.454219Z失败，无新草稿/发布，不算验收通过。原493字段投影中473个conditions、481个exceptions为null，同一检查点编译请求对应项为[]。只读overlay复现：原真实基线测试清空内存缓存、读取既有签名gob投影后，在validateBatchConceptBase830G3失败。Gob空slice变nil，reflect.DeepEqual误判，既有冷读测试仅覆盖成员索引而非下一稿基线。

沿用G3-AUTO-3/5/6，root唯一写者。写域为concept_free_wiki_830_g3.go、必要同目录窄比较函数、g3_platform_incremental_base_test.go、g3_platform_candidate_transfer_test.go及本规格/证据。比较只在既有明确可选集合（definition.aliases；field.evidence/concept_ids/conditions/exceptions；page.concept_ids/conditions/exceptions）允许nil与空slice等价，外层成员集合按长度和顺序比对；值、原文、证据定位、非空集合顺序、必需证据、身份及版本仍精确比较，不修改签名投影、历史候选或摘要。不改权限，不新建存储或编译路径。

先将冷读下一稿校验和真实transfer→draft冷读路径写成RED；覆盖字段值、证据/页码、非空条件变化仍拒绝及输入不变，后最小修复、GREEN及独立冻结复核。仅构建部署受影响APP，复用已热构建缓存、Harness/UI/DB。之后从网页恢复失败任务重新计时；增量通过后仍须全新产品三原件网页完整验收。不得用本诊断或代码测试宣称真实链路完成。

## 2026-09-15 Task3aq：检查点控制输入与已执行输出边界

Task3ap 三组件已部署 source `2f2fe5ca87cbad3a3c0ea9ff12609a81aa139cb7`。网页恢复于 04:41:52.577Z 发起，child `7c42de0e-fa1e-5927-94b5-88ab9cad5bda` 在 04:42:11.935192Z 以 CHECKPOINT_INVALID 结束；本轮增量验收失败，未发布，记录调用为0。原9响应和82字段仍不变，新产品尚未上传。

只读根因及独立复核：旧 `processing_recovery_plan` 是 enqueue 控制输入，producer_generation=0；被当 source 执行产物选入 plan，实际 source job generation=1，dependency也不同。其他15产物的生成任务/代次/依赖相同。Jobs enqueue=0、claim后代次>0是既有生产语义，不按artifact名字补黑名单。

同 G3-AUTO-3/4/6，root唯一写者：仅 checkpoint_store.py、checkpoint合同测试和现有规格/证据。新计划对本run和继承引用均只选择 producer_generation>0 的已执行输出，必需输出检查和worker完整性校验继续执行；旧plan/记录不可变。先RED覆盖控制记录、失败checkpoint再恢复、只有零代次必需产物，后GREEN及独立复核。仅重建部署受影响Harness，APP/UI复用本轮已验证镜像；再从网页恢复失败child并重新计时。全部真实成功前 G3 未完成，随后仍需新产品三份材料网页完整验收。

## 2026-09-15 当前队列：增量候选传输与检查点恢复

必要端口写域补充（同一已授权边界）：A 复用 g3_platform_base_snapshot.go 原加载实现，避免复制另一份发布身份校验；B 包含 models.py/composition.py 的 typed 状态和唯一 checkpoint handler 注册。root 同步修改 product_ingestion_bridge.go、frontend/src/api/product-ingestion.ts、knowledge-base/product-ingestion-status.vue 及对应测试，独立显示 reused_stages 原结果/原耗时，不能伪造为新执行成功。

交付入口的小型适配由 g3_docker_connection 在 /private/tmp 提供测试/实现分离补丁、root 集成：仅 scripts/app_artifact.py、docker/Dockerfile.app、必要原README及tests。复用 BA0 identity/lookup/receipt，加冻结 git archive context（不创建 worktree）及显式 exact runtime-rebase；runtime资源与依赖必须与基础镜像来源一致，唯一例外构建工具 app_artifact.py 在rebase明确同步覆盖。基础本地image ID由已核验tag供FROM，构建前后/父层核对同一identity。缓存marker不作正确性门禁。Harness用同一冻结端口和既有Dockerfile，不新增制品平台/第二selector。上传或恢复业务不触发构建。

当前验证进展（CODE，2026-09-15）：A Python传输/客户端/完整pipeline及Go原发布服务集成通过，Unicode完整性独立复核0 BLOCKER；B原82字段三态检查点组合10 PASS 133.54s，早期source/routing完整恢复2 PASS 327.38s，继承partial终态8 PASS 20.62s；旧v1/v2/v3记录兼容和新调用拒绝边界明确分开测试（26+24+3 PASS）。UI 35 PASS、typecheck PASS、Go状态桥PASS；BA0正式构建适配140 PASS 81.97s，空diff、默认runtime、私有umask目录可读性均已RED→GREEN。Ruff和diff检查PASS。独立B最终0 BLOCKER，原partial finding已闭合。此时未构建部署、未外发模型、未恢复业务，G3依然未完成。独立复核/完整验证记录见 docs/insurance-kb/evidence/830-g3/checkpoint-transfer-code-20260915.md。

用户已明确批准“可以，按照你的建议执行”。适用 G3-AUTO-3/4/5/6，沿用现有环境和唯一 Release 权威。原 ef9bf57f-ae07-5206-b2d1-ff34c331f8a2 终态失败不改写：9 份字段调用响应、82 项状态（21 verified、31 not_provided、30 extraction_failed）已保存，compilation 因 8 MiB 请求上限失败。当前 compile_request 6,997,509 bytes、base_snapshot 3,133,391 bytes、compile_delta 209,781 bytes。此队列替代继续扩大错误字符串/恢复前缀白名单的做法，不改变旧协议的审计读取。

复用核验：WeKnora wiki_ingest.go 的持久待办/触发分离、wiki_ingest_batch.go 的按需缓存及退出统计可参考；正常业务仍必须经过既有 Candidate/Review/Release。直接复用 ProductArtifact、ProductStage、JobStore.enqueue/report_success、既有阶段顺序，以及 g3_platform_base_snapshot.go 的已发布投影加载和 wiki_release_automated.go 的自动 draft/source/policy/CAS 校验。不新增表、队列、存储、审批或签名平台。

唯一仓库写者/集成 Owner 为 root。g3_extraction_finish 仅在 /private/tmp 准备恢复的测试与实现分离补丁，不编辑活动仓库；g3_incremental_code_review 只读审查冻结协议及最终实现。Root 维护本计划、现有设计/OpenSpec 和交付记录。

### A. 发布边界的窄传输协议（root）

写域：product_ingestion/{candidate_transfer,platform_client,pipeline,compilation}.py，internal/types/g3_platform_candidate_transfer.go、internal/application/service/{g3_platform_candidate_transfer,wiki_release_automated}.go，internal/handler/g3_platform_release.go，对应测试及共享 fixture。现有 POST preparations 接受旧 bundle 或新 transfer 二选一。transfer 绑定外层已发布 snapshot 的 scope/release/epoch/candidate/manifest，不使用 projection.parent 冒充当前版本。

只处理七个固定数组槽：request.base_request 的 sources/existing_definitions/existing_fields/existing_pages；compile_result.output 的 definitions/fields/pages。与投影逐值相同的成员传 base_index，其余 inline；保持顺序。只在已有明确集合槽应用 null→[] 的兼容，无模糊比较或通用 JSON patch。完整其他候选内容、原响应、审核和摘要均保留；可使用 gzip+base64 压缩传输审计数据。协议限制 wire 8 MiB、解压 delta 64 MiB、展开后候选 128 MiB；单 gzip member，拒绝尾随流、重复索引、越界引用、重复 JSON key 及任何超限。Go 在分配完整展开结果前累计预算，核对完整 canonical manifest SHA，再执行原候选合同校验。解码/压缩不占 Python 心跳事件循环。大于协议能力的输入明确失败，不静默丢弃、不全局放宽 schema 接口。

RED/GREEN：共享跨语言 fixture 精确还原；历史增长不重复传历史成员正文；当前增量/顺序/原响应不变；超8MiB的原候选可在有界传输内表示；旧 bundle 兼容；错误作用域/版本/摘要/null标量/重复或越界索引/解压及展开超限拒绝；真实 handler→service 校验不旁路。完整候选仍仅在发布边界组合，其成本随完整集合增长，不宣称1000文件已验证。

### B. 有效检查点恢复（g3_extraction_finish 提供补丁，root 集成）

写域：product_ingestion/{recovery,artifacts,store,progression,stages,pipeline,api,artifact_models}.py 及必要同目录 checkpoint 模块、对应测试；pipeline.py 接线由 root 最后应用，与 A 不并发写。复用现有 retry-processing 网页/API、表及队列。原子登记小型引用计划并及时返回身份，昂贵验证由 worker 执行，不在提交请求内读取全部来源/历史响应。typed plan 绑定作用域、origin run/version、材料/Schema/base 身份、各原 stage/dependency/settlement 和 artifact ID/contract/key/hash；仅引用，不复制大 payload。原 stage dependency 含 run_id，保留原值；新恢复输入摘要另算。

根据阶段输出和依赖有效性确定接续点，不根据错误文案或任务前缀。不伪造新 run 的前序成功 job；通过验证 receipt 展示复用并满足依赖。ArtifactStore 提供公开的授权引用读取接口，按需读原记录并验摘要；重复恢复引用链必须有界/去环并可直接定位原资产。状态查询只取元数据。当前已完整保存 synthesis 的例子应直接进入 compilation，复用 compile_request/compile_delta/可选 discovery_review、全部82三态字段和原9调用；不能使用只选成功值的 lookup_cached_fields。Schema、来源、base 或相关合同漂移仅使相关依赖失效，未知发送状态不得盲目重发。原失败终态、调用原始身份/用量和证据不改写。发布仍核对当前 source/ACL/policy/Head。

RED/GREEN：等价现场从编译恢复且分类/抽取/自由发现0调用；三态结果及原响应不变；缺失/篡改/跨域/来源Schema或base漂移不误复用；未知发送不补发；并发恢复幂等、失租拒绝回写；状态不读大payload；原任务终态不变，恢复过程/部分成功/失败均有明确终态。旧V1/V2/V3只作兼容，正常入口由检查点机制决策。

先测试 RED 再实现；冻结后独立复核，再仅构建受影响 APP/Harness（UI仅有真实改动才构建），复用仓库 BA0 入口和组件快照，不临时改写 Dockerfile。部署完成后仅从网页发起必要恢复，运行期间不改代码、不执行业务接续脚本、不补普通字段。各阶段/总耗时、调用新旧计数、字段三态、真实发布/检索/证据结果独立记录。CURRENT=CODE_VALIDATED_READY_TO_BUILD；CODE=PASS，DELIVERY/BUSINESS=NOT RUN，G3 尚未完成。

# G3 explicit source recovery follow-up (root, 2026-09-14)

Existing user authority: complete G3 in the existing environment, incremental result reuse, original evidence retention, normal webpage entry only. This continues G3-AUTO-3/4/6; no new Goal, database, service, ACL, provider or manual business continuation.

Independent read-only findings and review: /private/tmp/g3-task3ad-recovery-readonly-01.md; g3_incremental_code_review requires a NEW ParseAttempt (DB generation fence), not merely a new processing trace attempt. Original artifacts and failed run remain immutable. Cold APP build at source 5aa5d05 is running; repository must remain unchanged until its build/smoke/deploy guards finish.

Task3ae Owner g3_service_inventory: only harness/src/insurance_harness/product_ingestion/store.py and harness/tests/product_ingestion/test_recovery.py. Permit existing explicit retry-processing for SOURCE_PARSE_FAILED and SOURCE_PARSE_DEADLINE by removing these reason exclusions only; retain original binding-change exclusion, scope/version/sealed-upload/stage/no-semantic-effects checks, deterministic child, original terminal and signature checks. This is permission to revalidate current sources, not a claim a failed source is ready. Existing worker does the revalidation. No automatic source reparse, model call or change to deadlines beyond existing child creation. RED old exclusion test, then failed/deadline eligibility, immutable original/idempotent child/stale/foreign/binding gates. Only prepare a reviewable patch in D while source is frozen; root will apply after guards, then run RED and authorize implementation application. No production source editing now.

Task3af proposed APP boundary (not yet implementation): reuse durable validated DocReader result through existing reparse/worker with new ParseAttempt and explicit immutable old-artifact reference. Rechunking is a real new stage, not a claim of precise old-plan reuse. Future parser/effective-config checkpoint, if necessary, must be separate/additive so old first-parse v1 stays unchanged. No vector per-batch checkpoint or reconstruction/backfill of historical f077 as this step's prerequisite. Exact smaller write paths and RED are frozen after owner feasibility review. Root owns plan/evidence/review/integration; runtime acceptance starts only after final deployment, through the webpage.

Outstanding issues remain explicit: failed-source count aggregation (109 observed vs incomplete summary), absent raw embedding response archive, complete chunk/vector success reuse. This follow-up does not by itself close these or declare G3 PASS.

## Task3af frozen minimal implementation (root approval 2026-09-15)

Feasibility and binding: /private/tmp/g3-task3af-docreader-reuse-feasibility-01.md. Independent review accepted DocReader-only reuse with NEW ParseAttempt. G3 always selects builtin PDF native capture; v1 native parser identity/capture version and original PDF digest are validated. Actual historical cache availability remains a runtime observation, not presumed.

Owner g3_admission_finish may prepare patches ONLY for internal/types/task.go; new internal/application/service/g3_docreader_recovery.go + test; internal/application/service/knowledge_process.go + focused recovery test; internal/application/service/g3_first_parse.go + existing test. Optional typed reference binds original parse/processing attempt, source SHA and artifact SHA; tenant/RAW/knowledge bind outer trusted payload, never user file paths. Selector runs before normal new-generation allocation; retain existing new ParseAttempt/cleanup/enqueue, pinned-source checks and stale-worker rejection. Only eligible configured G3 RAW PDF with successful frozen parse and failed embedding can select reuse. Convert validates actual current PDF SHA, frozen native parser contract and artifact MAC/hash before resolving a DocReader; a validated hit yields stored ReadResult. Ordinary paths remain unchanged. No model/retriever/indexing-tail rewrite. Split is a genuine new stage under current config. Add optional origin_docreader to the NEW signed first-parse record only; omitempty must preserve old record serialization/hash and all historical signatures. No existing artifact edits/backfill. Keep Task3ad no-retry policy through existing processChunks.

Tests must prove a real cached parse bypasses DocReader, new generation fencing and old artifact preservation, changed/tampered/foreign/pinned/missing references cannot authorize reuse, new artifact records origin, nil optional field preserves v1 bytes, and legacy/non-G3 behavior. No model calls. Prepare test and implementation patch in D only while root APP guards are active. Root applies tests first and obtains valid RED before applying implementation; missing runtime/cache/dependency errors never count as RED. No commits/deployments by agent.



## Task3ad: prevent implicit whole-batch embedding replay (2026-09-14)

Billing diagnosis correction: the user showed CNY199.91 available balance and the free-quota-exhausted notification. The official error-code reference maps this exact 429 insufficient_quota message to TPS/TPM throttling. A subsequent saved-model short-input debug request succeeded with 1024 dimensions; there is no evidence requiring recharge. Root may use the existing model settings endpoint to set this G3 tenant's embedding background MaxConcurrency from inherited default to 1, preserving all other model parameters and server-held credentials, and verify exact readback. This reduces bursts, not a claim of complete token-rate governance. No service restart is required. Both this diagnostic call and setting change occur after the immutable failed acceptance run and are excluded from its timing/call counts.

Requirement G3-AUTO-3 and the existing zero automatic retry acceptance constraint. Frozen source 8dd22b327 produced webpage run f0776a58-90a8-419c-ae0a-7e6d3c478996, now FAILED. The rate table was parsed successfully, but embedding made 100 dispatches for 35 distinct request hashes, including 17 HTTP 429 insufficient_quota responses. batchEmbedWithBackoff replays the complete list up to five times; zero transport_retry_index and worker_retry do not prove absence of this outer replay. Preserve the failed run and all 109 three-material receipts.

Owner g3_admission_finish may modify only internal/types/model_dispatch.go and its test; internal/application/service/knowledge_model_dispatch.go and its test; internal/application/service/retriever/keywords_vector_hybrid_indexer.go and its test; internal/models/embedding/openai.go and model_dispatch_test.go. Add explicit context policy disabling automatic model retry, set by the configured G3 withG3ModelDispatchParent path. Both outer batch backoff and OpenAI embedding transport consume it; do not infer retry policy from recorder presence. Ordinary non-G3 behavior is unchanged. Errors return without whole-list replay. No new cache protocol, service, database, or business continuation.

RED must prove the existing five outer calls; tests cover G3 single invocation, legacy compatibility, successful path, context wiring, no transport retry on connection error, and original error preservation. Root owns evidence, independent review and integration; deployment and subsequent webpage acceptance are separate. Current task remains failed. Failed-run summary undercount and upload layout are separate outstanding issues.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. User has already requested continued execution; no additional execution-choice prompt.

**Goal:** Make one new product's three uploaded originals reach searchable, traceable publication using deployed platform tasks alone.

**Architecture:** Extend Python wiki-api/wiki-worker and P1 durable JobStore with product ingestion services. WeKnora remains sole original-source and serving Release authority; only versioned REST crosses the boundary. UI uploads and observes, never compiles or signs.

## 2026-09-14 first independent run failure follow-up

The frozen d7812093 platform run `8e5693b4-6365-458b-89e6-7ced242b200d` accepted three new originals through the webpage and reached FAILED in source processing. Preserve this failed receipt; no manual continuation or acceptance PASS. Diagnosis remains read-only until its cause is verified. A separate observed response-contract gap drops Harness `source_processing`, `model_call_count_complete` and `discovery_summary` at the Go `ProductIngestionRun` typed bridge. Owner g3_service_inventory owns only `internal/application/service/product_ingestion_bridge.go` and its focused bridge test for safe typed forwarding, with RED asserting returned JSON retains declared summaries and strips unknown/raw fields. No new authority or broad JSON passthrough. Root owns integration, deployment and the proven parse repair: the current APP has BATCH_EMBED_SIZE=100 while the actual qwen3.7-text-embedding response caps batches at20. Reuse the existing batchEmbedder with BATCH_EMBED_SIZE=20 at the next approved APP replacement; no new embedding adapter or repeated quality calls. Source failure repair and a new measured/recovery run must not rewrite this attempt as passing.

## 2026-09-14 required open-discovery integration amendment

User authority: `/Users/houjing/Documents/LLM_wiki/G3-统一知识结构补齐任务-2026-09-14.md`, including “Schema 外自由发现必须实际接入”. This extends the current G3 queue, not a new Goal. Keep the deployed navigation, existing 493 field identities and performance/recovery work. Current permanent `pipeline.synthesis` only projects field artifacts; legacy ENTITY_SYNTHESIS and published free pages do not prove this new path is connected.

### Task3w: bounded discovery source coverage

Owner g3_service_inventory after root review of this amendment. Files: new `harness/src/insurance_harness/knowledge_compiler/g3_discovery_routing.py` and `harness/tests/test_g3_discovery_routing.py` only. Reuse `g3_field_task_routing._spans` and original SourceBlock metadata/offsets. Pure `route_discovery_sources(sources, *, max_source_chars=24000, max_span_chars=2000)` returns `source_options` in the existing offered-spans shape plus an explicit coverage record. Select by material/page/chapter coverage without Schema keywords: round-robin materials and spread selection across their ordered chapter spans, including later sections. Do not truncate or normalize quotes. Return offered and omitted exact ranges/counts so bounded coverage is never described as full reading. Budget parameters are caller-controlled and validated. No model, new index/database or schema mutation.

- [ ] RED: long material's later non-Schema section is offered; two materials share budget; exact original offsets/text; strict budget; truthful omitted coverage; deterministic output and invalid-budget rejection.
- [ ] GREEN: implement only this pure selector and run its focused tests.
- [ ] Independent root review before any runtime integration.

### Task3x: permanent discovery and independent disposition

Root owns `product_ingestion/pipeline.py`, new `discovery_stage.py`, `compilation.py`, focused runtime/compilation tests and configuration/template wiring. Task3x status Owner g3_service_inventory owns `product_ingestion/api.py`, its test, `frontend/src/api/product-ingestion.ts` and `frontend/src/components/knowledge-base/product-ingestion-status.{vue,spec.ts}` only. Reuse recorded stage calls/artifacts and existing G2/G3 definitions/pages, evidence projector and reviewer; do not create a second compiler or serving Head. Freeze precise adapter interfaces after the bounded port review. Only current changed material is eligible. Failed-field-only recovery reuses prior discovery; no-new-material carry performs zero discovery calls. New material with no field targets still receives an explicit discovery disposition.

- [ ] RED: permanent pipeline currently omits discovery; technical failure is distinct from zero valid candidates; recorded responses replay without redispatch; ordinary field unknowns remain publishable.
- [ ] Add bounded source coverage and existing-field/page comparison to candidate generation. Independent review must retain decisions/reasons, reject noise/unsupported claims, route duplicate facts toward existing knowledge, and require an independently useful purpose for a new page. Preserve conditions, exceptions, entity/version and exact evidence. Reuse existing score/admission contracts; no automatic Schema rewrite.
- [ ] Only accepted evidence-validated members enter the existing composed candidate and system review/publication. Preserve rejected/pending raw candidates and coverage. Old published members remain intact.
- [ ] Deploy the shared Harness update before the measured new-product run; no Go rebuild solely for Python changes. Verify a real Schema-external example or honestly report lack of evidence, plus duplicate/noise dispositions and source/navigation clicks, reusing actual prior artifacts where sufficient.

No implementation or existence of a legacy page alone closes this amendment. Service-line runtime integration remains a separate outstanding item in this same G3 queue.

Task3x pure adapter ownership: g3_extraction_finish owns new `product_ingestion/discovery.py` and `harness/tests/product_ingestion/test_discovery.py`; root owns orchestration/compilation/config/status. Use a strict bounded proposal envelope containing the existing `G3DCompileReferenceResponseV1` plus audit-only dispositions with candidate identity/text, exact source selections, reason, independent business use and an optional existing comparison target. Dispositions distinguish proposed new members, duplicate, existing-knowledge update proposal and rejected noise/unsupported claim; existing-member updates are not silently inserted into G3 delta. Include current validated field delta, inherited same-entity fields/pages and Schema field descriptions in both generation and independent review context. Only the bound entity and offered source spans may be referenced; current raw model responses remain immutable artifacts.

The pure adapter exposes context/projection functions for generation and independent review, without HTTP/store side effects. Review can be one bounded entity-level call using existing `ReviewOutput`/six-part PageScore rather than replaying every field review window. Review binds the exact final composed request/output hashes, checks every proposed new member and every audit disposition, and returns explicit reasons. Existing ordinary field validation is a truthful RULE component; independent member review retains actual model raw and call identity. Missing/invalid scores, failed review, unresolved equivalence or below-threshold members cannot enter automatic publication. The current platform may keep the entire proposed free-member group rejected/pending while publishing validated ordinary fields; do not fake a model review of a pruned output or rerun the model to force a pass. Root candidate assembly must call the existing `_g3_human_admission` on any actual added free members and preserve the independently reviewed hash. Tests must prove unsupported evidence/foreign entity rejection, current-field/Schema comparison availability, duplicate/noise audit-only custody, exact score coverage, stale review binding rejection and explicit failed/pending/empty distinctions.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/PostgreSQL/P1 JobStore, Go/Gin/WeKnora, Vue, existing Gemini and embedding/rerank configuration.

---

## Authority and tracking

### 2026-09-14 confirmed navigation and service completion

The user's confirmed 830 structure remains part of G3, including blueprint §§4–6 and G3-R5; the earlier 815 exclusion of benefits does not override it. Reuse this worktree and existing runtime. Root owns integration. Complete insurance classification → entity → Profile section → independent field navigation, retaining existing member IDs, pinned URLs and evidence without model calls or duplicate publication. Reuse the existing directory and page renderer, not a new Wiki, Head or editor. Add navigation on G3 field pages and a selectable Profile section view using the same overview and field members; a section is a view, never a second field fact.

Inventory the six medical service lines (安有医、安有护、就医通、臻享家医、御享国医、私董保健医), two eldercare lines (居家养老、高端康养), and separately 家族办公室 from the existing service registry and original materials. Distinguish catalog/Schema presence from real published content. Preserve unresolved version spellings as explicit gaps. Service entities consume their own existing Schema definitions through thin adapters; 11 insurance packs are a subset, not the global enterprise capacity. Prioritize one real 臻享家医 version; relationships require actual evidence.

Bounded validation: first demonstrate missing navigation with component tests; verify existing field targets and release pins remain byte-for-byte unchanged after reclassification; verify section direct URL/refresh and invalid-section rejection. Then check actual deployed medical, critical-illness and service paths, independent field counts, original-source clicks, supported relationships, and representative read times. Ordinary missing fields remain allowed. A fixture or empty service directory is not real acceptance. No build or repair during the measured independent upload run.

Spec: `docs/superpowers/specs/2026-09-13-g3-platform-independent-design.md`; Requirements G3-AUTO-1 through G3-AUTO-6 append existing OpenSpec 129. Current seven-product Head stays unchanged during development. All test fixtures/provider-zero remain CODE only. root is sole integration/deployment owner. Do not commit until independent review; no push.

### Task 1: Persistent product/field artifacts and task settlement (Python store owner)

Files: create `harness/src/insurance_harness/product_ingestion/{__init__,models,tables,store}.py`, `harness/tests/product_ingestion/test_store.py`, migration under `harness/migrations/versions/` after checking current heads. Reuse existing `jobs` package and database clock/generation fencing; do not modify its contracts without returning findings to root.

- [ ] Write RED cases: process restart retains result/raw; partial windows retain successful fields; source/Schema dependency change misses cache; model/prompt-only change reuses success; cross-space access refuses; stale generation refuses; interrupted provider call becomes explicit failure rather than repeated dispatch; terminal timing/counts stable.
- [ ] Run focused pytest and retain genuine assertion failures on preimplementation.
- [ ] Implement strict DTOs and scoped persistence: run/material/stage/call/field-attempt state with immutable successful results, exact dependency identities and raw evidence. Use separate Harness DB, never WeKnora DB. Expose store methods via explicit service port for durable create/attach/seal/read/settle/retry.
- [ ] Run focused SQLite deterministic tests; real PostgreSQL lease/concurrency check belongs to integration and must be separately labelled.

### Task 2: Service extraction outcomes and reusable validation (Python extraction owner)

Files: create `harness/src/insurance_harness/product_ingestion/extraction.py`, tests `harness/tests/product_ingestion/test_extraction.py`; read/reuse `knowledge_compiler/g3_field_tasks.py`, `g3_field_task_routing.py`, `g3_title_routing.py`, `concept_free_wiki_830_g2.py`. No edits to store/API/release files.

- [ ] RED mixed window: valid field survives sibling invalid quote; unknown value maps not_provided; absent_explicitly requires actual evidence; format failure preserves raw and yields failed statuses with no unverified values.
- [ ] Implement a transport-injected executor using FieldTaskV1 and exact SourceBlocks, bounded existing task batching. Persist raw through callback before projection; no automatic provider retry. Only scope/product/entity/field + immutable source revision/digest dependencies + Schema identity/version form success cache inputs. Task/model/prompt/validator identities remain provenance. Omit cached valid tasks before calling transport.
- [ ] RED/verify exact repeated evidence locations, no joined-line quote, enum/date/number failures, duplicate/missing refs, future discovery adapter inputs, and unchanged success reuse with zero calls.
- [ ] Run focused tests and report exact output; no real model calls in development lane.

### Task 3: Platform REST/source/release integration (root)

Files: service plugin in `harness/src/insurance_harness/product_ingestion/{api,worker,platform,compilation}.py`; register with `service_shell/{cli,config}.py`; Go scoped adapter/handler/routes under `internal/{application/service,handler,router}`; automation policy service file and focused tests. Freeze exact subpaths before each edit.

- [ ] RED actual composition has no product handler/routes, then tests for authenticated durable admission, revision-fenced source attachment, timeout/conflict terminal and restart recovery.
- [ ] Reuse immutable source download/manifest REST and first-page routing. Avoid generic Wiki ingest and avoid provider replay of historical products.
- [ ] Compose existing compiler functions from persisted field artifacts; ordinary failures project unknown plus reasons while identity/custody failure blocks.
- [ ] Add explicit system automation identity/policy receipt route without weakening human endpoints. Tests reject missing policy/scope/invalid signature/stale Head, accept exact scoped configured test policy and reuse existing CAS.
- [ ] Register long-lived handlers and API settings; add bounded end-to-end fixture test through real app composition, not direct helper only.

### Task 4: Browser upload and product task display (UI owner after API contract freeze)

Files: `frontend/src/api/product-ingestion.ts`, `frontend/src/components/knowledge-base/product-ingestion-status.vue`, `frontend/src/views/knowledge/KnowledgeBase.vue` (verify actual path first), existing Schema Wiki state display as needed.

- [ ] RED upload contract: durable run ID/attachments/seal use original files only and no candidate fields; component status handles partial_success/failed/needs_confirmation with timings/counts.
- [ ] Connect scoped server API, resume by run ID and show published product/evidence links. Target retry uses field service endpoint; never reparses full document for field error.
- [ ] Run frontend typecheck/build and relevant existing tests. Browser smoke after deployment is separate.

### Task 5: Independent review, deploy, actual acceptance (root)

- [ ] Review frozen code/tests by disjoint read-only reviewer, fix within owner domains.
- [ ] Preserve old runtime and diagnostic evidence; verify original services restored.
- [ ] Freeze source, build/reuse needed artifacts, migrate Harness job artifacts, configure explicit service identity/model/automation scope, deploy API/worker/UI/Go adapter once before measurement.
- [ ] Verify real health, registered jobs, policy readiness and actual UI entry. Report software/container/provider/provisioning/local-live separately.
- [ ] Verify chosen product absent by file hashes and platform records. Upload three originals from browser, then only observe. Capture upload-finished instant, all stage times/calls/outcomes, terminal published search and original evidence.
- [ ] Archive original/raw/provenance and acceptance receipt. Mark G3 passed only if all G3-AUTO requirements have actual independent platform evidence; otherwise keep exact incomplete items visible.

## Frozen first implementation slice after review

Task1/2 proceed under the design's "Durable window and call contract" amendment. Same-transaction P1 row read/lock and require_active_lease are mandatory for call audit mutations. recorded raw replay performs zero provider calls; dispatching uncertainty ends interrupted; old finished run never reopens. Task1 owns shared models/store; Task2 returns its own frozen outcome and communicates JSON with store. Do not add model/prompt/validator to success dependency key. Root owns routing.py/tests and Task3 integration design; release/source/Go/UI integration stays NOT RUN pending detailed review. All audit findings about legacy PG publisher are rejected and that chain is prohibited.

Dependency order: Task1 store port and Task2 outcome port freeze -> separate GREEN -> root composition -> Go/UI wiring -> independent review -> deployment -> no-edit browser acceptance. Root may implement pure first-page routing after its bounded RED before integration. Exact additional root files: harness/src/insurance_harness/product_ingestion/routing.py and harness/tests/product_ingestion/test_routing.py.

### Task3a frozen source/base port owner

Owner g3_incremental_origin_review (now implementation role); root independent review. Files: internal/application/service/g3_platform_source_snapshot.go and test; g3_platform_base_snapshot.go and test; narrow non-evidence-seeded capture refactor in concept_source_reuse_830_g3.go and internal EnsureCompletedBinding in knowledge_revision_source.go. No routes/handler/container/activation mutation in this slice. API must accept an injected authorization and signing port and fail closed if missing; no fake human/evidence seed. RED covers current revision/source drift, denied scope, signature absence, repeat snapshot with zero second DocReader call, actual page/native custody, fixed-base identity/member drift. Existing old capture/read tests remain regression gate. Root owns later REST registration/configuration.

Root Task3b owns product_ingestion/api.py, composition.py, worker.py, compilation.py, source adapter and service_shell/{cli,config,principal}. Go HTTP upload/proxy and system activation are separately frozen before edits. Additional root integration edit: harness/migrations/env.py imports product_ingestion.tables so migration metadata includes new job artifacts.

Task3b bounded regression ownership also includes harness/tests/test_service_shell_principal_039.py: retain the closed principal enum test and explicitly add the authorized product_ingestion identity and its two scoped capabilities. Do not weaken unknown-principal rejection.

### Task3c frozen browser gateway port

Owner g3_incremental_code_review after completing independent API review; root reviews this new implementation. Exact new files: internal/handler/product_ingestion.go and product_ingestion_test.go; internal/application/service/product_ingestion_bridge.go and product_ingestion_bridge_test.go. Root owns constructor registration/config and routes later. Reuse KnowledgeHandler current RAW and WIKI access checks; writes require existing editor/admin permission and route guards. The handler only uploads originals via existing KnowledgeService and calls the configured Harness REST bridge. A server-created run ID and upload ordinal are stored in each original's metadata under product_ingestion_upload as run_id:ordinal. Reject client-supplied candidate/field/metadata bodies. Failed uploads remain explicit accepted/rejected counts and the run deadline closes incomplete groups. No fallback or second upload on uncertain results. The bridge is configured with fixed endpoint/service credential/exact scope/capacity, rejects redirects, bounds response size and time, never forwards browser credentials or returns upstream secrets. A dedicated exact run/ordinal source reconciliation read will use existing scoped FindByMetadataKey; no historical full-list scan. No source parsing/model/compile/release logic belongs in this gateway. Tests use injected ports and a local fixture HTTP server only; do not upload live materials.

Task3a base output is explicitly a signed PublishedProjection containing the complete incremental-base closure, not a validator-valid original candidate bundle. Old raw C/D/model/review payloads are neither required nor reloaded. Exact release/preparation/candidate/member identities remain pinned.

### Task3d non-field immutable checkpoints

Owner g3_two_product_path_audit; root independent review. New product_ingestion/artifacts.py, artifact_models.py, artifact_tables.py and tests/test_artifacts.py; migration 0017_product_artifacts.py follows 0016. Root registers metadata in migrations/env.py. Reuse Task1 store read/scope and P1 active-job fence; do not alter jobs contracts or use fake field tasks. Implement immutable artifact prepare-writes/read plus separate non-field model call reserve/begin/record/read, exact duplicate idempotency and changed-body conflict. Artifact origin labels distinguish model/rule/platform source; caller model artifact references an actual recorded call in the same scope/run. Atomic stage completion combines prepare-writes with existing prepare_stage_settlement. Tests cover cross-scope and stale generation refusal, interrupted dispatch no resend, recorded exact replay, and raw/validated output association. No live provider/database/deployment.

Root Task3b additional files progression.py/test_progression.py implement the design's short-stage graph and periodic repair. API admission will queue upload reconciliation instead of the finalizer; finalizer is queued only on final barrier or terminal failure. No root waits for child workers. Existing jobs queue/lease/finalizer checks remain unchanged. Final stage execution and model policy composition are implemented separately from this graph.

Root Task3e gateway composition paths: internal/config/config.go and new product_ingestion.go; internal/handler/product_ingestion_composition.go and test; internal/container/container.go; internal/router/router.go and new routes_product_ingestion.go and test. Configuration is disabled unless an explicit exact scope, fixed Harness service endpoint/credential and capacities are supplied. The six browser routes retain existing auth, role and KB read/write guards; handler rechecks both RAW and WIKI. Root migration env also registers product_ingestion.artifact_tables for 0017. These are deployment prerequisites, not live acceptance evidence.

### Task3f system review service

Owner g3_incremental_code_review; root independent review and later REST/config integration. Exact new service files: system_policy_decision.go, system_policy_decision_test.go, wiki_release_automated.go, wiki_release_automated_test.go. Narrow existing edits: WikiReleaseService fields/options in wiki_release.go and common draft body in concept_free_wiki_830_g3.go; retain all existing human entry guards. New SystemPolicyDecisionReceiptV1 has its own domain/key verifier and binds exact principal, four-part scope, preparation/candidate/ready digest, outer policy identity/version/digest, covered capabilities, expected parent, nonce and times. Explicit current policy must be enabled, unexpired, exact scoped and ISOLATED_NOT_FOR_PRODUCTION; missing/drifted/revoked policy has zero publication writes. No fake human context. Inner preparation review policy identity is unchanged. System create/review/activate reuse canonical candidate, exact source and dual-KB ACL gates, repository Draft-to-Ready transition, PublishAuthorizationV0 and existing private activate/CAS. Ready replay requires exact same canonical system receipt digest and all bound identities. Provider/model extraction not in this slice. Existing human signing rings and routes remain unchanged. No new serving Head, activation protocol or legacy publisher. RED through bounded existing G3 fixture helpers and new system-signature/policy negatives precedes implementation; no live publication or keys configured by the lane.

### Task3g machine source REST

Owner g3_incremental_origin_review; root reviews and registers constructors/main router. New service/g3_platform_machine_access.go and test, handler/g3_platform_snapshots.go and test, router/routes_g3_platform_snapshots.go and test. Machine access binds the existing authenticated api_tenant Principal.StorageID plus actual TenantAPIKeyScope.KeyID, exact tenant/space/RAW/WIKI, current allowed KBs and existing sealed WikiReleaseService dual-KB ACL. Do not mint context principals or invent a human identity. Source/base services receive this authorizer and a separately configured signer. New REST routes beneath /knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/platform reuse the existing schemaWiki active guard chain including both evidence records and SealAccess. GET /uploads/:run_id/:ordinal resolves only that server metadata binding through FindByMetadataKey and exposes safe parse status/knowledge identity; POST /sources/:knowledge_id/attempts/:attempt/snapshot captures one exact immutable revision; GET /bases/:release_id/epochs/:epoch returns the exact signed base closure. No filesystem paths or credentials in responses. Bounded tests cover missing/wrong machine key/scope/ACL, lookup absence, parse not ready, and signature port custody. Existing human backfill/read routes unchanged.

### Task4 UI contract freeze

Owner g3_incremental_code_review (new implementation role, independent reviewer of routing only). Exact files: frontend/src/api/product-ingestion.ts; frontend/src/components/knowledge-base/product-ingestion-status.vue; frontend/src/views/knowledge/KnowledgeBase.vue; corresponding focused frontend tests. All routes below use /api/v1/knowledge-bases/:id/product-ingestions. GET /capabilities yields {success:true,data:{enabled}}; POST /uploads uses multipart repeated files fields and yields {success:true,data:{run_id,accepted_file_count,rejected_file_count}}; GET root yields {success:true,data:{runs}}; GET /:run_id yields {success:true,data:Run}; POST /:run_id/retry-fields {field_keys} yields a new Run. Run carries run_id/state/stage/stages/timestamps/counts/model_call_count/fields with safe field outcomes/reasons, optional published_url/reason. Stage carries name/state/started_at/finished_at/success_count/missing_count/failure_count. Capability absent/disabled preserves normal existing upload; enabled routes the entire selected original-file batch to server upload, never browser attach/seal. Run terminal set includes succeeded/partial_success/failed/needs_confirmation; preterminal created/uploading/processing/running/waiting_sources supported. Read status persists on server; client list restores after refresh. Only failure fields can be selected for new-attempt retry. No unvalidated values shown.

### Task3h bounded runtime progression

Owner g3_two_product_path_audit after read-only worker/progression review; root reviews and composes CLI. New product_ingestion/runtime.py and tests/test_runtime.py; narrow store.py/test_store.py additions for keyset-paginated run reconciliation and recent-first UI listing. Reuse P1 public outbox read/mark, lease reclaim, registry and prepare-run-finalization. Pump runs in the platform worker process, advances only product events for configured exact scopes, and periodically scans bounded pages with a rotating cursor so old terminal runs cannot starve newer work. Never hold a DB transaction while advancing jobs in another connection; at-least-once delivery is safe through existing deterministic enqueue. Exceptions are isolated per run and observable, not silently converted to success. Reconciler repairs committed stages without delivered events, interrupted fanout and terminal child failures. Finalizer is short and calls final_state before existing fenced prepare-finalization, with the original typed confirmation reason retained. Expose async run(lifecycle)/tick and register_finalizer; root owns CLI lifecycle wiring. No model/source/compiler/release implementation or live I/O in this lane.

Root Task3b stage integration additionally owns product_ingestion/stages.py, platform_client.py and focused tests. Each stage returns artifact writes plus the existing stage settlement in the same WorkerLoop completion. Upload reconciliation polls server-owned ordinal bindings once per attempt, attaches originals idempotently and seals only a complete group; deadline or explicit parse failure is terminal. Source stage consumes signed snapshots from current parse attempts and routing uses exact first-page ranges. Retry runs reuse prior sealed snapshots only after current source identity checks. REST uses fixed configured endpoint/key/scope, no redirect, bounded response/time, and no automatic mutation retries. No model, candidate or source values supplied by browser.

Task3i system REST owner g3_incremental_code_review after Task3f freeze; root independent review. New internal/handler/g3_platform_release.go and tests, internal/router/routes_g3_platform_release.go and tests. Exactly scoped POST platform/preparations accepts only preparation_id plus batch candidate raw bytes; POST platform/preparations/:preparation_id/review consumes canonical system receipt; POST platform/activate accepts decision and PublishAuthorizationV0 raw objects. Require existing authenticated api_tenant plus exact actual key scope via service policy, existing dual-KB ACL/seal and requestIdentity; browser/human cannot use system entry. Reuse Task3f ports, no new signing or compilation in handler. Bound request sizes, reject duplicate/unknown fields, preserve raw canonical signed receipt bytes. Use safe existing errors. No container/config/main-router ownership (root composes), no live publish.

### Task3j permanent configured model boundary

Owner g3_two_product_path_audit after Task3h freeze; root independent review. New product_ingestion/model_execution.py, model_settings.py and tests/test_model_execution.py; narrow worker.py/tests/test_worker.py optional transport-factory port only. The platform model policy is explicitly configured for the exact product scope, endpoint/model, roles, approved template identities, expiry and request/context/output/response capacities; no browser-controlled policy or old filesystem admission runner. Reuse existing PolicyReceipt/ModelPermitView as truthful serialized evidence of this new evaluator's actual decision, never fabricate old signed admission. Endpoint and credential come only from server settings. Each non-field call reserves its immutable operation, commits exact request before dispatch, checks current policy before dispatch, stores raw before projection and returns recorded raw on replay. An uncertain dispatched call terminates without resend. Actual endpoint request bytes and provider response usage are retained; safe errors omit URL/key/raw. No automatic HTTP or model retry. Field transport can be constructed for exact scope/run/job and must verify its stored model policy dependency before use; old injected transport tests remain supported. A bounded mock-HTTP test covers policy denied before request, token/output limits, identity drift, cross scope, one dispatch, recorded replay, interrupted call zero resend and usage. No provider calls, external endpoints or deployment from this lane.

### Task3k actual incremental compiler closure

Root owns Python knowledge_compiler/batch_concept_compile_830_g3.py and focused test_batch_platform_incremental.py, plus product_ingestion/compilation.py/tests. g3_incremental_origin_review is designated Go owner after source/client review and after exact optional binding DTO agreement: internal/types/concept_free_wiki_830_g3.go, focused new tests; narrow service/concept_free_wiki_830_g3.go current-base comparison (Task3f wrapper change frozen), focused new service tests. Independent review is exchanged across lanes; fixed Python/Go wire vector required. Optional published_base/refresh_fields must be omitted when absent so old fixtures/hashes remain unchanged. No fake historical classifier corpus/model receipts; complete current-parent closure verified by Go. RED covers new-product-only C with old parent carry, forged/missing/extra base identities, source closure drift, changed parent, failed-field-only replacement and unselected old-field mutation. No live calls or release writes during implementation.

Task3l Go deployment composition owner reassigned from root to g3_incremental_code_review after Task3i freeze. New config/g3_platform_processing.go/tests and service/g3_platform_snapshot_signer.go/tests, handler/g3_platform_composition.go/tests. Narrow root-owned existing config/config.go, container/container.go and router/router.go are handed to this sole lane for Task3l; root will not edit them concurrently. Explicit disabled-by-default exact machine scope/key and current isolated system policy/public key configuration; snapshot private signer is independent and never logged/JSON-exposed. Preserve existing human/publish/golden/citation key configuration and validation. Reuse existing dependency constructors for signed source/base and release ports, register both new REST groups through existing guards. One factory extends WikiReleaseServiceOptions with current configured system provider/verifier; the Harness retains separate signing private keys for its own system decision and existing PublishAuthorizationV0. No policy or signer inferred from browser input. Missing required enabled configuration refuses startup; disabled configuration has no enabled machine routes. RED registration/config/key/signature-vector tests and bounded combined package checks before deployment. No actual keys, API-key creation, model calls or service deployment by the lane.

Root source/compiler adapter also owns product_ingestion/source_geometry.py/tests. Promote the previous pure native geometry projection into the platform package without any hardcoded tenant/path or source rebuilding. Consume the verified signed source snapshot, check native markdown/parser/page hashes and actual geometry, and reuse existing G3 native-reference classifier projector. First-page evidence is selected from real page ranges; no synthetic boxes or invented dimensions. Native geometry and all original chunks remain in the signed source artifact even when a span is ineligible for identity evidence.

### Task3m permanent Harness runtime composition

Owner g3_two_product_path_audit; root implements the concrete pipeline stage factory and independently reviews this slice. New product_ingestion/configuration.py, composition.py and focused tests; narrow product-ingestion composition changes only in service_shell/config.py and cli.py. Enabled configuration binds exact ProductScope values to a WeKnora base URL and machine key, source public-key ring, permanent model settings, isolated automation signer policy and distinct opaque private-key material. The trusted catalog, profile confirmation and resolution policy are loaded only from configured path/hash/size triples and supplied as exact bytes to the future pipeline factory. ProductPipelineFactory must return real handlers for identity, field_plan, extract aggregate, synthesis, compilation, review, publish and verify, plus the sealed window-plan reader and code-owned field prompt. Composition itself registers upload/source/routing, field windows and the root finalizer and refuses startup unless all eleven product stages plus window and root handlers are present. The composed runtime runs WorkerLoop and ProductRuntimePump against the same Harness database and lifecycle, exposes pump issues, closes platform clients on exit and never registers placeholder-success handlers. Product ingestion remains disabled by default; enabled startup without the future product_ingestion.pipeline factory fails closed. No provider calls, real database, deployment or signing occur in this lane.

Root Task3n owns product_ingestion/identity.py, pipeline.py and focused tests. Build current-run corpus from verified platform snapshots using knowledge IDs as stable material IDs, truthful platform upload provenance, and immutable source bytes. Identity prompts use first-page evidence and bounded identity-bearing source blocks from only current materials. Published entity metadata remains local except plausible identity matches; no historical source/model raw replay. Current configured Gemini executor supplies actual model receipts, and the existing semantic-reference projector and resolver validate identity, version, role and taxonomy. Platform title routing is explicit input, never an unrecorded Codex decision. Invalid or conflicting identity terminates with needs_confirmation and retains raw. Ordinary field extraction remains separate bounded tasks with reusable results; compilation and activation run only as durable platform stages.

Task3k Python adapter ownership is handed from root to g3_incremental_origin_review after the four pure keyword-only interfaces were frozen. This owner may add only product_ingestion/compilation.py and its focused test_compilation.py. `build_existing_snapshot` consumes the already verified signed-base body and binds `head_receipt_sha256` to that real signed snapshot digest. `build_platform_compile_request` derives that existing snapshot internally, accepts only sorted current resolution refs and explicit refresh rows, and delegates the semantic closure to the existing batch compiler. `project_field_attempts` revalidates persisted field outcomes and maps ordinary missing/failed outcomes to explicit unknown fields without creating model raw. `assemble_platform_candidate` records only a RULE structural/evidence decision and rule-derived synthesis; it never claims a model or human review. Root retains pipeline/identity orchestration and final REST calls.

Root Task3o owns product_ingestion/signing.py and focused tests, plus release REST methods in platform_client.py. Reuse the frozen Go system-decision domain and existing PublishAuthorizationV0 byte protocol with server-only exact automation configuration. Sign only exact scoped Draft metadata; bind candidate/manifest/ready/parent and immutable preparation time. Deterministic nonce and expiry permit exact-byte replay after process failure. No human identity is minted. Current policy is rechecked by Go before each write. Unit keys and protocol fixtures only before deployment; no real candidate, approval or activation is executed by test helpers.

### Task3q fixture-only platform runtime acceptance

Owner g3_two_product_path_audit; root retains all production pipeline files and independently reviews the test. New file harness/tests/product_ingestion/test_pipeline_runtime.py only, plus fixture-local helpers in that test when needed. Exercise the real SQLite stores, P1 WorkerLoop, ProductRuntimePump, progression graph and production pipeline handlers from three platform-returned source snapshots through identity and field model calls, incremental compilation, system review, activation and serving verification. Only injected HTTP fixture transports may answer Gemini and WeKnora requests; do not stub every stage as success or call a live provider/service. Cover one validated unknown and one invalid field as an ordinary partial result, durable recorded replay with zero redispatch after worker reconstruction, failed-field retry selecting only the requested target while reusing source/identity, and a typed identity conflict ending needs_confirmation. The published base fixture is the existing valid five-product candidate projected to the signed base contract without historical model raw. No production edits, deployment, real database, provider call or release write belong to this lane.

### Task3s truthful extraction progress (root)
Root owns a read-only status projection in store.py/api.py, test_api.py and stage label display in product-ingestion-status.vue. The projection merges durable field-window job times and settlements for display only; orchestration continues reading original aggregate stages. No schema migration, synthetic business completion, raw response exposure, or provider call. RED must observe an active field window before the aggregate job exists and preserve its actual start through aggregate completion. Terminal window failures must never remain displayed running.

### Task3u atomic admission correction (root)
Review found P1 enqueue could commit before its product domain row. Extend the existing JobStore enqueue with optional pure-data domain writes and a validated explicit job ID; execute with the same transaction and existing protected-table checks, never expose a Session/callback. Product stage/window admission uses deterministic IDs and atomic inserts. Root binding is committed before publishing its deterministic job, so crash recovery can re-admit but cannot claim an unbound root. Exact domain identity conflicts must reject without orphan jobs. Owner: jobs/store.py, product_ingestion/store.py, bounded job/admission tests. Existing enqueue consumers retain defaults and behavior. RED covers crash immediately after enqueue commit for stage/window/root.

### Task5a permanent deployment composition (root)
Root owns deploy/product-ingestion/{Dockerfile,compose.yaml,README.md,requirements.lock}. Use an exact existing Linux Python base and export locked runtime dependencies; API, worker and one-shot migration share one image. Mount trusted configuration read-only, keep credentials in private env/config files outside source, use restart supervision and persistent dedicated Harness DB (reuse PostgreSQL server, no shared WeKnora business tables). Health checks and migration readiness are actual CLI contracts. Deployment is performed before, never during, the measured upload run. Legacy temporary provider guard is prohibited; restore the configured embedding model's real authorized endpoint before acceptance. Validation is compose rendering/build/health plus independent source review, not a live product PASS.

### Task3v durable RAW parse model-dispatch receipt
Owner g3_incremental_origin_review; root independently reviews and owns the Harness decoder/settlement and deployment changes. Add a strict provider-dispatch journal over the existing attempt-bound `knowledge_processing_spans`, without a second database table or an external guard. The journal is enabled only when a new parse begins in the configured G3 RAW tenant/KB scope and writes a durable enabled marker before any counted call, so a completed zero-call parse is distinguishable from a legacy attempt with no records. Existing parses and all other scopes retain their behavior.

The only counted boundaries are each real `http.Client.Do` in the Aliyun text/OpenAI-compatible embedding retry loop and the Gemini raw HTTP chat path. Each network attempt writes a versioned generation receipt with safe model/operation identity and request hash: reserved before dispatch, dispatching immediately before the send, and recorded or interrupted afterward. A required pre-dispatch write failure prevents the send; terminal accounting uses a bounded detached context and is propagated as an operation error. No prompt, chunk text, endpoint, credential or raw provider response is stored. Count actual attempts, including transport retries and the separate summary-chunk embedding; do not infer calls from chunks, vectors, `BatchIndex`, or logical `Chat` calls. A crash at the send boundary remains explicit as interrupted/uncertain and is never described as provider-confirmed.

The signed source snapshot gains a required processing receipt for journal-enabled attempts. It carries the exact knowledge/parse identity, availability (`AVAILABLE` or legacy `UNAVAILABLE` with a reason), the marker identity, sorted per-dispatch safe receipts and derived counts. `AVAILABLE` requires a completed current parse, exact generation-parent closure under the embedding stage or `postprocess.summary`, and no reserved/dispatching rows. Legacy absence is `UNAVAILABLE/LEGACY_NO_JOURNAL`, never zero and never repaired with model calls. The receipt is inside the existing snapshot hash and Ed25519 authority. Go owner files: new `internal/types/model_dispatch.go` and tests; new `internal/application/service/knowledge_model_dispatch.go` and tests; narrow changes/tests in `knowledge_process.go`, `models/embedding/openai.go`, `models/chat/remote_api.go`, `g3_platform_source_snapshot.go`, `handler/g3_platform_composition.go`, and `container/container.go`. RED covers a proved zero-call attempt, legacy unknown, every embedding retry, Gemini dispatch, DB failure before send, interruption, unsafe-data omission, parent/scope/attempt drift, pending-row rejection and deterministic signed receipt. No provider calls or deployment occur in tests.

Task3v Python consumer (root): new product_ingestion/processing_receipts.py and tests validate the signed attempt-bound processing receipt, exact dispatch accounting and truthful recorded phase times. Narrow platform.py invokes validation; stages.py persists a small PLATFORM_SOURCE processing summary alongside the original signed snapshots, preserving raw custody. API adds external material-processing counts to Harness semantic counts, distinguishing incomplete counts and reused historical processing. Missing legacy receipts remain explicitly unavailable, never zero. No external model calls or reconstructed receipts.

### Task5b offline private deployment configuration generator

Owner g3_two_product_path_audit; root independently reviews and supplies the real restricted machine credential through a private input file. New `deploy/product-ingestion/configure.py` and fixture-only `deploy/product-ingestion/tests/test_configure.py`. The offline tool accepts one closed, explicit deployment input containing the exact four-part scope, machine principal/key identity and secret, three distinct Ed25519 seeds, current Go YAML path, Harness bridge settings, permanent Gemini settings, policy lifetime and path/hash/size pins for the catalog, profile confirmation and resolution policy. It validates the input through the production Harness configuration models, derives only the corresponding public or full private Ed25519 encodings, independently reproduces Go `system-automation-policy.v1` canonical hashing, and writes a private Harness runtime JSON, env file, patched Go YAML copy and hash-only manifest. The Go patch preserves every unrelated value, adds the generated publish public key without removing existing authority keys, and binds product ingestion, frozen scope and G3 processing to the same exact scope and machine key. No network, database, material, candidate or release operation belongs in this tool. Tests use fixture secrets/files only and cover exact policy/hash/key agreement, trusted-file drift, wrong Gemini identity, machine/scope mismatch, authority collisions and preservation of unrelated Go configuration.

### Task5c exact artifact Docker context selection
Owner g3_incremental_code_review; root independently reviews and freezes the source commit. The running default Colima VM (Docker context `colima`) already contains the G3 services and warm caches; starting a second build VM would duplicate memory/disk pressure. Extend only the official artifact selector and exact-image smoke entry to explicitly accept `colima-g1-build` or `colima`, retaining the original default. Carry the selected context through every inspect/build/lookup/compose/cleanup call and record it in build/smoke receipts. Reject cross-context smoke before execution; legacy receipts without a context mean the historical `colima-g1-build` only. Do not change source cleanliness, artifact identity/hash, one-build budget, exact labels or reuse rules. Owner files are scripts/app_artifact.py, scripts/start_exact_image.py and their bounded fixture tests; tests must not start Docker or build real artifacts.

### Task5 reuse correction (takes precedence over earlier deployment expansion)
User correction: stop per-test environment provisioning and focus on the platform flow. Inventory confirms the existing G3 app/UI, PostgreSQL, Redis, DocReader and file volumes are running. The current new Harness logical DB (`weknora_g3_product_harness`, Alembic 0017) is inside the existing PostgreSQL server, and no new database container has been started. The prepared runtime image is reusable; product-api/product-worker have not been started. Reuse these prepared assets and current platform resources without extra VM/database/full-stack provisioning or per-product builds. Keep required product worker lifecycle shared and persistent. Owner-only key provisioning is a separate actual platform access constraint; do not change roles or bypass the 403. Actual independent browser acceptance is still NOT_STARTED.

### 2026-09-14 首次运行的调用计数闭合

已记录的12次embedding发送不能代表全部模型调用：标准OpenAI兼容Chat分支未接入已有dispatch journal。此问题在第二次独立测量前修复，不通过外部脚本估算补账。g3_service_inventory唯一写者：internal/models/chat/remote_api.go及对应测试；使用已有journal协议记录标准SDK实际发送、HTTP响应/错误和去图重试，保留当前provider行为与scope。RED先证明标准Chat缺记录，GREEN验证实际HTTP次数对应记录、journal失败不外发。root维护计划、独立review后统一构建部署。来源失败回执展示缺口单列遗留，不放宽成功source snapshot契约。

### 2026-09-14 Task 3y：首次解析文字与定位统一（第二次真实验收后的修复）

业务根因已经真实回执证明：普通PDF解析与后续native捕获产生不同文字，312/312原始块均UNRESOLVED；不得伪造定位或手工填写产品身份。目标是首次解析产生同一Markdown+Native坐标，持久化并由后续编译/证据消费，不重复读取PDF生成第二套正文。

唯一实现Owner g3_extraction_finish，写域 internal/application/service/knowledge.go、knowledge_process.go、concept_source_reuse_830_g3.go、g3_platform_source_snapshot.go、internal/container/container.go，以及对应测试和必要同域小型parse artifact store文件；root维护计划与交付证据，g3_docker_connection独立review。只在G3启用且精确Tenant/RawKB范围的PDF启用builtin/native_capture，不改其他知识库、DocReader镜像、模型或数据库。两服务共享独立文件store/codec，禁止互相依赖形成构造环。

首次ReadResult以sourceSHA+knowledgeID+parseAttempt+parser identity签封原子持久化于现有文件卷，后续封存manifest后绑定既有source-reuse缓存。分块必须取同一原文的精确Start:End，新增上下文只留ContextHeader；图片改写不得破坏原文字坐标。Capture消费匹配当前来源/修订的首次产物，不再次Read；缺少/损坏/错revision/旧格式产物明确不可用，不回退另一解析器、不修改既有记录。旧有非G3 source/citation兼容性保持。

RED：普通路径不同文字/CRLF/插入表头时实际无法定位；GREEN：精确G3范围首次read一次，后续capture与重启重用不增加read、逐块映射和首页路由可用；非G3不改变、来源/修订/签封篡改拒绝、写入失败不能标成功。先定向低并行测试和独立复核，再统一部署。

已封存旧材料不能覆盖重解析；恢复应保留旧原文及失败审计，由平台创建引用同一PDF的新解析身份后重启任务。此恢复接线另行冻结接口/写域，不能由Codex复制业务记录或运行临时接续脚本。

Task3y独立方案复核补充（实施前）：首次产物必须签封已验证的分块seq/原文codepoint Start/End/content hash，manifest封存后按ChunkIndex+Content绑定真实chunkID；重复正文和跨页不可用strings.Index猜第一次出现。Owner写域补充internal/application/service/concept_source_locator_830_g3.go及对应测试，并包含g3PlatformChunkPageMapping映射。新source快照与后续citation定位均消费同一已签封映射；旧记录不伪造位置。首次产物身份检查须先于legacy cache命中或采用独立版本键。parser/config override在refreshRevisionBinding之前生效，按revision.ParseAttempt绑定并在processChunks之前持久化，后续不得改坐标正文。增加重复段落、跨页、CRLF及缓存旁路的RED/GREEN。

### 2026-09-14 Task3z：正式清单绑定与来源阶段恢复

适用 G3-AUTO-3/4/6。第三次网页验收 d1dd4a86-a4ae-49f3-93e0-decbf56ca9d0 已失败终结；不得重写初次验收结论。三份材料已完成首次解析、向量与摘要，124 个正式 text 块的原文范围均正确。首次位置资产另含 11 个父块，而正式 revision manifest 只选 text 子块。g3_extraction_finish 唯一修改 g3_first_parse.go/tests：每个正式清单成员必须唯一匹配签封范围、正文和摘要；只输出正式成员，允许未被选入清单的父块资产，保留全部缓存哈希及范围校验。RED 必须模拟真实仓储的 text-only 清单，补丢块、重复及篡改反例。

来源阶段恢复使用平台正式入口 POST /:run_id/retry-processing，唯一请求字段 expected_version 为正整数。现有 RAW/WIKI 写权限及 Harness capability 不变。Run 响应增加 version、can_retry_processing。首切片仅对已封存且来源阶段失败、未进入身份/抽取的终态任务开放；解析失败、身份冲突、成功任务不冒充可恢复。平台复制既有材料引用，保留原任务失败，创建有明确版本化恢复计划的子任务，由已有队列执行。原任务版本和幂等键绑定；重复提交返回同一子任务，过期版本拒绝。不得把空 retry_field_keys 隐式解释成恢复；字段重试语义保持。

g3_service_inventory 唯一写域 harness/src/insurance_harness/product_ingestion/{api,store,stages,pipeline,discovery_stage,artifact_models}.py、必要同目录小型 recovery.py，以及对应 tests。复用现有表和 artifact/job 原子提交，不迁移、不建服务。恢复计划须区分字段重试；未执行的身份/抽取按正常流程执行，已有解析、摘要、向量不重复。统计必须区分历史复用调用与本次新增调用。root 唯一写域 Go product_ingestion bridge/handler/routes 及测试、frontend product-ingestion API/status 及测试、计划和交付记录。g3_docker_connection 只读独立复核冻结代码。完成测试后统一构建、部署现有 APP/Harness/UI；恢复仅在网页点击，由平台继续。首次失败与恢复结果分别计时；随后再用一款未处理产品三份原件进行完整独立验收。

RED/GREEN 覆盖严格请求、双库权限、跨作用域/版本拒绝、重复点击幂等、运行中及错误失败类型不可恢复、队列中断后可接续、原失败不变、已保存来源复用零新增解析模型调用、恢复不走字段专用身份分支。SOURCE_PARSE_FAILED 和旧坐标失效材料的新解析身份恢复仍列遗留，不能由本切片宣称解决。

Task3z 能力边界补充：API 的 can_retry_processing 依据持久化失败原因、封存及未执行身份/抽取记录，表示可发起来源校验；不声称同步确认解析成功。worker 在任何快照捕获前重新查询全部原材料，只有 completed 且身份绑定不变才继续。无需 API 注入新的同步平台调用；失败不触发自动重新解析。

### 2026-09-14 Task3aa：首页标题格式与识别阶段恢复

适用 G3-AUTO-1/3/4/6，承接既有授权，不新建环境。恢复任务 50687540-c345-581d-aa7c-6199d162b7bd 来源成功，124/124 块 EXACT_BLOCK，新增调用0/复用14；终态 FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE。真实根因是费率表标题《产品名》年交费率表不匹配整行标题规则；其它两份同名成功。原失败与待确认任务保持不变，不以此代替新产品独立验收。

唯一写域：g3_extraction_finish 修改 routing.py/test_routing.py，先真实三首页格式 RED，兼容成对书名号、常见 Markdown 标题及交费费率表后缀，证据保持原文偏移。保留身份冲突、正文/后页不补首页的边界。g3_service_inventory 修改 recovery/store/stages 及对应测试，仅扩展明确首页名称不可用且来源完整、未执行语义任务的终态恢复；身份版本冲突不自动消除。保持已有 V1 恢复计划字节/摘要兼容，必要时新增 V2 合同，不修改历史资产。恢复重新核对当前原材料绑定，复用有效 source_snapshot，只重跑必要识别阶段。root 修改前端恢复按钮允许后端明确授权的 needs_confirmation 并区分识别重试文案，Go API 不变；root 维护计划/证据/部署。g3_docker_connection 只读独立审核。

RED/GREEN 覆盖三份实际首页同时识别、原文证据校验、冲突拒绝、来源快照复用、无新增来源调用、原终态不变、V1兼容和恢复幂等。完成后仅部署必要 Harness/UI；APP/数据库/DocReader 复用。网页点击正式恢复，运行期间冻结不改代码；成功后再以未处理产品三份原件验收。普通字段缺失不补抽。失败如实记录具体阶段。

Task3aa 用户最新修订（2026-09-14）：不用完全匹配标题，使用 Gemini + Schema 候选判断。前述 regex 格式适配方案取消，尚无该实现写入。复用现有 identity 阶段一次持久化 Gemini 分类，不另添 routing 模型调用。routing 仅准备有真实首页定位的来源与候选，不再以整行标题规则阻断；identity 接收非权威可选提示、候选分类及材料原文，由既有响应证据校验与 resolver 决定产品/Schema/材料角色。取消与 regex 结果完全相等的门槛；保留单产品、全部材料归属、真实身份及版本冲突。成功后封存 material_source 与独立 resolved_routing 资产；field_plan 使用该结果，兼容旧成功任务的 routing 资产。已有原始模型响应/调用日志/原文证据持久化机制复用，零自动重试。

新增唯一写域 g3_extraction_finish：pipeline.py、identity.py、必要 routing.py 及对应 identity/pipeline/routing 测试；待 g3_service_inventory 完成 stages.py 来源恢复修改并明确移交后，才修改其中 routing 函数。不改现有 IDENTITY_PROMPT 字节和模型模板配置；既有提示已支持首页优先与候选分类。首页输入使用可回查定位，限制于当前产品材料，不发送历史全库正文。RED 包含《完整产品名》年交费率表无需regex命中即可到达且只执行一次模型分类、分类候选约束、证据校验、真实冲突终态、模型原响应复用、后续字段计划使用已解析模型身份。root 独立检查阶段接线，g3_docker_connection 审核最终冻结实现。其余恢复/API/UI 边界保持。

### 2026-09-14 Task3ab：同产品联合证据与已记录分类响应恢复

Task3aa 已部署（APP沿用0c22，UI7a1249，Harness0931e2）。网页恢复590980a5-803a-5d3f-bee9-d910a32187fd于10:15:45.987385Z开始，10:16:35.274146Z明确待确认。来源复用14次/新增0，Gemini实际1次，三份名称/终身寿险/材料角色均正确，JSON与offered引用校验PASS。原文及Head9未变。首个错误是identity refs冗余包含classification用途；内存诊断去除此冗余后，条款备案值引用了名称块，真正备案行已在同次offered输入中。进一步代码核验：v2仅完整合格条款向说明书关联，不能联合说明书公司、条款代码/备案及费率表名称；空值不能冒充真实冲突。本轮失败保持原样。

适用既有 G3-AUTO-1/2/3/4/6 与用户按产品组处理、缺失不阻断普通字段的明确授权。目标是平台自己完成可靠的三材料联合归并，并复用已保存分类响应。不会由Codex整理实际候选或执行业务接续脚本。

接口/写域冻结：
- g3_extraction_finish 唯一负责 Python semantic identity adapter（product_ingestion/identity.py或同目录小型identity_adapter.py）及 knowledge_compiler 中新增v3联合锚点分支、必要batch resolver/compiler/对应tests。分类/name/role均沿用已记录模型值；适配保留raw，删除多余的跨用途引用关系，不改原证据用途。缺少正确链接的已声明身份值只能在同材料、本次确实offered的原始定位中作规范化后精确包含验证，存在合格的原文定位时派生验证证据并记录修复原因；同值多处出现按稳定页码/原文位置选择，不把重复出现当冲突；找不到/存在不同取值冲突则不展示该值，不猜值、不复制其他文件的原文。不得把代码当备案号。
- 新 resolver 版本使用 batch-entity-resolution-compiler.830.g3.v3，v1/v2算法及输出保持。按各材料已验证的完整产品名称、版本与Schema形成唯一组；仅合并有效、互补的非空身份锚点，任何不同非空值/同名多版本/多目标仍明确拒绝。条款实际提供代码和备案，说明书实际提供公司时允许联合；rate-table可归入相同组。原MaterialProposal、原raw及各来源空值不改，统一锚点只进入派生decision；所有支持证据保持原material/revision/page/locator。不得引入伪聚合文件。
- g3_admission_finish 唯一负责 Go types 中对应v3重算及binding验证和固定向量测试。复用既有协议形状，保持旧v1/v2向量及历史Release验证不变；新分支必须与Python确定性一致。不得改11类Schema/Profile、权限、签名或Active Head协议。
- g3_service_inventory 唯一负责 product_ingestion recovery/store/artifacts/model_execution及必要models/artifact_models/tests；stages.py仅sources段。为已封存source、identity返回无效且恰有一个完整recorded分类响应、未进入fields的终态增加正式恢复模式，复用原source和原模型记录。原V1/V2恢复wire不变，新增显式V3计划绑定origin_call_id/raw/request/input/policy/source摘要。当前重建输入、模型配置、原来源或base变化时明确失效，不偷偷新发调用。已有原始响应、policy/execution receipt继续可追溯；模型复用统计和本次新增调用分开。不得伪造同run dispatch记录。原终态不可变，重复按钮幂等，仍用现有retry-processing API与server capability，无迁移、无新增服务。
- root 唯一负责 pipeline.py机械集成上述已冻结端口、必要API输出字段、计划/证据/部署。各owner不得并发编辑该文件；跨域接口先由root协调。g3_docker_connection在实现冻结后独立只读复核。

验收/STOP：先以真实响应派生的固定fixture RED，覆盖首个错误和后续全部门，不能只修一层就上传新产品。验证三来源互补成功、真实冲突拒绝、必要支持来源变化失效、全部值可回查原文件、Python/Go固定向量一致、旧v1/v2重算不变、记录分类响应复用0新分类调用、真正worker从网页恢复可继续到编译/发布。fixture不是实际验收；所有代码及必要APP/Harness镜像部署后冻结，从网页恢复，运行中不改代码或临时续接。普通字段不重复补抽。之后仍需全新产品三原件完整平台验收。用户未要求新环境，继续原18295/DB/队列/DocReader；UI若无改动直接复用7a1249。

Task3ab接口确认：适配入口为adapt_identity_response(raw, context)，输出semantic_raw与audit；原raw由既有call保存，audit以identity_adaptation关联原call。首页约束继续用于名称、分类、材料角色；公司辅助块若本已offered，也可验证同文件产品代码、版本/备案，不再额外要求这些锚点都在首页。不得增加模型输入或改现有提示字节；稳定位置顺序使用页号、原blocks顺序和locator顺序。已记录恢复入口为replay_stage_call，显式MODEL_REPLAY来源，先以真实job lease保存model_replay_receipt，之后适配失败也能统计复用；input/request/model policy/prompt/source/base漂移拒绝，不重新调用。API独立输出reused_model_call_count/reused_usage，本次usage不累加历史。root新增test_joint_identity_pipeline.py负责互补新产品全worker验证；g3_service_inventory负责自己文件内的已记录分类恢复全worker验证。

root必要API透传写域补充：internal/application/service/product_ingestion_bridge.go及_test.go。Go现有白名单DTO会丢弃新增复用统计，增加两个明确数字字段及HTTP往返RED/GREEN；不输出原响应或调用凭据。UI继续沿用已部署入口，不为本次统计重新构建。


### 2026-09-14 Task3ac：已发布结果空集合兼容

Task3ab已实际部署：APP297d4db镜像2a2c94b5、Harness297d4db镜像f894c242，UI7a1249复用。网页恢复任务7b652803-6b5e-59c9-b750-19a878e3b273于14:00:02.916129Z开始、14:00:48.454094Z失败。source/routing/identity均成功，复用已记录分类1次、新模型调用0。字段计划未生成，原因是Go发布投影的nil集合序列化为null，Python CompileRequest集合类型拒绝1662处。此终态不是模型分类失败，不是普通字段缺失；原失败与发布Head9保留。

沿用G3-AUTO-2/3/6及用户增量复用授权。g3_extraction_finish唯一写product_ingestion/compilation.py、tests/test_compilation.py；root维护计划、证据和部署，独立review在冻结diff上进行。先使用真实已签名base的只读副本复现RED。原始base通过既有签名/成员校验后，仅在派生CompileRequest视图把definitions.aliases、fields的evidence/concept_ids/conditions/exceptions、pages的concept_ids/conditions/exceptions中显式null解释为空集合。复制处理，保留原始bytes/hash/原字段值/全部非空集合；不得全局递归替换null，不改value、unknown_reason等标量，不改旧Release、Catalog、Profile、签名或权限。

Validation需覆盖实际base+已保存identity一直到field windows、父实体和字段carry、原输入字节不变、非法非集合值仍拒绝、旧无null输入输出不变及Go既有typed canonical的nil/空集合语义。fixture不计真实业务验收。无需Go/UI代码或镜像重建，仅更新既有Harness并复用APP/UI。当前恢复任务保持失败终态；不使用临时脚本续接，不扩展新的恢复协议。部署后冻结版本，再从网页上传此前未处理的第四产品三份原材料，平台独立运行，记录各阶段与总耗时/模型调用/字段状态，普通字段不重复补抽。若还有失败，明确列平台遗留，不宣称G3完成。


Task3ac同轮真实输入验证补充：空集合兼容后已可生成75新字段/8个窗口，原502个definition/field/page成员与原page_members.payload完全一致，但所有原10字段窗口超过已配置300000 bytes（最大629253）；主要来自重复的来源依赖元数据。root新增唯一写域pipeline.py、test_pipeline.py，按实际render_window_request及既有_template_and_request的完整请求检查确定性细分过大的窗口，保留原单次最多10字段、任务/来源/缓存身份、原prompt与模型额度配置。已有小窗口保持原组，批次大小不硬编码新数字；严格复用现有上下文/完整请求字节上限。仅容量错误触发分拆，权限/模板/配置错误原样拒绝；单字段也超限则明确容量错误，不放宽配置或重复发送。RED覆盖多字段原请求超限、拆后每窗满足同一传输前置检查、字段集合恰好覆盖且无重复、缓存身份不变、完整请求信封较小限额、非容量错误不被吞掉。真实离线check需重跑拆分后的全部窗口检查，0模型/0业务写。两个独立写域冻结后统一review与仅Harness部署；当前测试任务已终态，下一次网页新产品运行期间不改代码。
