# 保险知识编译能力：主迭代更新清单

> 本文合并 `2026-07-insurance-knowledge-compiler.md` 与 `2026-07-insurance-knowledge-compiler-feedback-backlog.md`，去除重复事项并识别依赖关系。后续产品排期、技术设计与开发任务均以本文为唯一主清单；前两份文档保留为调研与反馈来源。
>
> **架构修订（2026-07-11，ADR-001）**：经讨论定为插件式架构——WeKnora 原样跟随官方上游，本文中"Go 与数据层/前端"条目的落点调整为独立 Python Harness（`harness/`）与其自有数据库/工作台；gRPC 契约降级为 Harness 内部 API。优先级与验收标准不变。落点映射表与决策记录见 [`docs/insurance-kb/02-architecture.md`](../insurance-kb/02-architecture.md) §6；另新增切片 **S0：金标与评估子系统**（先于 S1 启动，见 [`docs/insurance-kb/05-golden-set-eval.md`](../insurance-kb/05-golden-set-eval.md)）。

## 1. 目标、范围与成功标准

### 1.1 产品目标

将 WeKnora 现有的 Wiki、RAG、Agent、权限和异步任务能力升级为保险行业的“知识编译与治理”平台：

```text
多源材料 / 产品库 / FAQ / 文档 / 多媒体
                    ↓
产品识别与领域分类 -> 结构化事实与证据 -> 版本化合并与审核
                    ↓
产品 Wiki / QA / 图谱 / 检索与 Agent
                    ↓
知识完整度、冲突、变更、缺口和研究闭环
```

### 1.2 必须遵守的原则

- 正确归属优先于自动化：不能确定产品的内容进入候选池，不污染产品知识。
- 权威度与有效期优先于内容完整度：正式条款/监管文件不能被培训、销售或外部材料覆盖。
- 每个可回答的结论必须可追溯到事实、证据和版本。
- Python 负责语义候选；Go 负责租户隔离、权限、任务、持久化和发布。
- 结构化数据不走 docreader；JSON/FAQ/产品库使用直接规范化和差异合并路径。
- 自动更新必须产生 change set；高风险替换、低置信归属和冲突必须审核。

### 1.3 首期验收指标

以一个险种（建议重疾险）为试点，使用正式条款、产品说明书和已批准 FAQ 建立金标准：

| 指标 | 首期门槛 |
| --- | --- |
| 产品归属正确率 | 达到业务确认的阈值；低置信内容不得自动发布 |
| 版本正确率 | 历史日期问答不得引用不适用版本 |
| 事实引用准确率 | 已发布结论均能跳转页码/片段/来源 |
| 结构化导入幂等性 | 同一 `external_record_id + source_revision` 重复导入不重复建知识 |
| 并发一致性 | 同一产品分片不丢更新，冲突可见、可处理 |
| 字段抽取质量 | 高风险字段（豁免、等待期、除外、理赔限制）使用字段级测试门槛 |

## 2. 当前可复用基础

无需重复建设以下能力：

- Wiki ingest/finalize、增量去重、失败重试和删除收敛：`internal/application/service/wiki_ingest.go`。
- Wiki 页面、互链、目录、版本字段和来源引用：`internal/application/service/wiki_page.go`。
- Wiki 巡检：`internal/application/service/wiki_lint.go`。
- Wiki HTTP API 和 RBAC 路由：`internal/handler/wiki_page.go`、`internal/router/router.go`。
- 前端 Wiki 页面、链接图、日志、问题和队列状态：`frontend/src/views/knowledge/wiki/WikiBrowser.vue`。
- 标准模式的 asynq 与 Lite 模式的同步任务执行器。
- docreader 的文档/PPTX/图片解析；其职责保持为解析，不承载语义编译、ASR 或发布。

## 3. 目标架构与共用数据对象

### 3.1 服务边界

> ⚠️ **历史文本**：本节所述"独立 `knowledge-compiler/` 服务、Go 经 gRPC 调用、Go Ingest Orchestrator"为 ADR-001（见文档顶部修订说明）之前的原方案，**已被插件式 Harness 架构取代**（保险能力全在 `harness/`、自有 PostgreSQL、只走 REST/MCP；gRPC 契约降级为 Harness 内部 API 形状参考）。本节保留作方案演进存档，不作实施依据；现行权威见 `docs/insurance-kb/02-architecture.md`。

新建独立 `knowledge-compiler/` Python 服务，通过 gRPC 被 Go 调用：

```text
Docreader -----------┐
结构化导入 ----------+--> Go Ingest Orchestrator --> Knowledge Compiler (Python)
音视频转写 ----------┘              |                         |
                                     v                         v
                           change set / review          claims / diff / insights
                                     |
                                     v
                    Go repositories, RBAC, audit, search, Wiki and Agent
```

首批 gRPC 契约：

```proto
AnalyzeDocument(AnalyzeRequest) returns (CompilationAnalysis)
StructuredImport(StructuredImportRequest) returns (StructuredImportBatch)
ResolveProducts(ProductResolutionRequest) returns (ProductResolutionBatch)
CompareRevision(RevisionDiffRequest) returns (RevisionDiff)
BuildGraphInsights(GraphSnapshot) returns (GraphInsightBatch)
ExtractImageClaims(ImageAnalysisRequest) returns (ImageClaimBatch)
```

所有返回均携带 KB、schema/model 版本、源 ID、证据、置信度与 request/trace ID；Go 重新校验 tenant/KB 作用域。

### 3.2 核心对象（贯穿各阶段）

| 对象 | 用途 |
| --- | --- |
| 产品主数据与别名 | 唯一标识、历史名称、产品代码、险种、版本和有效期 |
| Claim | 一条可验证事实；绑定主语、属性/关系、产品版本、状态和置信度 |
| Evidence | Claim 的原文、页码/时间戳、chunk/图片、来源权威度和抽取方式 |
| Change set | 一批导入产生的 add/enrich/supersede/conflict/retract 候选及其决策 |
| Review item | 产品归属、冲突、低置信、Schema 变更或高风险变更的人工决策 |
| QA item | 关联实体和事实的一等知识对象，而非产品实体中的非结构化字段 |
| Schema/Profile | 领域 Schema、必填/条件字段、同义词、提示词、质量门槛和路由规则 |

## 4. 合并后的优先级清单

## P0：可信产品知识入库与可回滚更新

P0 完成前，不建设自动发布的图谱洞察或 Deep Research 写回。

### P0-1 领域 Schema、产品主数据与路由门禁

**关联来源：** 原 P0 Wiki 模板/Schema、反馈中的智能分类和多产品文档对齐。

**Python**

- [ ] 新建 `knowledge-compiler/schemas/insurance.yaml`，定义产品、条款、责任、疾病、理赔条件、除外、豁免、监管、案例和培训材料实体及关系。
- [ ] 定义险种处理 profile：重疾、医疗、寿险、年金、意外、车险等；profile 绑定 Schema、必抽字段、提示词、质量阈值。
- [ ] 实现产品识别：产品代码/标准名/别名的确定性规则优先，向量和 LLM 仅作候选召回与判别。
- [ ] 按章节、表格、标题和产品锚点拆分多产品文档；输出事实级 `product_candidates[]`，允许一对多归属。
- [ ] 低置信或同分候选返回待审核，禁止自动路由到特定产品。

**Go 与数据层**

- [ ] 新增 `insurance_products`、`product_aliases`、`product_documents`；产品使用稳定 ID，不以 Wiki 路径作为身份。
- [ ] 扩展 `WikiConfig`：`purpose`、`domain_schema_id`、`authority_policy`、`effective_time_required`。
- [ ] 新增 Compiler interface/client，并在 `container.go` 注入。
- [ ] 在 `wiki_compilation.go` 持久化前执行产品和租户校验；无法归属的内容写入 `unassigned` 候选池。
- [ ] Wiki 路径按 `products/{product-code}/{version}/...` 展示，但所有关联依赖实体 ID。

**前端**

- [ ] 知识库配置增加行业模板、用途、权威来源策略、生效期强制开关和险种 profile。
- [ ] 上传批次显示产品候选、未归属事实、跨产品内容和人工确认操作。

**验收**

- 一份包含多款产品的材料可把不同责任、豁免和 FAQ 写入相应产品候选集；无法判断的内容不进入产品 Wiki。

### P0-2 结构化产品库、JSON 与 FAQ 快速接入

**关联来源：** 原知识编译入口、反馈中的 JSON/格式化产品库和 FAQ 快速接入。

**Python**

- [ ] 实现 `StructuredImport`：JSON、JSONL、CSV、FAQ 输入直接转换为标准 Product/Claim/QA 批次。
- [ ] 内置保险产品、保障责任、费率/保额、除外、监管和 FAQ 映射器。
- [ ] 对未知 JSON 自动生成候选映射草案，要求用户确认；规范化日期、金额、年龄段、百分比、疾病编码和枚举值。

**Go 与数据层**

- [ ] 新增结构化导入任务类型、上传/API/datasource 三入口，统一进入批次与 change set。
- [ ] 记录 `source_system`、`external_record_id`、`source_revision`、幂等键和原始记录快照。
- [ ] 提供导入预检/dry-run：记录数、产品匹配率、缺字段、映射待确认、预计新增/更新/冲突。
- [ ] 跳过 docreader，不把结构化数据串成大文本再抽取。

**前端**

- [ ] “结构化知识导入”向导：文件/API、字段映射、预检、dry-run、确认提交和模板复用。

**验收**

- 10 万条 FAQ/产品记录可幂等导入；前端在执行前显示匹配和冲突统计。

### P0-3 事实、证据、有效期与非显式字段抽取

**关联来源：** 原事实级溯源/保险版本能力、反馈中的“豁免”等无明显字段无法提取。

**Python**

- [ ] 所有事实输出主语、属性/关系、值、产品/版本候选、有效期、原文摘录、页码/位置、置信度和抽取方法。
- [ ] 对豁免、等待期、除外、理赔限制定义同义词、否定表达、表格模式、上下文窗口和二次验证提示词。
- [ ] 采用 `present`、`absent_explicitly`、`unknown` 三态；未抽取不得等同不存在。
- [ ] `unknown` 生成可定位缺口任务，保留候选证据和重试建议。

**Go 与数据层**

- [ ] 新增 `wiki_claims`、`wiki_claim_evidence`、`knowledge_effective_versions`；为 Claim 存储 `product_id`、`product_version_id`、状态、来源与证据。
- [ ] RAG、Wiki 和 Agent 查询支持 `as_of_date`，默认只检索当前有效且已发布知识。
- [ ] 引用输出改为“答案 -> Claim -> 文档页/片段/图片”，而非仅页面或 chunk。
- [ ] 建立字段级金标准单测和集成测试。

**前端**

- [ ] Wiki 证据抽屉展示原文、页码、有效期、来源等级、置信度和抽取状态。
- [ ] 聊天引用支持跳转证据及查看适用版本。

**验收**

- “2023 年投保的产品癌症如何赔”只命中当时有效条款；未知豁免不能显示为“不含豁免”。

### P0-4 Change set、合并、冲突、删除与回滚

**关联来源：** 原语义增量/版本控制、反馈中的第二/三批资料自动补全、冲突和 change log。

**Python**

- [ ] `CompareRevision` 按 canonical entity + property/relation + 产品版本对比，输出 `add`、`enrich`、`supersede`、`conflict`、`retract`。
- [ ] 每个决定附权威度、发布时间、完整度、证据和理由；完整度仅作排序，不能压过权威度和有效期。

**Go 与数据层**

- [ ] 新增 `knowledge_change_sets`、`knowledge_change_items`、`knowledge_conflicts`、`knowledge_version_snapshots`。
- [ ] 权威排序：正式条款/监管 > 已批准说明与 FAQ > 内部流程 > 培训 > 销售 > 外部研究；允许租户策略配置。
- [ ] 批次先产生不可变 change set；低风险补充可自动应用，高风险替换、冲突、低置信归属进入审核。
- [ ] 发布时将事实、Wiki 页、QA、图谱边作为逻辑版本提交；支持按批次/版本回滚。
- [ ] 删除来源按证据引用计数撤销或降级 Claim，不能删除仍有其他权威证据支持的知识。
- [ ] change log 必含系统/操作者、时间、来源、变更前后、合并原因、审核与回滚批次。

**前端**

- [ ] 产品级 change log、变更集详情、差异对比和回滚确认。
- [ ] Wiki 页显示当前版本、历史、有效期和来源变更。

**验收**

- 后续批次可补全首次导入的未知字段；冲突不会静默覆盖；回滚后 Wiki、Claim、QA、索引一致。

### P0-5 审核与发布门禁

**关联来源：** 原 Human-in-the-loop、当前 Wiki issue、产品方对更新验证的需求。

- [ ] 新增 `knowledge_review_items`、`knowledge_review_decisions`，不复用仅适合页面问题的 `wiki_page_issues`。
- [ ] 覆盖产品归属、冲突、低置信、高风险变更、Schema/Profile 修改和研究写回。
- [ ] 复用 RBAC、租户审计和任务体系，按产品、核保、理赔、合规配置审核人。
- [ ] 只有 `published` Claim/QA 可进入默认检索；候选和草稿需显式授权才可见。
- [ ] 前端建立审核工作台：证据对照、批准、退回重编、驳回、分派和批处理。

## P0.5：高吞吐批处理与一致性

**关联来源：** 现有 Wiki 并发 ingest 能力、反馈中的百/千份材料并发、冲突与合并。

### P0.5-1 分片策略与任务调度

- [ ] 复用现有 asynq/sync executor 与 task pending ops；不创建不兼容的第二套队列。
- [ ] 流程固定为：并行解析/抽取 -> 按产品版本分片 merge -> change set -> 批次 finalize/index。
- [ ] 以 `tenant + KB + product_id + product_version` 为 merge 分片键；不同产品可并行。
- [ ] 同一分片使用乐观锁/change-set revision 或等价串行化；延迟 worker 结果必须重新比较，不能覆盖新版本。
- [ ] 加入全局、租户、KB、产品、模型 provider 五级并发与限流；显示排队原因。
- [ ] 支持失败隔离、死信重放、取消未开始任务；重放使用原 schema/model/source 快照。
- [ ] finalize 只处理受影响产品/页面，避免每份文档全局重建索引。

### P0.5-2 批次可观测性

- [ ] 新增批次控制台 API：吞吐、分片、处理中、重试、冲突、待审核、死信和成本。
- [ ] 前端在现有 Wiki 队列状态之上增加批次控制台和失败/冲突定位。

**验收：** 千份混合材料导入时，不同产品并发；同一产品无丢更新；失败文档不阻塞其他产品。

## P1：产品知识运营、QA 与 Schema 工作台

### P1-1 产品知识仪表盘、质量与缺口

**关联来源：** 原 Graph Insights/知识缺口、反馈中的产品知识概览、全貌、质量评分和批量补全。

**Go**

- [ ] 新增 `ProductKnowledgeOverviewService` 与 `knowledge_completeness_snapshots`；异步聚合，避免仪表盘全表扫描。
- [ ] 完整度按 Schema 的必填/条件必填、`unknown`、冲突、过期、无证据和未审核状态计算。
- [ ] 质量分由字段覆盖、来源权威度、证据完整度、版本新鲜度、冲突、审核和 Wiki 链接健康度构成，并可解释到字段。
- [ ] 每个缺口生成可执行建议：指定材料重编、批量补抽取、人工确认不适用、补充已有资料或发起研究。

**前端**

- [ ] 新增 `frontend/src/views/knowledge/products/ProductKnowledgeDashboard.vue`。
- [ ] 展示产品/版本/险种筛选、知识全貌树、字段矩阵、质量分、缺口、冲突、来源和变更趋势。
- [ ] 支持选择缺口批量优化；先生成 change set 预览。

### P1-2 独立 QA 知识对象

**关联来源：** 原 FAQ 自动生成、产品方“主实体均需要 QA”反馈。

- [ ] 新增 `knowledge_qa_items`：问题、标准意图、答案 Claim IDs、关联实体 IDs、产品/版本、有效期、来源、状态和质量分。
- [ ] Python 从 FAQ、条款、服务材料提取/去重/对齐 QA；回答必须由 Claim 支持，不能只保存 LLM 文本。
- [ ] 一个 QA 可关联多个产品/服务/实体；产品页仅聚合显示相关 QA。
- [ ] RAG/Agent 将已发布 QA 作为高精度候选，仍执行权限、版本、审核与证据过滤。
- [ ] 前端支持 QA 相似问题合并、答案差异、来源、审核和历史版本。

### P1-3 Schema/Profile 与提示词工作台

- [ ] 新增 `knowledge_schemas`、`knowledge_schema_versions`、`extraction_profiles`，全量版本化、可回滚。
- [ ] 前端支持 JSON Schema/表单编辑、字段类型、条件必填、同义词、示例、证据要求和风险等级。
- [ ] Python 根据知识背景介绍、样本文档和产品线生成 Schema/提示词草案；人工确认后才可用于生产批次。
- [ ] dry-run 展示将抽取字段、缺项、成本、与当前 Schema 差异和受影响知识范围。
- [ ] Schema 更新只能产生再编译计划，不能隐式重写已发布知识。

## P2：融合图谱、分类优化与主动研究

### P2-1 领域图谱、社区与洞察

**关联来源：** 原 4 信号图谱、Louvain、Graph Insights、知识缺口发现。

- [ ] Python 融合 Wiki 链接、共同来源、实体关系、类型/保险本体约束，计算关联；权重以保险金标准集调优。
- [ ] Python 实现 Louvain 社区、孤立节点、稀疏社区、桥接节点、意外关联和知识缺口。
- [ ] Go 新增 `knowledge_graph_edges`、`knowledge_graph_communities`、`graph_insights`；保留现有 Wiki 页面链接图 API，另建领域图谱 API。
- [ ] 新增 `query_insurance_graph` Agent 工具，先做权限、版本、有效期过滤。
- [ ] 前端切换“页面链接图/保险知识图”，展示关系、证据、有效期和洞察卡；洞察可进入审核或补全任务。

### P2-2 分类与多产品精度持续优化

- [ ] 从 P0 的基础产品路由扩展为完整文档分类：条款、说明书、FAQ、理赔、核保、监管、培训、营销、案例、转写材料。
- [ ] 前端展示分类、置信度、所选 profile，允许有权限用户覆盖并保留模型理由。
- [ ] 建立多产品文档标注集和持续评测：分类、归属、字段抽取、跨产品污染和冲突发现。
- [ ] 只有达到阈值的 profile 可开启自动 merge，其余仅产生候选 change set。

### P2-3 受控 Deep Research

- [ ] Python 根据缺口/洞察生成可编辑研究主题、查询词和预期 Schema。
- [ ] Go 复用已有 Web Search 和 Agent 工具，增加受控 research task；记录 URL、抓取时间、提供商、许可/可信度、模型和证据链。
- [ ] 研究结果只能进入候选和审核，不能自动替换正式条款或监管知识。
- [ ] 前端支持从洞察卡发起、编辑查询、查看进度和提交审核。

## P3：PPTX、音视频与多模态事实

### P3-1 PPTX 处理强化

- [ ] 核验并完善 docreader 对 PPTX 标题、备注、表格、讲稿、图片/OLE 对象和跨页上下文的提取。
- [ ] Compiler 使用“演示文稿 -> 幻灯片 -> 内容块/图像”证据层级，保存页码和对象位置。
- [ ] 前端支持幻灯片预览、图表证据和跳页。

### P3-2 音视频知识编译

- [ ] 新建独立 media pipeline，负责转码、ASR、说话人、时间戳和章节；不把转写塞入 docreader。
- [ ] 转写片段作为 Evidence，Compiler 提取事实/QA 时必须返回时间戳。
- [ ] 加入数据分类、访问控制、保留期、脱敏和人工审批，尤其适用于客户/理赔录音。
- [ ] 前端提供播放器、文本、时间戳跳转、状态和失败恢复。

### P3-3 图片知识化

- [ ] Go 为现有 docreader 图片建立 `image_asset_id` 并保持对象存储在 Go 侧。
- [ ] Python 通过受控 URL/ID 提取图表事实和实体，写入 Claim/Evidence，保留 OCR/VLM 置信度和源页。
- [ ] 前端在 Wiki/检索结果展示图片证据、预览和源页跳转。

## 5. 实施依赖与推荐交付切片

| 切片 | 依赖 | 交付范围 | 完成定义 |
| --- | --- | --- | --- |
| S1 产品对齐 | 无 | P0-1 | 多产品文档产生产品级候选事实，未归属内容隔离 |
| S2 快速导入与证据 | S1 | P0-2、P0-3 | JSON/FAQ 直入；Claim 有证据、有效期和三态字段 |
| S3 可控更新 | S2 | P0-4、P0-5 | change set、审核、版本、删除和回滚闭环 |
| S4 批量生产 | S3 | P0.5 | 产品分片并发、限流、失败隔离和批次控制台 |
| S5 产品运营 | S3 | P1-1、P1-2、P1-3 | 仪表盘、缺口、QA、Schema 工作台与批量优化 |
| S6 智能演进 | S5 | P2 | 领域图谱、洞察、分类评测、受控研究 |
| S7 多模态扩展 | S2 | P3 | PPTX、音视频、图片事实及证据体验 |

## 6. 统一测试与发布要求

- [ ] Python：Schema 校验、路由、字段三态、结构化映射、diff、冲突和图谱算法单测；以金标准语料做评测。
- [ ] Go：repository/service/handler 单测，重点覆盖跨租户、版本过滤、幂等导入、并发 merge、回滚、删除引用计数和任务重放。
- [ ] 前端：导入预检、产品候选确认、审核、差异、回滚、仪表盘和 Schema dry-run 的组件/API 测试。
- [ ] 集成测试：一份多产品材料 + 一批 JSON FAQ + 后续修订/删除材料，验证最终产品 Wiki、QA、引用、change log 和查询结果一致。
- [ ] 发布开关：按租户、KB、险种 profile 分阶段启用；P0 未达到门槛时，系统只能生成候选，不允许自动发布。

## 7. 不在当前主线内的事项

- 浏览器剪藏器、Obsidian 兼容性和桌面端体验不是保险知识编译 P0-P3 的阻塞项。
- Deep Research 在 P0 证据、版本、审核能力完成前不得开放自动写回。
- 图谱可视化可以复用现有页面链接图，但领域图谱不应以单纯可视化替代版本化事实模型。
