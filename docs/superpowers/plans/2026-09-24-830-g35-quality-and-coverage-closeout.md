# G3.5 自由 Wiki 质量与覆盖度收口执行计划

> **For agentic workers:** 使用 superpowers:executing-plans 按项执行；独立审查遵守仓库规则，root为唯一写者和集成Owner。清单采用checkbox跟踪。本文整理已批准方向及剩余事项；尚未确定的协议/根因必须在对应项内先冻结Spec与RED，不能把本清单当成未经验证的实现方案。

**Goal:** 原生自由发现产生有价值的实体、概念和解释，进入现有统一知识与发布流程，重要条款不遗漏、产品事实不失真、补充内容有标识、原文依据可点击。

**Architecture:** 复用WeKnora解析、候选发现、引用及必要的完整正文生成能力；Harness承担语义准入、事实核查、分段来源、独立审核和既有唯一Active发布。原生最终页面只可作为待核验草稿，不能直接升级为有证据的正式知识；不增加第二套发现器、队列或发布平台。

**Tech Stack:** 既有Go、Python Harness、Vue、PostgreSQL、原生Wiki任务与现有StageCall；沿既有测试环境和账号。

---

## 适用范围、现状与职责

2026-09-24用户已批准按本清单执行，并追加tracer bullet/deep modules：以一份真实材料验证最小端到端路径，随后按能力扩展；解析保真归解析模块，生成失败/恢复归已有任务模块，语义事实与来源归准入模块，发布归唯一Release模块。root唯一写者，独立agent只读诊断/评审。既有正常验证授权继续有效，不逐项重复询问。每项新增合同仍先Spec与RED。

当前执行：P0-1/P0-2前置软件460c664cf已部署；正常网页上传确认5014字符输入及14行恢复。新原生发现成功，但引用单次返回OUTCOME_UNKNOWN，健康正文基线BLOCKED。P0-3一次请求内校验复用与阶段取消软件定向回归/独审通过，尚未部署或证明真实发布通过；同候选Linux新旧21.026s/17.234s，来源合同定向90.398s通过。详见同目录证据入口及`docs/insurance-kb/evidence/830-g35/native-recheck-20260924.md`。

用户2026-09-24先要求“按照这个思路，梳理下要做的事项”，随后批准执行。沿既有G35-R1—R7，不另起Goal；原梳理阶段仅改计划，后续实施按各项合同推进。适用Spec：`openspec/changes/129-830-g3-catalog-batch/specs/catalog-batch/spec.md`。原计划`2026-09-23-830-g35-knowledge-admission.md`保留历史与已冻结合同，本文件作为后续执行顺序入口。

当前源码cb69e41ae；字段兼容、语义准入与purpose-v2已有修复，Harness制品已构建未部署；片段标识/引用、更新和重放已有软件能力，真实非空Wiki验收未闭合。R4正式实体关系、R6依赖隔离尚未实现。原生基线11页属于降级样本，18项为7完整/7部分/2缺失/2错误，不是健康质量基线。正式发布仍有超时，Active保持epoch17。

唯一执行/写入Owner=root；独立Reviewer只读。表中路径是调查入口及已有归属，不自动授权扩大修改面；查清根因后只扩至必要文件，并在原OpenSpec中冻结行为与反例。不存在为原生单独放宽正式发布门禁的例外。

## 执行顺序与依赖

| 顺序 | 事项 | 类型/现状 | 对应要求 | 交付与完成标准 |
|---|---|---|---|---|
| P0-1 | 原文和解析输入对齐 | 根因待查 | R1/R3/R7 | 明确表格丢失发生点；原生和G3.5使用同版完整原文，差异有记录 |
| P0-2 | 调用失败与降级状态治理，取得健康原生基线 | 引用失败、页面缺失却completed已复现 | R1/R5/R7 | 原生发现、引用、生成均有成功回执；失败不冒充质量成功，成功计算不丢 |
| P0-3 | 解决正式发布超时 | 阻断，根因未确认 | R1/R5 | 同实际运行环境定位并修复，正常流程完成审核/发布，旧版本与权限约束保持 |
| P1-1 | 高召回发现和完整正文生成 | 提示词已有，完整生成边界待比较 | R1/R2/R7 | 获得真实有价值非空知识；按证据决定是否接原生正文草稿 |
| P1-2 | 语义去重、事实保真、模型补充和原文定位 | 部分软件已实现，待完善/实测 | R2/R3 | 重要规则不误拒；错公式不放行；混合页逐段标识并可定位 |
| P1-3 | 必要实体和正式关系接入 | 未实现 | R4 | 复用既有实体图/Schema，保留主客体、条件、版本、证据 |
| P1-4 | 最小依赖范围隔离及增量恢复 | 未实现 | R5/R6 | 一个候选失败不清空无依赖知识；旧页保留；最终结果重新审核 |
| P2-1 | 集中部署和首条完整业务流程 | 未执行最终配置 | R1—R6 | 正常上传到发布/搜索/来源点击完成，部署与质量回执分别记录 |
| P2-2 | 覆盖、保真、重复/增量及成本验收 | 未完成 | R7 | 固定样本+有界独立材料验收，完整报告有效知识、错误、遗漏与成本 |

P0-1→P0-2→P1-1提供可信对照；P0-3的只读/离线诊断可独立推进，不等新的模型结果。P1各项按接口依赖收口后进入P2。当前优先动作是P0-1，不先连续重跑模型。部分代码已完成的事项只补真实缺口，不整套重写。

## Task P0-1：对齐原文、解析器和模型实际输入

**入口文件：** `docreader/parser/pdf_parser.py`、`docreader/tests/test_pdf_router.py`、`internal/application/service/knowledge_process.go`、`internal/application/service/wiki_ingest.go`、`internal/application/service/g3_native_discovery.go`、`frontend/src/views/knowledge/KnowledgeBaseEditorModal.vue`。

- [ ] 比较既有两份PDF的SHA、解析引擎实际选择、上传覆盖、结构化原文与chunk内容，定位年度表格从哪一步消失。
- [ ] 分别记录不重叠原文、带重叠chunk总长、模型拼接正文，避免将6123与4591直接相减当漏字。
- [ ] 如为解析或配置适配缺陷，先在对应入口冻结窄场景与失败反例；仅修责任模块。若仅配置差异，则修对照配置并保留事实，不制造产品补丁。
- [ ] 通过正常平台入口获得同版完整文本、表格和引用定位；保留旧失败制品，不手工编辑原文凑一致。

**检查：** 表格年度行、公式、迟报例外和演示边界都进入发现输入；同源跨路径内容差异可解释。定位PDF路由缺陷后运行`cd docreader && uv run pytest tests/test_pdf_router.py -q`；测试环境错误不计RED，若根因在其他模块则更换为对应最小回归。

## Task P0-2：处理EOF、降级结果与原生健康基线

**入口文件：** `internal/application/service/wiki_ingest_batch.go`、`internal/application/service/wiki_ingest_cite.go`、`internal/application/service/wiki_ingest_cite_test.go`、`internal/application/service/wiki_ingest.go`；现有模型调用及任务追踪模块沿实际调用栈确认。

- [ ] 按实际请求时间核对连接EOF、网关和调用回执，区分明确失败、已成功、结果未知；不把EOF等同于“请求没发送”。
- [ ] 冻结引用失败、单页生成失败、首次发现失败的状态/恢复要求；复用现有任务与StageCall能力，禁止多层重试叠乘。
- [ ] 增加反例：引用失败不能据候选短说明把产品事实标为有原文支持；局部失败必须显示部分完成/需处理；成功兄弟结果保留。
- [ ] 按实际接口实现必要的状态与恢复修复，未知发送不自动重发；原生直写实验与正式准入的语义状态明确区分。
- [ ] 已建实验库保留用于失败恢复/增量验证；其中已有页面会影响原生发现和合并，不能把重试结果当干净基线。健康standard基线在同一workspace、同环境下新建空隔离库，通过正常入口执行一次，固定原文/模型参数，保留发现、引用、正文和失败成本；不重置或删除旧实验数据。

**完成：** 引用和各正文生成阶段有可检查的成功结果；仅有completed/页面数不算通过。若基础调用仍不稳定，保留失败事实并先解决调用层，不盲目扩大对照次数。变更后以实际反例测试名定向运行Go service测试，不把全包长测作为反复诊断手段。

## Task P0-3：正式发布超时定位与修复

**入口文件：** `internal/application/service/wiki_release_automated.go`、`internal/application/service/concept_free_wiki_830_g3.go`、`internal/application/service/concept_source_authority_830_g2.go`、`internal/application/service/g3_published_read_reuse.go`、`internal/application/service/wiki_release_automated_test.go`。

- [ ] 在实际容器约束下重放已保存13.5MB候选的只读校验，分开测解析、重复校验、来源查询、数据库等待、取消与CPU限额影响。
- [ ] 形成可复现根因，先冻结失效场景与RED，再做最小修复；不靠增大超时或跳过校验达成通过。
- [ ] 核查优化后仍验证权限、来源版本、候选/审核身份、当前Head和发布并发；失败不得改Active。
- [ ] 保存的旧候选仅用于只读性能/恢复诊断，不为测性能激活旧失败候选。软件修复进入P2后，以当时重新审核通过、授权与Head依赖均有效且不会损失已有知识的候选，通过正常平台完成真实发布并记录时延；性能验证不计作质量验收。

**完成：** 真实请求不再超时，完整约束通过；本机13秒不能代替容器证明。若同环境诊断需要新增工具链，先复用当前构建能力，不重复无CGO交叉编译失败尝试。

## Task P1-1：高召回发现与完整正文

**入口文件：** `internal/agent/prompts_wiki.go`、`internal/application/service/g3_native_discovery.go`、`harness/src/insurance_harness/product_ingestion/native_discovery.py`、`native_discovery_stage.py`、`native_admission.py`（后三者在同一product_ingestion目录）、`docs/insurance-kb/evidence/830-g35/insurance-native-purpose-v2.txt`。

- [ ] 记录健康原生standard的候选和完整正文，按现有18项及有效概念解释核对。
- [ ] 准备exhaustive+保险Purpose的版本化配置；强调重要短规则、权利义务、对象、条件、例外和演示边界，不要求固定页数，不把测试答案写进提示词。
- [ ] 比较原生完整正文与G3.5准入生成结果：如已充分承接则不新增阶段；如确认原生正文提供稳定有效增量，则在原Spec冻结最小草稿输出接口后复用WikiPageModify。
- [ ] 如引入草稿：沿现有StageCall保存raw/输入身份，草稿不直写正式Wiki；准入不再重复发现、不无故完整重写一遍草稿，新增调用收益和成本必须记录。
- [ ] 新提示词/输入策略变化按真实依赖失效；不声称旧raw可exact复用。

**完成：** 有实际有用的非空自由知识、可读完整解释、无强行凑页。组合配置对比只报告组合效果；若要归因单独Purpose，再补必要的单变量对照，不默认跑多轮。

## Task P1-2：语义准入、事实保真及来源展示

**入口文件：** `harness/src/insurance_harness/product_ingestion/native_admission.py`、`native_admission_stage.py`、`source_geometry.py`、`discovery_composition.py`；`harness/tests/product_ingestion/test_native_admission.py`、`test_source_geometry.py`、`test_discovery_provenance_review.py`；`frontend/src/views/knowledge/schema-wiki/ConceptFreeWiki830G2.vue`及既有知识来源适配器。

- [ ] 复用cb69已有修复，补真实反例：同主题字段不等于通用概念/完整流程重复；“常见”不是拒绝理由；字段失败也不靠同名自由页规避。
- [ ] 保持产品事实、通用概念和解释文章的语义职责；已有产品按确认过的发行人+完整名称+年份关联，不重新制造身份歧义。
- [ ] 将本次错贷款公式、现金价值减额、年龄边界、免责退款对象、告知退费差异纳入保真回归与独立审核样例；可算公式用确定性核对，复杂语义仍需原文审核，不建关键词清单冒充理解。
- [ ] 事实段绑定精确引文及原文位置；补充解释标模型生成；无依据的产品金额/义务不能仅换标签放行。引用失败不自动变成“模型生成”而绕过证据要求。
- [ ] 纯生成的通用解释按适用质量维度审核，不伪增原文证据分，也不因缺少原文而一概删除；真实页面验证其可正确通过或给出具体拒绝原因。
- [ ] 检查正文、摘要及相关知识预览的一致性；页内有来源不代表全页有依据。
- [ ] 真实已发布页验证纯生成、混合页、原文页码/高亮和无伪造引用。

**定向验证：** `cd harness && uv run pytest tests/product_ingestion/test_native_admission.py tests/product_ingestion/test_source_geometry.py tests/product_ingestion/test_discovery_provenance_review.py -q`。仅修改相关模块后运行；真实UI验收不能由fixture替代。

## Task P1-3：必要实体与正式业务关系（R4）

**复用入口：** `harness/src/insurance_harness/knowledge_compiler/service_schema_catalog_830_g3.py`、`batch_concept_compile_830_g3.py`、`harness/tests/test_service_schema_catalog_830_g3.py`及既有实体图/关系合同。

- [ ] 将原生实体候选分清：已存在实体、确有独立身份的新实体、普通类别/概念。未命名“提前给付型重疾险”不能凭空建一个具体产品。
- [ ] 在原Spec冻结本场景必要实体/关系映射和字段；先复用既有服务Schema与实体图，不并建自由页实体系统。
- [ ] 添加反例：跨版本混淆、同名异主体、仅有相关链接冒充正式关系、条件/证据缺失。
- [ ] 实现正式关系主客体、关系含义、作用条件、版本和证据的准入/编译/页面导航；保留未决处置和原因。

**完成：** 必要结构可查询和导航，不能用一篇文章或wikilink冒充结构关系已实现。详细写域及测试在映射合同冻结后收窄。

## Task P1-4：依赖隔离、失败更新与增量复用（R5/R6）

**入口文件：** `harness/src/insurance_harness/product_ingestion/native_pipeline.py`、`native_admission.py`、`discovery_composition.py`、既有审核/编译边界；`harness/tests/product_ingestion/test_native_pipeline.py`、`test_native_admission.py`、`test_pipeline_runtime.py`。

- [ ] 冻结显式候选依赖与最小隔离范围：旧响应无依赖字段不等于没有依赖；混合新增/更新、共享定义、环及冲突须有确定处理。现有v2提案仅供审查，不视为已生效协议。
- [ ] 写最小反例：A失败但独立B保留；依赖A的C不能通过；新定义被裁剪后不能留悬空引用；失败更新保留旧正文。
- [ ] 在既有pipeline按依赖剔除受影响增量，保留raw/成功计算；不新增队列或发布权威。
- [ ] 裁剪后对最终成员集合重新绑定审核hash，旧集合的审核不能复用为新集合授权；审核自身失败也有明确隔离范围。
- [ ] 验证重复上传不重复创建；只重算实际输入/策略改变部分，来源未变可复用；未知发送不盲重发。

**完成：** 原先“任何pending清空整组自由成员”的反例消失，同时依赖不完整内容不被发布。定向测试从`cd harness && uv run pytest tests/product_ingestion/test_native_pipeline.py tests/product_ingestion/test_native_admission.py -q`起，真实worker恢复用选定场景验证。

## Task P2-1：集中部署及完整业务验证

- [ ] 汇总最终Spec→实现→测试→commit/制品→部署矩阵，独立审查冻结身份；仅修复未关闭问题，不把所有切片塞入未经复核的大补丁。
- [ ] 对齐Purpose/模板hash/粒度与运行策略，核实旧任务、待处理调用及回滚制品；已有cb69镜像只有源码仍适用才复用，新增代码必须使用对应新制品。
- [ ] 按当前服务身份执行集中部署，分别核对健康、权限、模型和Active，不迁移或改动无关服务。
- [ ] 正常网页完整上传/处理→候选与状态→审核→发布→搜索→知识页→原文点击；关闭页面后平台继续处理。
- [ ] 交付可直接查看的非空新知识页面与真实回执；未运行维度标NOT RUN，失败标BLOCKED，代码通过不推导业务通过。

## Task P2-2：最终质量、覆盖与成本验收

- [ ] 守护说明书18项逐项追踪到字段、已有知识、新自由知识或明确待处理；关键规则应完整且正确，不要求18个页面，未解决漏项不得写成完成。
- [ ] 抽查完整PDF其余章节，补充先前清单未覆盖的有用概念；检查表不作为发现输出的封闭名单。
- [ ] 执行前冻结一个已有不同类型材料作为有界独立验证，优先含长文/跨窗口/主附险或服务关系；不将其答案注入Prompt，不扩大为全库重跑。
- [ ] P1/P2每次真实执行前，按窗口与页面规模在既有任务回执冻结调用预算、停止条件和计数口径；新发送、复用及结果未知分别记账，失败用量缺失标未知，不另建预算平台。
- [ ] 核查产品数值/公式/条件/例外无已知错误，原文依据均可定位，模型补充有清楚标志；重要漏项、误拒和错合并均关闭。
- [ ] 验证一次重复、一次真实增量、一次失败恢复；记录新调用、复用、未知失败用量、耗时、必要成本及有效知识变化，不把缺失账单当0。
- [ ] 对照原生完整输出和最终G3.5结果；披露输入/模型/配置差异与单样本限制。未通过不宣称“高于原生”。

## 不增加的工作与完成口径

不另建workspace，不更换账号，不并建第二Wiki发布体系，不用强模型代替当前问题，不为凑数量制造实体，不复制开源项目整套流程。必要的实验草稿与正式知识严格区分；参考原生能力不继承已确认的错误降级或失败覆盖行为。

本次“梳理事项”完成标准：九项有顺序、职责、依赖、验收与现状，独立审查无阻断，入口指向一致。**G3.5完成标准仍是以上功能与真实业务验收全部闭合**；当前计划完成不改变G3.5未完成结论。

## P0健康对照所需的最小交付窗口（2026-09-24）

P0-1/P0-2软件已过独审与有界验证，需将这些修复放入同一现有测试环境才能取得可信原生基线；这是用户批准顺序中的正常验证前置。root冻结当前源码，APP/UI各至多一次必要构建，DocReader复用当前精确运行镜像、仅COPY已验收pdf_parser.py至既有路径；不重装依赖，不迁移数据库。Harness暂保持当前制品/运行配置，P1/P2再按依赖合并交付。构建全部完成、核对任务静默后才切换；保留旧容器/配置/镜像，失败即恢复，不在真实任务运行中热切换。切换后验证健康、旧Active一致、原生失败徽标，再通过正常网页在同workspace新空实验库上传同一完整PDF一次。模型/参数沿原对照，不触发正式Active发布，不把原生published等同于产品发布。此切片不使P0-3/P1/P2完成。

P0-3实施收窄（2026-09-24）：实际只读A/B为18.214/25.044秒，不足以解释历史400秒；按Spec G3-AUTO-5补充，先集中修复一次自动激活内的验证复用与阶段取消。新私有结果只服务该请求，不引入cache授权/持久token/新执行器；既有独立source入口无结果时仍完整验证，错误的已传入结果fail closed。最终性能和有效发布仍需真实验证，不把该软件切片写成全部超时已解决。
