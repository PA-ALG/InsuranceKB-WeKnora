# Enterprise LLM Wiki：保险知识编译主迭代清单

> 本文合并 `2026-07-insurance-knowledge-compiler.md` 与 `2026-07-insurance-knowledge-compiler-feedback-backlog.md`，是**需求范围与依赖关系的唯一主 backlog**，不是实现状态账本，也不覆盖已批准 OpenSpec 的验收规格。当前实现状态看 [`HANDOFF.md`](../../HANDOFF.md) 与 [`13-blueprint-status.md`](../insurance-kb/13-blueprint-status.md)；并行排期看 [`22-parallel-execution-blueprint.md`](../insurance-kb/22-parallel-execution-blueprint.md)；架构与产品取舍以北极星和 02～05 为准。本文出现的任务必须在开发前登记 OpenSpec，编号与 canonical admission 状态以 `openspec/changes/` 为准。
>
> **架构修订（2026-07-11，ADR-001）**：现行实现是仓库内独立 Python Harness（`harness/src/insurance_harness/`）+ 自有 PostgreSQL + 独立 Workbench；WeKnora 保持通用企业底座，只经 REST/MCP 交互。禁止恢复旧 `knowledge-compiler/` gRPC、Go 保险 repository/service 或 WeKnora Vue 保险页面方案。落点与决策记录见 [`02-architecture.md`](../insurance-kb/02-architecture.md) §6；S0 金标与评估先于 S1 指标准入（见 [`05-golden-set-eval.md`](../insurance-kb/05-golden-set-eval.md)）。
>
> **产品北极星修订（2026-07-21，核心方向确认、书面设计待复核）**：Enterprise LLM Wiki 是产品本体与未来默认知识权威；WeKnora 只承载企业平台/权限/解析/检索/页面载体，Harness 承载模板优先、生产弱模型、多 Agent、校验、融合、版本与告警。目标态 Wiki 与同快照 MCP 供人和 Agent 共用，RAW 只作证据/标注兜底。`NS-RIGHTS=recorded`：LLM-wiki-black 是项目方第一方完整著作权资产，可按 provenance 把其 TS 能力迁移/重构到统一 Python Harness；当前未完成的是 NS-0 生产模型硬门禁与适用 admission，因此 004/020/merge/release 仍不得真实生产执行。最高层基准见[`Enterprise LLM Wiki 北极星设计`](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)；本文中的历史 Go/前端落点不得作为偏离 ADR-001/002 的依据。

## 1. 目标、范围与成功标准

### 1.1 产品目标

建设运行在 WeKnora 企业底座上的 **Enterprise LLM Wiki**，将多源材料持续编译为人和 Agent 共用、有证据、有关系、有版本、可审核、可回滚和可演进的企业知识：

```text
多源材料 / 产品库 / FAQ / 文档 / 多媒体
                    ↓
产品识别与领域分类 -> 结构化事实与证据 -> 版本化合并与审核
                    ↓
同一 ReleaseSnapshot 的产品 Wiki / QA / 关系 / MCP / Agent
                    ↓
知识完整度、冲突、变更、缺口和研究闭环
```

### 1.2 必须遵守的原则

- 正确归属优先于自动化：不能确定产品的内容进入候选池，不污染产品知识。
- 权威度与有效期优先于内容完整度：正式条款/监管文件不能被培训、销售或外部材料覆盖。
- 每个可回答的结论必须可追溯到事实、证据和版本。
- WeKnora 负责企业平台、租户隔离、权限、解析、通用检索和 Wiki 页面载体；Harness 通过 REST/MCP 独立负责语义候选、任务、治理持久化、页面编译和发布。
- 生产只依赖 MiniMax/Qwen/Qwen-VL 级弱模型；质量由模板、多 Agent、多次尝试、确定性校验、证据回验与人工最终审核保证，强模型仅可选离线评测。
- 结构化数据不走 docreader；JSON/FAQ/产品库使用直接规范化和差异合并路径。
- 自动更新必须产生 change set；高风险替换、低置信归属和冲突必须审核。
- 人与 Agent 默认消费同一 ReleaseSnapshot；RAW 缺口兜底必须明确标注，且不能覆盖已发布 Wiki。
- 模板失效、无共识、证据断链、重试/预算耗尽或质量退化必须产生可认领告警并停止不安全发布。

### 1.3 首期验收指标

首期采用**跨险种组合验收 + TemplatePackage 切片渐进启用**：可以从一个险种模板开始调通，但项目验收不得等同于单一重疾险试点通过。每个拟进入自动候选范围的险种、文档类型和产品族必须有独立 golden slice；样本不足的切片只允许人工审核候选。

| 指标 | 首期门槛 |
| --- | --- |
| 产品归属正确率 | 达到业务确认的阈值；低置信内容不得自动推进，只能进入审核；任何生产发布仍须授权人批准 |
| 版本正确率 | 历史日期问答不得引用不适用版本 |
| 事实引用准确率 | 已发布结论均能跳转页码/片段/来源 |
| 结构化导入幂等性 | 同一 `external_record_id + source_revision` 重复导入不重复建知识 |
| 并发一致性 | 同一产品分片不丢更新，冲突可见、可处理 |
| 字段抽取质量 | 高风险字段（豁免、等待期、除外、理赔限制）使用字段级测试门槛 |
| 人/Agent 一致性 | Wiki、MCP、QA 与索引绑定同一 ReleaseSnapshot，发布与回滚后无口径分叉 |
| 人工发布授权 | 每个生产 ReleaseSnapshot 有 Space 授权人最终批准，批准 hash 与完整制品完全一致 |
| 失败可接管性 | 模板失配、证据失败、无共识和预算耗尽产生完整 Alert/ReviewItem，不以空结果伪绿 |

## 2. 当前可复用基础

以下能力只作为 **WeKnora 通用底座**复用，不代表使用其内置自动 Wiki 生成，也不转移 Enterprise LLM Wiki Compiler 的语义所有权：

- Wiki ingest/finalize 的通用实现可作契约与失败处理参考；保险 KB 的内置自动 ingest 必须关闭，编译/融合/删除语义由 Harness 管理。
- Wiki 页面、互链、目录、版本字段和来源引用：`internal/application/service/wiki_page.go`。
- Wiki 巡检：`internal/application/service/wiki_lint.go`。
- Wiki HTTP API 和 RBAC 路由：`internal/handler/wiki_page.go`、`internal/router/router.go`。
- 前端 Wiki 页面、链接图、日志、问题和队列状态：`frontend/src/views/knowledge/wiki/WikiBrowser.vue`。
- 标准模式的 asynq 与 Lite 模式的同步任务执行器。
- docreader 的文档/PPTX/图片解析；其职责保持为解析，不承载语义编译、ASR 或发布。

## 3. 目标架构与共用数据对象

### 3.1 服务边界（现行）

```text
WeKnora：租户/RBAC/原始文件/docreader/chunks/通用检索/Wiki 页面载体/Agent 外壳
                              │ REST + MCP + 生命周期事件/轮询
                              ▼
Harness：TemplatePackage/任务编排/生产弱模型 Agent/Claim-Evidence/校验/合并/审核/快照
                              │
                              ▼
CurrentRelease：同一 snapshot 的 Wiki/QA/关系/目录/MCP/索引 → 人与 Agent
```

- 保险代码全部位于 `harness/src/insurance_harness/`，数据库与迁移位于 `harness/src/insurance_harness/db/`、`harness/migrations/`；不得新增 `knowledge-compiler/`、Go gRPC compiler client 或保险 Vue 页面。
- WeKnora 交互只经 `harness/src/insurance_harness/adapters/weknora/` 与 `harness/src/insurance_harness/mcp/`；Harness 不直读 WeKnora 数据库、不消费其 asynq。
- 工作台位于 `harness/src/insurance_harness/workbench/`；通用平台缺口才允许作为 ≤3 个上游补丁进入 WeKnora，且须有契约测试和上游 Issue/PR。
- 所有调用与制品必须携带 Space、source revision、schema/template/model immutable identity、Evidence、request/trace/causation ID 和内容 hash。

### 3.2 核心对象（贯穿各阶段）

| 对象 | 用途 |
| --- | --- |
| 产品主数据与别名 | 唯一标识、历史名称、产品代码、险种、版本和有效期 |
| SourceRevision / SourceEvent | 文档或结构化记录的不可变来源版本、删除/替换/重激活裁决与审计 |
| Claim | 一条可验证事实；绑定主语、属性/关系、产品版本、状态和置信度 |
| Evidence | `document | structured` tagged union：文档分支含 quote/页码/时间戳/chunk/table/image 定位；结构化分支含 source revision/content/record hash、json pointer/value snapshot；两者都绑定来源 trust 与抽取方式 |
| Change set | 一批导入产生的 add/enrich/supersede/conflict/retract 候选及其决策 |
| Review item | 产品归属、冲突、低置信、Schema 变更或高风险变更的人工决策 |
| QA item | 关联实体和事实的一等知识对象，而非产品实体中的非结构化字段 |
| SchemaRegistry | 领域字段定义、三态、类型、风险和条件必填规则 |
| TemplatePackage / TemplateVersion | 四级模板栈、路由、prompt、validator、证据/来源准入、尝试/预算、质量门槛、golden slice 与告警策略 |
| CompilationJob / StageRun / Attempt | 可恢复编译批次、阶段、重试/checkpoint、预算与状态事件 |
| AgentReceipt / Alert | 每次弱模型或确定性 Agent 尝试的完整身份/输入/输出/成本账本，以及可认领失败信号 |
| ClaimRevision / EvidenceLifecycleEvent | 不可变事实修订与证据失效/替换历史 |
| ReleaseSnapshot / WikiArtifact | 同一版本的 Claim、QA、页面、关系、目录、MCP 与索引制品 |
| ReleaseApproval / CurrentRelease | 绑定 snapshot hash 的真人最终批准；目标态在线 serving pointer 是 WeKnora P-1 active alias，本地 CurrentRelease 只镜像 verified receipt/ETag，MCP 每次核对 |
| KnowledgeHealthSnapshot | 按产品/版本/snapshot 冻结的完整度、质量、冲突、过期、任务可靠性与缺口画像 |

## 4. 合并后的优先级清单

## P0：可信产品知识入库与可回滚更新

P0 完成前，不建设图谱洞察或 Deep Research 写回。即使 P0 全部完成，系统也只可自动形成低风险 ChangeSet 候选；**每个生产 ReleaseSnapshot 始终必须由该 Space 的授权人最终批准**，不存在全自动生产发布模式。

### P0-1 领域 Schema、产品主数据与路由门禁

**关联来源：** 原 P0 Wiki 模板/Schema、反馈中的智能分类和多产品文档对齐。

**Harness Schema 与 Compiler**

- [ ] 在 `harness/src/insurance_harness/schemas/` 定义产品、条款、责任、疾病、理赔条件、除外、豁免、监管、案例和培训材料实体及关系。
- [ ] 实现四级 `TemplatePackage`：通用保险 → 险种 → 文档类型 → 产品族；每版绑定 Schema、条件必抽字段、prompt、validator、证据/来源准入、尝试/预算、质量阈值、golden slice、告警与批准身份。
- [ ] 实现产品识别：产品代码/标准名/别名的确定性规则优先，向量和 LLM 仅作候选召回与判别。
- [ ] 按章节、表格、标题和产品锚点拆分多产品文档；输出事实级 `product_candidates[]`，允许一对多归属。
- [ ] 低置信或同分候选返回待审核，禁止自动路由到特定产品。

**Harness 数据与服务**

- [ ] 在 Harness 自有 PostgreSQL 新增 Space-scoped `insurance_products`、`product_aliases`、`product_versions`、`product_documents`、`unassigned_pool`；产品使用稳定 ID，不以 Wiki 路径作为身份。
- [ ] 为 Schema/TemplatePackage、来源 trust policy 和生效期要求建立版本化注册表；模型/分类器不能授予来源权威。
- [ ] 所有 repository/service 接口接收 `KnowledgeScope`，复合 FK/UQ/幂等键闭合 Space；持久化前执行产品与来源身份校验。
- [ ] Wiki 路径按 `products/{product-code}/{version}/...` 展示，但所有关联依赖实体 ID。

**Workbench 与平台适配**

- [ ] `harness/src/insurance_harness/workbench/` 增加 TemplatePackage、用途、来源 trust policy、生效期要求和险种支持矩阵配置。
- [ ] 上传批次显示产品候选、未归属事实、跨产品内容和人工确认操作。
- [ ] WeKnora 只提供租户/RBAC/上传/解析/页面载体；不得在其 Go/Vue 中实现保险产品路由。

**验收**

- 一份包含多款产品的材料可把不同责任、豁免和 FAQ 写入相应产品候选集；无法判断的内容不进入产品 Wiki。

### P0-2 结构化产品库、JSON 与 FAQ 快速接入

**关联来源：** 原知识编译入口、反馈中的 JSON/格式化产品库和 FAQ 快速接入。

**Harness Structured Import**

- [ ] 实现 `StructuredImport`：JSON、JSONL、CSV、FAQ 输入直接转换为标准 Product/Claim/QA 批次。
- [ ] 内置保险产品、保障责任、费率/保额、除外、监管和 FAQ 映射器。
- [ ] 对未知 JSON 自动生成候选映射草案，要求用户确认；规范化日期、金额、年龄段、百分比、疾病编码和枚举值。

**Harness 数据与任务**

- [ ] 在 `harness/src/insurance_harness/structured_import/` 提供上传/API/datasource 三入口，统一进入 CompilationJob、SourceRevision 与 ChangeSet。
- [ ] 记录 `source_system`、`external_record_id`、`source_revision`、幂等键和原始记录快照。
- [ ] 提供导入预检/dry-run：记录数、产品匹配率、缺字段、映射待确认、预计新增/更新/冲突。
- [ ] 跳过 docreader，不把结构化数据串成大文本再抽取。

**Workbench**

- [ ] “结构化知识导入”向导：文件/API、字段映射、预检、dry-run、确认提交和模板复用。

**验收**

- 10 万条 FAQ/产品记录可幂等导入；Workbench 在执行前显示匹配和冲突统计。

### P0-3 事实、证据、有效期与非显式字段抽取

**关联来源：** 原事实级溯源/保险版本能力、反馈中的“豁免”等无明显字段无法提取。

**Harness Compiler**

- [ ] 所有事实输出主语、属性/关系、值、产品/版本候选、有效期、原文摘录、页码/位置、置信度和抽取方法。
- [ ] 对豁免、等待期、除外、理赔限制定义同义词、否定表达、表格模式、上下文窗口和二次验证提示词。
- [ ] 采用 `present`、`absent_explicitly`、`unknown` 三态；未抽取不得等同不存在。
- [ ] `unknown` 生成可定位缺口任务，保留候选证据和重试建议。

**Harness 知识模型与消费接口**

- [ ] 在 Harness 自有库新增 Space-scoped Claim、ClaimRevision、Evidence、SourceRevision 与 effective version 表；复合 FK 禁止跨 Space 引用。
- [ ] Wiki/MCP/Agent 查询支持 `as_of_date`；默认先解析 WeKnora active alias 并核对批准/seal/manifest，Harness `CurrentRelease` 仅作 receipt 镜像。
- [ ] 引用输出改为“答案 -> Claim -> 文档页/片段/图片”，而非仅页面或 chunk。
- [ ] 建立字段级金标准单测和集成测试。

**Workbench 与 Wiki 投影**

- [ ] Wiki 证据抽屉展示原文、页码、有效期、来源等级、置信度和抽取状态。
- [ ] 聊天引用支持跳转证据及查看适用版本。

**验收**

- “2023 年投保的产品癌症如何赔”只命中当时有效条款；未知豁免不能显示为“不含豁免”。

### P0-4 Change set、合并、冲突、删除与回滚

**关联来源：** 原语义增量/版本控制、反馈中的第二/三批资料自动补全、冲突和 change log。

**Harness Merge Engine**

- [ ] `CompareRevision` 按 canonical entity + property/relation + 产品版本对比，输出 `add`、`enrich`、`supersede`、`conflict`、`retract`。
- [ ] 每个决定记录固定六步 `decision_path`：①产品/版本/主语身份，②已注册来源 trust/authority，③可靠生效时间与可验证来源发布时间，④Evidence 完整性/明确程度，⑤多个生产弱模型 Agent 的结构化 receipts（只能建议），⑥人工裁决/升级结果；完整度只能在前三级同等时比较，不能压过权威度和有效期。

**Harness 数据与发布制品**

- [ ] 新增 Space-scoped `change_sets`、`change_items`、`conflicts`、`claim_revisions`、`release_snapshots` 与不可变 manifests。
- [ ] 权威排序：正式条款/监管 > 已批准说明与 FAQ > 内部流程 > 培训 > 销售 > 外部研究；允许租户策略配置。
- [ ] 批次先产生不可变 change set；低风险补充最多可按批准策略自动形成 `candidate` ClaimRevision 与 append-only 决策事件，高风险替换、冲突、低置信归属进入审核；任何自动化都不能移动 `CurrentRelease` 或替代 release 级真人批准。
- [ ] 发布快照同时冻结 Claim、Wiki 页、QA、关系、目录、MCP manifest 与独立索引 generation；支持按批次反向 ChangeSet 和按已批准 snapshot 原子回滚。
- [ ] 删除来源按证据引用计数撤销或降级 Claim，不能删除仍有其他权威证据支持的知识。
- [ ] change log 必含系统/操作者、时间、来源、变更前后、合并原因、审核与回滚批次。

**Workbench 与 Wiki 投影**

- [ ] 产品级 change log、变更集详情、差异对比和回滚确认。
- [ ] Wiki 页显示当前版本、历史、有效期和来源变更。

**验收**

- 后续批次可补全首次导入的未知字段；冲突不会静默覆盖；回滚后 Claim、Wiki、QA、关系、目录、MCP、索引一致。

### P0-5 审核与发布门禁

**关联来源：** 原 Human-in-the-loop、当前 Wiki issue、产品方对更新验证的需求。

- [ ] 在 Harness 自有库新增 `review_items/review_decisions/release_approvals/current_release`；review key、外键、唯一键与指针全部 Space-scoped，不复用仅适合页面问题的 `wiki_page_issues`。
- [ ] 覆盖产品归属、冲突、低置信、高风险变更、Schema/TemplatePackage 修改和研究写回。
- [ ] 通过 WeKnora RBAC 身份与 Harness policy 映射，按产品、核保、理赔、合规配置审核人；决定与批准记录不可变。
- [ ] 每个生产 `ReleaseSnapshot` 必须由该 Space 具备 release 权限的真人最终批准；批准绑定完整 snapshot content hash，制品或身份任一变化都必须重新批准。
- [ ] 只有 WeKnora P-1 `active_release_id` 指向、批准 hash 匹配且被 Harness 验证的 snapshot 可进入默认 Wiki、QA、关系、MCP 与索引；本地 CurrentRelease 是 receipt 镜像，不能独立决定在线版本；仅有 `published` Claim 状态不等于在线可见。
- [ ] 发布先写不可见 release namespace，回读全部 manifest 后以 `seal-release(expected_write_etag, manifest_hash)` 原子冻结 namespace/index；批准仍有效且 hash 匹配时才以 WeKnora `activate-release` CAS 移动 serving alias。Space/target/staging KB 一一绑定，MCP 每次核对 alias/批准；当前及可回滚 release 制品 pin，GC 有显式授权事件，回滚先做物理 hash preflight。任一步失败保持旧 alias 或 fail closed。P-1 前只可写 ACL 隔离 staging，禁止生产 Wiki UI。
- [ ] Workbench 建立审核与发布工作台：证据对照、批准、退回重编、驳回、分派、批处理、snapshot diff、发布确认与回滚。

**验收**

- 任意生产 snapshot 均能定位授权人、策略版本、批准时间和完全匹配的 content hash；缺批准、hash 漂移或跨 Space 身份一律 fail closed。
- 发布/回滚后 Wiki、QA、关系、目录、MCP 与索引读取同一 snapshot；模拟第 N 页/索引失败时 active alias 不移动，并覆盖 alias CAS 竞争、ack 丢失、staging 不可见与 MCP mismatch fail-closed。

## P0.5：高吞吐批处理与一致性

**关联来源：** 现有 Wiki 并发 ingest 能力、反馈中的百/千份材料并发、冲突与合并。

### P0.5-1 分片策略与任务调度

- [ ] Harness 使用自己的持久任务、checkpoint、attempt ledger 与队列；不得直读/消费 WeKnora asynq。WeKnora 只负责其平台内部解析任务，双方通过 REST 生命周期契约衔接。
- [ ] 流程固定为：并行解析/抽取 -> 按产品版本分片 merge -> change set -> 批次 finalize/index。
- [ ] 以 `space_id + product_id + product_version_id` 为 merge 分片键；不同产品可并行，跨 Space 永不共享锁键或状态。
- [ ] 同一分片使用乐观锁/change-set revision 或等价串行化；延迟 worker 结果必须重新比较，不能覆盖新版本。
- [ ] 加入全局、租户、KB、产品、模型 provider 五级并发与限流；显示排队原因。
- [ ] 支持失败隔离、死信重放、取消未开始任务；重放使用原 schema/model/source 快照。
- [ ] finalize 只处理受影响产品/页面，避免每份文档全局重建索引。

### P0.5-2 批次可观测性

- [ ] 新增批次控制台 API：吞吐、分片、处理中、重试、冲突、待审核、死信和成本。
- [ ] Workbench 增加批次控制台、Alert/ReviewItem 认领与失败/冲突定位；WeKnora 原生队列状态仅作解析底座观测。

**验收：** 千份混合材料导入时，不同产品并发；同一产品无丢更新；失败文档不阻塞其他产品。

## P1：产品知识运营、QA 与 Schema 工作台

### P1-1 产品知识仪表盘、质量与缺口

**关联来源：** 原 Graph Insights/知识缺口、反馈中的产品知识概览、全貌、质量评分和批量补全。

**Harness 服务与数据**

- [ ] 在 `harness/src/insurance_harness/workbench/` 与 Harness 自有库新增产品知识概览查询和 `knowledge_completeness_snapshots`；异步聚合，避免仪表盘全表扫描。
- [ ] 完整度按 Schema 的必填/条件必填、`unknown`、冲突、过期、无证据和未审核状态计算。
- [ ] 质量分由字段覆盖、来源权威度、证据完整度、版本新鲜度、冲突、审核和 Wiki 链接健康度构成，并可解释到字段。
- [ ] 每个缺口生成可执行建议：指定材料重编、批量补抽取、人工确认不适用、补充已有资料或发起研究。

**Workbench**

- [ ] 在独立 Workbench 增加 Product Knowledge Dashboard；不向 WeKnora Vue 写保险业务页面。
- [ ] 展示产品/版本/险种筛选、知识全貌树、字段矩阵、质量分、缺口、冲突、来源和变更趋势。
- [ ] 支持选择缺口批量优化；先生成 change set 预览。

### P1-2 独立 QA 知识对象

**关联来源：** 原 FAQ 自动生成、产品方“主实体均需要 QA”反馈。

- [ ] 在 Harness 自有库新增 Space-scoped `qa_items/qa_revisions`：问题、标准意图、答案 Claim IDs、关联实体 IDs、产品/版本、有效期、来源、状态和质量分。
- [ ] Harness 从 FAQ、条款、服务材料提取/去重/对齐 QA；回答必须由目标 ReleaseSnapshot 的 Claim 支持，不能只保存 LLM 文本。
- [ ] 一个 QA 可关联多个产品/服务/实体；产品页仅聚合显示相关 QA。
- [ ] Wiki/MCP/Agent 将 `CurrentRelease` 同快照 QA 作为高精度候选，仍执行权限、版本、审核与证据过滤。
- [ ] Workbench 支持 QA 相似问题合并、答案差异、来源、审核和历史版本。

### P1-3 Schema/TemplatePackage 与提示词工作台

- [ ] 在 Harness 自有库新增 `schema_registry/schema_versions/template_packages/template_versions`，四级叠加、全量版本化、可评测、可批准、可回滚。
- [ ] Workbench 支持 JSON Schema/表单编辑、适用范围、继承栈、字段类型、条件必填、同义词、示例、证据/来源准入、风险、尝试/预算、质量和告警策略。
- [ ] Harness 可根据知识背景介绍、样本文档和产品线用生产弱模型提出 Schema/prompt 草案；草案必须经确定性校验、golden slice 与人工批准，不能直接进入生产批次。可选离线强模型不得成为模板生成或批准前置。
- [ ] dry-run 展示将抽取字段、缺项、成本、与当前 Schema 差异和受影响知识范围。
- [ ] Schema 更新只能产生再编译计划，不能隐式重写已发布知识。

## P2：融合图谱、分类优化与主动研究

### P2-1 领域图谱、社区与洞察

**关联来源：** 原 4 信号图谱、Louvain、Graph Insights、知识缺口发现。

- [ ] Harness 融合 Wiki 链接、共同来源、实体关系、类型/保险本体约束，计算关联；权重以保险金标准集调优。
- [ ] Harness 实现 Louvain 社区、孤立节点、稀疏社区、桥接节点、意外关联和知识缺口。
- [ ] 在 Harness 自有库新增 Space-scoped graph edges/communities/insights，并编入 ReleaseSnapshot relation manifest；WeKnora 只复用通用页面链接图展示/API。
- [ ] 在 `harness/src/insurance_harness/mcp/` 新增 `query_insurance_graph`，先按 Space、当前 snapshot、版本、有效期过滤。
- [ ] Workbench 提供“页面链接图/保险知识图”视图，展示关系、证据、有效期和洞察卡；洞察只可进入审核或补全任务。

### P2-2 分类与多产品精度持续优化

- [ ] 从 P0 的基础产品路由扩展为完整文档分类：条款、说明书、FAQ、理赔、核保、监管、培训、营销、案例、转写材料。
- [ ] Workbench 展示分类、置信度、所选 TemplatePackage stack，允许有权限用户覆盖并保留模型理由；覆盖不能提升来源 trust level。
- [ ] 建立多产品文档标注集和持续评测：分类、归属、字段抽取、跨产品污染和冲突发现。
- [ ] 只有达到独立阈值的 TemplatePackage slice 可自动形成低风险 merge 候选，其余仅产生待审核 ChangeSet；生产 snapshot 仍须真人最终批准。

### P2-3 受控 Deep Research

- [ ] Harness 根据缺口/洞察生成可编辑研究主题、查询词和预期 Schema。
- [ ] Harness 经批准的 adapter/MCP 调用受控搜索工具，记录 URL、抓取时间、提供商、许可/可信度、不可变模型身份和证据链；不得把保险 research 逻辑写入 WeKnora Go。
- [ ] 研究结果只能进入候选和审核，不能自动替换正式条款或监管知识。
- [ ] Workbench 支持从洞察卡发起、编辑查询、查看进度和提交审核。

## P3：PPTX、音视频与多模态事实

### P3-1 PPTX 处理强化

- [ ] 核验并完善 docreader 对 PPTX 标题、备注、表格、讲稿、图片/OLE 对象和跨页上下文的提取。
- [ ] Harness Compiler 使用“演示文稿 -> 幻灯片 -> 内容块/图像”证据层级，保存页码和对象位置。
- [ ] Workbench/Wiki 投影支持幻灯片预览、图表证据和跳页。

### P3-2 音视频知识编译

- [ ] 新建独立 media pipeline，负责转码、ASR、说话人、时间戳和章节；不把转写塞入 docreader。
- [ ] 转写片段作为 Evidence，Compiler 提取事实/QA 时必须返回时间戳。
- [ ] 加入数据分类、访问控制、保留期、脱敏和人工审批，尤其适用于客户/理赔录音。
- [ ] Workbench 提供播放器、文本、时间戳跳转、状态和失败恢复。

### P3-3 图片知识化

- [ ] 通过 WeKnora 通用 REST 能力或已登记的上游通用补丁暴露稳定 `image_asset_id` 与受控对象 URL；不得在 WeKnora Go 中加入保险语义。
- [ ] Harness 通过受控 URL/ID 与已批准 Qwen-VL 级弱模型提取图表候选事实，写入 Claim/Evidence，保留模型 identity、OCR/VLM 置信度和源页。
- [ ] Workbench/Wiki 投影展示图片证据、预览和源页跳转。

## 5. 实施依赖与推荐交付切片

| 切片 | 依赖 | 交付范围 | 完成定义 |
| --- | --- | --- | --- |
| S0 金标与评估 | 无 | 05 的独立标注/eval | 跨险种分层 golden slice、冻结 comparator、disputed≤5%、零实时强模型门禁 |
| S1 产品对齐与模板栈 | S0 的指标契约 | P0-1 | 多产品文档产生产品级候选事实；四级 TemplatePackage 可版本/评测；未归属内容隔离 |
| S2 快速导入与证据 | S1 | P0-2、P0-3 | JSON/FAQ 直入；Claim 有证据、有效期和三态字段 |
| S3 可控更新 | S2 | P0-4、P0-5 | change set、审核、版本、删除和回滚闭环 |
| S4 批量生产 | S3 | P0.5 | 产品分片并发、限流、失败隔离和批次控制台 |
| S5 产品运营 | S3 | P1-1、P1-2、P1-3 | 仪表盘、缺口、QA、Schema 工作台与批量优化 |
| S6 智能演进 | S5 | P2 | 领域图谱、洞察、分类评测、受控研究 |
| S7 多模态扩展 | S2 | P3 | PPTX、音视频、图片事实及证据体验 |

## 6. 统一测试与发布要求

- [ ] Harness：Schema/TemplatePackage 解析、路由、字段三态、结构化映射、diff、冲突、Space 隔离、审批 hash、CAS 发布与图谱算法单测；以冻结金标准语料做评测。
- [ ] WeKnora adapter：REST/MCP/RBAC/source lifecycle/页面回读契约测试；只有通用上游补丁才增加对应 Go/Vue 测试，保险逻辑修改数必须为 0。
- [ ] Workbench：导入预检、产品候选确认、审核、差异、snapshot 发布/回滚、仪表盘和 TemplatePackage dry-run 的组件/API 测试。
- [ ] 集成测试：多产品材料 + JSON FAQ + 后续修订/删除 + 并发失败注入，验证最终 Wiki、QA、关系、目录、MCP、索引、引用和 change log 均来自同一 snapshot。
- [ ] 准入开关：按 Space、险种、文档类型、产品族 TemplatePackage slice 分阶段启用；未达到门槛时只能生成待审核候选。达到门槛也只减少逐字段人工操作，**不能绕过每个 ReleaseSnapshot 的授权人最终批准**。

## 7. 不在当前主线内的事项

- 浏览器剪藏器、Obsidian 兼容性和桌面端体验不是保险知识编译 P0-P3 的阻塞项。
- Deep Research 在 P0 证据、版本、审核能力完成前不得开放自动写回。
- 图谱可视化可以复用现有页面链接图，但领域图谱不应以单纯可视化替代版本化事实模型。
