# 830-G3.5 自由发现与知识准入实施计划

## 当前状态：原生任务接线与持久恢复软件验证（2026-09-23）

原生候选模式已接入既有任务主流程，按显式配置校验三个模板，任务/检查点固定策略及更新授权。缺省旧流程保持。发现和准入复用现有StageCall，授权祖先raw跨三代恢复；无关Head可重投影、实际知识上下文改变需新判断。PENDING/实体待解析保留整组围栏，字段独立；来源覆盖与准入状态分开记录。

冻结tree 2a10bcb6bb88a6d2f9071be06a8c51cc837a34a7，两项最终独审0 BLOCKER。最终协调器/准入14PASS5.24s，实际SQLite三代成功调用不重发，重启配置漂移1PASS20.16s，旧worker/checkpoint12PASS141.29s，Ruff/mypy通过；详细RED、测试替身限制及审查见native-pipeline-validation.json。CURRENT=NATIVE_PIPELINE_SOFTWARE_REVIEWED；NEXT_READY=后续必要结构实体/关系、最小依赖组与有界真实纵切。运行配置尚未启用，新增真实模型/构建/部署/发布均0，BUSINESS=NOT RUN，G3.5未完成。

## 当前状态：原文定位与准入执行软件完成（2026-09-23）

原文定位及逐窗准入执行冻结tree0d3f2b43f7a39095cadc46cdbc5c750651a3ed63，两项独审0 BLOCKER。跨页引用复用source_geometry拆分，并按完整Evidence合并共享片段、同步重映射内容来源索引；正文/生成段不变，缺定位不改标生成。逐窗执行复用StageCall、精确父响应与未知发送阻断，先存raw后准入/几何，失败保留回执，无自动修复调用。

几何5PASS0.56s，执行4PASS2.48s（executor/父调用为测试替身），受影响合跑8PASS2.56s后追加倒序几何反例已覆盖于最终5项；Ruff/mypy PASS，证据native-admission-stage-validation.json。CURRENT=NATIVE_ADMISSION_EXECUTION_SOFTWARE_GREEN；NEXT_READY=任务主流程显式接线、检查点和完整持久计数/恢复验证。尚未运行启用，新增真实model/build/deploy/publish均0，BUSINESS=NOT RUN，G3.5未完成。

## 当前状态：原生准入与审核回放计数软件完成（2026-09-23）

原生准入纯投影与v5回放计数软件完成：冻结tree c761124a6f37a027d38beb58a444872bbd7332dc（metrics独审ac5371b7），两项最终独审0 BLOCKER。逐成员强制来源标志、原文精确字符引用、候选完整处置、同身份/版本更新，并保留“更新旧页+新增相关概念”的各自动作；复用编译与v5审核。新增10项通过7.61s；真实持久metrics旧/新审核9项通过1.60s，Ruff/mypy PASS。证据native-admission-validation.json。

CURRENT=NATIVE_ADMISSION_SOFTWARE_GREEN；NEXT_READY=原文PDF定位与逐窗准入执行/Harness显式接线。运行未启用；纯投影要求调用方先验证签名，尚不代表PDF点击实测/实体关系创建/真实发布。新增真实模型/构建/部署/发布0，BUSINESS=NOT RUN，Goal未完成。

## 当前状态：原生候选模式互斥软件完成（2026-09-23）

来源审核已提交c7e8a8ccc。Go候选模式互斥冻结tree81b75d36c0dee4db78989ba4dd5d2df113b0725a，独审0 BLOCKER：显式native-candidates.830.v1策略绑定tenant/space/RAW/Wiki；未配策略的native候选接口503，启用后postprocess不计/不排旧Wiki子任务，旧ingest/finalize先拦截，启动恢复跳过且保留既有durable rows。旧空配置对其他原生行为兼容。

实际YAML配置与API反例RED后，config/service/container/handler/router五包定向PASS；证据见native-write-exclusion-validation.json。CURRENT=NATIVE_WRITE_EXCLUSION_SOFTWARE_GREEN；NEXT_READY=候选语义准入/更新和Harness显式接线。未启用运行配置；启用需旧worker退出且无活动任务，未提供热切换屏障或迁移旧待办。本轮真实model/build/deploy/publish均0，BUSINESS=NOT RUN。

## 当前状态：来源片段独立审核软件完成（2026-09-23）

原生逐窗执行已提交e879cf7ff。来源审核冻结tree88443394f2ab52a2944b57c69bd576eb5ac2b3f1，独审0 BLOCKER：新来源对象自动采用v5，不允许降到旧审核；逐片段标志、完整展示内容及按真实Evidence次序校验的原文进入审核。新模板独立受purpose/prompt授权，无原文的纯生成内容不得获得evidence_quality分。旧v3/v4及旧提示保持，最终hash/整组准入复用。

来源反例4RED、模板接线4RED后，最终受影响45PASS，语义依赖29PASS，Ruff/mypy PASS；证据见provenance-review-validation.json。CURRENT=PROVENANCE_REVIEW_SOFTWARE_GREEN；NEXT_READY=原生候选语义准入/更新、显式runtime策略和旧写页互斥。新pipeline/模型配置尚未启用，本轮0真实模型/构建/部署/发布，BUSINESS=NOT RUN。以下历史状态不覆盖本段。

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

## 下一切片：来源片段独立审核（G35-R3，沿既有审核边界）

已实现的展示合同必须贯穿最终语义审核，不能只加UI标签。现有review v4只向审核展示正文与页面级evidence，且旧prompt一律拒绝无来源补充。新增review context v5及单独受模板授权的新prompt：含新来源合同的候选逐片段核查来源支持/模型生成，允许明确标注且有用的补充，拒绝把产品保障/金额/资格条件猜测包装成通用补充；纯生成的evidence_quality必须0。最终输出hash和整组审核发布门禁复用，不增加独立审核平台。旧v3/v4及旧prompt字节保持，新的来源对象不允许降级到旧审核上下文。

root必要写域：discovery.py的独立review renderer/版本选择，必要同职责纯来源视图helper；现有discovery_stage.py最终审核模板选择与评分校验、discovery_composition.py父响应prompt核验；tests/product_ingestion中对应review/provenance/replay tests、计划/OpenSpec129/evidence。先验证新内容在旧renderer中丢失片段标志的RED，再实现；尚不改变运行配置或新增真实模型调用。

## 下一切片：显式原生候选模式与旧直写互斥（G35-R1/R3）

复用ProductIngestionConfig的既有tenant/space/RAW/Wiki绑定和原生持久队列，新增可省略wiki_producer_policy=native-candidates.830.v1。旧空配置保持；未知策略或不完整绑定拒绝启动。显式候选模式只禁止该绑定RAW/Wiki的原生自动写页，其他KB保持。postprocess不再把原生Wiki子任务计入/入队；ingest/finalize在任何模型/写页/队列消费前拒绝既有触发；启动恢复跳过这些lane且保留durable行。部署启用须在旧worker退出/任务静默后进行，不支持进程内热切换，也不删除既有页面/待办或宣称迁移完成。

root写域：internal/config/product_ingestion.go及config.go验证入口/相应tests；knowledge_post_process.go、wiki_ingest.go/wiki_ingest_batch.go及定向tests；container/recover_pending_wiki_tasks.go及reset_pending_tasks_test.go必要签名/测试；本计划/OpenSpec129/evidence。复用唯一策略判定，不新增队列或修改Active。先旧配置忽略策略/旧worker仍可进入副作用的RED，再实现/冻结独审。实际运行配置不变。

互斥接缝补充：机器native-discovery请求也必须核验同一显式完整scope策略，防止Harness误启用时另一端仍走旧直写；因此本切片必要写域扩至handler/g3_platform_native_discovery.go、g3_platform_snapshots.go、g3_platform_composition.go及native handler测试。纯producer领域服务和历史签名向量不变，只有机器接线要求策略；未配策略不得派发原生候选计划。

## 下一切片：原生候选到正式知识的语义准入投影

现有DiscoveryProposal/G3D响应只允许有证据的新增成员，UPDATE_PROPOSAL是审计项，不能承载用户允许的生成补充。新增原生准入v1短引用响应：只处理签名窗口内候选，逐个给出NEW/UPDATE/REFERENCE/REJECT/PENDING或REQUIRES_ENTITY_RESOLUTION处置；每个生成定义/页面必须关联候选并显式提供content_provenance，不能再自行发现第二套主题。已有知识语义比较复用build_discovery_knowledge_view；更新必须绑定原身份与不可变revision且启用现有显式update策略，字段结果不能被覆盖。

候选级UPDATE表示至少一个既有成员更新，可同时新增该页需要的概念；NEW候选只含NEW成员。每个成员各自校验action/identity/revision，传入独立审核的disposition也必须保留成员动作，不能将随附新概念误标UPDATE。

原文短引用给出source_ref/start/quote，服务端按已验SourceBlock构造Evidence并核对原字符位置；仅模型片段可以无引用。签名候选description/details始终标模型生成，chunk关联只是线索。准入输出复用CompileOutput、AuditDisposition和最终v5独立审核；结构实体/关系不足保留待解析处置，不伪装成已创建实体。窗口跨页/原文PDF定位在接runtime时复用source_geometry验证，不把当前纯投影结果当业务验收。

本步root写域：新增product_ingestion/native_admission.py及test_native_admission.py；extraction.py仅公开复用既有严格JSON解析器，不改变其旧调用；计划/OpenSpec129/evidence。原生collector/pipeline/模型配置暂不启用。先新provenance缺失/无引用生成/显式更新/候选覆盖/原文偏移反例，再实现；尚不扩大外部调用或部署授权。

## 下一切片：来源审核回放的持久计数兼容

接线核对发现discovery_replay_metrics仍固定旧审核prompt，已授权v5审核父响应虽能正确复用，却会在持久计数阶段被当成变更而拒绝。沿既有唯一metrics边界，从已校验hash的子review context合同选择旧/v5提示，再核对真实父StageCall；不信任回执自报prompt，不放宽祖先/raw/operation绑定。root写域仅discovery_replay_metrics.py及既有test_discovery_replay_metrics.py、计划/OpenSpec129/evidence/HANDOFF。先使用真实artifact/StageCall持久存储复现v5错误，再实现并保留旧回放与篡改拒绝测试。无新调用、无运行启用。

## 下一切片：自由知识的原文定位与片段索引

原生准入的Evidence先证明原字符位置；正式接线前还必须复用source_geometry确认原PDF可定位。新增纯native_evidence适配器：一次按材料准备现有几何索引，调用project_evidence_locations；跨页引用按既有规则拆为真实页片段，同步重映射content_provenance.evidence_indexes，保留正文/来源片段和原始引用审计。生成片段不伪造PDF定位，缺几何的原文依据明确失败，不静默改成模型生成。唯一root写域为新增product_ingestion/native_evidence.py及test_native_evidence.py、计划/OpenSpec129/evidence。先跨页索引及缺定位反例，复用实际签名source fixture；当前仍不启用pipeline/真实模型。

## 下一切片：逐窗语义准入执行

沿同一StageCall调用与恢复边界执行native admission，单窗输出仅准入候选，不自行发现或发布。模板必须单独授权g3-native-admission及精确prompt；操作身份绑定序列化完整语义输入，父响应需校验原scope/model/request/prompt/raw，结果未知不重发。模型raw由既有executor先持久，子任务回放记录RULE归属。纯响应投影后运行已复用PDF定位，正式输出及最终审核使用定位后的完整Evidence/来源索引；失败保留context/response/错误审计而不产出可编译输出。root写域新增native_admission_stage.py及test_native_admission_stage.py、计划/OpenSpec129/evidence/HANDOFF；暂不改pipeline、运行配置或远端状态。新生成、已知父响应零新调用、未知父调用阻断与语义失败保留回执先验证。

## 下一切片：任务主流程、配置及持久恢复接线

当前已复用原生候选producer、StageCall collector、语义准入、source_geometry、CompileOutput与v5独立审核；缺口是pipeline仍只调用旧发现。下一步新增显式可省略NativeDiscoverySettings（native-candidates.830.v1、language/granularity/purpose、allow_knowledge_updates），缺省仍旧路线。启用时启动校验三个精确模板native discovery/native admission/provenance review；Go同scope候选模式接口已有503防线。运行配置不在本步修改。

field_plan将本任务的发现策略及实际模型/模板指纹持久为native_discovery_policy（旧模式不生成），并通过现有builder可省略knowledge_update_policy参数在允许时声明已支持的更新合同；默认旧请求字节不变。discovery及compilation核对本任务策略与当前配置，checkpoint验证沿既有依赖边界执行同样核对；配置切换不得使旧任务悄悄执行另一套producer。恢复时不匹配明确阻断，已成功StageCall不删除、不以新配置盲重发；待明确重新规划/新任务后才执行变更策略。checkpoint rebase保留已声明更新策略。

原生stage协调器只读已验证source_snapshots，对当前corpus每份文档执行一次完整原生发现；按实体/资料绑定把签名窗口交给逐窗准入，无候选窗口无需额外模型调用。只编排已有接口，不引入调度器/队列/第二发现。集合组合复用CompileOutput；跨窗source短引用与candidate审计ID加作用域以防串文，正式同id冲突明确pending/failed。任何未绑定资料/窗口失败不伪装完整，成功窗口raw及draft仍保留；首纵切保持现有整组审核，G35-R6最小依赖组随后按已定队列完善。主pipeline产出既有discovery_candidates/delta/summary供唯一编译/审核消费；字段结果保持独立。

持久计数复用verified_discovery_replay_calls：collector补保存真实execution content；native discovery/admission执行回执必须匹配子context哈希、固定提示、真实祖先StageCall的operation/input/raw/状态，不能相信自报call_id。checkpoint仅新增这些已存在artifact的版本声明，不复制来源或模型raw。

本步root独占写域：configuration.py及配置测试；新增native_pipeline.py及对应协调器/接线测试；pipeline.py的field_plan/discovery/compilation窄接缝；compilation.py及batch_concept_compile_830_g3.py仅公开builder可省略update策略及对应回归；checkpoint_validation.py/checkpoint_rebase.py/checkpoints.py必要策略/保留接缝；native_discovery_stage.py仅补execution context留存，discovery_replay_metrics.py及持久测试增加原生回执校验；本计划/OpenSpec129/evidence/HANDOFF。先配置/阶段选择/完整覆盖/持久回放篡改反例，再实现；既有source/field/审核/发布权威不变。部署、真实provider及业务写入仍须核对本Goal已有明确窗口与预算，不由本软件切片推导。

接线设计独审发现三代恢复缺口：native适配器目前仅查直接父run，partial discovery的成功调用仅以checkpoint audited_calls继续传递。采用现有plan.calls/audited_calls授权祖先raw重投影，在checkpoint_artifacts公开只读调用接口并逐条核验引用/作用域/request/raw身份；native适配器复用该集合，不遍历任意历史。纯Go签名计划允许按同source/policy重请求，不重复解析或provider；不新建成功投影缓存/恢复协议/队列。必要写域扩为checkpoint_artifacts.py、native_call_replay.py及对应祖先恢复验证，native_admission_stage.py仅改回放读取/原run回执；checkpoint_store.py如现有授权引用已完整则保持不改。必须覆盖三代恢复及base变更只影响准入的实际依赖，不能把第一代回放测试冒充完整恢复。

恢复验证口径补充：准入调用依赖实际完整语义上下文，而不是无关 Active Head 的 epoch。无关发布导致旧编译输出失效并重新投影，但上下文逐字一致的准入 raw 仍可复用；现有知识正文/版本/Schema 等实际输入变化会改变调用输入身份并重新判断。三代真实 SQLite worker 测试覆盖原生发现与准入 raw 留在第一代，第二代不新增调用，第三代换无关 Head 后仍读取授权祖先记录，重新编译请求保留更新策略。额外验证实际准入上下文变化重新调用。

接线独审修复：原生PENDING/REQUIRES_ENTITY_RESOLUTION纳入现有整组围栏，不能因其它NEW成员通过最终审核而消失；完整集合失败时仍保留逐窗原响应/处置回执。字段独立继续。source coverage只描述原生发现覆盖，完整发现后的准入失败不应把omitted_chars=0与complete=false混成非法状态；native_coverage另记准入是否完整。最小反例覆盖混合NEW+两种pending、准入失败/预检失败及现有API状态投影，不扩R6分组协议。

## 2026-09-23 用户要求完整真实流程与保险提示词验证

用户明确要求“走个完整的流程，看下完整的效果，是否抽取到合适内容”，并要求针对场景调整提示词。沿同一G35 Mission执行真实本地隔离测试窗口，不重复索要已批准的普通执行授权；不推导生产或合并G3授权。Owner=root；软件冻结223aa8ed2，现有APP/Harness/UI分别54cadb3d3237/646234d2d0ef/d488e95945f5，复用现有数据库、解析/文件卷、网络和18295网页。

先保留原生通用提示主体与两段候选/引用流程，通过已有Purpose配置注入insurance-native-purpose-v1.txt；其身份已进入原生policy与持久native_discovery_policy。准入与v5审核原有保险约束不另做重复发现。现有模型gemini-3.7-flash-medium/原gateway与scope不变，不刷新或扩大automation权限/有效期。新增三项精确模板授权只服务已交付native discovery/admission/provenance-review。

先完成构建与离线配置验证再启用：APP、Harness、UI各最多一次必要构建（精确制品存在就复用），数据库/DocReader/Redis不构建、不迁移。不修改或删除旧原生页面/队列。切换前核对任务与未决发送为0，并先停旧worker及旧APP，避免热切换原生直写。保留旧镜像与私密配置备份用于恢复；新服务健康及当前Head一致后开放一次正常网页任务。只能走平台正常上传/处理/审核/发布/检索，不用手工候选或发布脚本完成业务。

实际材料优先沿既有e生保样本及已解析版本；执行前冻结可用原PDF/材料集合和预计窗口数。完整任务只启动一批，不自动重跑。执行前按真实资料窗口和实体绑定估算新增调用，运维目标为整批40次以内、对照最多4次；运行中观察真实新增发送，接近44次时停止领取新工作并让已发送调用按既有持久边界收尾。独审确认现有执行器没有per-run发送硬上限，所以44是本次运维停止阈值，不能声称软件已提供硬预算保证，也不为本次验收另建预算平台。该数字是Owner的执行规划，并非用户给出的硬次数/金额限制。保存实际尝试、raw、用量、失败、候选处置、审核/发布结果和首尾时间；不以HTTP200或纯EMPTY宣称抽到合适知识。若正常平台任务不能沿已有合同完成，保留失败后先修根因与独审，再讨论必要恢复，不用临时脚本替代业务流程。

对照保持同一真实解析窗口、模型和粒度，仅比较Purpose为空与保险Purpose的候选发现/引用；两阶段原生候选与最终准入页分别记账，不能冒充完整原生自动Wiki的端到端A/B。业务评价关注有用知识覆盖、字段/已有页重复、营销噪声、产品事实越界、引用是否直接支持及条件例外保真。网页检查模型生成标志、混合内容、原文页码/高亮、搜索可见；不能据一次样本宣称整体优于系统原生。

本窗口必要写域：现有计划/OpenSpec129/HANDOFF/evidence/830-g35；仅为构建/配置/部署的一次性运维准备可在私密临时目录保存审计脚本及备份（不进入正常产品处理路径）。发现产品行为缺陷时先记录RED并扩展现有Owner矩阵，不在验收运行途中改代码或切服务。页面当前登录失效；用户明确要求复用830-G3总控的已有测试账号，已定位归档记录，通过正常登录入口恢复。真实效果仍NOT RUN。

用户追加质量要求：自由发现同时检查质量与覆盖度。按实际材料建立重要知识检查表，逐项区分Schema字段/已有知识覆盖、新自由知识覆盖、合理拒绝及真实漏项；原生候选召回与最终准入保留分别评价，保留条件/例外与引用支持核验。单次随机模型对照只报告观察差异，不能将差异直接归因于Purpose，更不能宣称整体质量提升。

2026-09-23构建事实：APP冻结223aa8ed2镜像0047b47d...与Harness构建通过。UI首次静态构建在Vite Less worker同步等待处timed-out，未产生可部署制品；相同出错组件的两段Less在主线程独立编译均通过（6960/208字节）。保留失败日志，允许一次同源码/同锁依赖的恢复静态构建，明确使用Vite既有css.preprocessorMaxWorkers=0设置关闭样式worker；不改产品源码，生效构建参数进入制品回执，UI累计至多2次尝试（首次失败+一次恢复）。尚未切服务或发送模型。

真实来源前置：原PDF的492101字节与5e2aef...哈希已同当前APIfile_sha256/attempt1核验一致，但原旧解析的签名来源接口409 G3_PLATFORM_SNAPSHOT_UNAVAILABLE，不能当新版可用来源。升级前只冻结这份原PDF输入，不伪造签名快照；新版部署后先经正常网页“重新解析”获取当前来源，再由正常单文件上传建立新manifest/run。来源成功签名/定位前不启动模型知识验收。重新解析是此次完整来源流程的准备步骤，旧尝试不手改、旧未知调用不重发。覆盖检查按同PDF内容匹配，不要求新parse沿用历史block_id。

## 2026-09-23 重试恢复后的文档区可达性修复

用户明确同意重试，自动审批与CUA滚动已成功。正常网页真实RED：30条历史产品任务撑满固定高度knowledge-layout，任务区没有高度/滚动边界，后续flex文档区被挤至不可操作；连续滚动、浏览器唯一名称查找、67%缩放仍无法到达目标卡片。原生文档区已有min-height:0与独立滚动，复用该布局，不删任务、不改查询或业务状态。

沿G35-R1真实平台流程的必要修复，root写域仅扩至frontend/src/components/knowledge-base/product-ingestion-status.vue样式；任务区限制视口占比并独立滚动，给原生文档区保留空间。低风险纯布局不新增镜像实现的静态断言，RED与GREEN以正常浏览器真实历史列表/目标文档可点击及任务详情可滚动核验；现有组件回归保护业务事件。冻结差异独审后仅构建/更新UI一次，APP/Harness/配置/数据库不变，实际重解析和新run尚未开始。不能将修复后续结果记为此前完整流程已通过。

用户后续明确“重新拿一份文件处理吧，先跑通，后续看下是不是重新建一个workspace，统一验证”。当前不新建workspace或服务。旧尊享版重解析被KNOWLEDGE_REVISION_SOURCE_PINNED拒绝，原attempt1未变；悦享版签名快照同样409，惠享版指纹查询发现历史别名来源，均不继续重试。整批14份说明书经已有指纹接口只读查重，选择真正未入库的平安守护百分百（2026）两全保险产品说明书：原路径/Users/houjing/Downloads/shouxian_product/平安守护百分百（2026）两全保险/产品说明书.pdf，SHA256 d4c9611b7a0b0f59e9b37aef6ff0e5d12d42b00ba20daff670630f2d04e5c08a，354102字节，7物理页。只启动这一份正常上传任务；原生解析记录由此次真实流程产生，不补造旧材料来源。

本次覆盖检查改按新材料：p1–2附加/未附加提前给付重疾险的满期/身故分支与18岁边界；p2提前给付后主险保额等额减少、责任与现金价值联动、减至零终止；p2–3贷款须被保人书面同意及审核/80%扣欠款/6个月/未偿还本息转本金/扣赔付/达现金价值中止；p3–4七类免责、自杀例外、不同退现价对象、10日通知与迟报例外；p4–5年龄错误、20日犹豫期、退保扣款/失去保障；p5年龄与保险期间分组、60日宽限期及中止；p6–7利益演示边界和说明书以条款为准。字段或已有页完整承接可计覆盖，不能因字段名宽泛而压掉重要流程。自由发现重点追踪主附险联动、贷款生命周期、说明书解读，原生候选/准入/发布分别计数；仍只报告此样本观察，不宣称整体优于原生。

## 2026-09-23 已有产品的唯一名称年款关联修复

实际 run 2f0f8a89-ff30-4c04-9268-9ceacc5a34e8 的模型正确返回公司、完整名称、2026及唯一已有实体引用；说明书未提供编码/备案。旧解析只按编码匹配并把相同名称当竞争，v3编译/Go发布还要求本次材料包含条款编码备案，造成假歧义。用户明确“平安寿险产品，名字+年份基本确认”并要求继续。沿G35-R1既有授权修复；不另建workspace。

复用现有v3关联、可信公司别名、ExistingEntitySnapshot、MATCH引用和模型raw恢复。已有产品凭有原文支持的公司+正式名称/已批准别名+明确年款唯一匹配；当前材料明确提供的编码/备案必须一致，多匹配/实际冲突/缺自有证据继续阻断。派生决定的完整anchors来自已有实体快照，原proposal/null/raw/证据归属不改；不把快照编码备案伪装成本次PDF引文。新建产品及互补材料CREATE门禁不变。

root唯一写域扩至g3_evidence_identity_v3.py、Go对应concept_free_wiki_830_g3_identity_v3.go及其测试/跨语言向量；必要恢复仅限现有checkpoint/model_execution模块且先单独RED。先测试复现真实形状，覆盖缺证据、公司/年份/编码/备案冲突、多匹配、原proposal不可变、MATCH编译及Go重放；离线回放实际raw。独审后按实际依赖一次更新Harness及APP（发布端实现确实改变），UI/DB复用。现有成功模型调用必须复用，未知发送不重试。真实网页恢复、抽取质量与覆盖、标志/引用/发布/检索分别记录，当前仍NOT RUN。

独审指出解析结果必须版本化：新增compiler v4承接唯一已有名称年款关联，v3历史决定与重放保持不变；复用v3关联实现的显式v4选项，Python/Go同时分派。写域补充batch_entity_resolution_830_g3.py、batch_concept_compile_830_g3.py、pipeline.py及Go主合同分派。RED已观察旧实现NEEDS_CONFIRM而期望MATCH；Go旧发布重放拒绝Python新决定。测试原文将去除未提取编码/备案，仅冲突负例按需加入观测值。普通checkpoint retry_calls会新发身份模型，须接现有replay接口并验证原调用/用量归属，不能直接重试浪费已成功结果。

恢复实现选现有checkpoint retry_calls→同一replay_stage_call，ProductArtifactStore统一读取旧recovery与已验证checkpoint授权，保留原MODEL_REPLAY marker形状/原call_id/费用复用统计，无新stage call。写域补充artifacts.py与checkpoint_store.py：三代恢复RED发现子代已经replay但identity阶段仍失败时，下一代仅因阶段存在就丢祖先proof；改以子代是否产生新identity调用判断，祖先ref仍全量验证。模型语义输出确实不足时重放仍待确认，不隐式重新采样；修复规则后同raw可以继续。三代原调用、新调用0、正常后续流程与用量分别验证。真实守护raw的Python V3→V4及Go最终身份重放/绑定已通过，0新provider；仅证明身份边界，非完整真实业务完成。
