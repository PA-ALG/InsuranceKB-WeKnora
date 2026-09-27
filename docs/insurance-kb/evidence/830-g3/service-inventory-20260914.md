# G3 权益服务清单与接入差异（2026-09-14）

本清单补充当前 G3 计划；只读核对旧结构定义和本机材料，不产生正式事实、解析结果或发布结果。**目录定义不等于已发布内容。** 本次未调用模型、未操作数据库或 Docker。既有保险产品和字段产物继续复用，不因补目录重新抽取。

## 口径与可追溯定义

- 旧定义：`/Users/houjing/Documents/LLM_wiki/customized-llm-wiki/frontend/src/lib/insurance-schema-registry.ts:1596` 的 `SERVICE_HIERARCHY`。添平安系列包含医健 6 条、养老 2 条，合计 8 条；家办的家族办公室单列。享平安系列为 pending，暂无下级。
- 当前产品 Schema 的 `eligible_service_packages` 也明确列出同样 8 条，要求根据最新准入清单映射并保留适用条件：`harness/src/insurance_harness/knowledge_compiler/schema_first_contracts.py:716`。
- 旧代码注释引用《服务权益知识结构.xlsx》。本次在 Documents、Desktop、Downloads 原名搜索及 Spotlight 原名搜索均未找到该工作簿，**不能声称已核验工作簿原文**。这是结构来源追溯缺口，不阻断其他已有设计接线。
- 旧迭代说明确认五级服务层级、跨版本服务项、来源关联及产品独立字段页：`/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/docs/project-iterations/llm_wiki文档/LLM_WIKI_FROM_NASHSU_ITERATION_SUMMARY.md:94`。

## 服务线、版本与材料

下面材料路径均以 `/Users/houjing/Downloads/` 为根。旧目录版本只代表已有定义，不能冒充材料已确认的版本。服务内容的当前状态统一为“有设计、尚未验证当前 G3 正式接入”，不能用材料存在或目录数量宣称发布完成。

| 场景／服务线 | 旧目录版本与定义行号 | 真实材料与具体缺口 |
|---|---|---|
| 医健／安有医 | 颐享版、尊享版、悦享版、惠享版、尊享易核版；1605 行 | `服务材料/服务手册/安有医健康服务手册（…版）.pdf`，上述 5 种均有；另有 `（易核版）.pdf`。`服务材料/一页纸/平安添瑞·安有医（悦享版）一页纸.pdf`、`平安添瑞·安有医（安医保尊享版）一页纸.pdf`。旧代码 1740 行明确易核版→尊享易核版别名，但两个 PDF 日期和字节不同，不能直接合并来源或时间版本。 |
| 医健／安有护 | 国际、国内；1615 行 | `服务材料/服务手册/安有护健康服务计划服务手册.pdf`、`服务材料/一页纸/安有护讲解一页纸.pdf`；手册首页真实版本为 **2025 年 9 月版**，国际／国内归属尚未核验。 |
| 医健／就医通 | 就医通；1622 行 | 本次在 Documents/Downloads 文件名搜索未发现专属原始材料。有目录和字段定义，原材料缺口。 |
| 医健／臻享家医 | V1、V2、V3；1628 行 | `服务材料/服务手册/平安臻享家医服务手册.pdf`、`服务材料/一页纸/臻享家医讲解一页纸.pdf`。手册首页为 **2025 年 4 月版**，未找到与 V1/V2/V3 的对应证据，不能手工指定为 V1。 |
| 医健／御享国医 | 御享国医；1636 行 | `服务材料/服务手册/御享国医健康服务计划服务手册.pdf`、`服务材料/一页纸/御享国医讲解一页纸.pdf`；另有 `智能体外网抽取资料/御享国医/御享国医.pdf`。来源版本需平台核验，不能仅按文件名合并。 |
| 医健／私董保健医 | 京华版、繁华版；1642 行 | `服务材料/服务手册/私董保健医服务手册（京华版）.pdf`、`私董保健医服务手册（繁花版）.pdf`、对应讲解一页纸。后者正文第 2 页也写 **繁花版**，旧目录“繁华版”与原文冲突，必须保留差异并按来源纠正。 |
| 养老／居家养老 | V1、V1优享、V2、V2优享；1654 行 | `服务材料/服务手册/平安人寿居家会员服务手册.pdf` 存在，首页无上述版本归属。`居家_wiki.html` 是旧衍生展示，不能冒充正式原始事实。 |
| 养老／高端康养 | 逸享、逸享PLUS、颐享家、臻享V1、臻享V2、臻享V3；1663 行 | `服务材料/一页纸/康养讲解一页纸.pdf` 存在，但文本层为空，需要平台 OCR／多模态。未发现上述各版本的独立原始手册；`平安康养服务V3.0.md`、`高端康养_wiki.html`、`八大康养服务知识库.html` 为待核来源的衍生材料。 |
| 家办／家族办公室（单列） | 准会员、正式会员、尊享会员、至尊会员；1679 行 | 本次未发现专属原始材料。不应删除该已定义目录，也不应挤入医健＋养老的 8 条口径。 |

### 臻享家医同名材料不得按文件名去重

两份首页均为“平安臻享家医健康服务计划服务手册（2025年4月版）”，但 PDF 字节不同：

- `服务材料/服务手册/平安臻享家医服务手册.pdf`：SHA-256 `22f5a7048a3886c25453e32a10207caf204d2e6a72f3d09803bd58eec4b331a0`。
- `智能体外网抽取资料/平安臻享家医服务手册/平安臻享家医服务手册.pdf`：SHA-256 `c6e241e3bfbb281aaed1d267a6f04956b2d226f5bee9060ecb8a74dfd67b47ad`。

需要分别保留来源；产品／服务版本归并由平台按有证据的身份处理。

### 产品—权益关系原材料

`智能体外网抽取资料/安有护/提供安有护服务的产品清单.pdf` 为真实映射材料，共 45 条产品／组合，含产品代码及保费统计条件。但列举的是 2025、2024、2023 等旧版本，不能据此断言现有 2026 同名产品享有权益。尚无本次验收的当前产品—权益正式正例。

## 可复用 Schema 与层级

以下均来自旧 `insurance-schema-registry.ts`，无需另创所有业务字段；需要转换为当前可验证的 Schema/Profile，而不能复制旧演示内容冒充发布事实。

| Schema | entityType／对象角色 | 字段数 | 定义行 |
|---|---|---:|---:|
| insurance.product.ServicePlan | service_plan／非保险健康服务计划实体 | 12 | 375 |
| insurance.product.ServiceBenefit | service_benefit／旧权益实体 | 15 | 466 |
| insurance.service.ServiceSeries | service_series／系列概念 | 3 | 509 |
| insurance.service.ServiceScenario | service_scenario／场景概念 | 3 | 525 |
| insurance.service.ServiceLine | service_line／服务线实体 | 5 | 542 |
| insurance.service.ServiceLineVersion | service_line_version／文件最小归属版本实体 | 16 | 561 |
| insurance.service.ServiceItem | service_item／最小业务服务项实体 | 21 | 598 |
| insurance.service.ServiceItemConcept | service_item_concept／跨版本通用概念 | 4 | 644 |

ServiceLineVersion 的 16 字段：`line_name, version_name, scenario_name, series_name, admission_rules, qualification_threshold, designated_products, effective_date_rule, eligible_persons, service_period, service_entry, service_system, coverage_scope, usage_notes, service_process, compliance_notes`。

ServiceItem 的 21 字段：`line_name, version_name, item_name, scenario_name, series_name, service_scenario, service_stage, service_intro, service_frequency, service_content, service_standard, activation_conditions, eligible_customers, coverage_cities, usage_process, service_notes, important_notes, marketing_materials, faq, service_features, knowledge_gaps`。

版本稳定身份为 `line_name + version_name`；服务项再加 `item_name`。层级用 `has_part/part_of`，服务项与通用概念用 `instance_of/has_instance`，保险绑定用有证据的 `bundled_with`。服务项是实体，不是字段；每个适用 Schema 字段仍须有自己的稳定 Wiki 页面。

旧导航可参考 `/Users/houjing/Documents/LLM_wiki/customized-llm-wiki/frontend/src/components/layout/knowledge-tree.tsx:251`。`service-benefit-enrichment.ts` 可参考表格解析思路，但其第 61 行存在默认“臻享家医健康服务计划”名称，且直接写旧 Markdown；不得原样迁入正式身份与事实链路。

## 当前 G3 最小扩展接线点（只读审计，未修改业务代码）

以下路径相对于当前 `830-g3-performance`；Python 的 `knowledge_compiler/` 和 `product_ingestion/` 均省略共同前缀 `harness/src/insurance_harness/`。这些是需要配套扩展的真实边界，而不是要求重写通用平台。

1. **Catalog 三端边界。** Python `knowledge_compiler/schema_pack_catalog_830_g3.py:139` 将类型锁为 `insurance_product`，219 行锁 11 项，286 行的 workbook mapping 锁 11 包；字段元数据还强制 workbook sheet、source_row > 5。Go `internal/types/concept_free_wiki_830_g3.go:3263` 锁 11 项、字段并集 154、交集 47，3286 行锁实体类型、同一 workbook。前端 `frontend/src/api/schema-wiki/schemaPackCatalog830G3.ts:41,192,237` 锁实体类型、11 项、版本及内容哈希；Go Catalog handler 的 ID／版本／wire hash 也固定（`internal/handler/schema_pack_catalog_830_g3.go:17`）。应保留既有 11 险种包的不可变身份，同时增加明确类型和可追溯定义来源；不能伪造不存在的工作簿行号，不能只改前端绕过校验。
2. **首页识别与材料类型。** `product_ingestion/routing.py:24-49` 只识别保险名称结尾以及条款／产品说明书／费率表；`knowledge_compiler/g3_title_routing.py:38` 的分类映射只有 11 险种。服务手册标题会在模型前被阻断。最小扩展是使用已有服务名称和版本字段定义的确定规则／注册项，加手册、一页纸等材料角色；不把服务强塞医疗险。
3. **身份与 Candidate。** `knowledge_compiler/batch_entity_resolution_830_g3.py:1494,1517` 身份主键基于 product_code，创建 Candidate 必需 issuer、name、product_code、version_label、filing_or_registration。Go 镜像校验见 `internal/types/concept_free_wiki_830_g3.go:2211,2254,2292,2815`。服务通常没有监管备案号，需按允许的服务类型使用已有 line/version/item 身份和真实来源锚点；保留保险规则，不合成假备案号或假产品代码，也不能全局去掉证据硬门。
4. **增量编译与旧结果复用。** `product_ingestion/compilation.py:199-205` 要求当前 Catalog 与已发布 base 的整个 Catalog 身份完全相等。追加服务包会被“published base catalog changed”阻断。最小接线需允许经验证的 Catalog 增量扩展，并逐项保证既有绑定所引用 pack/profile/hash 保持不变；不得为新服务重算已发布产品。实体类型、版本、关系需贯穿当前 Binding／Candidate 校验，而非只给页面加显示名称。
5. **前端与关系。** 从既有实体／Profile／字段路由接入服务，沿用独立字段页和来源组件。分类是同一 Head 的视图；不能建立第二事实仓库。单次目录调整必须验证既有实体 ID、字段 URL、值、证据、历史不变，新增模型调用为 0。

状态：本文件为业务清单及接线审计，**不是八条服务线内容验收通过证据**。真实服务页面、来源定位、版本判断、关系正例及平台独立发布仍需逐项验收。
