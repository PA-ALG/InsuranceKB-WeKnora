# 830-G3.5 自由发现与知识准入实施计划

**Goal / Mission**：真实已解析材料中的有效Schema外知识经过既有Candidate、审核与唯一Active，在网页可读、可检索、可回原文。唯一Owner及Integration Owner=root；reviewer只读冻结身份。用户2026-09-23启动消息已授权有界设计、实现和验收；不重复索要普通实现批准。预计一条依赖G3的产品PR；首切片时间盒1工作日，至2026-09-24 18:00+08。独审按项目默认gpt-5.6-sol/high。

**Architecture**：WeKnora保管原件、解析与版本化来源；Harness集中承担发现准入及可替换语义策略。既有任务模块负责恢复/调用记账，审核和发布保持既有唯一边界。同语义输入只运行一套必要发现，不先完整原生Wiki再重复发现。技术栈沿Go/Python3.12/PostgreSQL/Vue，不增服务/数据库。

## 实际基线与当前状态

- 产品工作树`.worktrees/830-g35-knowledge-admission`，分支`codex/830-g35-knowledge-admission`，base=`8f7201dd428033de1e66f8783c125ebf2b617d53`。
- 2026-09-23重新核实[产品PR130](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/130)：OPEN/Draft、未合并、HEAD等于base，deterministic/integration-postgres/wheel-smoke均SUCCESS。明确依赖PR130，不使用停留G2的本地main，不合并G3。
- 历史部署源码`ec0721083`，当前只读docker ps确认app image`54cadb3d3237`、Harness`646234d2d0ef`、UI`d488e95945f5`仍存在；完整digest引用G3部署回执。源码、制品与部署身份分别记账。
- G3 FLOW PASS、QUALITY=DEFERRED_TO_Q0、NOT_FOR_PRODUCTION；真实发现EMPTY只证明阶段执行。
- CURRENT=SEMANTIC_VIEW_VALIDATION；SPEC=首个共用切片冻结、CODE=验证中、BUSINESS=NOT RUN；D1、DOCKER_ACTION=SKIP。当前RED：真实非空准入未证明，更新仅审计，服务实体/正式关系未接本路径。

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
