# G2 验收合同

## ADDED Requirements

冻结实现判定：`concept_id`从Space、canonical_key、sense_key确定性派生，别名不改变该id；
相同名不同sense保持独立。definition hash只含稳定身份、定义正文、来源和定义修订元数据，
不包含实体集合/Release id/聚合计数。成员hash覆盖结构化payload及确定性Content。
CandidateBundle包含严格版本PageManifest（有序member集合及digest），拒绝/待处理/重复等处置
保留在manifest的audit集合而非正式Members；new/update/sense通过领域审核才进入拟发布成员。
60–79在独立审核中保持NEEDS_HUMAN；未决项不进入成员，人类决议必须随整个candidate hash一起
被既有whole-batch ReviewDecision绑定，不能通过逐项临时开关激活。首实现可保持全部此类项pending。
聚合纳入同版真实FieldAssertion的present/absent_explicitly/unknown三态并显式标记；unknown无值无证据，
不得作为肯定/否定的业务结论，也不得省略其独立页。概念链接是导航关系，不能冒充证据支持。

### 2026-09-06 人工准入分支补齐（G2-R1/R3/R6）

用户在确认66分属于60–79人工区间、G2先验真实流程而Q0再验质量后，明确“继续推进g2”。
保留原80/60边界及所有模型raw输出；不重新抽样拿高分，不把继续开发冒充整包候选已获人工批准。

新增 `concept-candidate-bundle.830.g2.v2`，仅承载需要具名人工整包决定的拟议候选，v1字节及>=80行为不变。
v2新增严格 `admission` 对象：contract=`concept-admission.830.g2.v1`、status=`NEEDS_HUMAN`、
`pending_page_ids`为所有新建/更新页中60–79分身份的排序集合；该对象必须由request/output/review确定性复算，
进入candidate hash。原始review的PASS+66仍原样保存；此处NEEDS_HUMAN是准入处置，不伪造模型输出。
v2允许原始review PASS或NEEDS_HUMAN，拒绝REJECT；新页必须有完整评分且均>=60，Evidence/身份/字段完整性
与raw真实性硬门不变。未达60或缺分者保持拒绝，不通过拟议成员绕过。

Draft的PageManifest/Members只冻结待审的拟议内容，不是正式Release成员；在具名人对同一完整candidate hash、
policy hash与独立review raw hash签署whole-batch ReviewDecision之前，不能Ready、不能Active、不能在线检索。
不增加逐页批准开关、不新增审核权威或表。旧whole-batch签名/ACL/CAS机制在v2上必须同样执行，
review/activate/fixed read/source verifier均显式识别v2，不能落入绕过来源检查的默认分支。

#### Scenario: 66分走人工整包待审
- **GIVEN** 真实compile/review完整且新概念66分，review raw为PASS，所有来源硬门通过
- **WHEN** 确定性装配v2并创建Draft
- **THEN** 保留原66及raw/hash，admission为NEEDS_HUMAN，pending集合包含该概念，Draft可审而不可激活
- **AND** 未签名/错误candidate hash/错误scope/过期人类决定均拒绝；正确whole-batch决定与既有publish授权才能激活

#### Scenario: 不以人工流程消除硬门
- **WHEN** 输入低于60、缺失评分、原审核REJECT、来源或raw被篡改
- **THEN** v2装配或平台校验拒绝；v1仍拒66，旧合格v1继续可读，模型raw省略默认contract也必须拒绝

### Requirement: G2-R1 可替换编译与独立审核

系统 SHALL 接受版本化CompileRequest（原始材料/定位索引、Schema/Profile、已有知识快照、策略、预算、exact identity），输出CandidateBundle（完整字段attempt/state、Claim/Evidence、开放知识、关系/义项、缺口与编译identity）。
编译器与审核器 SHALL 为分别可注入替换的领域接口；模板/规则和LLM初始实现必须可运行。
审核上下文包含候选、原始来源、Schema、作用域/时间及策略，SHALL有独立execution id、输入hash及原始输出，不消费生成者自评分/推理。
平台 SHALL 校验版本/引用/权限/完整性；不得把字符串命中等同领域语义正确。

#### Scenario: 实现替换与真实出口

- **WHEN** 分别替换compiler或reviewer并回放同一冻结请求
- **THEN** 平台UI/Review/Release代码不变；三态和完整attempt集合仍通过同一合同
- **AND** 至少初始实现由真实材料经过独立审核、隔离发布产生可打开页面；fixture只证明协议

### Requirement: G2-R2 稳定定义与同版聚合

ConceptDefinition SHALL 有Space内稳定id、canonical key、sense、definition正文、来源及独立content hash；已有Schema/专家定义优先复用。
实体FieldAssertion SHALL 保持自己的主体、状态、值/条件/版本/时间和Evidence，仅链接concept id/sense。
动态聚合 SHALL 在一次WeKnora pinned read上从该Release成员查询引用关系，返回该release/epoch及被聚合assertion身份，不持久化为可编辑定义。

#### Scenario: 实体集合改变

- **WHEN** 两个真实FieldAssertion链接同一定义，隔离Active实体集合变化
- **THEN** 定义正文hash不变，聚合集合/hash改变；每个聚合项保留自身实体及来源
- **AND** 同名不同义项不误合并、实体条件不提升为通用定义、跨Space引用失败关闭

### Requirement: G2-R3 开放知识处置与价值硬门

准入 SHALL 先分析用途/材料，复用已有页并保守消歧，判断new_page/update/sense/field_rule/alias_link/pending/reject/mention/duplicate等明确处置。
Evidence和身份为不可抵消的硬门；独立页评分固定25/20/20/15/10/10，>=80入Candidate、60–79人工决定、<60 mention-only。
Schema required字段 SHALL 完整尝试并生成独立页，不受评分淘汰；unknown不等于无，不允许伪造值。

#### Scenario: 固定24项准入回放

- **WHEN** 执行运行前冻结digest和预期处置的24项Seed Cases
- **THEN** 24/24 attempted，覆盖晋级、更新、义项、字段补充、别名/提及、重复、广告、OCR、无证据及60/80边界
- **AND** 无来源/无身份/重复/拒绝不得晋级；短重要规则不按字数/页数淘汰

### Requirement: G2-R4 原文优先与来源精确定位

编译 SHALL 记录EXTRACT/NORMALIZE/COMPRESS/SYNTHESIZE方式，quote逐字保留原文，value允许语义等价。
数值、否定、条件、例外、主体、版本、时间 SHALL 保留；重编读取原材料而非旧摘要。
文档与专家修订记录来源 SHALL 类型明确，复用WeKnora SourceRevision/ACL/source viewer；失败typed，无current或第1页fallback。

#### Scenario: 引文漂移与信息丢失

- **WHEN** 引文、revision、locator/hash漂移或编译删除否定/条件/例外
- **THEN** 机械来源漂移拒绝；信息保留反例由独立审核拒绝/需人工，不由生成者自评通过
- **AND** 实际晋级项locator/quote精确回验100%，语义质量仍为Q0 DEFERRED

### Requirement: G2-R5 唯一Candidate与发布链

G2 SHALL 使用新版本严格manifest和独立candidate digest，包含完整领域输出/原始审核记录identity；不放宽G1 exact-key合同、不复制旧G1审核资格。
WeKnora SHALL 从验证后的结构化bundle派生同一preparation成员，沿既有ReviewDecision/Release/CAS发布；Content为可重建呈现。
Candidate/拒绝项 SHALL 不进入Active导航或默认检索；缺依赖、孤立页/断链和来源不完整在发布前lint失败。

#### Scenario: 发布前后边界

- **WHEN** G2新候选到达Draft、完成独立审核并经隔离发布
- **THEN** 激活前正式读取保持旧Release；激活后只读一份完整新Release；并发/旧Head不能覆盖其它成员
- **AND** 拒绝项保持候选审计记录但不成为正式成员，生产8081及其Active不变

### Requirement: G2-R6 Wiki、Search、Agent与来源同版

系统 SHALL 在既有平台路由增加concept/free_wiki详情，从FieldAssertion链接定义，开放知识留在实体free_wiki分组。
搜索 SHALL 覆盖定义/free_wiki正文；Agent消费相同release/epoch和作用域来源，不读Harness候选或RAW作为正式答案。

#### Scenario: 正文检索及来源点击

- **WHEN** 以只出现在正文的真实问题检索或通过Agent读取晋级页
- **THEN** 命中该Release内容并保留实体条件，source click重开同版准确来源
- **AND** 未发布/拒绝候选在默认导航和检索中零出现


冻结G2页面接线（R2/R6）：在既有scope/ACL下新增GET `/concept-pages/:member_id`，
无query时解析一次Active Head；`release_id`显式固定旧版，不接受current/latest占位或失败回退。
返回`concept-page-read.830.g2.v1`，含read_mode/release_id/activation_epoch/candidate_hash、
space_id/raw_kb_id/wiki_kb_id、一个PageMember、同版related_members、citations、
definition_hash/aggregate_hash（不适用空字符串）。PageMember仍为已冻结vector结构。
related_members只来自同一固定Release；概念页返回引用字段；entity_overview/free_wiki
返回payload.member_ids指定的完整成员集合且owner与当前实体一致；field_assertion/free_wiki_item
返回payload.concept_ids指定的完整概念集合。返回集合不得丢失、重复或增加这些导航目标。
来源入口GET `/concept-pages/:member_id/citations/:citation_id/preview?release_id=...`，
返回既有citation authority，PDF内容继续走现有opaque-token source viewer。citation条目仅
citation_id/page_number/quote，服务端从固定成员Evidence派生，禁止浏览器拼来源身份。
前端路由`knowledge-bases/:kbId/schema-wiki/concept-pages/:memberId`，导航固定读取所得release_id。
总控独占本次API/Vue新增文件和测试，Go lane独占两个types文件；共同消费vector d3654617...，
集成顺序为types→service/handler→UI；共同截止仍原M1物理演示截止，不另开Goal。

冻结R6 Agent接线（2026-09-06，用户已授权合理必要扩展）：managed Wiki KB的Agent turn
首次创建工具时解析并持有唯一WeKnora Release pin；同turn的search/read/多query共同消费该pin，
返回release_id/activation_epoch/member identity和来源身份。managed检测或pin验证失败必须失败关闭，
不得调用mutable wiki_pages、RAW或Harness candidate作为其正式内容。普通unmanaged路径维持既有行为。
并行写Owner g2_bundle_review转实施lane：新增internal/agent/tools/wiki_release_830_g2.go及tests，
internal/application/service/agent_service.go、新增service/concept_agent_830_g2.go及tests、
internal/container/container.go的最小依赖接线；如需接口仅新增interfaces/concept_agent_830_g2.go。
不改平台lane独占的11文件；必要跨界先给总控具体理由。RED为Head切换后同turn仍同epoch、
错误下mutable/RAW调用0、正文独有查询命中、未发布/拒绝成员不出现。先定向RED后实现和独立复核。

R4来源必要修复（2026-09-06）：真实隔离backfill HTTP409，日志证实现有全局FileService
将storage://backend/local://path误读为普通本地路径。总控独占knowledge_revision_source.go及其
tests，注入已有StorageBackendResolver/TenantRepository，按已验证Resource的tenant/backend/provider
解析读取服务；普通backfill、exact3与fixed read均保持原source hash/size/locator校验。
缺少指定backend或tenant漂移必须失败关闭，不读取默认backend或修改Resource定位。
RED采用真实BackendScopedFileService包装的本地文件，重现已有字节却读不到的路径错误。

R5集成补充：来源 verifier 未接入或核验失败时，Review 与 Activate 必须在变更前拒绝。
总控追加 internal/handler/wiki_release.go 最小错误映射，沿现有 handler 错误响应返回 HTTP503，
code=CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE；不得把受控不可用映射成无区分500。
定向测试复用 concept_free_wiki_830_g2_test.go，分别覆盖 schema review 与 release activation 错误路径。

R4受托原文桥实施切片（2026-09-06，用户持续授权）：新增来源不复用旧C5的17条坐标，
也不把离线pdfplumber自hash作为线上权威。仅复用既有docreader builtin pypdfium与固定
SourceRevision字节，进行服务端只读页内位置重放；历史WeKnora parse attempt/chunk manifest
与本次locator producer身份分别校验，不回写历史revision。源引用的BLOCK_ID必须精确指向
durable chunk，quote在该chunk内按code point逐字回验，再在所声明native页内唯一定位；
重叠chunk不得凭quote猜身份。无法唯一定位、扫描页、parser/parse/file drift均typed拒绝。

第一并发Owner g2_bundle_review独占隔离worktree830-g2-native-source-producer：
docreader/parser/pdf_parser.py及其focused tests、internal/infrastructure/docparser/grpc_parser.go
及其focused tests。通过已存在parser overrides明确请求只读native capture；无新proto字段，
通过既有metadata传递NativeStructureArtifact，SanitizedJSON仍不含正文。正文保留在既有
ReadResult.MarkdownContent，sidecar可用页/字符范围和hash绑定正文及bbox。默认导入行为保持。
实现前把最小wire schema/override入口交总控冻结；额外生产文件先报具体必要性。

第二并发Owner g2_sources独占隔离worktree830-g2-native-source-bridge的后端12文件：
service/concept_source_authority_830_g2.go及测试（新增），service/wiki_release.go、
service/concept_free_wiki_830_g2.go、service/schema_wiki.go及各自测试，
handler/concept_free_wiki_830_g2.go及测试，container/container.go及
schema_wiki_production_readiness_test.go（路径均在internal下对应目录）。
来源桥依赖KnowledgeRevisionSourceService、knowledge/chunk repositories与DocumentReader，
不依赖SchemaWikiService而引入循环。Review/Activate的双KB ACL必须先于原文IO；
逐字引文匹配所声明页，不要求旧parser的完整Markdown chunk与新native正文格式相同。

G2采用独立封闭concept-source-content-token.830.g2.v1，复用既有citation读签名环，
不得伪造旧G1 authority要求的parsed_document或coordinate receipt。token绑定固定
scope/release/epoch/candidate/member/citation/source/页/bbox/quote及TTL；读取时重新绑定
同版成员并执行ACL，再读取固定PDF。沿现有citation-content路由按独立contract分派，
不改变旧Schema token的验证域。总控负责独立G2原文viewer，复用pdfJsPort，避免放宽旧解析器。

不在构建工作树内改正在构建的源码。
此切片不上传B，不调用embedding/compiler，不新表或部署服务；发布继续默认拒绝直到
真实revision/bytes/native capture/ACL均有服务端回验。


R4/R5真实输入必要纠偏（2026-09-06，用户持续预批合理扩展）：真实A的SourceBlock包含LF，
G2此前复用旧Schema canonical会在request hash阶段拒绝。仅G2增加兼容canonical：
文本value允许LF/CR/TAB并以JSON转义保留原字节及Unicode offset；对象key与identity保持严格，
其他C0/DEL、non-NFC、float及不合法Unicode仍拒绝。无这些新增合法文本的既有G2 vector
及旧G1/Schema hash必须完全不变，禁止改写durable原文以绕过限制。
Owner g2_sources独占concept_free_wiki_830_g2.py及对应Python test、
internal/types/concept_free_wiki_830_g2.go及对应Go test，以及新增
harness/tests/fixtures/concept_free_wiki_830_g2_canonical_vector.json。
RED绑定真实A source/request hashing与LF/CRLF/TAB/non-BMP跨语言vector，另有非法文本负例；
总控集成、g2_bundle_review独立复核。此修复不改变旧canonical、不扩大provider调用。
应用第二次构建因专用builder数据盘20GB已满而在编译前失败；保留失败回执，按用户持续授权
增加一次恢复构建额度（累计上限3），builder数据盘有界扩到40GB，不清理任何旧镜像或volume。
