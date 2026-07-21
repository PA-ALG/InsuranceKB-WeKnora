# 保险知识编译能力迭代方案

> **历史输入，已被合并**：当前唯一主 backlog 是 [2026-07-insurance-knowledge-compiler-master-plan.md](2026-07-insurance-knowledge-compiler-master-plan.md)，最高产品/架构口径是 [Enterprise LLM Wiki 北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)。本文件只保留需求来源与演进记录，不再单独决定落点、模型策略或发布权限。

## 背景与目标

本迭代旨在把 LLM Wiki 的知识编译理念融入 WeKnora，并使其可用于保险公司的产品、条款、核保、理赔、监管和培训知识管理。

目标不是另建一个桌面 Wiki，而是增强现有 WeKnora 的企业级能力：文档经解析后被编译为可追溯、带时间有效性、可审核、可持续演进的知识资产；RAG 与 Agent 仅消费已授权、处于正确版本的知识。

LLM Wiki 的公开实现包含两阶段 ingest、页面级来源追溯、增量缓存、4 信号图谱、Louvain 社区发现、图谱洞察、异步审核、Deep Research 及多模态图片 ingest。参见 [LLM Wiki README](https://github.com/nashsu/llm_wiki)。

## 当前 WeKnora 基线

当前仓库并非传统“文档分块 + 检索”系统，已经具备 Wiki 的重要基础：

- `internal/application/service/wiki_ingest.go`：异步 Wiki ingest、增量处理、失败重试、删除回收和 finalize 收敛。
- `internal/application/service/wiki_page.go`：Wiki 页面、双向链接、目录层级、版本字段和来源引用。
- `internal/application/service/wiki_lint.go`：孤页、死链、过期引用等巡检。
- `internal/handler/wiki_page.go` 与 `internal/router/router.go`：Wiki 页面、目录、索引、日志、链接图、问题和修复 API。
- `frontend/src/views/knowledge/wiki/WikiBrowser.vue`：页面浏览、目录、搜索、日志、问题与页面链接图。
- `frontend/src/api/wiki/index.ts`：前端 Wiki API 模型与调用。
- `docreader/`：Python gRPC 文档解析服务。其职责是提取 Markdown 与图片；文件明确说明分块、OCR、VLM caption 由 Go 应用负责。

因此，本方案只补齐“知识编译与治理”缺口，复用现有任务、租户、权限、审计、对象存储、检索和 Agent 基础设施。

## 差距分析

| 能力 | 当前状态 | 需补齐部分 |
| --- | --- | --- |
| 两阶段编译 | 已有 Wiki 自动生成和互链 | 缺少持久化、可审计的结构化分析产物；生成结果无法作为事实资产复用 |
| 来源追溯 | 页面级 `source_refs`、chunk 引用已存在 | 缺少事实/主张级证据、页码、原文定位、置信度 |
| 增量演化 | 已有去重、队列、重试和删除收敛 | 缺少语义 diff、条款有效期、历史版本与版本冲突 |
| 图谱 | 有 Wiki 页面链接图，且有实体关系知识图谱能力 | 缺少融合关联模型、社区发现、图谱洞察和知识缺口 |
| 审核 | 有 Wiki issue 状态处理 | 缺少候选知识审核、批准发布、退回重编、责任人与审计闭环 |
| Deep Research | Agent 已可 Web Search 和写 Wiki | 缺少由知识缺口驱动、确认后执行、受控写回和审核的流程 |
| 多模态 | docreader 可输出图片，Go 可处理 OCR/VLM | 缺少图片事实、图片知识节点、图片检索与源页跳转 |
| Purpose 与 Schema | 有 Wiki 配置 | 缺少知识库用途、保险领域本体、权威来源策略与编译规则 |

## 目标架构

新增独立 Python 服务 `knowledge-compiler/`，不要将语义编译塞入 `docreader/`：

```text
Docreader（解析） -> Go 知识服务（存储、权限、任务）
                                 |
                                 | gRPC
                                 v
                  Knowledge Compiler（Python）
       分析 / 事实抽取 / 语义差异 / 图谱洞察 / 图像事实
                                 |
                                 v
      Go Wiki 服务（校验、持久化、审核、发布、检索和 Agent）
                                 |
                                 v
             Vue Wiki / 图谱 / 审阅 / 研究界面
```

Python 只返回结构化候选知识，绝不直接访问 WeKnora 主库或取得发布权限。Go 负责 tenant/RBAC 校验、密钥管理、任务调度、持久化和最终发布。

建议先定义 `knowledge_compiler.proto`，包含以下 RPC：

```proto
AnalyzeDocument(AnalyzeRequest) returns (CompilationAnalysis)
CompareRevision(RevisionDiffRequest) returns (RevisionDiff)
BuildGraphInsights(GraphSnapshot) returns (GraphInsightBatch)
ExtractImageClaims(ImageAnalysisRequest) returns (ImageClaimBatch)
```

每项响应必须含 `tenant_id`、`knowledge_base_id`、`schema_version`、`model_version`、`source_ids`、置信度和 trace/request ID。Go 必须重新校验作用域，不能信任服务返回的身份字段。

## P0：可信知识编译基础

### P0-1 保险 Schema、Purpose 与权威策略

**Python**

- [ ] 新建 `knowledge-compiler/schemas/insurance.yaml`。
- [ ] 定义 `insurance_product`、`policy_clause`、`coverage`、`disease_definition`、`claim_condition`、`exclusion`、`regulation`、`case`、`training_material` 等实体、属性和关系。
- [ ] 依文档类型选择提取模板，使用 JSON Schema 校验 `CompilationAnalysis`。
- [ ] 定义权威等级：正式条款、监管文件、已批准 FAQ、产品说明书、培训材料、销售话术、外部研究。

**Go**

- [ ] 扩展 `internal/types/wiki_page.go` 中的 `WikiConfig`：`purpose`、`domain_schema_id`、`authority_policy`、`effective_time_required`。
- [ ] 新建 `internal/types/interfaces/knowledge_compiler.go`。
- [ ] 新建 `internal/infrastructure/knowledgecompiler/` gRPC client，并在 `internal/container/container.go` 注册。
- [ ] 新建 `internal/application/service/wiki_compilation.go`；由 `wiki_ingest.go` 在现有队列流程中调用它。
- [ ] 增加 Go 单测：Schema 缺字段、越权 KB、模型超时、无效 JSON、低权威来源等情形。

**前端**

- [ ] 修改 `frontend/src/api/knowledge-base/index.ts` 的 `wiki_config` 类型。
- [ ] 修改 `frontend/src/views/knowledge/KnowledgeBaseEditorModal.vue`：行业模板、用途、权威来源策略和“必须填写生效期”开关。
- [ ] 补全 `frontend/src/i18n/locales/*.ts` 文案。

**验收**

一份寿险条款能够稳定生成“投保规则、保障责任、等待期、除外责任、赔付条件、适用产品版本”结构，且不允许以销售话术替代正式条款。

### P0-2 事实级证据与时间有效性

**Python**

- [ ] 每个事实返回 `claim_id`、原文摘录、文档 ID、页码/页内位置、抽取方法及置信度。
- [ ] 为事实标注 `effective_from`、`effective_to`、`status`；无法确认时返回待审核状态，而非猜测。

**Go**

- [ ] 创建新的顺序迁移：`wiki_claims`、`wiki_claim_evidence`、`knowledge_effective_versions`。
- [ ] 为事实保存来源、页码、chunk、图片资产与模型版本，建立 KB、实体和时间范围索引。
- [ ] 在 Wiki/RAG/Agent 查询入口增加 `as_of_date` 过滤；无日期时按当前有效版本检索。
- [ ] 聊天引用升级为“答案 -> claim -> 文档页/片段”，并在版本不确定时提示用户。

**前端**

- [ ] 扩展 `frontend/src/api/wiki/index.ts` 的页面和引用 DTO。
- [ ] 在 `WikiBrowser.vue` 增加证据抽屉：原文、页码、有效期、来源等级、置信度。
- [ ] 在聊天引用组件增加“查看适用版本/原始页”的跳转。

**验收**

查询“2023 年投保的产品癌症如何赔付”时，只能使用 2023 年有效条款；UI 必须显示可点击的页码级证据。

### P0-3 语义增量与版本控制

**Python**

- [ ] 实现 `CompareRevision`：输出新增、变更、撤销、冲突和受影响 Wiki 页/FAQ/实体。

**Go**

- [ ] 保留 hash 去重作为快速路径；文档内容改变时调用语义 diff。
- [ ] 将正式知识生命周期建模为 `draft`、`review`、`published`、`superseded`、`withdrawn`。
- [ ] 避免以新条款原地覆盖旧条款；以不可变修订和有效期保存历史。
- [ ] 在现有 Wiki finalize 阶段只重建受影响索引与链接。

**前端**

- [ ] 新增 `frontend/src/views/knowledge/wiki/WikiRevisionDiff.vue`。
- [ ] 按责任、除外、赔付条件显示变更、来源与发布状态。

## P1：融合图谱与主动洞察

### P1-1 4 信号关联与领域图谱

**Python**

- [ ] 构建融合关联：Wiki 链接、共同来源、实体关系、类型/保险本体约束。
- [ ] 关联权重必须基于保险金标准集调优，不照搬 LLM Wiki 的固定权重。

**Go**

- [ ] 新增 `knowledge_graph_edges`、`knowledge_graph_communities`、`graph_insights` 迁移和 repository/service。
- [ ] 保持现有“Wiki 页面链接图”API，另建“保险知识图谱”API，避免前端混淆两类图。
- [ ] 新增 Agent 工具 `query_insurance_graph`，先做权限、版本和有效期过滤，再图谱扩展。

**前端**

- [ ] 修改 `WikiBrowser.vue`，明确切换“页面链接图”和“保险知识图”。
- [ ] 节点/边显示实体类型、关系、有效期、证据和来源等级。

### P1-2 社区、缺口与冲突

**Python**

- [ ] 实现 Louvain 社区发现、孤立页、稀疏社区和桥接节点检测。
- [ ] 实现规则 + LLM 冲突检测；正式条款和监管文件优先于培训及销售材料。

**Go**

- [ ] 洞察写入 `graph_insights`，冲突写入独立 `knowledge_conflicts`，不滥用现有单页 `wiki_page_issues`。
- [ ] 增加指派、状态、处理理由和审计记录。

**前端**

- [ ] 新增 `frontend/src/views/knowledge/insights/`：洞察、缺口和冲突列表。
- [ ] 支持按产品线、有效期、来源等级、风险等级筛选。

## P2：审核与 Deep Research 闭环

### P2-1 异步人工审核

**Python**

- [ ] 对低置信度、矛盾、缺失字段和高风险条款输出受限的审核建议。

**Go**

- [ ] 新增 `knowledge_review_items` 和 `knowledge_review_decisions`。
- [ ] 复用现有 RBAC、审计日志和 asynq/sync task，分配产品、核保、理赔、合规审核责任。
- [ ] 只有 `published` 事实可进入默认检索范围。

**前端**

- [ ] 新增 `frontend/src/views/knowledge/review/`：证据比对、批准、退回重编、驳回、分派和批处理。

### P2-2 由洞察触发的 Deep Research

**Python**

- [ ] 从知识缺口生成可编辑的研究主题、查询词和预期 Schema。

**Go**

- [ ] 复用已有 Web Search provider 和 Agent 工具；增加受控 `research` 任务类型。
- [ ] 记录 URL、抓取时间、提供商、许可证/可信度、模型版本和证据链。
- [ ] 研究结果写入候选区并进入审核，不能直接改写正式条款。

**前端**

- [ ] 洞察卡片增加“发起研究”；支持编辑主题和查询、查看流式进度和提交审核。

## P3：多模态与运营完善

### P3-1 图片知识化

**Python**

- [ ] 接收 Go 已持久化的图片 URL/ID，抽取图表事实、实体和字段；Python 不管理对象存储。

**Go**

- [ ] 在现有 docreader -> Go 图片链路中建立 `image_asset_id`。
- [ ] 将图片事实写入 claims/evidence，保留 OCR/VLM 置信度与源页。

**前端**

- [ ] Wiki 和搜索结果展示图片证据，支持预览与跳回原始页。

### P3-2 外部同步与可观测性

- [ ] 基于现有 datasource 框架增加文件夹/网页变更监听或定期扫描，触发已有增量编译。
- [ ] 采集编译成功率、人工采纳率、冲突率、过期知识比例、每文档成本。
- [ ] 在知识库首页展示编译健康度，并复用当前 Wiki 队列状态展示。

## 实施顺序与准入条件

1. 先交付 P0-1、P0-2 与 P0-3，形成可信、可回滚、可按时间查询的事实资产。
2. 再交付 P1 图谱和洞察；任何洞察均不可自动发布或越过版本过滤。
3. P2 的 Deep Research 必须建立在审核门禁之上。
4. P3 多模态与外部同步最后上线。

首个试点建议限定为一个产品线，例如重疾险。金标准语料仅使用正式条款、产品说明书和已批准 FAQ；验收指标至少包括版本正确率、事实引用准确率、冲突识别率、审核采纳率和编译成本。

## 关键风险

- 保险知识最严重的风险是错误版本或低权威材料被表述为确定结论，而非召回率不足。
- Python 编译服务不可拥有数据库写权限、租户决策权或发布权限。
- Deep Research 的网页结果只能作为候选研究材料，不能自动替代正式条款或监管文件。
- 模型输出必须使用严格 Schema、证据最小化引用和 Go 二次校验，避免提示注入、跨租户串读与事实幻觉。
