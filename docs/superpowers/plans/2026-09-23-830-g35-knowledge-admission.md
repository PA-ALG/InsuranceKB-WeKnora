# 830-G3.5 自由发现与知识准入实施计划

## 当前状态：原生逐窗执行软件完成（2026-09-23）

内容来源与展示已提交d04868fdd。原生逐窗collector冻结tree0b2352e49d5df56df37240684cf4ee3cd39aa013，最终独审0 BLOCKER。完整签名窗口、先存provider raw后投影、精确父响应复验、未知发送阻断及兄弟失败保留已实现；模型计划预算覆盖真实JSON包装和provider envelope。固定原生批次超预算明确失败，不截断。

首轮47PASS（collector4及既有stage/replay/native），预算反例2RED后受影响collector6PASS，Ruff/mypy PASS。验证见native-discovery-stage-validation.json。CURRENT=NATIVE_WINDOW_COLLECTOR_SOFTWARE_GREEN；NEXT_READY=来源审核v5、原生语义准入/更新、显式runtime策略与旧原生写页互斥。尚未接pipeline持久消费/metrics或执行真实provider；本轮新增模型/构建/部署/发布均0，BUSINESS=NOT RUN。下方历史状态不覆盖本段。

## 当前状态：内容来源与页面展示软件完成（2026-09-23）

原生producer已提交5043c7b55；内容来源domain/编译/Go验收/页面展示冻结tree 18814ec469c14a3f9e973f656d4bf2bfc3421509，后端独审及UI定向复审均0 BLOCKER。新对象逐片段区分“模型生成”和“原文依据”，完整条件/例外/有效期也覆盖；纯生成可无引用，混合页仅有依据片段显示精确原文按钮。旧对象字节及旧展示保持。验证和文件身份见content-provenance-validation.json。

Python 107PASS/1个历史真实fixture缺失skip，Go类型/服务定向PASS，前端六文件109PASS；UI复审修复后两文件41PASS、全项目类型检查PASS。CURRENT=CONTENT_PROVENANCE_SOFTWARE_GREEN；NEXT_READY=原生逐窗StageCall执行、准入/更新及来源审核接线。当前未启用新运行策略；真实模型/应用构建/部署/发布新增均0，BUSINESS=NOT RUN，G3.5未完成。下方阶段性未实现说明属于历史记录，以本段为准。

## 2026-09-23 用户已选择原生候选交接

用户随后补充：原生Wiki实际补充生成的信息可以保留，必须增加“模型生成”标志；原文有证据的内容必须能点击查看原文。本要求覆盖此前将无原文证据的补充一律拒绝的表述。准入按内容片段记录来源支持与模型生成，混合页面分别展示。原生chunk引用仅是定位线索，不能使整段/整页补充变成原文事实；证据仍绑定真实材料版本和精确引文。模型生成内容不得伪造原文引用，也不能借此填充需要原文确认的产品保障/数值/条件字段。使用现有Candidate/审核/Active/页面载体扩展来源表达，无第二发布权威。

原生PreviousSlugs固定为空，不从native wiki_pages读取旧身份，不调用extractCandidateSlugs内部的原生存量页去重模型。正式已有知识比较在Harness唯一准入边界完成。持久性承诺为“已提交StageCall原始响应可恢复；发送结果未知时不盲重发”，不把收到响应但尚未落库的崩溃窗口宣称为零丢失。

用户明确答复“先按推荐的执行吧”：原生负责发现候选，Harness负责准入、审核、唯一发布。此前NEXT_READY中的选择阻断已解除；不再重复要求架构批准。沿用本Goal授权及外部动作限制。

实现采用原生两段候选能力（WikiCandidateSlugPrompt、WikiChunkCitationPrompt及chunk handles），不调用写页、归并已有原生页或发布入口。版本化REST提供签名计划及签名候选快照。Harness继续使用已有StageCall保存原始响应、请求/模型身份和未知发送状态，执行原生计划后交回原生解释和引用关联；不另建模型队列或第二调用日志。原生签名证明来源/计划/候选投影绑定，不证明模型内容真实或已获审核。候选快照作为既有artifact持久保存，语义准入只裁决这些候选，不再执行第二次自由发现。

原生候选计划绑定scope、完整来源快照hash、窗口内chunk身份与顺序、提示词/策略和前一段原始响应hash。窗口由原生既有引用batch划分，所有非空来源chunk覆盖且不截断；超预算明确失败。引用阶段每个窗口的成功响应分别持久保存，兄弟失败不抹除成功调用；空结果与缺失/失败不同。快照保留无引用候选为未支持提案，禁止将Description/Details当作原文依据。未知chunk、重复slug、类型/slug不一致和来源版本变化均拒绝，禁止静默降级。Harness仍负责事实级引文验证、Schema/已有知识比较和最终整批审核。

先交付候选producer/REST/跨语言验证，再接入持久stage和显式产品策略，最后贯穿新增/更新准入。显式候选策略启用时阻止该产品RAW路径的原生自动写页，其他知识库旧行为保持；旧请求/旧发现协议保持可回放。代码默认不改变运行中配置。

本切片root独占写域：新增internal/application/service/g3_native_discovery.go及测试、internal/handler/g3_platform_native_discovery.go及测试；既有g3_platform_snapshots/composition、routes_g3_platform_snapshots；Harness新增native_discovery.py及测试和必要platform/client接缝。后续stage/config/准入producer接线在下一RED前明确扩展此写域。先RED→实现→有界验证→冻结独审。当前BUSINESS=NOT RUN。

跨语言签名接线的必要扩展写域：既有g3_platform_snapshot_signer.go及测试、新增testdata/g3_native_discovery_v1.json合成向量、platform_client测试。发现计划与候选快照使用不同签名domain；真实Ed25519签名器（非stub）回放同一向量，Python验证scope/request/source/窗口/raw/引用绑定。当前纯producer子项已实现，尚无runtime策略启用、StageCall调用或最终页面展示；模型生成标签目前只进入候选DTO，不能据此声称用户新增展示要求完成。

### G35-R3 内容来源片段子项（用户新增要求的后续实现）

现有ConceptDefinition/FreeWikiPage要求至少一条页面级evidence，前端分别展示正文和全页引用；MODEL_COMPILE表示编译来源，不能区分模型补充与原文支持。新增可省略content_provenance扩展，contract=knowledge-content-provenance.830.v1；segments按顺序覆盖完整展示内容，每段含text、origin（SOURCE_SUPPORTED或MODEL_GENERATED）和指向同对象evidence的evidence_indexes。片段拼接必须逐字等于统一renderer结果：定义为body；自由页为body及原顺序追加的\n条件：…、\n例外：…、可选\n有效期：…；有依据片段必须有合法索引，无依据模型生成片段不伪造引用；索引在各段内不重复，所有顶层evidence须被片段消费。保留不同段引用同一真实证据的能力。

省略扩展维持旧合同/字节/证据必需；显式新合同允许纯模型生成补充无evidence，仍走独立语义审核/评分及唯一发布。Schema/专家定义保护和字段必须原文证据规则不变。生成来源及索引纳入内容hash/最终审核，不由页面有任意引用推断整个正文来源。展示逐段标“模型生成”或“原文依据”；点击索引必须按完整Evidence身份精确映射现有citation_id，不能按quote猜原件。conditions/exceptions/valid_time等有语义的页面附加内容也须有清晰来源展示，不能绕过片段标注。为本次必要目标扩展现有合同，不新增内容发布平台。

后续root写域：G2 Python/Go domain合同及必要compile/页面投影/严格wire边界，前端conceptFreeWiki830G2/batchConcept830G3适配及ConceptFreeWiki830G2.vue，必要共用片段helper与定向tests/跨语言向量、当前计划/OpenSpec129/evidence。先旧对象拒绝新标记/空证据的RED与缺失页面标记RED，再贯穿实现；未完成前不得启用新运行策略。

**Goal / Mission**：真实已解析材料中的有效Schema外知识经过既有Candidate、审核与唯一Active，在网页可读、可检索、可回原文。唯一Owner及Integration Owner=root；reviewer只读冻结身份。用户2026-09-23启动消息已授权有界设计、实现和验收；不重复索要普通实现批准。预计一条依赖G3的产品PR；首切片时间盒1工作日，至2026-09-24 18:00+08。独审按项目默认gpt-5.6-sol/high。

**Architecture**：WeKnora保管原件、解析与版本化来源；Harness集中承担发现准入及可替换语义策略。既有任务模块负责恢复/调用记账，审核和发布保持既有唯一边界。同语义输入只运行一套必要发现，不先完整原生Wiki再重复发现。技术栈沿Go/Python3.12/PostgreSQL/Vue，不增服务/数据库。

## 实际基线与当前状态

- 产品工作树`.worktrees/830-g35-knowledge-admission`，分支`codex/830-g35-knowledge-admission`，base=`8f7201dd428033de1e66f8783c125ebf2b617d53`。
- 2026-09-23重新核实[产品PR130](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/130)：OPEN/Draft、未合并、HEAD等于base，deterministic/integration-postgres/wheel-smoke均SUCCESS。明确依赖PR130，不使用停留G2的本地main，不合并G3。
- 历史部署源码`ec0721083`，当前只读docker ps确认app image`54cadb3d3237`、Harness`646234d2d0ef`、UI`d488e95945f5`仍存在；完整digest引用G3部署回执。源码、制品与部署身份分别记账。
- G3 FLOW PASS、QUALITY=DEFERRED_TO_Q0、NOT_FOR_PRODUCTION；真实发现EMPTY只证明阶段执行。
- CURRENT=EXPLICIT_UPDATE_SOFTWARE_GREEN；SPEC=共用输入及显式增量准入冻结、CODE=语义视图已提交/增量切片GREEN且独审0 BLOCKER、BUSINESS=NOT RUN；D1、DOCKER_ACTION=SKIP。当前RED：真实非空准入未证明，更新仅审计，服务实体/正式关系未接本路径。

## 复用 / 适配 / 缺失

路径均为产品仓库相对路径；Python简称省略`harness/src/insurance_harness/`。

| 处置 | 当前入口 | 已核实事实及责任 |
|---|---|---|
| KEEP | product_ingestion/stages.py、platform.py、platform_client.py、source_geometry.py | 原件、签名解析快照、SourceBlock/Evidence与定位复用；REST边界不变 |
| KEEP | discovery.py v4、discovery_stage.py、discovery_replay_metrics.py | 全原文窗口及46d541d81真实依赖缓存/父响应重投影复用，不重做缓存 |
| REWIRE | internal/application/service/wiki_ingest_batch.go、wiki_ingest_cite.go、wiki_ingest_dedup.go、wiki_ingest.go；internal/container/recover_pending_wiki_tasks.go | 原生候选、chunk关联、归并/更新/恢复存在；公开候选边界由只读独审核实，不直接发布 |
| REWIRE | product_ingestion/discovery.py、discovery_composition.py | PROPOSED_NEW能投影；UPDATE_PROPOSAL仅审计；禁止新增实体/正式关系；整组审核失败会排除全部自由知识 |
| KEEP/REWIRE | knowledge_compiler/concept_free_wiki_830_g2.py、batch_concept_compile_830_g3.py | 稳定概念/字段/自由页及增量编译和最终审核hash复用；字段实例与通用概念不可因同名误合并 |
| REWIRE | knowledge_compiler/service_schema_catalog_830_g3.py及既有实体/关系合同 | 服务线/版本/服务项是结构资产，尚未接运行；必要服务身份不能用free_wiki文章替代 |
| FREEZE | 旧publisher/current_release | 只保留审计，不恢复第二Active |

只读独审核实：仅当RAW的WikiEnabled=true时，原生Wiki会在parse completed前运行并可能直接写页。fresh3190的native14只计embedding/document summary/summary embedding，不能证明执行Wiki发现；目标克隆当前wiki_enabled未获回读，9月7日源环境true不能移用。缺口属于拟接入边界风险，不是已复现的双发现事故。

当前源码重验：mapOneDocument确有截断/发现失败回退，reduceSlugUpdates缺引用时使用Description/Details。页面级SourceRefs/ChunkRefs不能证明事实级版本。原生直接输出不得跳过证据准入。参考本地upstream-llm-wiki的ingest.ts：purpose/分析后生成/checkpoint；不采纳page-merge.ts失败覆盖旧正文。purpose使用已有知识库目标配置。

## 第一条真实切片

来源及可重算身份见[选材记录](../../insurance-kb/evidence/830-g35/source-selection.json)：既有真实冻结请求内《平安e生保（尊享版）医疗保险产品说明书》，knowledge=`1265a343-c408-4620-8eed-c4f6a2adadc2`，79个原始SourceBlock，不手工清洗模型输入。

- 第26页说明书与条款适用顺序：有材料阅读用途的Schema外候选；先比较已有知识，允许引用/补充，不强制新页。
- 第1页30日等待期：归waiting_period字段，不重复自由页。
- 第1页“特需国际省心住，尊享品质医疗”：宣传反例，不独立成页；具体保障内容不随宣传丢弃。
- 选材检查项不是手写模型结果、专家Golden或已批准页面。模型raw、审核及发布证据仍须真实运行/复用。
- 臻享家医原PDF存在，尚未证实平台已解析；不把磁盘文件冒充解析产物，不臆造八条服务线。

## 稳定Requirement

消费OpenSpec128/129；按既有合同补充本次要求，不另造平台。仅当已保存真实RED且现合同无法安全表达时占新号。

| ID | 合同 |
|---|---|
| G35-R1 | 原文/解析/定位共享且版本化；只执行一套必要发现，不依赖字段成功或字段剩余片段 |
| G35-R2 | 真实非空有效知识，重复/宣传不独立发布；区分引用、补充、更新、新页和必要实体；身份含主体版本条件 |
| G35-R3 | 关键事实关联具体原文及版本，保留raw/失败；数值否定条件例外主体版本不丢；专家修订沿既有来源记录 |
| G35-R4 | 相关链接与业务关系分开；必要关系保留主体客体类型条件版本证据，不以共现推导 |
| G35-R5 | 重复无重复身份页；依赖不变不重解析/重发成功调用；真实索引/策略变化失效；未知发送遵既有规则 |
| G35-R6 | 链通后按最小依赖组隔离；失败更新保留旧页；裁剪后不能复用旧集合或正文审核 |
| G35-R7 | 同批材料/模型/解析输入有界对照遗漏、低质重复、关系定位、调用成本耗时；无证据不声称优于原生 |

## 执行队列与写域

Owner root，当前写域：本计划、OpenSpec129、evidence/830-g35、HANDOFF；产品写域在接缝核实后精确冻结，再RED→实现。不并行产品写域，仅有界独立设计/代码审查。

- [x] G3身份核实与独立工作树。
- [x] 真实解析样本及选材记录。
- [x] 原生候选边界只读独审；正式接线仍待边界选择。
- [ ] 冻结设计/Requirement并独审，按TDD实现首条纵切。
- [ ] 既有解析→真实发现准入→审核→唯一发布→网页/来源；实际外部动作先核对现有明确授权。
- [ ] 首链后补重复、小增量、局部失败及最终内容审核绑定。
- [ ] Requirement→实现→测试→identity矩阵，必要组件验证和独审，交付页面及调用时间对照。

非目标：普通字段全量补齐、全八服务线、千文件长稳、新服务/数据库、G4复杂跨版本冲突、Q0专家质量评测、生产发布、合并G3及无限调用。外部操作超已有授权时先形成可审阅包再集中请求，其余工作继续。STOP：第二权威、假证据、手工补业务、样本分支或职责无法确定；语义分歧向用户讨论。48小时无真实物理结果按章程停线；同冻结实现不重复验证。

## 首个共用软件切片（独立于原生候选边界选择）

补已有知识语义比较视图，消除仅看标题索引导致的重复/更新不可判定和正文变化不失效。
此为首条链路准入所需输入，不另造缓存。写域冻结为：
`harness/src/insurance_harness/product_ingestion/discovery.py`，
`harness/tests/product_ingestion/test_discovery_local_dependencies.py`，
`test_independent_discovery.py`及必要的现有runtime/checkpoint测试context识别；
本OpenSpec/计划/evidence。先记录旧实现在同一page身份下正文变化输入仍相同的RED，
再增加版本化语义视图；历史renderer字节回归只执行一轮。
原生候选公共协议vs先Harness单次发现的边界已向用户讨论，相关实现等待回答。


首个共用切片已GREEN，冻结tree `8e31ffd203452cfae38f34c7571f795b9aa132fa`只读独审0 BLOCKER。
产品实现与测试四文件相对冻结tree字节一致；后续只增加验证及交接记录。
Requirement→实现→测试→身份矩阵：

| Requirement | 实现 | 证据 | 状态 |
|---|---|---|---|
| G35-R2/R5语义比较及真实依赖子项 | discovery.py knowledge view / generation v5 / review v4 | semantic-view-validation.json，11项RED、最终受影响30PASS、其余相关65PASS中的通过项；产品identity以上述tree和文件SHA固定，commit为本记录所在提交 | PASS（软件子项） |
| G35-R1/R3输入完整性子项 | 既有routing及同一v5 renderer | offline-real-input-budget.json，历史真实238块/76859字符/4窗口 | PASS（仅离线输入） |
| G35-R1—7业务目标 | 原生交接、准入、更新、实体/关系、独立审核及唯一Active | 尚无本次真实页面或模型结果 | NOT RUN |

D1软件检查如上述回执；Docker/build/deployment/provider/Candidate/Draft/review/publish/activation/live-probe均NOT RUN。0新增模型、0发布。软件提交不升级BUSINESS或Goal完成状态。


## 同身份知识增量准入切片（2026-09-23）

原生接入选择尚未答复；该切片复用已经公开的G2 AuditDisposition.update及最终审核，不改变发现producer或发布权威。G3 Python validate_delta_output/compose_batch_output及Go validateDelta830G3/composeBatchOutput830G3目前全部拒绝同身份旧成员，已核实为更新无法进入Candidate的根因。唯一Owner=root；读审只核对冻结身份。

设计：delta必须显式标为update、确有旧同类型同身份目标且内容有变化；未声明覆盖、新id假称update、无变化和受保护概念正文改写均拒绝。按稳定成员id在最终组合中替换并保留一条update审计，其余旧成员保持原样。已有最终完整性、原文Evidence、主体/版本、专家/Schema保护、独立评分及最终output_hash继续生效；失败不写Active也不改旧对象。字段增量合同不变，复杂跨版本语义冲突不纳入。既有无update样例字节不变。

本轮写域：harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py，harness/tests/test_batch_concept_compile_830_g3_updates.py，internal/types/concept_free_wiki_830_g3.go，internal/types/concept_free_wiki_830_g3_updates_test.go，必要的既有fixtures/batch_concept_compile_830_g3新增跨语言update向量；计划/OpenSpec129/evidence/交接。先Python和Go旧实现RED，再实现、跨语言最终候选验证、冻结独审；无模型、构建部署或业务发布授权扩张。

更新能力通过可省略的request.knowledge_update_policy=`explicit-same-identity.830.v1`显式声明并进入request hash；只有该请求的compiler context使用NEW_AND_UPDATED_MEMBERS。缺省旧请求保持NEW_MEMBERS_ONLY及禁止update，省略值维持旧canonical字节；空值/未知策略拒绝。当前producer不自动启用该能力。

只读审查补核对：实际bounded模型display context硬编码NEW_MEMBERS_ONLY；Candidate边界缺少变化成员评分/pending闭包重验。追加同Owner写域g3_bounded_model_execution.py及本切片测试：复用/下沉既有变化成员识别与准入规则至compiler公开helper，bounded renderer消费同一output_mode；仅显式新策略Candidate执行完整评分及pending核对，历史请求字节/验收合同保持。


本切片验证事实见[evidence](../../insurance-kb/evidence/830-g35/knowledge-update-validation.json)。Python/Go旧实现各2项更新RED，模型display/评分准入4项RED；最终Python受影响及bounded旧链26PASS，Go更新/已发布增量/旧canonical/完整Python候选及反例PASS。显式策略保留既有整批审核和唯一Active；未自动启用该策略。

| Requirement子项 | 实现 | 证据 | 当前状态 |
|---|---|---|---|
| G35-R2/R5同身份替换、旧请求拒绝及版本化输入 | Python batch compiler与Go candidate mirror | frozen tree 269f586b329d857d5e5d6573441e159966b3dd24，六文件SHA见JSON；commit为本记录所在提交 | PASS（软件） |
| G35-R3完整审核/评分/pending | 中央knowledge_admission_g3，Go对应验收 | 全重哈希缺评分/低分/错pending/旧审核反例；完整跨语言candidate hash固定 | PASS（软件） |
| G35-R2模型UPDATE_PROPOSAL贯穿 | producer响应schema/投影与runtime启用尚待接线 | 当前响应只允许新增，未发模型 | NOT RUN |

后续接线必须给定义和页面显式update响应及原身份/依赖，升级相应producer上下文，保留旧响应字节；不能把同ID输出默认为new_page或从audited disposition直接发布。原生接入待答复，真实发现非空/页面/来源与服务实体/关系仍未交付。

冻结tree269f586b329d857d5e5d6573441e159966b3dd24最终只读独审0 BLOCKER，机械文档豁免成立；六个产品/测试/向量文件与冻结树一致。尚未启用producer、未发模型及未部署，本Goal仍未完成。

G35-R3来源一致性：含MODEL_GENERATED的定义必须origin=MODEL_COMPILE；含生成片段的CompileOutput必须transformation=SYNTHESIZE。主正文及相关知识预览使用同一片段展示。仅新来源合同的citation增加可省略evidence_index，绑定完整Evidence派生的citation_id；排序位置和quote不得代替身份。G2仅新合同自由页采用完整renderer，旧对象正文/hash保持。

G35-R3展示检查发现G2目录也直接展示定义正文，故同Owner必要写域包含conceptDirectory830G2.ts/.vue及对应测试，复用同一来源解析/片段组件；不新增展示协议。整批组合若保留旧生成片段，最终transformation仍须SYNTHESIZE，不能被本次EXTRACT增量抹掉；以carryover反例验证，旧无生成对象合同不变。

完整G3跨语言向量包含原文允许的非NFC业务文本，暴露前端bodyText仍强制NFC的不一致；按既有G3业务正文保真合同移除该处NFC要求，结构化身份及对象键仍要求NFC，禁止归一化原文。该反例并入G35-R3同一显示切片。

## 下一切片：原生候选逐窗执行（用户已批准路线，默认尚不接运行）

复用source_snapshot既有签名artifact、PlatformClient.native_discovery及ConfiguredModelExecutor.execute_stage_call。每文档先验证完整plan，逐窗执行发现和引用，成功provider raw先进入StageCall，再请求签名候选快照；收集完整窗口集合后才供后续准入使用。窗口失败保留已完成结果和明确失败阶段，不能把单窗成功当全文完成。模型请求键绑定来源、原生策略、阶段、窗口与输入，父任务只复用同策略且请求/raw完整的已记录结果；未知发送继续阻断，HTTP确定失败可按现有规则重新规划。原生两阶段只生成候选及线索，不编译正式Evidence或写Active。

该步唯一root写域：新增product_ingestion/native_discovery_stage.py及test_native_discovery_stage.py；现有discovery_stage.py仅把同职责模板选择/父调用校验helper公开复用，必要model_execution既有测试与checkpoints的artifact声明；本计划/对应OpenSpec129/evidence。暂不启用pipeline策略，不执行真实provider；后续准入响应/投影、来源review新版本以及Go自动写页互斥完成后才能接运行。模型/部署授权不扩大。
