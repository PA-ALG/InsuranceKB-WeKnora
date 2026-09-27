# G3.5 自由 Wiki 质量与覆盖度收口执行计划

> **For agentic workers:** 使用 superpowers:executing-plans 按项执行；独立审查遵守仓库规则，root为唯一写者和集成Owner。清单采用checkbox跟踪。本文整理已批准方向及剩余事项；尚未确定的协议/根因必须在对应项内先冻结Spec与RED，不能把本清单当成未经验证的实现方案。

**Goal:** 原生自由发现产生有价值的实体、概念和解释，进入现有统一知识与发布流程，重要条款不遗漏、产品事实不失真、补充内容有标识、原文依据可点击。

**Architecture:** 复用WeKnora解析、候选发现、引用及必要的完整正文生成能力；Harness承担语义准入、事实核查、分段来源、独立审核和既有唯一Active发布。原生最终页面只可作为待核验草稿，不能直接升级为有证据的正式知识；不增加第二套发现器、队列或发布平台。

**Tech Stack:** 既有Go、Python Harness、Vue、PostgreSQL、原生Wiki任务与现有StageCall；沿既有测试环境和账号。

---

## 2026-09-27 最终集成补充

- [x] 完整业务链和原文点击已到epoch27，质量遗漏统一后置。
- [x] CI发现的测试类型声明修正：全mypy733/fullruff通过，25文件独审0BLOCKER。
- [x] R6-ROUTE-1通用多材料误路由根因修复，旧fixture保持；79定向及持久恢复PASS。
- [x] 9ebf5bd11 Harness-only交付06:18:25Z PASS；原任务/Head/账本只读PASS，新模型0。
- [ ] 原PR130修复后精确HEAD远端CI及机械集成；不得沿用a7e2失败或更早PASS。

## 2026-09-27 最终流程门禁澄清

独立收口复核：真实非空多窗口是补充证据目标，不是R6/REF-TARGET协议的强制门禁；
REF-TARGET-4允许全窗合法空结果，不能为凑页增加模型重跑。双窗完整输入、聚合、恢复、
发布和verify已有epoch25真实证据；非空survivor有软件/worker覆盖，非空多窗live保留NOT RUN。
个别字段遗漏及R7的2部分/1缺失依用户最新要求进入统一质量维护，不阻断本轮流程。
本轮新增唯一通用阻断是发布缓存重启后[]丢为null：bcfce2fa6已修复，发布→重启→base
snapshot真实接口回归GREEN，定向cache/base/transfer/citation PASS82.168秒，独审0BLOCKER。
App-only交付及新正常上传d6d071a6至epoch27发布/verify已PASS，原文第2页高亮PASS。
13jobs首次成功、7新语义调用；新free0保持真实partial_success。最终PR130精确HEAD CI/合入待执行。
service966全包默认10分钟总超时仅记incomplete，不声称PASS；不重复无界全包长测。

## 2026-09-27 用户最新范围修订

仅解决跨页、表格、截断等通用能力缺陷；已完整进入模型输入的个别字段遗漏后置统一维护，
不逐case调参，也不再据此阻断本轮G3.5。历史R7质量结果保留，不改写成质量全覆盖PASS。
SRC-REUSE-1—4已由3da99755c完成：92测试、两次独审0BLOCKER、Harness-only部署及原run GET PASS；5新/3历史，Head/ledger不变。
通用输入能力独立复核同步进行，R6非空多窗口真实语义结果及远端CI/最终集成仍须如实区分。

## 2026-09-27 当前执行覆盖（以下旧清单保留历史，不代表当前未实现）

- [x] 跨页发行人证据修复、独审、Harness部署d0157306；正常护理条款身份成功。
- [x] 长材料原生2窗口发现/引用完整，23及28候选；非去重计数。
- [x] 正常上传→编译→审核→发布→验证到epoch24，等待期第2页原文高亮可点击。
- [x] R4关系、R6多窗口并集/最多一次裁剪重审软件已部署；不重复重写。
- [x] 通用v4引用目标公开schema修复：8 RED，58定向PASS，独审0BLOCKER、9871a880部署完成。
- [x] 原恢复入口c6a06d47复用13语义调用、新增2准入，双窗签名聚合，正常发布/verify到epoch25；新free0，非非空质量PASS。
- [x] R3模型生成标志及R4正式关系真实非空Active页面：031a2交付后run41b7009c发布2成员到epoch26；关系导航/原文第2页高亮PASS。
- [ ] R6非空多窗口聚合真实页面（空结果诚实保留，不以凑页达标）。
- [x] R7统一比较已执行：18项15完整2部分1缺失；引用位置64条PASS、旧页段落支持有缺口，成本独立列账；结果不等于质量PASS。
- [ ] R7质量剩余：通用字段完整性、原生利益演示覆盖、逐段来源支持集中维护；非单case调参。

统一质量QUAL1—6已由031a2fb83实现：复用field_comparison模块提供有效字段正文；
纯MODEL_GENERATED证据维仍0，显式新policy按80适用满分评估，64/48为资格阈值；
六维raw不改，旧审核不重释。32路径独审0BLOCKER，App/Harness制品完成，交付中。旧coverage资产未经当前集成/真实质量验收，不整体部署，
不把未闭合深度审核强加为正常流程新前置。PENDING人审override/KMS不是当前必需。

## 适用范围、现状与职责

2026-09-24用户已批准按本清单执行，并追加tracer bullet/deep modules：以一份真实材料验证最小端到端路径，随后按能力扩展；解析保真归解析模块，生成失败/恢复归已有任务模块，语义事实与来源归准入模块，发布归唯一Release模块。root唯一写者，独立agent只读诊断/评审。既有正常验证授权继续有效，不逐项重复询问。每项新增合同仍先Spec与RED。

当前执行（2026-09-24 DeepSeek恢复后）：P0-1/P0-2前置软件460c664cf已部署；同一隔离库原任务在DNS修复后完整跑通原生Wiki，2实体18概念共22页、引用/正文/收尾均成功，25调用成功。18项独审14完整/4部分；模型补充标识、精确引文与PDF预览尚未通过，辅助文档摘要保留早期失败，G3.5未完成。报告见`docs/insurance-kb/evidence/830-g35/native-deepseek-baseline-20260924.md`。P0-3请求内校验复用与取消软件通过但未部署/真实发布；P1复核确认现有准入已接收窗口全文并能生成完整正文，先验证修订后的准入；尚无依据新增逐候选正文生成阶段。同名误拒修复进展见`docs/insurance-kb/evidence/830-g35/native-semantic-admission-20260924.md`，之后继续R4/R6与P2。

用户2026-09-24先要求“按照这个思路，梳理下要做的事项”，随后批准执行。沿既有G35-R1—R7，不另起Goal；原梳理阶段仅改计划，后续实施按各项合同推进。适用Spec：`openspec/changes/129-830-g3-catalog-batch/specs/catalog-batch/spec.md`。原计划`2026-09-23-830-g35-knowledge-admission.md`保留历史与已冻结合同，本文件作为后续执行顺序入口。

计划首次梳理时源码cb69e41ae；字段兼容、语义准入与purpose-v2已有修复，Harness制品已构建未部署；片段标识/引用、更新和重放已有软件能力，真实非空Wiki验收未闭合。R4正式实体关系、R6依赖隔离尚未实现。原生基线11页属于降级样本，18项为7完整/7部分/2缺失/2错误，不是健康质量基线。正式发布仍有超时，Active保持epoch17。

唯一执行/写入Owner=root；独立Reviewer只读。表中路径是调查入口及已有归属，不自动授权扩大修改面；查清根因后只扩至必要文件，并在原OpenSpec中冻结行为与反例。不存在为原生单独放宽正式发布门禁的例外。

2026-09-24 最新确认：用户回复“可以”，调整为先 P1-4/R6 候选隔离，接首条非空完整流程验证，再 P1-3/R4 正式关系。其他要求与单一发布权威不变。R6 首切片源码/本地验证已实现，独立审查0 BLOCKER，未部署；多窗口最小隔离及审核失败后二次裁剪仍待后续切片，不能视为全部 R6。

## 执行顺序与依赖

| 顺序 | 事项 | 类型/现状 | 对应要求 | 交付与完成标准 |
|---|---|---|---|---|
| P0-1 | 原文和解析输入对齐 | 清理误删已修复部署，正常上传输入验证PASS | R1/R3/R7 | 明确表格丢失发生点；原生和G3.5使用同版完整原文，差异有记录 |
| P0-2 | 调用失败与降级状态治理，取得健康原生基线 | 失败治理已部署；DeepSeek健康Wiki基线PASS，原Gemini未知记录保留 | R1/R5/R7 | 原生发现、引用、生成均有成功回执；失败不冒充质量成功，成功计算不丢 |
| P0-3 | 解决正式发布超时 | 重复验证/取消首条软件切片PASS；完整发布仍未验证 | R1/R5 | 同实际运行环境定位并修复，正常流程完成审核/发布，旧版本与权限约束保持 |
| P1-1 | 高召回发现和完整正文生成 | 提示词已有，完整生成边界待比较 | R1/R2/R7 | 获得真实有价值非空知识；按证据决定是否接原生正文草稿 |
| P1-2 | 语义去重、事实保真、模型补充和原文定位 | 部分软件已实现，待完善/实测 | R2/R3 | 重要规则不误拒；错公式不放行；混合页逐段标识并可定位 |
| P1-3 | 必要实体和正式关系接入 | 未实现 | R4 | 复用既有实体图/Schema，保留主客体、条件、版本、证据 |
| P1-4（调整为先行） | 最小依赖范围隔离及增量恢复 | 单响应首切片本地验证/独立审查通过，未部署 | R5/R6 | 一个候选失败不清空无依赖知识；旧页保留；最终结果重新审核 |
| P2-1 | 集中部署和首条完整业务流程 | 未执行最终配置 | R1—R6 | 正常上传到发布/搜索/来源点击完成，部署与质量回执分别记录 |
| P2-2 | 覆盖、保真、重复/增量及成本验收 | 未完成 | R7 | 固定样本+有界独立材料验收，完整报告有效知识、错误、遗漏与成本 |

P0-1→P0-2→P1-1提供可信对照；P0-3的只读/离线诊断可独立推进，不等新的模型结果。P1各项按接口依赖收口后进入P2。健康DeepSeek基线已取得；旧Gemini未知调用仍保留且不重发，当前优先验证P1准入质量和已确认的软件缺口。部分代码已完成的事项只补真实缺口，不整套重写。

## Task P0-1：对齐原文、解析器和模型实际输入

**入口文件：** `docreader/parser/pdf_parser.py`、`docreader/tests/test_pdf_router.py`、`internal/application/service/knowledge_process.go`、`internal/application/service/wiki_ingest.go`、`internal/application/service/g3_native_discovery.go`、`frontend/src/views/knowledge/KnowledgeBaseEditorModal.vue`。

- [x] 比较既有两份PDF的SHA、解析引擎实际选择、上传覆盖、结构化原文与chunk内容，定位年度表格从哪一步消失。
- [x] 分别记录不重叠原文、带重叠chunk总长、模型拼接正文，避免将6123与4591直接相减当漏字。
- [x] 如为解析或配置适配缺陷，先在对应入口冻结窄场景与失败反例；仅修责任模块。若仅配置差异，则修对照配置并保留事实，不制造产品补丁。
- [ ] 通过正常平台入口获得同版完整文本、表格和引用定位；保留旧失败制品，不手工编辑原文凑一致。

**检查：** 表格年度行、公式、迟报例外和演示边界都进入发现输入；同源跨路径内容差异可解释。定位PDF路由缺陷后运行`cd docreader && uv run pytest tests/test_pdf_router.py -q`；测试环境错误不计RED，若根因在其他模块则更换为对应最小回归。

## Task P0-2：处理EOF、降级结果与原生健康基线

**入口文件：** `internal/application/service/wiki_ingest_batch.go`、`internal/application/service/wiki_ingest_cite.go`、`internal/application/service/wiki_ingest_cite_test.go`、`internal/application/service/wiki_ingest.go`；现有模型调用及任务追踪模块沿实际调用栈确认。

- [ ] 按实际请求时间核对连接EOF、网关和调用回执，区分明确失败、已成功、结果未知；不把EOF等同于“请求没发送”。
- [x] 冻结引用失败、单页生成失败、首次发现失败的状态/恢复要求；复用现有任务与StageCall能力，禁止多层重试叠乘。
- [x] 增加反例：引用失败不能据候选短说明把产品事实标为有原文支持；局部失败必须显示部分完成/需处理；成功兄弟结果保留。
- [x] 按实际接口实现必要的状态与恢复修复，未知发送不自动重发；原生直写实验与正式准入的语义状态明确区分。
- [x] 已建实验库保留用于失败恢复/增量验证；其中已有页面会影响原生发现和合并，不能把重试结果当干净基线。健康standard基线在同一workspace、同环境下新建空隔离库，通过正常入口执行一次，固定原文/模型参数，保留发现、引用、正文和失败成本；不重置或删除旧实验数据。

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

- [x] 记录健康原生standard的候选和完整正文，按现有18项及有效概念解释核对（DeepSeek基线：14完整/4部分，非G3.5质量通过）。
- [x] 准备exhaustive+保险Purpose的版本化配置（已离线校验，尚未部署实跑）；强调重要短规则、权利义务、对象、条件、例外和演示边界，不要求固定页数，不把测试答案写进提示词。
- [ ] 比较原生完整正文与G3.5准入生成结果（现有准入已接全窗口原文；旧零产出由旧语义拒绝/未决隔离影响，先验证修订版再决定新增阶段）：如已充分承接则不新增阶段；如确认原生正文提供稳定有效增量，则在原Spec冻结最小草稿输出接口后复用WikiPageModify。
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

2026-09-24只读边界复核：既有服务Schema只有结构定义，实体页面图/原生graph/wiki link没有正式关系发布合同。R4需新增明确版本化的Candidate relation成员贯穿既有审核、Go重放和读取；不能视为薄接线。推荐最小产品→险种概念切片见`docs/insurance-kb/evidence/830-g35/r4-capability-boundary-20260924.md`；此为草案，未冻结生产接口。已询问是否先R6及非空完整流程，未收到答复前不记录执行顺序已改变。

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

## R6 后第一条真实非空纵切设计（2026-09-24 用户继续确认）

业务目标是让同一份完整材料产出真实可阅读、可审核、可发布、可回查的自由知识，并逐项解释覆盖/遗漏。先完成这一条纵切，再扩 R4 正式关系和跨窗口最小隔离。方案选择沿既有流水线接通：直接扩成全局依赖编排会增加未验证范围；复制原生直写链会引入第二发布路径；当前方案复用成功计算与唯一 Release，仅补实际端到端缺口。

### 深模块职责与窄接口

| 责任模块 | 输入 → 输出 | 封装的复杂性与失败边界 |
|---|---|---|
| 原生候选端口与 collection | 已封存来源/策略 → 签名窗口候选快照 | 原生发现、引用、完整覆盖、持久 raw；未知发送不盲重发 |
| native_admission + StageCall | 原候选、完整窗口原文、已有语义 → 完整已验证响应 | 身份、来源片段、版本、更新前置条件；结构不合法的窗口不晋升 |
| native_dependency_selection | 已验证响应/成员 → 闭包选择与隔离回执 | 显式依赖、共享成员、结构依赖、环及孤定义固定点；不做 I/O、状态推进或发布 |
| native_pipeline | collection/投影 → discovery delta/摘要 | 整次运行的隔离资格和汇总；只在单依赖域允许部分保留，多窗口仍整组围栏 |
| final review / composition | 完整计划、保留成员、最终组合 → exact hash审核授权 | 语义独立性、来源与生成标志、条件保真；失败不发布，不复用旧集合授权 |
| 既有发布与读取模块 | 已审核 Candidate/当前Head → 唯一Release/验证读取 | 权限、来源版本、并发与旧页保留；请求内复用验证不形成跨请求缓存授权 |
| 状态API / Go桥 / 页面 | 安全摘要 → 可见已发布及待处理数量 | 状态仅由Harness计算；桥仅白名单透传；页面不读取raw/依赖图，也不创建工作流 |

本轮确认展示链路缺口：Go桥遗漏三个新摘要字段，页面仅ACCEPTED显示发布。已在Spec冻结并先跑HTTP/组件RED；只补这两个边界。领域依赖图和候选归属仍留在Harness。没有为了“深模块”横向抽象通用引擎。

### 交付窗口

1. 核对审查冻结源码与目前dirty文件，关闭展示补充独审，记录准确源码/配置identity。旧审查不覆盖新增代码。
2. 对当前现有APP/Harness/UI执行一次集中交付：每类至多一次必要构建；精确制品存在则复用，依赖lock/基础镜像不变，不重装依赖。DocReader/数据库/向量库维持当前版本，无migration。
3. 只读核对当前容器身份、配置、Head及队列；逐路径比较正式运行配置与准备配置，仅允许已批准模板/Purpose/粒度/依赖策略变动。正式Harness模型/endpoint不随原生DeepSeek实验切换。
4. 保留旧容器/配置/制品。仅在新制品全部就绪且任务静默后切换；异常立即停止当前窗口并按已有回滚路径恢复。不得在活跃任务中热换代码，不重复构建试错。
5. 首条业务样本复用已验证完整说明书及同一账户/workspace；优先利用平台既有来源指纹和正常入口，不修改原文/旧候选/DB，不删除原生基线。若新策略使旧checkpoint不可复用，则通过正常新任务处理同文件并记录此原因，不绕过policy身份检查。
6. 实际执行前从计划窗口/字段任务冻结调用预算、停止条件和计数；未知结果保留为未知，成功步骤按真实依赖复用。首条纵切不自动扩全库/多材料。

### 第一条纵切的可见验收

至少有一项独立审核通过并经正常正式发布的有用非空自由知识；源支持片段可点击查看相应原文，模型补充清楚标识；失败更新旧页保留；“部分已发布+部分待处理”界面诚实并存。核对18项覆盖清单及原文其他章节、条件/例外/对象/年份/公式；未完成项明确记录。页面数量、容器健康、fixture GREEN都不能替代此验收；本条通过仍不代表R4、跨窗口R6和全部G3.5通过。

## 首条真实纵切后的准入边界设计（2026-09-24）

真实执行见 `docs/insurance-kb/evidence/830-g35/r6-real-tracer-20260924.md`：软件已交付，任务33dd1349失败。准入成功响应存在offset、concept_ref标识混用、9个孤立definition三个共同输出合同问题；另有宿主合盖休眠导致编译租约耗尽。不能以单点修正后立即再部署作为下一步。

### Tracer bullet

下一条仍为“同一份说明书→完整候选→有效Wiki页面→逐段来源/模型生成标识→完整审核→单一Release→页面回点”。先用真实 raw 做离线完整预检，当前 raw 必须继续失败于孤定义，不能把反事实数据写回。新准入合同明确：独立有用概念应生成 Wiki page；definition 是供页面引用的术语定义，并非任意孤立概念的替代载体。允许概念页无新definition，不为凑数复制正文或自动造配套页；通用性本身不构成拒绝理由。此澄清仍保持现有正式成员合同，不新增 serving 权威。

### Deep module 与复用边界

- 唯一负责模块仍是 native admission；其 stage 只负责调用/回放及持久记录。投影前的纯 wire preflight 接收原始响应、验证过的上下文/来源与版本，返回完整校验后的投影及版本化审计，或结构化失败；不承担审核、重试、发布。
- 精确 occurrence 枚举可从既有 D 字段定位器提取成公开纯原语；不能跨模块调用私有 `_resolve_g3_d_evidence`，其多命中展开策略不适用于 native evidence_indexes。字段仍保留自己的多命中合同。
- 仅R6/v2允许可证明的机械归位：原start有效则不动；否则同source/offered span内唯一逐字quote才可重新定位。concept_ref仅在逐字等于本响应唯一canonical_key且没有现有identity/member_ref命名冲突时，才可映射对应member_ref。拒绝模糊/空白归一化/跨source、0或多处命中、歧义标识；不修改正文、provenance语义、decisions或候选集合。
- 必须保留原始provider raw和native_admission_response。新增版本化RULE回执绑定original/canonical/context/source hash，列JSON pointer、旧/新值及归位理由；strict projector、R6依赖闭包、PDF geometry与最终审核继续各自负责完整不变量。孤定义/伪证据等继续拒绝，不能利用R6隔离掩盖结构非法。
- producer/checkpoint派生产物升版，与模型输入身份分开；只要模型请求语义完全相同，已有成功raw应可复用。真正修改提示/response_schema说明时必须新模板身份，旧失败准入内容不得冒用为新合同输出。实现前应离线验证恢复计划实际能保留哪些成功阶段，不承诺未经证明的全量复用，不再默认重传整份材料。

### 冻结实现前的验证清单与顺序

1. OpenSpec对应R5/R6增量明确机械归位边界、完整预检、definition/page职责和审计/恢复身份。
2. RED覆盖中文/CRLF/emoji偏移、原offset正确的重复quote、唯一/零/多命中、source越界；member_ref/canonical_key冲突和未知引用；孤definition必须持续失败；v1不放宽。
3. 保存真实raw的链式反例：原始quote失败→仅offset仍foreign-ref→两类机械归位后仍orphan。这是协议诊断通过，绝非业务通过。以另外合法的完整响应证明端到端strict projection+依赖隔离+精确定位和原文/生成标识。
4. 统一补齐准入上下文的明确ref及page-use说明与样例，按原保险场景保留条件/例外/公式/对象；不额外引入逐页生成阶段。独立复核后，再冻结必要组件交付和最小新调用窗口；本轮构建/真实提交预算已结束。
5. 宿主合盖不改产品租约机制；下一真实窗口选择机器持续运行的时段。不要声称普通防空闲命令能解决合盖休眠。使用正常恢复入口，未知发送不盲重发。

本段是根因驱动的后续设计，尚未写上述preflight实现/RED，也没有执行新的模型调用/构建/部署。9个孤定义证明“仅offset修复即可跑通”不成立，须先关闭完整输出合同再推进真实纵切。R4及跨窗口R6仍未完成。

## 准入预检与同策略恢复切片结果（2026-09-24）

已先Spec/RED后实现纯预检、完整strict/geometry串接、projection v2和v2保险场景member_contract；首次92 PASS/1有意v1skip，加集成52 PASS。真实raw经5处机械归位仍孤定义失败。详见`docs/insurance-kb/evidence/830-g35/native-admission-preflight-20260924.md`。本段取代前文“尚未写preflight/RED”的状态。

发现修改system prompt/template会改变全局模型策略并拒绝成功调用复用。经独立设计复核，撤销该方案：新增成员职责/引用规则仅作为服务端版本化context，保持系统prompt、模板和完整运行配置原值；只改变准入input/operation。无需跨策略兼容，不删global hash。完整旧配置离线校验、原native policy一致、实际旧请求兼容检查PASS；新增持久worker恢复1 PASS：source/identity/field计数不变，6次原生发现/引用全部复用，仅1次新准入。它是本地恢复接线证据，未执行真实供应商恢复。

CURRENT=最终变更独审/冻结；NEXT_READY=仅Harness必要制品交付，复用现有配置和其它组件；随后正常网页恢复原任务并事前冻结必要调用预算，失败停止。当前新build/deploy/provider/business均0，真实质量/点击/非空发布、R4和完整G3.5未完成。不得部署先前废弃的新模板配置。

## 预检交付与真实断点验证结果（2026-09-24 15:11Z）

本段取代上段CURRENT：d8d99b85f Harness-only一次构建/交付PASS，完整配置/APP/UI/DocReader复用。第一次UI恢复16452cbb新增模型0，错误复用FAILED发现结果而字段发布epoch18；原checkpoint只在PARTIAL_SUCCESS检查发现失败，遗漏后续compilation FAILED。现已在同模块修复最早失效边界，健康阶段metadata-only、成功调用/unknown围栏保持；Spec/RED后42个不同测试PASS，独审0 BLOCKER，尚未部署该后续修复。

已只读/独审核对16452cbb现有恢复计划确实回到discovery，沿正常UI再执行一个单独冻结的有限窗口，复用已部署版本而不另构建。a9b39523新增准入1、复用8、模型返回成功；14候选→2页/0定义，旧孤定义消失，但两个quote各漏6处PDF行内CRLF，且原文evidence未绑定任何SOURCE_SUPPORTED段，完整输出仍非法。字段流程终态PARTIAL_SUCCESS/epoch19，自由发现FAILED，无非空自由知识发布。详细证据见native-admission-preflight-20260924.md；两窗口均已关闭，不能连续点击重试。

CURRENT=完整raw离线质量/证据合同复核；NEXT_READY=把证据选择与逐段来源归属集中到原准入/证据责任边界，复用原生source引用和已校验原文，先完整协议反例后实现。只改offset/删除换行/自动重标provenance都不足以闭合。九项Schema拒绝需比较真实字段语义与有效内容；候选/页面数量不代替覆盖。此后续方向尚未实现，需在现有OpenSpec冻结具体最小协议再RED。R4、跨窗口R6、正式质量/点击/完整G3.5仍未完成。

独立质量复核已关闭：9项去重8项由当前字段完整承接，c8漏中止期间不承担责任的后果；告知页遗漏投保人与被保险人的询问范围。下一条完整反例须同时覆盖这两项语义损失、逐字quote和SOURCE_SUPPORTED段/evidence归属，不能只通过格式测试。当前BLOCKER为4项，完整质量/点击仍未验收；不凭页面数量或字段verified状态推导覆盖。

### 2026-09-24 继续：原文编号准入 v3（设计复核后首切片）

复用调查：原生候选已成功；native_admission/source_options已提供精确span，strict/R6/geometry已有完整门禁。quote丢6处CRLF与证据未归属段需要把原文绑定交回程序。独审确认旧v2 system prompt不能冒充refs-only，且新增准入配置必须进入完整discovery恢复校验。

本切片先完成 G35-R5-WIRE-1—3：纯wire适配 → admission-only显式模板及同executor配置派生 → 原StageCall/完整阶段恢复 → 定向软件与原raw反例 → 独审 → 集中交付/新有限窗口。旧model和native_discovery字节不改，不新增兼容白名单/恢复器/队列/第二Wiki。spec已先冻结于129；root独占新增wire/policy及configuration/composition/stage/preflight/checkpoint_validation/checkpoints和相关tests。

Wire模型逐段text/origin/evidence_refs；服务端按既有完整span顺序展开exact evidence及indexes，复用原v2领域投影。旧v1/v2不改；MODEL/SOURCE必须由模型明确声明，不自动重标。完整span使首次来源高亮粒度为原chunk，不能声称句级最小引文。新prompt加强后果/对象范围，只是生成约束；全部REJECT尚不在现v6独立审核scope，4个真实质量阻断不能在此直接标PASS，后续需独立disposition覆盖切片和真实结果逐项核验。

RED：新wire参数旧预检不支持（9项失败）；可选admission配置旧loader extra_forbidden（1失败/6拒绝已有PASS）。先实现纯适配并22项定向GREEN，再推进新配置与worker接线。部署/provider/business本切片尚NOT RUN；旧真实窗口保持关闭。

2026-09-25本切片软件收口：完整94 PASS/1 SKIP，首审两项审计命名/反例覆盖阻断修复后35 PASS（与前组重叠）、非空stage1 PASS、ruff与7源码mypy PASS；revision2独审0 BLOCKER。详见native-admission-wire-20260925.md。自动全REJECT/零成员覆盖审核仍为后续明确缺口。本轮真实GET仍epoch19，未构建/部署/调用模型。下一物理结果为单独冻结Harness-only一次构建/可逆切换、一次UI恢复、最多准入1+审核1，四个真实质量阻断需对新结果逐项验证。

## 2026-09-25 审核作用域首修复及质量后续

wire v3已交付，43e71710真实准入成功但审核输入730770/300000 bytes失败，字段发布epoch20，自由页0。根因/质量证据见native-admission-wire-20260925.md末节。本轮窗口已关闭，后续不连续重试。

沿tracer bullet/deep modules，当前最小方案复用v6单entity接口，独审确认无须改prompt/model/config；直接提高预算不能解决输入随历史库膨胀的问题，全面v7审核改版则会扩大当前范围。root在原native_dependency_selection封装纯scope校验，原review stage调用，其他外部接口不变。

- [x] 冻结G35-R6-REVIEW-SCOPE-1/2；用真实stage无entity调用验证旧输出错误包含全库；校验scope冲突/多实体/缺绑定/篡改与全局concept保留。
- [x] 在native_dependency_selection.py实现唯一scope一致性；discovery_stage.py原入口构造对应index；保持非selection旧路径。
- [x] 跑相关review/replay/组合回归、真实14实体全链式离线重放；确认214790 bytes、同finalhash/完整selection，不复用旧全库review。
- [x] 冻结identity revision2独审0 BLOCKER，记录131有界PASS、最终stage8 PASS（重叠）、ruff/mypy PASS；此切片不部署、不新provider、不新业务窗口。

质量下一切片先冻结真实反例再设计：准入c8段落证据完整、c9重复判定；字段贷款条款/退款对象完整；全材料s14–s17利益演示漏发现。复用原source、native raw、effective fields构造同一材料的覆盖核对视图，分清“已提供原文”“形成候选”“字段/页面承载”“独立核验”；不能把Schema定义视为有效字段正文，也不能只审已有候选而声称全文无遗漏。v7全处置/零成员审核需显式新合同，不并入当前scope接线。没有产品批准的新发布路径或通用覆盖平台。

## 2026-09-25 有效字段比较输入纵切

沿已批准质量方向，先补缺失输入而不重复调参。复用调查：旧discovery v2的_comparison_view已提供字段正文语义，但native admission及v6 knowledge view没有字段实例；正常上传的字段在compile_delta，不可仅取existing_fields。选用原compose_batch_output生成当前有效fields一次，pure field_comparison封装实体/版本/完整键覆盖与精简语义投影；准入与独审共用。候选全处置和未发现内容需要下一版本审核，不能混入本次而宣称全部质量修好。

- [x] Spec G35-R5-FIELD-COMPARE-1—4先冻结。RED：原准入不接收有效fields；真实worker首次上传字段未送入；旧产物未截断；错误实体/版本/缺项/重复/unknown理由不得变。
- [x] field_comparison.py：输入request/entity/已组成fields→精简正文及修订hash；保持原条件/例外/未知原因，不外发重复证据，不负责字段合并。
- [x] native_pipeline/pipeline：通过原read路由取得compile_delta，原compiler compose一次；纯fields沿admission→preflight→projector传递；v1历史行为保持。
- [x] discovery.py：v6有比较合同才投影actual final fields、核对准入比较值一致；旧context不改。检查上下文实际字节预算和hash，不改大预算。
- [x] checkpoints产物升版；真实worker首发/恢复exact复用、字段变化与旧review失配反例；相关有界回归/静态检查/真实raw离线验证。
- [x] 独立冻结审查；质量五阻断仍逐项保留，收口后再集中交付，不在本轮追加真实恢复。

本切片软件收口：140 PASS/267.51秒、9源码mypy与ruff PASS、冻结14文件独审0 BLOCKER；真实材料反事实输入79字段，准入97008 bytes，审核286480/300000，全finalhash保持。未提交/部署/新provider，五项真实内容质量仍BLOCKED；详见effective-field-comparison-20260925.md。后续在原审核职责内冻结全处置/零成员与未发现内容核验，同时处理v6重复视图的预算余量，不能从补输入推导覆盖通过。

## 2026-09-25 全处置与覆盖审核纯合同纵切

设计选择：直接重用旧v6 prompt会与“only retained”冲突；另建覆盖服务/执行器会重复治理。采用原review深模块的显式v7接口，首切片先把完整输入、保义去重和严格响应闭合，再接原executor/配置/恢复。现有renderer拆出公开纯语义构造，旧v6 wrapper保持；专属v7 builder复用该构造、公开source resolver和review validator，并检查最终预算，不调用跨模块私有函数。全部selection留服务端，模型只接所需语义和绑定hash。

- [x] Spec COVERAGE-1—4先冻结；RED覆盖原renderer不支持v7、全处置/全span/零保留成员、缺项重复外来引用、unknown伪覆盖、错hash、缺selection拒绝、预算边界。
- [x] 新native_coverage_review.py封装v7 prompt、输入压缩和响应检查。保留所有候选/决定/依赖/隔离、正文与来源，不为页数改候选；字段与原文去重，覆盖目标必须来自当前有效知识或保留成员。
- [x] discovery.py公开纯语义构造，旧renderer入口及v3—v6行为不变；专属native_coverage_review builder显式构造v7，runtime尚不启用。
- [x] 五项真实质量反例的source refs都能进入v7输入；真实raw仅用于离线尺寸与保义诊断，不能写回执行结果或冒充新模型。
- [x] 有界回归/静态检查、冻结独立审查和真实限制记录。

纯合同已闭合全零原生候选无selection的snapshot/source作用域；正常worker尚须装载这些已验证输入。下一接线包括新审核模板的独立配置身份与完成阶段checkpoint重验（复用已成功模型调用，不改global base policy）；内容与覆盖结论如何映射已有状态/UI和部分发布。未闭合前不部署/新provider、不点击已关闭真实窗口。

软件终态：150 PASS/72.05秒，4源码mypy/ruff及diff检查PASS；冻结7文件独审0 BLOCKER。真实签名材料离线139753/300000 bytes，18span/14候选/14决定/79字段，完整final hash和原文保持。没有新模型语义结果、部署或发布；详见native-coverage-review-20260925.md。


## 2026-09-25 覆盖审核正常任务与恢复纵切

沿已批准顺序，选用原compilation/StageCall/composite adapter，pure v7负责语义、runtime负责验证输入和执行身份。另起覆盖任务会复制调度，替换global model配置会使无关成功计算失效，均不采用。当前只新增审核专用可选配置，模型不变。

- [x] RUNTIME-1 配置反例先RED：未配置旧策略字节保持；合法覆盖模板仅改最终审核；错误role/purpose/prompt/ID/dependency拒绝；composition派生原executor。
- [x] RUNTIME-2 stage反例先RED：合法非空/零候选/全拒绝均调用v7，已签名装载与多域拒绝，实际输入预算/hash与明确提示一致；exact replay及unknown阻断。
- [x] RUNTIME-3 composite和持久产物：完整响应不丢，retained内容决策与coverage/处置分开，合格内容+明确待补，失败内容不发布；旧路径不改。
- [x] RUNTIME-4 完成阶段版本/配置/调用身份复验；持久worker正常首发及恢复的最小纵切，成功上游不重算。
- [x] 摘要/UI具体缺口核对后冻结追加合同；定向有界回归、静态检查、冻结独审与真实材料离线预算，集中交付随后单独记账。

RED用项目harness/.venv/bin/pytest定向运行；首次功能用例失败后才写实现。root唯一写者，reviewer只读冻结身份；不在本切片增加新的模型能力或第二发布路径。

软件终态：172 PASS/891.64秒（1条现有弃用warning），12源码mypy/ruff、Vue50项/类型检查及Go bridge PASS；冻结21文件revision2独审0 BLOCKER。retained异议阻止自由组发布，多代审核后失败复用原成功调用；持久worker的零候选与配置漂移边界已验证，均为本地模拟外部端口。真实配置离线准备139753/300000 bytes，未应用。源码未提交/部署，新provider/build/deploy/UI业务提交0。五项质量反例、非空发布/点击/补充标志、跨窗口R6、R4与完整G3.5仍未完成；下一项按原职责收口五项真实内容问题。详见native-coverage-runtime-20260925.md。


## 2026-09-25 五项质量诊断与下一验证

- [x] 核对旧请求/响应：贷款及免责生成正文遗漏，非原文缺失或截断；c8引文范围不足，c9旧准入没有有效字段全文。
- [x] 独立原生检查：s14–s17全文、exhaustive与Purpose v2均已应用；cite支持new_slugs且适配未删补充候选，但模型仍漏利益演示。
- [x] 核对既有修订入口：retry-fields仅技术失败；compiler refresh_fields可以复用，present字段语义修订的运行接线尚缺。
- [ ] 当前v7反事实输入一次受控模型评估，验证识别五反例，保留原raw/完整协议校验；自动审批要求具体材料与外部地址确认，已询问，未发送。
- [ ] 根据真实评估结果冻结最小字段修订/原生补漏合同，再RED/实现；不堆叠盲试提示词、不新建循环重试平台。

详见quality-root-cause-20260925.md。五项质量仍未关闭；本轮provider/build/deploy/业务写入0。旧窗口不重开；评估即使通过也不等于完整平台流程或G3.5通过。


## 2026-09-25 授权到位与审核真实误判收口

用户一次性授权G3.5全部剩余工作，具体模型输入/地址授权已覆盖。第一次独立原executor评估只调用1次，32.75秒，43746输入/4763输出tokens（报告total52376含reasoning3867）；无应用DB/平台写入。模型没有断联，但JSON对象错用数组闭合，且五缺口全漏。旧闭合窗口不复开；该raw仅保留作为失败证据。

本最小切片沿G35-R6-GROUND-1—4在原审核深模块解决无正文依据的泛化自报；不先对失败审核自动触发修订。

- [ ] 冻结摘录/逐段支持最小合同并独立设计核对；旧全文/有效字段/最终hash保持。
- [ ] RED：有目标ID无正文摘录不能COVERED；Schema/其他目标/未知字段/虚构摘录拒绝；entity不能覆盖非身份；缺失/重复SOURCE段拒绝，段否定覆盖原整体PASS。
- [ ] RED：原模板不接受JSON模式，新增后只覆盖模板实际请求带response_format；旧model policy/wire不变，参数变化使重放失效。
- [ ] 原pure模块及stage/composite/checkpoint版本接线；有界测试/类型/独审，不修改旧raw为成功。
- [ ] 同一139753-byte基准材料按新合同保义重建，事前实际测量预算；单次新有限评估验证五缺口，失败则保持质量BLOCKED并回到可证实原因。

已验证字段语义修订和原生缺口补发有明确既有能力/缺口清单，待审核真实可信后续接；R4正式关系仍在首条非空完整流程之后。根因诊断、独审和全局授权不等于G3.5完成。

GROUND首审确定两项收口：comparison不能以新生成member自证已有知识，需与final coverage目标域明确分开；一次性eval需绑定冻结源码manifest。跨span联合摘录保留：必须含本span且每条逐字存在，SOURCE段支持仍只在自己的indexed slice内；禁止联合摘录会损失跨chunk条件，不采用。先追加RED，再修复和一次冻结复审。

## 2026-09-25 模型能力对照的最小切片

GROUND最终84 PASS、独审0 BLOCKER；v8 Gemini真实原raw在正式decoder下因2处伪造目标摘录被拒绝，独立语义5项全漏。停止Gemini同类重试。按MODEL-ALT-1—3在原settings/policy/executor增加明确DeepSeek部署配对和正确回执，旧Gemini字节/旧schema67权限不变；先测试和独审，后同输入一次隔离对照。输出16384/超时180/最多1次，不改正式运行配置。两字段语义刷新和gap-focused原生补发现仍待后续：审核身份升级本身不会失效原native discover/cite，不能误称其已自动补发现。

## 2026-09-26 R4 接续（FLOW 优先）

主流程最新事实以 `flow-first-20260925.md` 为准：4 正式自由页已发布、检索和 PDF 回点通过。
继续必要正式关系，不再逐 case 优化。采用版本化 typed relation extension 复用现有原子
PageMember 生命周期；具体合同见原 OpenSpec 下 `business-relation.md`。
root 唯一写者，既有工作树不重建，未提交质量改动保持；独立 agent 只读审查。

- [x] REL-1/2：测试先行，结构、身份、来源与同版目标依赖深模块。
- [x] REL-3：跨语言 JSON/哈希和原编译/增量/审核链验证。
- [x] REL-4：现有正式页的结构化关系展示与导航。
- [x] REL-5 软件：显式v4准入、v9独立审核、完整Candidate及持久worker恢复；156回归+1worker，独审0 BLOCKER。
- [x] REL-5交付：clean ac12fca1a，173PASS/1SKIP+worker1，独审及APP/Harness/UI可回滚部署PASS。
- [x] REL-5正常流程实测：用户确认后已生成typed关系+MODEL_GENERATED概念，准入/审核/正常发布verify完成epoch22；配套概念71分导致新增自由成员0，关系正式可读验收仍待，不记质量PASS。
- [ ] 同一计划后续：R6 跨窗口闭包/重审 → 综合验收与集成；质量统一后置。


### 2026-09-26 下一R6切片只读边界核对

以已提交ac12fca1a为基线，当前仅单窗口selection。多窗口需版本化aggregate：candidate按窗口命名空间，member保留全局身份，相同member的多个owner共同进退，不同内容同身份继续冲突。每窗口沿现有严格selection，先限同材料/同实体版本/完整成功窗口和普通页，typed relation仍保持现有围栏。初审只有可定位的page score或disposition失败才能播种反向依赖/孤定义闭包裁剪；全局不通过但无局部seed不得猜测。变更集合后必须重算final hash、生成pruning receipt并最多重审一次；不能复用旧proof授权新结果。此为能力核对和下一设计边界，未冻结新Spec、未RED/实现。真正跨窗口语义引用需后续协议增量，不能静默重释v6或依赖candidate ID字符串。已有质量WIP不计已交付能力。

### 2026-09-26 身份输入边界与新正常窗口

12fae1231仅Harness交付PASS；干净61PASS/独审0BLOCKER。新27d23f17完整流程279.676秒到epoch22，8调用，新typed关系94分/配套概念71分，组PENDING。字段沿用79/26已核验，未新抽字段；质量统一后置。窗口关闭不重试；转R6多窗口普通page/definition依赖并集及一次局部裁剪重审。证据identity-source-boundary-20260926.md。

### R6 执行序列（2026-09-26，单写root）

规格native-multiwindow-closure.md；12fae1231为干净基础，已有coverage WIP不进入本切片。

1. 保留非隔离窗口的内部dependency domain及明确member/review映射（先RED），不变原模型输入/v1 wire；统一已有闭包算法供单窗与多窗两真实用途。
2. 构造并验证同一材料/实体完整多窗aggregate v2，global member owners、冲突、环与孤定义固定点；native_pipeline消费服务端结果，缺窗/typed继续围栏。
3. v10紧凑审核视图复用现模板/purpose；审计保留完整domain。所有source/provenance/阈值沿旧合同。
4. discovery_review_compilation深模块返回delta/review/drafts/state，内部最多一次局部裁剪后重新合成与独立审核；final artifact product唯一，初审用initial:<hash>。
5. artifact/checkpoint与组合proof精确绑定；持久worker证明初审已记录不重发、失败UPDATE旧正文保留及最后hash经过二审。
6. 冻结干净源码验证/独审→Harness必要交付→有界真实流程→综合矩阵，源码GREEN不当live PASS。

唯一write set：原identity以外不再改身份；native_admission、native_dependency_selection及按职责新增的domain/aggregate内部文件、native_pipeline、discovery review/view/policy/composition与新review_compilation、pipeline一处消费、checkpoint注册，以及对应定向测试/本Spec计划证据。新或实质重构模块不超过500行；不建立独立队列/发布器/模板体系。

## 2026-09-26 R6 交付及正常业务终态（当前口径）

- [x] R6普通page/definition完整多窗聚合、局部失败最多一次复审、审计/断点恢复：a587823fe38b6328297cf5cd42c85f36a84fabc4；独审0BLOCKER，103定向+29metrics+6持久worker最终验证通过。
- [x] Harness-only镜像4f8529ce…交付05:41:07Z PASS；APP/UI/model/runtime配置不改；精确制品与回滚容器保留。
- [x] 正常UI单次run310651e0走完编译/审核/发布/verify，218.11秒，epoch23；当时API计7/0，已核实4次新Harness语义调用＋3历史source回执，不能记7次新增。
- [x] 失败透明：准入模型c11—c14输出REJECT+existing_target违规，旧合同拒绝；新free0，页面显示发现失败。保留旧知识/raw，不手工修模型结果/反复重试。
- [ ] R6多窗口真实材料及一次真实增量/失败恢复的综合业务验收。现有持久worker测试不是live，多窗不含typed/multi-entity/material扩展。
- [ ] 正式typed关系与MODEL_GENERATED标志真实发布/页面验收；源码已交付，本轮未发布此类新增成员。
- [ ] 统一质量、覆盖、保真、对照原生及协议稳定性：依用户FLOW优先要求后置；当前不为单case改提示词或分数。
- [ ] 远端CI与最终合入：本轮未执行，不由本地构建/运行推导。

完整G3.5仍未完成。软件、交付与单窗主流程回执已闭合，未验收项不能隐去。
详见evidence/830-g35/multiwindow-review-20260926.md；私密证据insurancekb-private-evidence/g35-r6-20260926/。
