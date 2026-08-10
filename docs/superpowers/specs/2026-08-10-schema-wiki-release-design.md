# Schema Wiki Release Design

> 日期：2026-08-10
> 状态：`APPROVED DESIGN / IMPLEMENTATION NOT STARTED`
> 范围：Schema 驱动的 Knowledge Wiki 编译、审核、发布、导航和引用合同
> 上位约束：WeKnora 是唯一 serving Active Release authority；Harness 负责
> Schema 语义编译、Candidate、审核和发布授权，不保存第二个 serving Head

## 1. 决策摘要

本期只建设平安 e 生保 `596-1` 医疗险的 **Schema Wiki 纵切**。它把已批准的
医疗险 `SchemaPack`、冻结 Candidate 和可回放 Evidence，确定性编译成一整版
`KnowledgeWikiRelease`，经具名人工审核后，由 WeKnora 原子激活为唯一 Active
Head。下述通用领域对象只冻结未来兼容边界，不授权或交付通用平台。

“产品 Wiki”只是一个 KnowledgeDomain，不是平台硬编码的唯一形态：

- 医疗险产品 Wiki 使用医疗险 SchemaPack；首个纵切是平安 e 生保 `596-1`；
- 权益 Wiki（包括“臻享家医”）和后续条款知识、服务知识、运营规则属于未来
  Mission；本期不实现这些知识域或跨域复用。

当前 WeKnora 从文档 chunks 自动生成的 Wiki 保留为 **材料 Wiki**。它用于浏览、
检索和回到原始材料，不因页面看起来结构化就成为 Schema 事实，也不得冒充产品
Wiki、权益 Wiki 或正式 Active Release。

## 2. 目标与原则

### 2.1 目标

1. 每个知识实体拥有稳定身份，分类和路径可以演进而不改变实体身份。
2. 每个 Schema 字段都有独立、可寻址、可引用、可审计的 Field Page。
3. 页面、字段值、引用、导航、重定向和 Agent payload 始终来自同一 Release。
4. `present`、`absent_explicitly`、`unknown` 都可被诚实发布；缺材料不被改写成
   “无”。
5. 发布是整版原子动作；审核失败、身份漂移或引用失效时零部分发布。
6. WeKnora 继续承载唯一 Active Head、pinned read、ACL 和回滚；Harness 不形成
   第二个线上 Head。

### 2.2 设计原则

- **Schema-first**：栏目和 Field Pages 来自版本化 SchemaPack，不来自通用 Wiki
  prompt 或 Markdown 猜测。
- **Identity before path**：路径是可变视图，Entity ID、Version ID 和 Release ID
  才是权威身份。
- **Evidence before prose**：页面 prose 是字段状态和 Evidence 的确定性渲染，不
  是新的事实来源。
- **Whole-release atomicity**：任何读取只能看到完整旧版或完整新版。
- **Fail closed**：缺身份、缺页码、revision 漂移、Candidate 结构不完整（缺少
  SchemaPack 要求的字段成员或合法状态）、审核未完成或 Active Head 不明确时拒绝
  正式发布和正式回答。合法的 `unknown` Field member 不属于结构不完整。
- **No fallback**：Schema 发布失败时不得退回 generic Wiki 页面充当正式页面。

## 3. 未来兼容领域模型（本期不实现通用平台）

### 3.1 核心对象

| 对象 | 职责 |
|---|---|
| `KnowledgeDomainV1` | 定义产品、权益等顶层知识域，不携带具体字段答案 |
| `SchemaPackV1` | 版本化定义 Category/Section/Field、字段顺序、状态和值形状、Evidence 要求和渲染规则 |
| `KnowledgeEntityV1` | 稳定实体身份；例如平安 e 生保、臻享家医 |
| `KnowledgeEntityVersionV1` | 实体的可版本化业务快照；例如产品版本 `596-1` |
| `ActiveTaxonomyV1` | 当前生效的分类树、父子关系、显示顺序、别名和重定向集合 |
| `SchemaCandidateV2` | 冻结 Schema 字段输出、Evidence、任务/批次回执和完整身份链 |
| `KnowledgeWikiReleaseV1` | 一整版页面、字段 payload、引用、导航、重定向及其 manifest |
| `CitationTargetV1` | 从字段页回放到 exact revision/page/locator/quote 的引用目标 |

SchemaPack 负责“应该有哪些知识槽位”；Candidate 负责“本次编译得到什么”；
KnowledgeWikiRelease 负责“哪一整版知识可以被正式读取”。三者不得合并成一个可由
调用方自签的对象。

### 3.2 稳定 Entity ID 与版本化 Active Taxonomy

`entity_id` 在实体生命周期内稳定，不从中文标题、目录路径或当前分类计算。路径
由 Active Taxonomy 物化，例如：

```text
/medical-insurance/medical-products/ping-an-e-sheng-bao/596-1/...
/benefits/medical-services/zhen-xiang-jia-yi/current/...
```

分类调整只产生新的 Taxonomy version：

1. `entity_id`、历史 EntityVersion 和历史 Release 不变；
2. 新 Active Taxonomy 改变父节点或显示路径；
3. 旧 canonical path 进入 release manifest 的 redirect map；
4. pinned 历史读取仍按历史 taxonomy snapshot 展示；
5. current read 使用当前 Active Taxonomy，但解析到同一稳定 Entity ID。

因此“臻享家医”从“增值服务”调整到“家庭医疗权益”时，只发生 reparent 和路径
重定向，不新建实体、不丢历史、不复制答案。

## 4. Wiki 层级与页面模型

统一层级为：

```text
Domain → Category → Entity → Version → Section → Field Page
```

- **Domain**：产品 Wiki、权益 Wiki 等知识域。
- **Category**：可版本化分类，例如医疗险、医疗服务权益。
- **Entity**：稳定业务实体。
- **Version**：产品版本、权益方案版本或其他业务版本。
- **Section**：SchemaPack 定义的栏目，只负责组织字段。
- **Field Page**：一个 Schema 字段的 canonical page；包含三态、公开值视图、
  Evidence 摘要、引用、审核状态和版本历史。

Section index 可以聚合字段摘要，但不能替代 Field Pages。Agent payload 与 UI 页面
必须引用同一 field member digest；不能让 UI 读聚合 prose，而 Agent 读另一套字段
JSON。

### 4.1 医疗险 Schema67 的七个栏目

医疗险的七栏目和 67 个字段仅属于
`medical-schema67.v1`，不是平台全局枚举：

| 栏目 | 字段数 | Schema 字段 |
|---|---:|---|
| 产品概览 | 16 | `product_code`、`product_short_name`、`product_name`、`sales_start_date`、`sales_end_date`、`product_type`、`insurance_category`、`sales_channels`、`external_publication_status`、`sales_status`、`policy_role`、`product_summary`、`official_product_features`、`target_customer_profile`、`marketing_tagline`、`product_overview` |
| 投保与合同 | 15 | `entry_age_range`、`insured_eligibility`、`health_declaration_requirements`、`geographic_eligibility_requirements`、`social_insurance_requirement`、`eligible_occupation_classes`、`underwriting_method`、`premium_payment_term`、`premium_payment_frequency`、`cooling_off_period`、`waiting_period`、`premium_grace_period`、`coverage_period`、`coverage_term_category`、`surrender_and_cancellation_terms` |
| 续保与费率 | 6 | `coverage_and_renewal_terms`、`guaranteed_renewal_status`、`guaranteed_renewal_period`、`product_conversion_rules`、`premium_adjustment_rules`、`post_discontinuation_renewal_arrangement` |
| 保障与除外 | 11 | `covered_risk_categories`、`coverage_responsibilities`、`coverage_summary`、`cancer_medical_coverage`、`age_segment_tags`、`coverage_limit_category`、`special_coverage_and_exclusion_tags`、`exclusions`、`pre_existing_condition_rules`、`out_of_hospital_special_drug_coverage`、`indemnity_principle` |
| 理赔与报销 | 9 | `zero_deductible_flag`、`deductible_rules`、`outpatient_inpatient_scope`、`reimbursable_expense_scope`、`reimbursement_rate_rules`、`eligible_hospital_scope`、`premium_medical_facility_coverage`、`direct_billing_and_advance_payment_rules`、`claim_application_deadline_and_documents` |
| 服务与权益 | 5 | `policyholder_rights`、`eligible_service_packages`、`medical_service_benefits`、`tax_qualified_status`、`tax_benefit_rules` |
| 销售支持 | 5 | `product_bundle_rules`、`objection_handling_scripts`、`product_faq`、`four_step_sales_script`、`sales_pitch_script` |

SchemaPack 可以在后续版本调整栏目归属和显示顺序，但字段迁移必须保留 Field ID、
历史页面和旧路径重定向。字段语义发生实质变化时必须新建字段版本或新 Field ID，
不能只改标题。

## 5. Candidate 到 Active Release

正式数据流固定为：

```text
approved SchemaPack + exact SourceRevisions
  → Schema67 CandidateV2
  → deterministic KnowledgeWikiRelease compilation
  → immutable Draft Release
  → named-human review of the exact Candidate/manifest
  → PublishAuthorization
  → WeKnora atomic activation/CAS
  → sole serving Active Head
```

确定性编译器只做：

- 校验 CandidateV2、SchemaPack、ProductVersion、Evidence 和批次回执；
- 为每个字段生成 Field Page payload；
- 生成 Section/Version/Entity index pages；
- 生成 CitationTarget、redirect map、search/index members；
- 计算 canonical member digests 和整版 manifest digest。

它不得重新抽取、改写字段状态、调用模型或从 Markdown 补事实。具名人工审核绑定
exact Candidate 与 exact manifest，不能只审核页面截图或单字段。激活失败时 Active
Head 不变；Draft 可以保留审计，但不得参与正式检索。

当前 generic Wiki 链继续生成材料摘要、实体和概念页面，但这些页面明确标记为
`material_wiki`，不进入 KnowledgeWikiRelease 的正式 Field members。Schema 发布
失败时保持上一个 Active Release；没有上一个 Active Release 时返回知识不足，而
不是 fallback 到材料 Wiki。

## 6. 字段三态及页面语义

### 6.1 `present`

- 表示当前版本、当前 scope 下有被支持的值；
- 页面显示规范值、适用条件、Evidence 摘要和引用入口；
- 至少一条 Evidence 必须通过 replay；多来源字段按 SchemaPack 要求保留全部必需
  source role。

### 6.2 `absent_explicitly`

- 只表示原文明示“无”“不适用”“不提供”等直接事实；
- 必须有可回放的正向否定 Evidence；
- “未提及”“没有证据表明”“材料未覆盖”不能进入此状态。

### 6.3 `unknown`

- 表示当前批准材料不足以判断；
- 无 value、无伪造 Evidence；
- **允许发布**，并生成稳定的“待补充”Field Page；
- 页面必须说明缺少的材料角色或审核项，不得显示为 absent；
- Agent 读取时返回 typed unknown，不从材料 Wiki、相邻产品或旧版本猜答案。

unknown 可发布不等于它通过了完整性目标。Release manifest 必须记录 unknown 数量、
字段集合和 ReviewItems，UI 在 Entity/Version/Section 层聚合显示待补充状态。后续补充
材料形成新 Candidate 和新 Release，不原地修改旧页。

## 7. `CitationTargetV1`

每条正式 Evidence 引用至少绑定：

```text
knowledge_id
source_revision_id
chunk_id
page_number
locator_kind + locator_id
bbox (x0, y0, x1, y1, coordinate_space)
quote_sha256
content_sha256
```

并同时绑定所属 `space_id`、`product/entity_version_id`、parse attempt、document/
manifest digest 和 release member digest。公开页面可以展示短 quote snapshot，但
canonical identity 使用 hash 和 exact locator custody。

引用行为：

1. 用户点击引用后打开 exact SourceRevision，而不是 current/latest 文档；
2. viewer 精确跳到 `page_number` 并高亮 bbox；
3. page、locator、bbox 和 quote/content hash 必须能在该 revision 重放；
4. revision、manifest、page count 或 locator 漂移时拒绝打开为“已验证引用”；
5. 缺 page 时返回 typed `PAGE_UNAVAILABLE`，**不得默认 page 1**；
6. 正式 Evidence 必须有可信 bbox；缺失时返回 typed `BBOX_UNAVAILABLE` 并阻断该
   Field member 的正式发布，不得制造 `(0,0)`、整页 bbox 或降级为无高亮的正式
   citation。

第 12 页和第 27 页必须作为 MVP 的独立验收引用：页面跳转、bbox、quote hash、
revision pin 和返回导航都要机械验证。

## 8. UI 与读取体验

### 8.1 导航

左侧导航按 Active Taxonomy 展示 Domain → Category → Entity → Version → Section →
Field Page。Entity 页显示当前 Active Version、历史版本、完整性摘要和该
SchemaPack 定义的 Sections；医疗险 `medical-schema67.v1` 才固定显示七个 Section。
Field Page 是最小可链接单位。

### 8.2 草稿和审核

- Draft 使用独立路由和显著 Draft 标识，不进入普通搜索、Agent 或 current read；
- Reviewer 看到 exact Candidate/manifest、字段状态变化、引用和 ReviewItems；
- 审核动作作用于整版 Candidate/Release，不提供绕过整版校验的单页“直接发布”。

### 8.3 历史与回滚

- Version 页面列出 Release history、named-human decision 和变更摘要；
- pinned URL 永远读取指定 `release_id`；
- current URL 读取唯一 Active Head；
- 回滚是 WeKnora Active Head 的原子整版切换，并产生 receipt；
- 回滚后 current read 全部指向旧 Release，已有 pinned read 不混版。

### 8.4 材料 Wiki

材料 Wiki 保留现有 generic summary/entity/concept/index/log 体验，但 UI 必须与 Schema
Wiki 分区并标记“材料整理，非正式字段结论”。材料页可以链接到正式 Field Page 的
CitationTarget，不能反向覆盖正式字段。

## 9. 发布安全边界

发布前按固定顺序 fail closed：

1. SchemaPack、Active Taxonomy、EntityVersion 和 source/revision 身份 exact；
2. CandidateV2 concrete seal、ordered fields、task/batch receipts 和 Candidate hash；
3. 每个 `present`/`absent_explicitly` 字段的 Evidence replay；`unknown` 必须无
   Evidence；
4. Field Page、CitationTarget、redirect、index 和 Agent payload 的 canonical digest；
5. manifest closed-world member set，无缺页、额外页、重复 ID 或跨 Entity/Version 成员；
6. named-human ReviewDecision 与 PublishAuthorization 绑定 exact Candidate/manifest；
7. WeKnora preparation、ACL、base release 和 CAS；
8. 激活后 pinned/current page、payload、search/index 同 release_id 回读。

任一步失败均为零 Active 写；不得留下部分 Field Pages、部分索引或新旧导航混用。
普通 `wiki_pages` PUT/DELETE 不能修改 release-managed 页面。没有可信 Active Release
时，正式回答必须返回知识不足。

## 10. 当前真实断点

本设计不把目标能力写成当前事实。2026-08-10 的真实状态是：

1. **generic chunks → Wiki 是外部运行快照**：KB
   `b1f1764c-443d-46b8-98e3-d5aa5e55eb42` 的三份材料已走过 WeKnora generic
   Wiki 链；该状态不属于本 Git tree，也不是 Schema67 Release 证据。terms 文档
   ID 为 `f987fc16-222a-4246-8ca0-22c1a81dd6d9`，rate 文档 ID 为
   `32402c40-6131-4049-8080-cc5b68188cd3`；brochure 文档 ID 未取得，不得虚构。
   仅 rate ingest 回执记录 `pages_affected=14`，这不是三份材料的总页数或总页面数。
2. **Schema Candidate absent**：真实 exact8 DeepSeek 执行以
   `EXTRACTOR_RESPONSE_INVALID` 终止，`candidate_published=false`，未产生可发布
   CandidateV2。
3. **旧 Candidate manifest 接口不兼容**：历史 Candidate/wiki member manifest 或
   repo-external runner 不能直接作为当前 Schema67 CandidateV2 → KnowledgeWikiRelease
   输入，禁止靠手工重组或自报 hash 接线。
4. **Release UI 未接**：WeKnora 已有 generic Wiki UI 和 release/custody 能力基础，
   但上述 Domain/Entity/Version/Section/Field 导航、Draft review、Citation viewer 与
   Active Release 读取尚未形成正式纵切。
5. **不能原地升级 generic 页面**：外部材料 Wiki 页面不得通过改 slug、标题或
   metadata 冒充 67 个 Field Pages；rate 的 `pages_affected=14` 也不构成
   Schema Field Page 闭包。

因此当前终态仍是 `NO_SCHEMA_WIKI_ACTIVE_RELEASE`。这不影响材料 Wiki 的已有浏览
价值，但应用不得把它当作正式 Schema 结论。

## 11. MVP 迁移

### 11.1 迁移顺序

1. 保留 `medical-insurance-mvp` 中的三份材料、chunks 和 generic Wiki，标记为材料
   Wiki 输入。
2. 注册医疗险 KnowledgeDomain、`medical-schema67.v1` SchemaPack 和 Active
   Taxonomy。
3. 创建稳定 Entity：平安 e 生保；绑定 ProductVersion `596-1`。
4. 对已失败 exact8 完成根因分析，形成新的 approved successor identity 和单次
   授权后才执行 Schema67 编译；不得重跑已冻结的失败 identity。成功后产生
   concrete sealed CandidateV2。
5. 确定性生成 1 个 Version root、7 个 Section indexes、67 个 Field Pages、引用、
   redirects、search/index members 和 manifest。
6. 具名人工审核 exact Candidate/manifest，形成 Draft → PublishAuthorization。
7. 在 release-managed Wiki KB 中原子激活 R1，回读 page/payload/search/index。
8. 用后续补充或 taxonomy 调整生成 R2，验证 pinned read 和整版回滚到 R1。

MVP 继续遵守 `1 Space = 1 RAW KB + 1 release-managed Wiki KB`。每款产品通过稳定
Entity/Version namespace 独立呈现，而不是为每款产品新建一套 serving authority。
未来若要求每产品独立 KB，必须另立 ADR、OpenSpec 和 ACL/migration 设计。

### 11.2 MVP 验收

| 验收项 | 通过条件 |
|---|---|
| 产品身份 | 平安 e 生保 Entity ID 稳定；`596-1` 与三份 exact source revisions 唯一绑定 |
| 页面闭包 | 1 个 Version root、7 个 Section、67 个 Field Pages 与 manifest exact 对齐 |
| 三态 | present/absent/unknown 均按合同渲染；unknown 生成“待补充”页且不伪装 absent |
| 引用 | 第 12、27 页引用跳转、bbox、quote/content hash、revision pin 全部通过 |
| 原子发布 | 发布前读 R0，成功后只读完整 R1；故障注入不得看到部分 R1 |
| 审核 | named-human decision 绑定 exact Candidate 和 manifest，单页不能绕过 |
| 读取一致 | page、Agent payload、search/index 使用同一 release_id |
| 回滚 | R2 → R1 原子回滚；current 与 pinned read 均不混版 |
| generic 隔离 | 材料 Wiki 可浏览，但不能进入正式回答或替代 Schema Field Page |
| taxonomy 演进 | `596-1` 医疗险分类路径调整后 Entity ID 不变、旧路径重定向、历史 snapshot 可读 |

## 12. 明确不做

- 不通过普通 `wiki_pages` 直写、更新或删除 release-managed 正式页面；
- 不用 generic Wiki prompt、Markdown 相似度或目录猜测伪造 Schema 字段；
- 不把医疗险七栏目、67 字段或产品术语硬编码为平台全局分类；
- 不允许部分字段、部分页面、部分索引先行发布；
- 不在引用缺页时默认跳到 page 1；
- 不让 current 文档替代 exact SourceRevision；
- 不让 unknown 自动变成 absent，不从相邻产品或旧版本补答案；
- 不把 Harness receipt 或本地 manifest 变成第二个 serving Active Head；
- 不在本设计中实现 Release Kernel、UI、migration、provider 调用或运行时部署；
- 不在本期实现权益 Wiki、“臻享家医”或跨知识域通用平台；
- 不以本设计文档授权生产代码、数据库、OpenSpec 或外部系统写入。

## 13. 后续实现前置门

本设计通过后，实施仍必须另行取得 Mission Card，并以小 PR/OpenSpec 交付。第一个
实现 Mission 应只冻结并验证以下最窄纵切：

```text
concrete Schema67 CandidateV2
→ deterministic 67 Field Page members + CitationTargetV1
→ immutable Draft manifest
→ named-human authorization
→ WeKnora experimental atomic activation/pinned read/revert
```

在 Candidate absent、旧接口未完成机械适配或 Release UI 未接时，不得跳过中间合同
直接改写当前 generic Wiki。
