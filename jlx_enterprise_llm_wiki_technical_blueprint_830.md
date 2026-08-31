# Enterprise LLM Wiki 技术蓝图 830 · 统一企业知识库扩展版

> 修订日期：2026-08-31
> 状态：`CURRENT_830_TECHNICAL_BLUEPRINT`
> 基线：`815 FLOW=PASS`；`QUALITY=DEFERRED`
> 核心裁决：830 只扩展已跑通的 815 节点，不新建平行系统

## 0. 权威、状态与执行顺序

本文是 830 唯一技术蓝图，定义产品模型、逻辑/物理架构、数据契约和演进边界。
830 执行章程与 Goal Cards 只细化执行和验收，不得另造架构。默认权威顺序：

1. `jlx_enterprise_llm_wiki_technical_blueprint_830.md`；
2. `docs/insurance-kb/28-development-execution-charter-830.md`；
3. `docs/insurance-kb/29-goal-cards-830.md`；
4. `AGENTS.md` / `HANDOFF.md` 当前执行与交接事实。

状态固定为：

```text
815_FLOW=PASS
815_QUALITY=DEFERRED
SCHEMA_CATALOG=11_PRODUCT_PACKS_SOURCE_VERIFIED_NOT_REGISTERED
CURRENT_GOAL=B0
B0_STATUS=EVIDENCE_FROZEN_PENDING_CONTROLLER_REVIEW
G1_AND_LATER=LOCKED
830_ORDER=B0→G1→G2→G3→G4→G5→G6A→G6B→G6C→G6D→Q0→G7
```

`FLOW=PASS` 指 815 已在同一 lineage 跑通：

```text
WeKnora parse → Harness → Formal Candidate → Preview → Review → Active → 来源点击
```

`QUALITY=DEFERRED` 既非 PASS 也非 FAIL。Q0 是 830 最后质量门；G7 只消费 Q0
完成多格式 FLOW + QUALITY 联合验收，不新增功能、不改样本和阈值。

## 1. 背景与总裁决

815 已解决“真实来源能否到正式 Active 并点回来源”的物理不确定性。830 要解决的
是从一个医疗险产品扩展到大量产品、权益、服务实体，同时保持一个企业知识库、
一条 Candidate→Release 主链和一个在线真相。

最终架构只有一条：

```text
WeKnora 上传 / 解析 / SourceRevision
  → Harness 分类、实体识别、SchemaPack 编译、Claim/Evidence、语义 Diff
  → WeKnora Formal Candidate / Preview / 唯一审核 / 唯一 Release / 唯一 Active
  → 同一 Active 的 Wiki / Search / Agent / 多格式来源点击
```

产品、权益、服务不是三套库或三套领域表，而是统一 `KnowledgeEntity` 上的可配置
分类视图。当前已收到并核验 11 类保险产品 Schema；医疗险 67 字段只是其中一个
版本化 `SchemaPack`。权益、服务等非产品实体仍可拥有自己的 SchemaPack，共用同一
编译、审核、发布、读取和 Evidence 合同。

## 2. 第一性原理与不变量

1. **结构化事实先于页面。** `Claim + Evidence` 是唯一内容源；Markdown/HTML 是
   同一 Release 的可重建投影，不是第二事实库。
2. **身份与分类分离。** 实体 ID 回答“是谁”，分类回答“在哪个视图展示”；重新
   分类不改变 ID、Evidence、Claim 历史或旧 Release。
3. **Evidence 先于自动化。** 模型可提出分类、事实和概念候选，不能创造来源、
   提升来源权威、伪造 locator 或直接写 Active。
4. **Candidate 到 Active 是唯一治理关口。** 自动、批量、人工和专家编辑都形成
   Candidate；`AUTO_ACTIVE` 也必须生成审计决定并走同一 Release/CAS。
5. **只有一个在线真相。** WeKnora 是唯一 Wiki、审核、Release 和 Active serving
   authority；Harness 只做领域编译，不拥有第二 Wiki/审核/Active/Evidence reader。
6. **失败关闭。** 来源定位必须使用 Release 绑定的 exact revision/locator；失败
   返回 typed error，不改用 current revision，不猜相似 quote，绝不跳第 1 页。
7. **不直接覆盖 Active。** 增量更新和专家修改都产生新 ClaimRevision、Candidate
   和 Release；新 Release 激活前旧 Active 完整服务。
8. **Schema67 不是企业本体。** 其他实体类型不继承医疗险字段，除非显式复用已
   版本化的 FieldDefinition/ConceptDefinition。

## 3. 现状证据与参考基线

830 冻结的客观起点如下：

| 815 节点 | 已有物理结果 | 830 处置 |
|---|---|---|
| parse / SourceRevision | 真实来源可冻结、重开、进入编译 | 复用 WeKnora parser |
| Formal Candidate | ordered Schema67 + Evidence 路径已通 | 参数化为 SchemaPack |
| Preview / Review | Candidate 可在 WeKnora 预览和决定 | 扩展页面图和策略 |
| Release / Active | immutable Release、Head、current/pinned 已接线 | 保持唯一 Active |
| source click | Active 字段可点回冻结来源 | 扩展联合 SourceLocator |

本轮基线 HEAD 为 `9fcf3386833d822a31f2de13fdf76c3eb6b13795`。可扩展接缝包括
Harness 的 `ec01_formal_candidate_run_815.py`、
`formal_candidate_derivation_validator_815.py`、`schema_wiki_c5_preview_815.py`，
以及 WeKnora 的 `schema_wiki.go`、`wiki_release.go`、
`schema_wiki_formal_candidate_preview.go`、`schema_wiki_citation_revision.go`、
`SchemaWikiBrowser.vue`、`SchemaWikiFieldPage.vue`。代码存在不替代真实验收，也不把
`QUALITY=DEFERRED` 改成质量通过。

三份已审输入：

- WeKnora `9b4f792a04d82bef630a2b2dc95344b3dad2649d`，版本 `v0.7.2+85`：
  复用上传、解析、ACL、Wiki/Search/Agent、Release/read/source viewer；
- nashsu/llm_wiki `e808211`，版本 `v0.6.11`：借鉴分析→生成、链接、去重和 lint；
  不照搬 GPL 实现表达、Markdown 权威、覆盖式 ingest 和缺少企业发布门的缺陷；
- 项目定制分支：复用已迁移到 Harness/WeKnora 的 Schema、Evidence、Candidate 和
  815 物理接线；不恢复旧 TypeScript 事实库、localStorage、逐页 publisher 或
  Harness Active。

### 3.1 11 类保险产品 Schema Catalog 输入

2026-08-31 新增核验的业务输入为：

- 文件：`【汇总】11类保险产品知识Schema_全局一致性校验更新版_20260812-v5.xlsx`；
- 当前本机路径：`/Users/houjing/Downloads/【汇总】11类保险产品知识Schema_全局一致性校验更新版_20260812-v5.xlsx`；
- SHA-256：`8feb33a1e7dc55fad1719a151737822e62bfac815f4b0969441e38744f0204ec`；
- 文件大小：112,185 bytes；工作簿共 12 个 sheet，其中 1 个汇总表、11 个产品 Schema；
- 汇总表列出 154 个去重字段，47 个字段实际出现在全部 11 类产品中；
- 11 个产品 sheet 的英文名均非空，单 sheet 内未发现重复字段名或重复英文名；
- 每个字段同时携带业务分类、中文/英文名、说明、取值来源、知识形成方式、知识角色、
  公共字段标识、其它适用险种和使用频次。

这只能证明 Catalog 结构可用，不能证明 11 类抽取质量均已通过。工作簿在 G3 前必须复制
到可持久审计的 Evidence Pack/项目资产位置并绑定上述 hash；不能让 Downloads 临时路径
成为生产依赖，也不能把“Schema 已定义”写成“模型已能准确抽取”。

## 4. 统一知识域、身份与分类

逻辑上只有一个知识域：

```text
KnowledgeSpace
  ├─ KnowledgeEntity
  │    ├─ overview
  │    ├─ section/*
  │    ├─ field/*       → FieldAssertion
  │    └─ free_wiki/*   → 受控发现页
  ├─ ConceptDefinition
  ├─ Claim / Evidence
  └─ ClassificationView
       ├─ products
       ├─ benefits
       ├─ services
       └─ enterprise_defined/*
```

稳定英文 ID 推荐使用 `ent_<ulid>`、`concept_<ulid>`、`claim_<ulid>`、
`evidence_<ulid>`、`schemapack_<english_key>`、`release_<ulid>`；中文名是可变短显示名。
canonical namespace/route 必须含稳定身份，不含分类路径：

```text
urn:jlx:wiki:<space_id>:entity:<entity_id>:field:<field_key>
/wiki/entities/<entity_id>/overview
/wiki/entities/<entity_id>/sections/<section_key>
/wiki/entities/<entity_id>/fields/<field_key>
/wiki/entities/<entity_id>/free-wiki/<free_wiki_id>
/wiki/concepts/<concept_id>
```

分类模型在最小解析之后、SchemaPack 选择之前先判定：

```text
parse → classify → resolve identity → select SchemaPack → compile
```

它输出实体类型/分类候选、置信度、依据 span 和 model receipt。高置信且身份门通过时
自动流转；不确定项人工确认。身份置信与分类置信分开。分类修改追加
`ClassificationAssignment`/`TaxonomySnapshot`，但稳定实体 ID、Evidence、Claim、
审核和历史不变，绝不“删旧实体后在新目录重建”。

批量冷启动时，exact identity key 唯一、身份/分类高置信、关键身份字段有 Evidence、
且无别名/版本冲突的新实体可自动创建 `EntityCandidate`。这只是自动建 Candidate，
不是自动 Active；歧义名称、混合材料和同名多版本进入人工队列。

## 5. 页面图与 FieldAssertion

| 页面 | 职责 | 唯一内容来源 |
|---|---|---|
| `overview` | 实体摘要、关键字段、目录、适用范围 | 同 Release Claim 投影 |
| `section` | pack-specific 字段分组与导航 | PresentationProfile + FieldDefinition + Claim |
| `field` | 实体某字段的状态、值、条件、Evidence、历史 | FieldAssertion 查询 Claim/Evidence |
| `free_wiki` | Schema 外高价值知识 | 通过硬门和评分的 Claim/Evidence |

每个实体适用 SchemaPack 中的每个 `FieldDefinition` 都是业务要求覆盖的字段，并且必须
生成且仅生成一个实体作用域 `FieldAssertion` 独立 Wiki 页；`required => page` 是
SchemaPack validator 的硬不变量，不提供把必填字段降为“只在表格中显示”的开关。
医疗险 Schema67 的 67 字段均属于该集合。有值显示
`present`；来源明确否定显示 `absent_explicitly` 和否定 Evidence；未知显示
`unknown` 与缺口，不得显示“无”。新增必填字段给既有实体生成 unknown 页；废弃字段
只 deprecated，旧 Release/路由保留。

产品字段“等待期”等默认先跳该产品自己的 FieldAssertion，展示该产品的值、适用范围、
Evidence 和历史，再链接共享 `ConceptDefinition(waiting_period)`。禁止直接跳共享
概念而丢失实体作用域事实。

815 的连续 `1 root + 7 presentation sections + 67 fields` 页面保留为组合视图；830 给每字段增加
独立 canonical page identity。组合页只内嵌/链接同一 ClaimRevision，不复制权威正文。

`PageManifest` 绑定 `page_id/page_kind/release_id/entity_id|concept_id/claim_revision_ids/
evidence_ids/schema_pack_identity/presentation_profile_identity/presentation_profile_hash/
renderer_identity/page_content_hash`，删除渲染 Markdown
后必须能由结构化对象确定性重建。

## 6. SchemaPack

`SchemaPack` 是一个实体类别在一个版本下的完整领域编译合同，至少包含：

```yaml
SchemaPack:
  schema_pack_id: schemapack_medical_insurance
  version: 1.0.0
  content_hash: sha256
  entity_type: insurance_product
  applicable_classifications: [medical_insurance]
  presentation_profile_ref: profile_medical_insurance@<version>+<hash>
  fields: []
  classification/extraction/normalization/validation/evidence/risk/review/renderer_policy_refs: {}
```

FieldDefinition 包含稳定 `field_key`、短显示名、说明、类型、三态、允许值、
`schema_category`、知识角色、知识形成方式、取值来源指导、风险、
适用范围、Evidence 规则、shared concept、normalizer/validator。进入 SchemaPack
的 FieldDefinition 即表示“必须尝试、必须成页”；仅用于内部计算的中间量不能伪装成
Schema 字段，应放在编译元数据中。

已核验的 11 类产品 Catalog 基线为：

| SchemaPack | 字段数 | 工作簿业务分类数 |
|---|---:|---:|
| 医疗险 | 67 | 9 |
| 意外医疗保险（sheet：意外医疗） | 70 | 9 |
| 意外险 | 62 | 9 |
| 重疾险 | 67 | 10 |
| 定期寿险 | 66 | 9 |
| 终身寿险 | 75 | 9 |
| 两全保险 | 79 | 9 |
| 年金险 | 82 | 9 |
| 护理保险 | 74 | 9 |
| 补充养老保险 | 83 | 9 |
| 失能收入损失保险 | 76 | 9 |

工作簿的 `02 产品主数据` 至 `11 保单价值、账户与保全规则` 是业务
`schema_category`；页面节点是 `presentation_section`。二者必须通过版本化映射配置关联，
不能假设数量相同或直接把分类编号当 UI 目录。医疗险当前 67 个字段落在 9 个业务分类中，
但展示为已验收的 7 个节点；其它 pack 根据实际可以是 6、7、8 或其它经确认的节点数。
调整展示映射不改变 field/entity ID、Claim、Evidence 或历史 Release。

11 类产品 pack 直接借鉴医疗险已验证的“分组页面 + 字段页面”布局方法，而不是分别开发
页面结构。下列 7 节点只是医疗险 Profile 的参考实例，不是其它 pack 的固定数量或语义：

```text
insurance_product_default_7
1. 产品概览
2. 投保与合同
3. 续保、费率与保全
4. 保障责任与除外
5. 理赔与给付
6. 服务与权益
7. 销售支持
```

每个 SchemaPack 持有自己的版本化 `PresentationProfile`，定义属于该 pack 的节点数、
section key、显示名、说明、字段顺序和 `field_key → primary_section_key` 映射。renderer
只依赖“有序 section 集合 + 字段映射”合同，不依赖节点数量或医疗险节点名称。例如年金险
可重点呈现交费、账户、领取与保全，医疗险则重点呈现续保与费率。映射必须满足每个
FieldDefinition 恰好进入一个主 section，且正式 Profile 不产生空节点；跨节引用使用链接
而不是复制字段。`presentation_section` 只在 exact PresentationProfile 中拥有权威，不能
作为可独立写入的 FieldDefinition 属性。Candidate/Release 必须绑定 exact profile
id/version/hash。非产品实体同样选择适合自身的 profile。

G3 可依据工作簿业务分类和医疗险既有布局批量生成 11 个 `PresentationProfile Candidate`，
由专家整包确认或调整节点数量及映射；不要求专家逐字段配置，也不允许为此手写 11 套
页面代码。

11 个 pack 从同一 Catalog 版本导入，例如
`schema_catalog_insurance_product@2026-08-12-v5+<hash>`，每个 pack 仍有自己的
id/version/content_hash 与 `presentation_profile_identity`。47 个出现在全部产品中的字段
只是公共 FieldDefinition 候选；必须在英文 key、说明、类型、允许值和 Evidence 语义一致
后才能显式共享。产品专属说明、允许值、Evidence 规则或语义不同则保留 pack-local
override，不能只因中文名相同自动合并。包间可显式复用字段/概念定义，不能通过隐式
继承静默互相改变。每个
Candidate/Release 绑定 exact catalog 与 pack id/version/hash。

兼容新增字段默认 unknown；字段语义变化创建新 field_key，旧字段 deprecated；section
重排不改变 FieldAssertion identity；重新分类导致 pack 变化时形成 migration Candidate，
不删除旧 Claim，不直接覆盖 Active。

## 7. Claim / Evidence 唯一内容源

最小 Claim 合同：

```yaml
Claim:
  claim_id: claim_<ulid>
  subject_ref: {entity_id} | {concept_id}
  predicate: lower_snake_case
  value_state: present | absent_explicitly | unknown
  value: json | null
  scope: {version, region, channel, population, scenario}
  valid_period: [valid_from, valid_to)
  system_period: [recorded_from, recorded_to)
  schema_pack_identity: {id, version, content_hash} | null
  origin: MODEL_COMPILE | STRUCTURED_IMPORT | EXPERT_EDIT | DERIVED
  expert_lock: boolean
  revision_no/previous_revision_id: {}
```

`SourceEvidence` 只表达原始材料支持，绑定 exact `source_revision_id + SourceLocator +
quote/value snapshot + authority policy`。专家修改记录使用独立但同属一个 ClaimRevision
生命周期的 `EditProvenance`，自动绑定 actor/time/before/after、可选 reason 和可选新
SourceEvidence，不能把人的决定包装成来源 Evidence。

专家改值而未补新来源时，新 ClaimRevision 的 `supporting_source_evidence_ids` 为空，并显示
“专家修改（无新增来源证据）”；旧 SourceEvidence 只作为 `prior_source_evidence_ids` 在历史
区展示，不得继续标成支持新值。专家补充了材料时，新增证据仍必须走普通 SourceEvidence
校验。这样既保留原始抽取和原文，也不会把原文与专家结论混成同一种证明。

Harness 在编译中形成 canonical Claim/Evidence Candidate；WeKnora 验证并把获准对象
绑定 immutable Release；Wiki/Search/Agent/source viewer 都读该 Release。Harness job
artifact 只用于重放审计，不能成为在线 Evidence reader。禁止把 Markdown 再解析回
Claim，禁止两处各自维护 evidence status/current。

## 8. 多格式 SourceLocator

公共字段：`kind/source_revision_id/source_content_hash/parse_manifest_hash/
parser_identity/locator_version/quote_hash`。联合类型 ID 固定为：

| kind | locator payload |
|---|---|
| `TEXT_BLOCK_OFFSET` | block id、code-point/byte 语义明确的 offset range、quote |
| `PDF_PAGE_BBOX` | 1-based page、quote/span、bbox；`text_origin=NATIVE|OCR` |
| `IMAGE_REGION` | image/page id、bbox/polygon、OCR quote |
| `DOCX_PARAGRAPH_RANGE` | `range_kind=PARAGRAPH|TABLE_CELL`；段落 range 或 table/cell range |
| `PPTX_SLIDE_SHAPE_RANGE` | slide id/number、shape id、text range、可选 bbox |
| `XLSX_SHEET_CELL_RANGE` | sheet stable id/name、A1 range、value/formula snapshot |

这些 adapter 复用 WeKnora parse/manifest，不建第二解析平台或无界 parser ladder。
若 parse contract 缺少稳定 locator，只补现有接缝的最小字段并版本化 adapter，不深 fork。

点击顺序固定：按 release 读 Evidence → 重开 exact SourceRevision → 核对 source/parse
hash → 按 kind resolve → 回验 quote/value → 成功才渲染。失败返回
`SOURCE_REVISION_NOT_FOUND`、`PARSE_MANIFEST_MISMATCH`、`LOCATOR_UNRESOLVABLE`、
`QUOTE_MISMATCH` 或 `UNSUPPORTED_LOCATOR_KIND`；不得打开 current revision、相似 quote
或第 1 页。

## 9. 逻辑与物理架构

```text
┌──────────────────────── WeKnora ─────────────────────────┐
│ Source/Parse → Candidate Intake → Preview/Review         │
│ → Immutable Release/Single Head → Wiki/Search/Agent      │
│ → Source Viewer + ACL + current/pinned read              │
└──────────────────────────┬───────────────────────────────┘
                           │ versioned compile contract
┌──────────────────────────▼───────────────────────────────┐
│ Harness: Classifier → Entity Resolver → SchemaPack       │
│ → Extract/Normalize/Verify → Claim/Evidence              │
│ → Semantic Diff/Bitemporal Merge → PageManifest/Candidate│
│ → Q0 offline evaluator（不持有 Active）                  │
└──────────────────────────────────────────────────────────┘
```

物理写入边界：SourceRevision/parse/ACL、Candidate/Review、Release/Head、Wiki/Search/
Agent/source viewer 均留在现有 WeKnora 节点；compile job、分类/实体/SchemaPack、抽取、
Evidence 验证、语义 Diff 和 Candidate 编译留在 Harness 现有运行时。跨边界只有版本化
`CandidateBundle(kind=FORMAL)`，至少带 base release、source revision set、taxonomy/
entity candidates、pack identities、Claim/Evidence、semantic changes、PageManifest、
review plan 和 compiler identity。

830 优先 adapter、service/repository/router/frontend 现有扩展点、Harness plugin、feature
flag 和 contract test。若 Goal 要求替换 WeKnora 核心 parser、复制 Wiki runtime、
新 serving 数据库或持续侵入大面积上游热点，立即 STOP；不得以“定制分支”名义深 fork。

## 10. free_wiki 高价值概念轨

free_wiki 处理 Schema 外但值得长期治理的概念、规则、流程、限制或关系。它仍走同一
Claim/Evidence→Candidate→Review→Release，不是自由 Markdown 区或图数据库。

评分前有两个硬门：

1. **Evidence 硬门**：至少一条按策略合格且 SourceLocator 可回验的 `SOURCE` Evidence；
2. **身份硬门**：稳定主语/概念边界/去重键明确，能区分新概念、别名、局部备注和营销词。

任一硬门失败，强制 `mention-only`，即使评分 100 也不得成页。通过后按 100 分评分：

| 维度 | 分值 |
|---|---:|
| 业务价值 | 25 |
| 复用性 | 20 |
| 证据质量 | 20 |
| 可定义性 | 15 |
| 新颖身份 | 10 |
| 名称稳定性 | 10 |

`>=80` 自动进入 Candidate；`60–79` 人工决定；`<60` mention-only。自动入 Candidate
不等于 Active。顺序固定为 analyze → resolve/link existing → deduplicate → hard gates/
score → structured Claim/Evidence → page compile → orphan/broken-link/evidence lint，禁止
先生成 Markdown 再事后去重。

## 11. 增量语义与双时态

| 语义 | 定义与结果 |
|---|---|
| `SAME` | 规范化事实、作用域、有效期相同且无新增 Evidence/信息；只记观察 |
| `ENRICH` | 事实不变但新增/增强 Evidence、条件或元数据；候选修订 |
| `SUPERSEDE` | 同一作用域/重叠有效期的新权威事实取代旧事实；旧事实留历史 |
| `COEXIST` | 值不同但版本/地域/渠道/人群/场景/有效期不重叠；明确范围后并存 |
| `CONFLICT` | 同一作用域、有效期重叠且值矛盾、规则不能裁决；强制人工 |
| `RETRACT` | 来源撤回、Evidence 失效或专家撤销；候选撤回，不物理删除 |
| `UNCHANGED` | 受影响闭包/Release diff 无语义影响；不生成 ClaimRevision/page delta |

`SAME` 是 incoming-vs-existing 逐事实比较，`UNCHANGED` 是闭包/Release 级结果。
每个 ClaimRevision 同时记录业务有效时间 `valid_time` 和系统知晓时间 `system_time`，
支持 `as_of_valid_time(t)` 与 `as_known_at(t)`。晚到材料追加 revision，不改旧时间段。
七语义都不能直接覆盖 Active；R2 审核完成前 R1 继续服务。

## 12. 审核策略与专家编辑

| 策略 | 适用与硬边界 |
|---|---|
| `AUTO_ACTIVE` | 仅低风险、无冲突、Evidence/身份/质量门全过；生成 `system:policy-engine` 决定，仍走同一 Release/CAS |
| `ONE_CLICK_BATCH` | 中风险/批量冷启动；具名审核人看摘要、Diff、Evidence 后整批批准/拒绝 |
| `MANDATORY_REVIEW` | 高风险、CONFLICT、低置信、Evidence 异常、专家锁冲突；必须具名人工 |

高风险和 `CONFLICT` 永不 AUTO_ACTIVE。三策略共用一种 ReviewDecision、同一 Preview/
Workbench、同一 Release API 和审计历史；不得形成 shadow review。

pack Q0 PASS 前，其知识内容无论使用 `AUTO_ACTIVE`、`ONE_CLICK_BATCH` 还是
`MANDATORY_REVIEW`，都只能在隔离环境验证策略与物理流程，结果必须标记
`NOT_FOR_PRODUCTION`，不得进入生产 Active。Catalog、PresentationProfile 和不改变知识
事实的分类/导航元数据可以注册。pack Q0 PASS 后才开放生产人工审核；只有质量门通过且
策略另行获批后，低风险内容才允许在生产启用 AUTO_ACTIVE。所有策略仍产生 ReviewDecision。

专家编辑作用于结构化 Claim，而非 managed Markdown。结果以专家为准：原因和新 Evidence
均可选；系统以 EditProvenance 自动记录 actor/time/before/after/revision/base/target
release；无新来源标“专家修改”且不伪造 SourceEvidence。编辑形成 `EXPERT_EDIT` ClaimRevision/Candidate/
Release，并置 `expert_lock=true`。以后模型可以携新 Evidence 发起冲突候选，但不得自动
覆盖、SUPERSEDE 或解锁；只有具名专家的新决定可以更新/解锁。

## 13. 端到端流程

冷启动：

```text
ingest/parse → classify → resolve existing/new EntityCandidate → exact SchemaPack
→ field Claim/Evidence → required FieldAssertion manifests → free_wiki gate/score
→ semantic compare → Formal Candidate → Preview → ReviewPolicy
→ WeKnora immutable Release/Head CAS → Wiki/Search/Agent/source click
```

增量：

```text
new SourceRevision | SchemaPackVersion | Reclassification | ExpertEdit
→ affected entity/field closure → recompile → seven semantics
→ Candidate Rn+1(base=Rn) → review → Active Rn+1
```

批量新实体先在批内做 identity/alias/version 去重；低风险可分批 Candidate，但不得把
全企业做成一个不可审核巨包。Candidate 激活前不进入正式分类视图、Search 或 Agent。

Wiki/Search/Agent 必须绑定同一 release_id/activation epoch。产品页默认链接顺序为
Entity → FieldAssertion → Evidence/ConceptDefinition。禁止 Wiki R2、Search R1，禁止
Agent 读 Harness Candidate，禁止 RAW chunk 和 free_wiki Candidate 旁路正式 Release。

## 14. MVP、企业路线与唯一 Goal 顺序

| Goal | 技术目标 | 物理出口 |
|---|---|---|
| B0 · 815 证据基线与资产裁决 | 冻结 FLOW/QUALITY、KEEP/REWIRE/FREEZE/SUPERSEDE、双系统红线 | 可重放基线/接缝清单 |
| G1 · 实体页图与独立 FieldAssertion | stable entity；overview/section/field/free_wiki | 每必填字段 canonical page |
| G2 · 共享 ConceptDefinition 与 free_wiki 准入 | FieldAssertion→Concept；硬门/评分/去重/lint | Candidate 或 mention-only |
| G3 · SchemaPack Catalog、展示 Profile、统一分类与批量实体识别 | 11/11 pack/profile 注册校验；节点数按实际；分类先判；高置信冷启动 | 多实体/多 pack Candidate |
| G4 · 增量更新、冲突、双时态与 R2 | 七语义、affected closure、valid/system time | R2 不覆盖 R1 |
| G5 · 专家编辑、审核策略与审计 | expert lock；三审核策略；唯一审计 | 专家/策略新 Release |
| G6A · OCR PDF / 图片纵切 | 冻结 union；PDF/OCR/图片；Text 基线 | exact click/fail closed |
| G6B · Word 纵切 | 段落/表格 range | Word 来源点击 |
| G6C · PPT 纵切 | slide/shape range | PPT 来源点击 |
| G6D · Excel / 表格纵切 | sheet/cell range/value snapshot | Excel 来源点击 |
| Q0 · Pack-scoped 领域专家质量门 | 医疗险 Schema67 先行；其它 pack 逐包准入 | 每个启用 pack 独立 PASS/FAIL |
| G7 · 多格式 FLOW + QUALITY 联合验收 | 11/11 结构注册；只对已质量准入 pack 发布 | 联合结论，不新增能力 |

Q0 开卡时冻结首个 `QUALITY_ADMISSION_WAVE_1`，至少覆盖医疗险、重疾险、寿险/储蓄型
之一和意外/护理/失能之一。Q0 PASS 只代表该波次逐包通过；其余 pack 保持
`REGISTERED_NOT_QUALITY_ADMITTED`，后续按实际启用顺序复用同一质量门，不能外推质量。

830 MVP 证明：815 FLOW 不回归；11 类产品 SchemaPack Catalog 可版本化注册且不写死；
11 个产品 pack 共用一个可变节点 renderer、各自持有版本化 PresentationProfile，业务
schema category 与展示节点不混淆；统一产品/权益/服务视图；
独立字段页与共享概念；受控 free_wiki；批量 EntityCandidate；七语义/R2/双时态；三审核
策略和专家锁；六类 locator 覆盖 PDF/OCR/图片/文本/Word/PPT/Excel；Q0/G7 得出真实
联合结论。

企业阶段仍沿同一节点增加更多 SchemaPack、实体/别名/版本、分类视图、专家队列、
结构化 connector、时态检索和 release-aware ranking。扩展不改变唯一 WeKnora Active，
不新增图数据库、Prompt 平台或独立审核产品。

## 15. 难点与取舍

- **Schema 分类 vs 展示目录：** 业务分类保留知识语义，展示 section 保障易用性；版本化
  映射两者，不能因数量不同复制字段或改变身份。
- **独立字段页 vs 页面数：** 选择独立身份和组合渲染；不复制正文，不退回仅锚点身份。
- **分类吞吐 vs 身份污染：** 分类可修、身份稳定；身份/分类双阈值，不确定项人工。
- **free_wiki 召回 vs 噪声：** 先硬门和去重，再评分和生成；低分 mention-only。
- **自动化 vs 风险：** AUTO_ACTIVE 不旁路；高风险/冲突/专家锁冲突强制人工。
- **专家权威 vs 新材料：** 模型只能带 Evidence 请求复核，不能覆盖专家。
- **多格式统一 vs 原生差异：** tagged union 保留格式特性，不压成虚假通用页码。
- **双时态 vs 实现复杂：** ClaimRevision 原生双时态，不用原地覆盖换短期简单。
- **定制速度 vs 跟版：** adapter/contract/窄扩展优先；大面积核心侵入即 STOP。

## 16. 非目标与双系统红线

830 明确不做：第二 Wiki、第二审核台、第二 Release/Active Head、第二 Evidence lifecycle；
Harness online reader/current pointer；managed Markdown 权威或 Markdown→Claim 回流；
图数据库；通用 Prompt 平台；深 fork WeKnora；把 Schema67 套给其他实体；用分类路径
作为身份；Candidate/专家 UI/AUTO_ACTIVE 直接写 Active；高风险/CONFLICT 自动激活；
模型覆盖专家；locator 失败跳第 1 页；照搬 nashsu GPL 代码/桌面 runtime；Q0 前声称
质量通过。

以下任一出现即 STOP：Harness `current_release/active_head`；独立可编辑 Claim Markdown/
Evidence 副本；free_wiki 走另一套 review/release；AUTO_ACTIVE 不产 ReviewDecision；
Search/Agent 旁路 Candidate/RAW；多格式另建解析平台；分类靠复制实体；兼容 UI 保留
第二可写发布路径；同一 Evidence 在两处有不同 status/current 解释。

## 17. 架构验收清单

- 一个 scope 只有一个 WeKnora Head，并发激活单赢家；Harness 无 serving Head；
- 三审核策略产同一种 ReviewDecision，走同一 Release；
- Candidate/Release evidence_id/digest 一致，无第二可编辑状态；
- Markdown 删除后可由 Claim/Evidence/PageManifest 重建；
- reclassify 前后 entity_id、Claim/Evidence/history 不变；
- 每实体必填字段恰好一个 FieldAssertion，字段先到自身页再到 ConceptDefinition；
- free_wiki 硬门失败不成页，80/60 边界正确；
- 高置信冷启动只自动建 Candidate；不确定项人工；
- 七语义齐全，R2 前 R1 服务，valid/system time 可分别回放；
- 无新 Evidence 的专家修改有标签，模型不能覆盖 expert_lock；
- 高风险/CONFLICT 永不 AUTO_ACTIVE；
- 六种 SourceLocator 均可 exact reopen，失败 typed 且不跳第 1 页；
- Wiki/Search/Agent/current/pinned 绑定相同 release/epoch。

## 18. 参考与 SUPERSEDE

参考：

- WeKnora：<https://github.com/Tencent/WeKnora>，commit `9b4f792...`，`v0.7.2+85`；
- nashsu/llm_wiki：<https://github.com/nashsu/llm_wiki>，commit `e808211`，`v0.6.11`；
- `jlx_enterprise_llm_wiki_technical_route_815.md`；
- `jlx_enterprise_llm_wiki_complete_728_v3.md`；
- `docs/superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md`；
- `docs/superpowers/specs/2026-08-01-enterprise-knowledge-compiler-architecture.md`；
- `docs/insurance-kb/02-architecture.md`、`03-knowledge-model.md`、
  `09-llm-wiki-feature-migration.md`；
- `docs/project-iterations/llm_wiki文档/EVOLUTION_FROM_NASHSU.md`。

830 **KEEP** 815 的唯一 WeKnora Active、Harness compiler、Formal Candidate→Preview→
Review→Release、Claim/Evidence、三态、稳定实体、current/pinned 和 fail-closed 来源。

830 **REWIRE/EXTEND**：Schema67 成为医疗险 SchemaPack，医疗险既有七节点成为其它
Profile 的布局参考而非数量约束；连续页成为组合视图并增加
独立 FieldAssertion；产品/权益/服务成为分类视图；PDF locator 扩展为六类联合类型；
整批审核扩展为三策略但仍是一套审核；增加 free_wiki、七语义、双时态和专家锁。

830 **SUPERSEDE**：重跑一套 815 主链；把 67/7 当企业固定结构；把连续页或 75 页
当内容权威；分类路径作为实体 ID；定位失败跳第 1 页；所有变化一律人工或一律自动；
模型覆盖专家；free_wiki 自由成页；Q0 前质量通过；任何第二 Wiki/审核/Active/Evidence、
图数据库、Prompt 平台或深 fork 路线。

## 19. 最终裁决

830 成功意味着：815 `FLOW=PASS` 地基不变；同一 WeKnora managed Wiki 承载大量稳定
实体和可配置视图；Harness 以不同 SchemaPack 编译但不获得 serving 权；每必填字段有
实体作用域 FieldAssertion；free_wiki 只让有 Evidence、有稳定身份、有足够价值的发现
进入 Candidate；增量、专家编辑和三审核策略都形成新 Release；多格式共享一个
Claim/Evidence/SourceLocator 合同；Q0 最后给出真实质量结论，G7 只联合验收。

一旦出现第二 Wiki、第二审核、第二 Active、第二 Evidence 或深 fork，即偏离本蓝图。
