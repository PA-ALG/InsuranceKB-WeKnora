# 从 nashsu/llm_wiki 到保险产品知识库的需求与功能迭代梳理

更新日期：2026-07-10

基线项目：`https://github.com/nashsu/llm_wiki`

当前项目分支侧重点：保险产品知识库、平安人寿产品资料抽取、险种产品库批量构建、服务端化导入、字段级质量治理。

当前本地定制开发周期：2026 年 5 月开始，持续迭代至今。

> 说明：本文档梳理的是从原 `nashsu/llm_wiki` 通用 LLM Wiki 项目演进到当前项目过程中已经做过的需求和核心功能变化，不是单纯罗列当前页面上能看到的功能。原项目后续 upstream 可能继续新增 MCP、Agent、Deep Research 等能力，本文以当前本地项目的实际迭代为准。

## 1. 原项目基线

原 `nashsu/llm_wiki` 是一个通用个人/团队知识库项目，核心目标是把本地文件、Markdown 页面、网页剪藏和资料导入为可检索、可关联、可对话的 LLM Wiki。

原项目主要能力包括：

| 方向 | 原项目能力 |
| --- | --- |
| 知识库形态 | 以 Markdown Wiki 为核心，文件树、页面编辑、预览、链接、Frontmatter 元数据 |
| 资料导入 | 文件导入、文件夹导入、OCR/文本抽取、来源页管理 |
| 检索 | 向量检索、关键词检索、图谱关系检索、RAG 上下文组装 |
| 对话 | 右侧 Chat 面板，基于 Wiki 知识库进行问答 |
| 图谱 | 页面、实体、关系、相似度关系、可视化图谱 |
| 审核 | 对导入内容、关系、页面演化进行人工审核 |
| 桌面端 | Tauri 桌面应用；React 是桌面 UI，Rust 是 Tauri 命令层，不是独立 HTTP 后端，也不是前后端分离架构 |
| 配置 | LLM Provider、Embedding、Chunking、界面、网络搜索等设置 |

当前项目在这个基线上，把通用 Wiki 进一步改造成面向保险产品资料的结构化知识生产系统。

## 2. 总体演进结论

从原项目到当前项目，最大的变化不是简单增加一个保险字段，而是把系统从“通用知识库”改造成“保险产品知识编译器”。

主要演进方向：

| 演进方向 | 变化说明 |
| --- | --- |
| 知识对象变化 | 从通用页面、片段、实体，扩展为保险产品、产品模块、字段页、服务权益、保障责任、费率表、QA、来源原文 |
| 抽取方式变化 | 从普通导入和摘要，演进为 OCR 全文、分节、分组 LLM、模块解析、原文注入、字段聚合、主产品页重建 |
| 数据治理变化 | 新增字段状态、证据模块、来源追踪、冲突审核、增量更新、删除清理、旧数据修复 |
| 使用场景变化 | 从个人知识管理，转向批量生产保险产品知识库、支持销售/运营查询、产品对比、条款问答 |
| 架构形态变化 | 从单机桌面应用和 Tauri 命令层，扩展为独立 Rust HTTP API、Node Worker、批量任务、Docker/Linux 部署 |
| UI 变化 | 从通用 Wiki 浏览编辑，增加产品上传、批量任务、来源管理、审核演化、后台精炼状态等业务入口 |

## 3. 需求迭代总览

| 阶段 | 需求背景 | 核心改动 | 主要产物 |
| --- | --- | --- | --- |
| 2026-05 起 | 在原桌面版 Wiki 能力上建立平安寿险资料知识库 | 初始导入、Schema v2.1、服务权益层级、RAG、保险知识域改造 | 保险 Wiki 基础工程 |
| 2026-06-05 | 图谱和 RAG 质量不足 | 实体命名、关系阈值、关系重建、Watchdog、日志治理 | 更稳定的图谱和检索 |
| 2026-06-14 | PDF 条款、说明书、扫描件抽取不稳定 | OCR 四级兜底、乱码检测、页图回退 | 更可靠的 PDF 预处理 |
| 2026-06-14 | 需要独立“险种产品库” | 新增 `product_catalog` domain、产品目录 Schema、目录结构 | 产品目录知识域 |
| 2026-06-15 至 06-17 | LLM 直接整篇抽取成本高、漏抽多 | Section-Scan 编译架构、分节、分组抽取、原文注入、Phase 5 精炼 | 产品知识编译器 |
| 2026-06-17 | 产品文件路径和命名需要自动识别 | 自动识别 `产品/{险种}/{产品名}` 目录和文档 | 路径上下文识别 |
| 2026-06-21 至 06-22 | 字段不齐、Excel 对齐差、页面不可控 | 字段聚合、字段提示、模块字段映射、占位清理、长字段治理 | 字段级抽取质量提升 |
| 2026-06-22 | 需要可编辑、可审核的字段级知识 | 字段页 `字段-{field}.md`、字段状态、证据模块、缺口清单 | 字段页体系 |
| 2026-06-22 | 不同险种字段混杂 | 分类模块白名单、拒绝无效字段、搜索跳过无效模块 | 险种专属字段约束 |
| 2026-06-24 至 06-25 | 重复导入会覆盖人工修订 | 增量抽取、只补空字段、冲突进入 review、编辑同步 | 增量更新和冲突治理 |
| 2026-06-25 | 删除来源后残留知识污染 | 来源删除清理 artifact/source_text/embedding/concept | lineage 删除治理 |
| 2026-06-26 | 审核结果没有反映到演化面板 | Evolution Panel 读取 resolved reviews、冲突采用同步 | 审核闭环 |
| 2026-06-29 | 需要本地模型和 Linux 部署 | 服务端配置、Docker、部署文档、Smoke Test | Linux/Docker 版本 |
| 2026-06-30 | 产品资料需要服务端批量导入 | Product Batch API、上传、状态持久化、Node Worker、SSE | 批量导入服务 |
| 2026-06-30 | QA/产品特色误抽 | QA 文档路由、产品特色路由、alias 同步 | 文档类型路由 |
| 2026-07-02 | 上千 Markdown 页面前端卡顿 | 文件树防抖、预览截断、后台精炼 API、任务持久化 | 大规模知识库性能治理 |
| 2026-07-08 至 07-09 | 保单贷款前置条件漏抽、医疗险重大疾病字段缺失 | 修复字段聚合和医疗险专属字段，跑 13 个产品验证 | `0709` 批量验证结果 |

## 4. 需求与核心功能清单

### 4.1 保险知识域扩展

在原通用 Wiki domain 之外，当前项目新增和强化了保险相关知识域：

| 知识域 | 用途 |
| --- | --- |
| `product` | 服务权益、服务项目、权益说明 |
| `product_catalog` | 险种产品库，承载每个保险产品的结构化字段、模块、主页面 |
| `method` | 方法论、销售方法、经营动作 |
| `cases` | 案例、客户场景、成交案例 |
| `customer` | 客户画像、客户需求、客群标签 |
| `compliance` | 合规规则、红线、话术限制 |
| `content` | 宣传内容、话术、素材 |
| `activity` | 活动、方案、运营动作 |
| `general` | 通用知识 |

新增能力：

- 为保险资料定义专属 entity type、relation type、frontmatter 字段。
- 通过 `knowledge-schema.ts` 维护 domain label、目录、实体类型。
- 通过 `insurance-schema-registry.ts` 维护保险产品目录 Schema。
- 支持产品、险种、模块、字段、来源、概念等多层对象。

### 4.2 服务权益知识图谱

当前项目在原图谱能力上新增了服务权益层级：

```text
Series
  -> Scenario(医健 / 养老 / 家办)
    -> ServiceLine
      -> ServiceLineVersion
        -> ServiceItem
          -> ServiceItemConcept
```

核心需求：

- 把服务权益资料从普通页面抽取为层级化知识。
- 让销售查询时能按场景、服务线、服务项目定位。
- 支持同一服务线多个版本、多个服务项。
- 在图谱和 RAG 中保留服务之间的关系。

核心功能：

- 服务名称规范化。
- 服务 identity canonicalization。
- 服务权益概念聚合。
- 服务项目和产品页面之间建立关系。
- 概念页、主页面、来源页之间互相追踪。

### 4.3 险种产品库 `product_catalog`

新增 `product_catalog` 是当前项目最重要的需求演进。

目标：

- 将保险产品说明书、条款、费率表、QA、产品特色、Excel 清单等资料，编译成统一的产品知识库。
- 每个保险产品形成一套稳定产物，包括主产品页、模块页、字段页、来源原文页、概念页。
- 支持寿险、重疾险、医疗险、年金险、意外险等不同险种的差异化字段。

产品目录核心对象：

| 对象 | 说明 |
| --- | --- |
| 产品主页面 | 产品总览、已有知识清单、知识缺口清单、模块索引、字段索引 |
| 产品模块页 | 产品职责、保单贷款、免责条款、投保规则、费率、QA 等按模块组织的页面 |
| 字段页 | 每个产品字段一页，如 `字段-保险期间.md`、`字段-保单贷款.md` |
| 来源原文页 | 保留导入文档的原始文本、页码、来源路径 |
| 概念页 | 用于图谱、RAG、产品字段实体聚合 |
| Review 项 | 冲突、缺失、弱值、人工确认事项 |

### 4.4 产品目录 Schema 和字段体系

产品目录 Schema 从固定字段逐步扩展为“通用字段 + 险种专属字段 + 文档类型字段”。

通用字段包括：

- 产品名称
- 产品代码
- 保险公司
- 产品类型
- 险种类别
- 投保年龄
- 保险期间
- 交费期间
- 交费方式
- 等待期
- 犹豫期
- 保障责任
- 责任免除
- 保单贷款
- 减保
- 退保
- 现金价值
- 身故保险金
- 全残保险金
- 续保规则
- 费率
- 产品特色
- QA

险种专属字段示例：

| 险种 | 专属字段 |
| --- | --- |
| 寿险 | 身故保险金、全残保险金、保单贷款、减保、现金价值 |
| 重疾险 | 重大疾病、中症疾病、轻症疾病、疾病分组、豁免责任 |
| 医疗险 | 重大疾病、一般医疗、重疾医疗、免赔额、报销比例、医院范围、续保条件 |
| 年金险 | 年金领取、领取年龄、领取方式、满期金、生存金 |
| 意外险 | 意外身故、意外伤残、意外医疗、职业类别 |

近期 0708/0709 迭代重点：

- 修复 `保单贷款` 字段抽取不全的问题。
- 要求保留“经被保险人书面同意”等前置条件原文。
- 医疗险领域补充 `重大疾病` 专属字段。
- `重大疾病` 字段不仅要抽“保什么疾病”，还要保留原文中的疾病数量，例如“多少种重大疾病”。
- 通过 13 个产品批量跑数验证字段抽取效果。

### 4.5 Section-Scan 产品知识编译器

原项目导入偏向“文件 -> 文本 -> Wiki 页面/Chunk”。当前项目为了保险产品资料，新增了产品知识编译器。

处理流程：

```text
PDF / Word / Excel / Markdown / 图片
  -> OCR / 文本抽取
  -> splitIntoSections
  -> group-round LLM 抽取
  -> parseModuleBlocks
  -> mergeFragmentContents
  -> 字段聚合
  -> 原文证据注入
  -> Phase 5 精炼
  -> 主产品页 / 模块页 / 字段页 / 概念页
```

核心改造：

- 不再让 LLM 一次性读完整产品文档。
- 先把资料按标题、页码、段落、表格拆成 section。
- 通过 section group 批量调用 LLM，减少调用次数。
- LLM 只输出结构化 key-field 和模块内容。
- 原文证据由代码注入，避免 LLM 改写关键条款。
- 字段聚合器负责合并重复片段、补齐字段、判断弱值。
- 对长字段使用专门 module map 和提示词。

效果目标：

- 减少 LLM 调用量。
- 降低 OOM 和超时。
- 增强原文可追踪性。
- 避免字段值被摘要化、遗漏前置条件。

### 4.6 PDF/OCR 和多格式资料处理

当前项目强化了 PDF 和多格式资料导入。

支持资料类型：

- PDF
- Word：`.docx` / `.doc`
- Excel：`.xlsx` / `.xls`
- PowerPoint：`.pptx` / `.ppt`
- Markdown / TXT / CSV / JSON
- 图片：`.png` / `.jpg` / `.jpeg` / `.webp` / `.bmp`
- HTML / RTF / EPUB / YAML

PDF 抽取兜底链路：

1. 内部 OCR 或视觉模型识别。
2. `pdf-extract` 文本抽取，并做乱码检测。
3. `pdftotext` 抽取，并做乱码检测。
4. `pdftoppm` 转图片，生成页面图像标记供视觉模型处理。

新增能力：

- Bailian Vision / 多模态 LLM 文档识别。
- OCR 文本修复。
- 页码和来源段落标记。
- Excel 字段对齐。
- 文档类型推断。
- QA、FAQ、产品特色等文档类型路由。

### 4.7 字段页体系

字段页是从原项目“页面级 Wiki”演进出来的字段级知识治理能力。

每个产品字段生成独立页面，例如：

```text
wiki/product_catalog/寿险/平安盛世金越（尊享版26）终身寿险/字段-保单贷款.md
wiki/product_catalog/医疗险/某产品/字段-重大疾病.md
```

字段页 frontmatter 记录：

| 字段 | 含义 |
| --- | --- |
| `domain` | `product_catalog_field` |
| `product_name` | 产品名称 |
| `insurance_category` | 险种 |
| `field_name` | 字段名 |
| `status` | 字段状态 |
| `extraction_state` | 抽取状态 |
| `value_source` | 值来源 |
| `evidence_modules` | 证据模块 |
| `source_hint` | 来源提示 |
| `gaps` | 缺口说明 |
| `aliases` | 产品别名、字段别名 |

字段状态：

- 已抽取
- 缺失
- 待精炼
- 被拒绝
- 弱值
- 冲突待审核

字段页用途：

- 人工编辑单个字段，不必改整篇产品页。
- 字段值可同步回主产品页和概念页。
- 搜索和问答可以直接命中字段级页面。
- 缺失字段可以集中展示和后续补抽。

### 4.8 模块页体系

产品资料被拆分为多个业务模块。

常见模块：

- 产品总览
- 投保规则
- 保险期间
- 交费规则
- 保障责任
- 重大疾病
- 轻症/中症责任
- 医疗责任
- 身故/全残责任
- 保单贷款
- 减保
- 退保
- 现金价值
- 责任免除
- 费率表
- 产品特色
- QA
- 合规提示

模块治理规则：

- 每个模块保留来源证据。
- 模块内容合并时去重。
- 低置信度或不属于当前险种的模块不进入最终知识库。
- 模块与字段之间通过 field map 建立关系。
- 模块页变更后可触发主页面和概念页重建。

### 4.9 主产品页重建

主产品页不是简单拼接文档摘要，而是由产品字段页和模块页重建。

主产品页包含：

- 产品基本信息
- 已有知识清单
- 知识缺口清单
- 关键字段表
- 模块索引
- 字段索引
- 来源索引
- 冲突或待审核提示

核心需求：

- 用户打开一个产品时先看到完整结构。
- 缺少哪些字段要清晰可见。
- 已有字段要能追溯到模块和来源。
- 后续编辑字段页后主页面可以同步刷新。

### 4.10 增量更新和冲突治理

原项目导入更偏向“新增页面/更新页面”。当前项目为保险产品资料新增了增量导入策略。

增量规则：

- 已存在产品主页面时，不直接覆盖人工修订。
- 新资料只补充空字段和新增模块。
- 新旧值冲突时生成 review 项。
- 弱值、占位值、无证据值不会覆盖强值。
- 人工采用冲突结果后，同步字段页、模块页、主产品页、概念页。

冲突治理对象：

- 字段值冲突。
- 模块内容冲突。
- 产品别名冲突。
- 文档类型误判。
- 来源删除后的残留值。

### 4.11 来源追踪和删除清理

当前项目强化了 lineage。

每个知识产物尽量保留：

- 原始文件路径。
- 上传批次。
- 文档类型。
- 页码或 section。
- source_text 页面。
- evidence_modules。
- alias。
- value_source。

来源删除时需要清理：

- 原始 source file。
- source_text 页面。
- 产品模块页中的证据引用。
- 字段页中的 value_source。
- 主产品页索引。
- 概念聚合结果。
- 向量索引 chunk。
- review 中与该来源强绑定的项。

### 4.12 QA 和产品特色路由

为避免 QA 和产品特色被普通条款误抽，新增文档类型路由：

| 文档类型 | 路由规则 |
| --- | --- |
| QA / FAQ / Q&A | 仅从问答类文档抽取 QA |
| 产品说明 / 宣传资料 | 优先抽取产品特色 |
| 条款 | 优先抽取保障责任、责任免除、保险期间等 |
| 费率表 / Excel | 优先抽取费率、交费、年龄、产品编码等 |

收益：

- 减少“产品特色”从条款里硬编。
- 减少 QA 误从非问答资料生成。
- 保留每类内容的来源可信度。

### 4.13 抽取质量治理

当前项目针对保险字段新增了一批质量规则。

质量治理内容：

- 弱值过滤。
- 占位值清理。
- 空字段标记。
- rejected 字段不进入搜索和 embedding。
- 不合法险种模块跳过。
- 主产品页缺口清单。
- 字段级 source hint。
- field gap refinement。
- 长字段独立提示。
- 字段替换策略 `shouldReplaceFieldValue`。
- 模块白名单 `isModuleAllowedForCategory`。

近期质量需求：

- `保单贷款` 必须保留前置条件和限制条件。
- `重大疾病` 需要覆盖医疗险领域。
- 如果原文写了疾病数量，需要保留数量。
- 抽取值不能超出 schema 范围，未定义字段需要先补 schema 再抽。

### 4.14 概念聚合和搜索

当前项目把产品字段也纳入概念聚合。

新增能力：

- 产品字段实体参与概念页生成。
- 产品别名同步到主页面、模块页、字段页、source_text 页面。
- invalid/rejected 字段不进入概念聚合。
- embedding/search 跳过不合格模块。
- 支持按产品名、别名、字段名、模块名检索。

### 4.15 后台精炼

为大规模产品库新增后台精炼 API 和任务状态。

后台精炼内容：

- 模块内容二次精炼。
- 字段缺口补抽。
- 主产品页重建。
- 字段页同步。
- 概念页重建。
- 精炼任务状态持久化。

任务状态：

- queued
- processing
- completed
- failed

支持指标：

- total_modules
- refined
- fields_updated
- skipped
- main_files_rebuilt
- field_gaps_attempted
- field_gaps_refined

### 4.16 服务端批量导入

原项目以桌面导入和本地文件操作为主。当前项目新增 Rust HTTP API + Node Worker 的服务端批量导入。

批量导入目标：

- 支持一个产品一次上传多份资料。
- 支持前端创建批次、上传文件、启动处理、查看状态、重试。
- 批次状态持久化，服务重启后可恢复。
- Worker 调用前端 TypeScript 抽取链路，避免重复实现。
- Docker/Linux 部署时也能跑完整导入。

批量导入流程：

```text
POST /api/ingest/product-batches
  -> POST /api/ingest/product-batches/{batch_id}/files
    -> POST /api/ingest/product-batches/{batch_id}/start
      -> Node Worker autoIngest
        -> finalize alias / concept / review
          -> SSE 通知前端刷新
```

批次状态：

- uploading
- ready
- queued
- processing
- completed
- failed

上传限制：

- 单文件最大 200MB。
- 通过 SHA256 记录文件指纹。
- 支持 duplicate policy。
- 支持 client batch id。

### 4.17 Worker 编排

新增 `backend/worker/ingest-worker.ts`，用于服务端调用 TypeScript 抽取能力。

Worker 模式：

| 模式 | 用途 |
| --- | --- |
| 普通批量导入 | 运行 `autoIngest`，从上传资料生成产品知识 |
| `--rebuild-only` | 不调用 LLM，只从已有模块重建主页/字段页/分组页 |
| `--refine` | 运行后台模块精炼 |
| `--finalize-only` | 只执行 alias、concept、review sweep 等收尾动作 |
| `--repair-scoped-fields` | 修复旧数据中的 scoped field |

Worker 收尾动作：

- alias 同步。
- concept aggregation。
- review sweep。
- 写入 `worker-result.json`。
- 返回 written_files、warnings、error、refinement summary。

### 4.18 大规模性能治理

当产品库达到上千 Markdown 页面后，原通用 Wiki 的文件树和预览会出现卡顿。当前项目做了性能治理。

前端优化：

- 文件树扫描防抖。
- 避免重复全量 scan。
- Markdown 预览默认最多渲染 100 行。
- 大页面减少即时渲染压力。
- Activity Panel 展示后台任务，而不是阻塞主线程。

后端/Worker 优化：

- 任务状态持久化。
- Mutex/worker 并发限制。
- `REFINE_PARALLEL` 控制精炼并发。
- 只重建变更产品。
- Section 分组降低 LLM 调用量。
- 失败任务可重试。

### 4.19 部署和运行方式

相对原项目的本地桌面优先，当前项目新增服务端部署能力。

新增内容：

- Rust Axum HTTP 后端。
- Node 20 Worker runtime。
- Docker 镜像。
- Linux amd64 部署包。
- 服务端配置读取。
- API Reference。
- Smoke Test。

已记录部署版本示例：

- `llm-wiki:0.4.3-linux-amd64`
- 后续服务端批量导入版本演进到 `0.5.0` 方向。

## 5. 前端功能与 UI 布局

### 5.1 总体布局

当前前端延续原项目 Wiki 工作台结构，并增加来源、审核、批处理状态等业务视图。

整体布局：

```text
┌────────────────────────────────────────────────────────────────────┐
│ 顶部/项目状态/更新提示                                             │
├──────────────┬───────────────────────┬─────────────────────────────┤
│ Icon Sidebar │ Left Sidebar          │ Main Content                │
│              │ - Knowledge Tree      │ - Wiki Editor / Viewer      │
│              │ - Source Tree         │ - Sources                   │
│              │ - View specific tree  │ - Search / Graph / Review   │
│              │                       │ - Settings / Lint           │
├──────────────┴───────────────────────┴─────────────────────────────┤
│ Chat Bar / Chat Panel / Activity Panel / Preview Panel / Research  │
└────────────────────────────────────────────────────────────────────┘
```

关键组件：

| 组件 | 作用 |
| --- | --- |
| `app-layout.tsx` | 应用主布局 |
| `icon-sidebar.tsx` | 左侧图标导航 |
| `sidebar-panel.tsx` | 左侧可切换侧栏 |
| `knowledge-tree.tsx` | Wiki 知识树 |
| `file-tree.tsx` | 文件树 |
| `content-area.tsx` | 中央内容区 |
| `wiki-editor.tsx` | Markdown 编辑器 |
| `wiki-page-viewer.tsx` | Wiki 页面预览 |
| `file-preview.tsx` | 文件预览 |
| `chat-panel.tsx` | 对话面板 |
| `chat-bar.tsx` | 底部/侧边对话入口 |
| `preview-panel.tsx` | 右侧预览面板 |
| `activity-panel.tsx` | 后台任务状态 |
| `research-panel.tsx` | 研究/检索辅助面板 |

### 5.2 主导航视图

当前 `wiki-store` 中的主要 view：

| View | UI 入口 | 功能 |
| --- | --- | --- |
| `wiki` | Wiki | 知识树、页面浏览、Markdown 编辑、产品页查看 |
| `sources` | Sources | 原始资料上传、产品批量导入、来源管理 |
| `search` | Search | 关键词/向量/知识库搜索 |
| `graph` | Graph | 知识图谱可视化 |
| `lint` | Lint | 内容质量检查 |
| `review` | Review | 冲突、候选变更、演化审核 |
| `settings` | Settings | LLM、Embedding、Chunking、多模态、接口等配置 |

### 5.3 Wiki 视图

Wiki 视图继承原项目的核心体验，并适配保险产品目录。

功能：

- 左侧展示知识目录。
- 中间展示产品主页面、模块页、字段页。
- 支持 Markdown 编辑和预览。
- 支持 Frontmatter。
- 支持页面内部链接。
- 支持产品字段页人工修订。
- 支持大页面预览截断。
- 支持编辑后同步字段/主页面/概念。

保险产品相关 UI 行为：

- `product_catalog` 下按险种和产品组织。
- 产品主页面展示结构化字段和缺口。
- 字段页可单独编辑。
- 模块页保留证据和来源。

### 5.4 Sources 视图和产品上传

Sources 是当前项目相对原项目增强最多的 UI 区域之一。

功能：

- 上传单个或多个来源文件。
- 选择或识别项目。
- 创建产品批次。
- 填写产品名称、产品代码、险种类别。
- 推断文档类型。
- 上传到后端 batch。
- 启动批量抽取。
- 通过 SSE 或轮询刷新任务状态。
- 查看上传成功、处理中、失败、完成。
- 删除来源时触发清理。

产品上传典型表单字段：

| 字段 | 说明 |
| --- | --- |
| 项目名称 / 路径 | 目标知识库项目 |
| 产品名称 | 产品目录中的产品名 |
| 产品代码 | 可选，用于产品身份识别 |
| 险种类别 | 寿险、医疗险、重疾险等 |
| 文档类型 | 条款、费率表、QA、产品特色等 |
| duplicate policy | 重复资料处理策略 |
| section parallel | Section 抽取并发 |

### 5.5 Review 视图

Review 视图从原项目审核机制扩展为产品知识演化治理入口。

功能：

- 查看字段冲突。
- 查看模块冲突。
- 查看导入候选变更。
- 采用新值或保留旧值。
- resolved review 进入 Evolution Panel。
- 采用结果同步字段页、模块页、主产品页、概念页。

关键组件：

- `review-view.tsx`
- `review-panel.tsx`
- `review-item-card.tsx`
- `evolution-panel.tsx`
- `status-badge.tsx`

### 5.6 Search 视图

Search 视图在原搜索能力基础上适配字段页和产品别名。

功能：

- 搜索产品名。
- 搜索产品别名。
- 搜索字段名。
- 搜索模块内容。
- 搜索来源原文。
- 跳过 rejected/invalid 字段。
- 支持向量检索和 RAG 召回。

### 5.7 Graph 视图

Graph 视图保留原项目图谱可视化，并扩展保险实体。

节点可能包括：

- 产品。
- 字段。
- 模块。
- 服务权益。
- 来源资料。
- 概念。
- 客户场景。
- 合规规则。

边关系可能包括：

- 产品包含字段。
- 字段来自模块。
- 模块引用来源。
- 产品属于险种。
- 产品关联服务权益。
- 产品具备保障责任。
- 产品与别名等价。

### 5.8 Settings 视图

Settings 视图用于运行配置。

设置区块：

| 区块 | 功能 |
| --- | --- |
| About | 版本和环境信息 |
| Interface | 界面配置 |
| LLM Provider | 大模型 Provider、Base URL、Key、模型名 |
| Embedding | Embedding 模型和向量配置 |
| Chunking | 文本切块参数 |
| Multimodal | OCR/视觉模型配置 |
| Output | 输出和写入策略 |
| Web Search | 网络搜索配置 |

### 5.9 Activity Panel

Activity Panel 用来承接耗时任务，避免 UI 冻结。

展示内容：

- 产品批量导入状态。
- 后台精炼状态。
- 文件上传状态。
- 错误和警告。
- 已完成任务摘要。

## 6. 后端 API

当前项目新增独立 Rust Axum 后端，统一提供文件、项目、向量、RAG、对话、上传、产品批量导入、LLM、认证等 API。

### 6.1 基础 API

| Method | Path | 功能 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 读取服务端配置 |

### 6.2 文件系统 API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/fs/read` | 读取文件 |
| POST | `/api/fs/write` | 写入文件 |
| POST | `/api/fs/list` | 列目录 |
| POST | `/api/fs/exists` | 判断文件是否存在 |
| POST | `/api/fs/delete` | 删除文件或目录 |
| POST | `/api/fs/mkdir` | 创建目录 |
| POST | `/api/fs/copy` | 复制文件 |
| POST | `/api/fs/copy-dir` | 复制目录 |
| POST | `/api/fs/preprocess` | 文件预处理/OCR/文本抽取 |
| POST | `/api/fs/read-base64` | 读取二进制文件为 base64 |
| POST | `/api/fs/related-wiki-pages` | 查询来源相关 Wiki 页面 |
| GET | `/api/fs/media` | 读取媒体资源 |
| GET | `/api/fs/clip-server-status` | 剪藏服务状态 |

### 6.3 项目 API

| Method | Path | 功能 |
| --- | --- | --- |
| GET | `/api/project/list` | 项目列表 |
| POST | `/api/project/open` | 打开项目 |
| POST | `/api/project/create` | 创建项目 |
| POST | `/api/project/create-auto` | 自动创建项目 |

### 6.4 向量 API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/vector/upsert-chunks` | 写入/更新向量 chunk |
| POST | `/api/vector/search-chunks` | 搜索向量 chunk |
| POST | `/api/vector/delete-page` | 删除页面向量 |
| POST | `/api/vector/count-chunks` | 统计 chunk 数 |
| POST | `/api/vector/drop-legacy` | 清理旧向量数据 |
| GET | `/api/vector/meta` | 读取向量元信息 |
| POST | `/api/vector/update-meta` | 更新向量元信息 |

### 6.5 RAG 和对话 API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/rag/retrieve` | RAG 召回 |
| GET | `/api/rag/status` | RAG 状态 |
| POST | `/api/chat/stream` | 知识库对话流式输出 |

### 6.6 上传 API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/upload/file` | 上传单文件 |
| POST | `/api/upload/files` | 上传多文件 |

### 6.7 产品批量导入 API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/ingest/product-batches` | 创建产品导入批次 |
| GET | `/api/ingest/product-batches` | 查询批次列表 |
| GET | `/api/ingest/product-batches/{batch_id}` | 查询单个批次 |
| POST | `/api/ingest/product-batches/{batch_id}/files` | 上传批次文件 |
| POST | `/api/ingest/product-batches/{batch_id}/start` | 启动批次处理 |
| POST | `/api/ingest/product-batches/{batch_id}/retry` | 重试失败批次 |
| GET | `/api/ingest/product-batches/events` | 批次状态 SSE |
| POST | `/api/ingest/product-refinements` | 创建产品精炼任务 |
| GET | `/api/ingest/product-refinements/{job_id}` | 查询精炼任务状态 |

创建批次请求字段：

| 字段 | 说明 |
| --- | --- |
| `project_name` | 项目名称 |
| `project_path` | 项目路径，可选 |
| `product_name` | 产品名称 |
| `insurance_category` | 险种类别 |
| `product_code` | 产品代码，可选 |
| `client_batch_id` | 前端生成的批次 ID，可选 |
| `duplicate_policy` | 重复文件处理策略 |
| `section_parallel` | Section 抽取并发 |

批次对象字段：

| 字段 | 说明 |
| --- | --- |
| `batch_id` | 服务端批次 ID |
| `client_batch_id` | 客户端批次 ID |
| `project_id` | 项目 ID |
| `project_name` | 项目名 |
| `project_path` | 项目路径 |
| `product_name` | 产品名 |
| `product_code` | 产品代码 |
| `insurance_category` | 险种 |
| `duplicate_policy` | 重复策略 |
| `status` | 批次状态 |
| `files` | 上传文件列表 |
| `written_files` | Worker 写出的文件 |
| `warnings` | 警告 |
| `manifest_path` | manifest 路径 |
| `error` | 错误 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `started_at` | 开始时间 |
| `completed_at` | 完成时间 |
| `section_parallel` | 并发参数 |

批次文件字段：

| 字段 | 说明 |
| --- | --- |
| `file_id` | 文件 ID |
| `name` | 文件名 |
| `relative_path` | 相对路径 |
| `stored_path` | 服务端存储路径 |
| `size` | 文件大小 |
| `sha256` | 文件 hash |
| `document_type` | 文档类型 |

### 6.8 LLM API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/llm/stream` | 文本 LLM 流式调用 |
| POST | `/api/llm/vision-stream` | 视觉/多模态 LLM 流式调用 |
| POST | `/api/llm/embed` | Embedding 调用 |

### 6.9 Web Search API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/search/web` | 网络搜索 |

### 6.10 Auth API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 当前用户 |

## 7. 前端/业务内部 API 和核心模块

### 7.1 产品目录抽取模块

| 文件 | 功能 |
| --- | --- |
| `frontend/src/lib/product-catalog-extractor.ts` | 产品目录抽取主逻辑、字段聚合、模块解析、页面生成 |
| `frontend/src/lib/product-catalog-modules.ts` | 产品模块定义、字段映射、险种模块白名单 |
| `frontend/src/lib/product-catalog-sync.ts` | 字段页、主页面、概念页同步 |
| `frontend/src/lib/product-identity.ts` | 产品身份识别、产品名/代码/险种上下文 |
| `frontend/src/lib/concept-aggregator.ts` | 概念聚合、产品字段实体汇总 |
| `frontend/src/lib/insurance-schema-registry.ts` | 保险 Schema 注册 |
| `frontend/src/lib/knowledge-schema.ts` | 知识域、实体类型、目录定义 |

### 7.2 抽取和预处理模块

| 文件 | 功能 |
| --- | --- |
| `frontend/src/lib/pdf-ocr.ts` | PDF OCR 和文本抽取 |
| `frontend/src/lib/ocr-text-repair.ts` | OCR 文本修复 |
| `frontend/src/lib/bailian-vision.ts` | 视觉模型文档识别 |
| `frontend/src/lib/extraction-quality-audit.ts` | 抽取质量检查 |
| `frontend/src/lib/knowledge-postprocess.ts` | 知识后处理 |
| `frontend/src/lib/knowledge-frontmatter.ts` | Frontmatter 读写 |
| `frontend/src/lib/knowledge-frontmatter-cleanup.ts` | Frontmatter 清理 |

### 7.3 图谱和关系模块

| 文件 | 功能 |
| --- | --- |
| `frontend/src/lib/entity-normalizer.ts` | 实体规范化 |
| `frontend/src/lib/knowledge-global-relation.ts` | 全局关系生成 |
| `frontend/src/lib/knowledge-identity-resolution.ts` | 身份解析 |
| `frontend/src/lib/knowledge-relation-index.ts` | 关系索引 |
| `frontend/src/lib/knowledge-resolution.ts` | 知识解析 |
| `frontend/src/lib/wiki-alias-map.ts` | Wiki alias 映射 |
| `frontend/src/lib/service-benefit-enrichment.ts` | 服务权益增强 |

### 7.4 服务端配置和错误治理

| 文件 | 功能 |
| --- | --- |
| `frontend/src/lib/server-config.ts` | 服务端配置适配 |
| `frontend/src/lib/fs-errors.ts` | 文件系统错误封装 |
| `frontend/src/lib/logger.ts` | 日志 |

### 7.5 测试覆盖

重点测试文件：

| 文件 | 覆盖内容 |
| --- | --- |
| `frontend/src/lib/__tests__/product-catalog-modules.test.ts` | 模块字段映射、险种白名单、重大疾病字段等 |
| `frontend/src/lib/__tests__/product-catalog-extractor.test.ts` | 字段聚合、保单贷款前置条件、医疗险重大疾病等 |
| `frontend/src/lib/entity-normalizer.test.ts` | 实体规范化 |
| `frontend/src/lib/knowledge-schema-normalizer.test.ts` | Schema 规范化 |
| `frontend/src/lib/ingest-write-guard.test.ts` | 写入保护 |
| `frontend/src/lib/service-identity-canonicalization.test.ts` | 服务身份规范化 |

## 8. 数据目录和产物结构

当前项目的数据产物比原项目更业务化。

典型目录：

```text
wiki/
  product_catalog/
    寿险/
      产品A/
        产品A.md
        字段-保险期间.md
        字段-保单贷款.md
        模块-保障责任.md
        模块-责任免除.md
    医疗险/
      产品B/
        产品B.md
        字段-重大疾病.md
        字段-续保规则.md
  source_text/
    ...
  concepts/
    ...

.llm-wiki/
  ingest-batches/
    {batch_id}/
      manifest.json
      files/
      worker-result.json
  refinement-jobs/
    {job_id}.json
  reviews/
    ...
```

核心产物：

| 产物 | 说明 |
| --- | --- |
| 产品主页面 | 产品知识总入口 |
| 字段页 | 字段级知识单元 |
| 模块页 | 业务模块级知识 |
| source_text 页 | 原文保留 |
| concept 页 | 图谱/RAG 概念 |
| review 项 | 冲突和人工确认 |
| batch manifest | 批次元信息 |
| worker result | Worker 执行结果 |
| refinement job | 精炼任务状态 |

## 9. 与原项目相比的新增、替换和弱化

### 9.1 主要新增

- 保险知识域。
- 险种产品库 `product_catalog`。
- 保险产品 Schema registry。
- 产品目录抽取器。
- Section-Scan 编译流程。
- 产品模块页。
- 产品字段页。
- 字段级状态和缺口。
- 险种模块白名单。
- 字段聚合和替换策略。
- 原文证据注入。
- QA/产品特色文档路由。
- 产品别名同步。
- 增量导入和冲突审核。
- 来源删除清理。
- 后台精炼。
- 服务端 Product Batch API。
- Node Worker 编排。
- Docker/Linux 部署。
- 大规模页面性能治理。

### 9.2 主要替换或重心变化

| 原项目重心 | 当前项目重心 |
| --- | --- |
| 通用文件导入 | 保险产品资料批量导入 |
| 页面级 Wiki | 产品/模块/字段/来源多层知识产物 |
| 通用摘要和抽取 | 保险字段级抽取和原文证据 |
| 单机桌面应用 / Tauri 命令层 | 桌面 UI + 独立 HTTP 后端 + Worker |
| 通用图谱 | 保险产品和服务权益图谱 |
| 用户手动整理 | 自动编译 + 人工审核 |

### 9.3 当前分支相对原 upstream 可能弱化或未完整跟进的部分

由于当前分支长期围绕保险产品目录深度迭代，原 upstream 后续能力不一定完整保留或同步，例如：

- 最新 MCP server 能力。
- 最新 Agent Skills。
- 最新 Deep Research 流程。
- 最新浏览器插件或剪藏扩展细节。
- 最新通用图谱算法升级。

迁移时需要逐项比对，而不能默认当前分支拥有 upstream 全部最新能力。

## 10. 迁移到 WeKnora 时可复用的内容

若后续迁移到 WeKnora，需要把当前项目拆成可复用资产和需要重做的部分。

### 10.1 高价值可复用资产

| 资产 | 复用方式 |
| --- | --- |
| 保险产品 Schema | 迁移为 WeKnora 的 domain schema / metadata schema |
| 产品目录字段体系 | 作为产品知识模板和字段定义 |
| 险种模块白名单 | 迁移为导入规则或后处理规则 |
| Section-Scan 编译思路 | 复用为 WeKnora ingestion pipeline 的前处理/抽取器 |
| 字段聚合策略 | 迁移为 structured extraction post-processor |
| 原文证据注入 | 迁移为 citation/evidence 机制 |
| 字段页/模块页产物 | 可转为 WeKnora document chunks、metadata、collection |
| 增量更新策略 | 迁移为 upsert/conflict review 策略 |
| Review 规则 | 迁移为人工审核工作流 |
| 产品批量导入 API 设计 | 复用为外围导入服务或适配层 |
| Worker 编排 | 可作为 WeKnora ingestion worker 的参考 |
| 0709 测试样例 | 作为迁移回归测试集 |

### 10.2 迁移时需要重点保留的需求

- 字段不能丢原文关键条件。
- `保单贷款` 这类条款字段必须保留前置条件、限制条件和申请条件。
- 医疗险要支持 `重大疾病` 字段。
- 疾病数量和疾病范围要可追踪。
- 不允许抽取超出 schema 的字段，新增字段必须先进入 schema。
- 产品别名要贯穿搜索、问答、字段页、来源页。
- 删除来源必须清理派生知识。
- 批量导入必须可重试、可恢复、可观测。
- 大规模产品库不能因为文件树和预览卡死。
- 人工修订不能被后续导入直接覆盖。

### 10.3 迁移时可能需要重做的部分

- 当前 Markdown 文件产物到 WeKnora 存储模型的映射。
- 当前 React UI 到 WeKnora UI 插件/页面的适配。
- 当前 Rust API 到 WeKnora API 的适配。
- 当前 Node Worker 和 WeKnora ingestion worker 的整合。
- 当前向量库和 WeKnora 检索机制的对齐。
- Review 数据结构迁移。
- Concept graph 迁移。

## 11. 当前 0709 验证进展

本轮针对用户反馈的两个质量问题做了修复和验证：

### 11.1 问题一：字段抽不全

示例：

```text
寿险-平安盛世金越（尊享版26）终身寿险-保单贷款.md
```

反馈问题：

- `保单贷款` 字段缺少前置条件。
- 原文条件包括“经被保险人书面同意，您可申请使用保单贷款功能”。

已做方向：

- 调整 `保单贷款` 字段聚合逻辑。
- 允许并鼓励保留申请前置条件。
- 避免只抽“贷款金额/比例/期限”等数值字段。
- 测试覆盖字段值需要包含前置条件。

### 11.2 问题二：超出 Schema 或缺少专属字段

反馈问题：

- 医疗险用户会问“保多少种疾病”。
- 医疗险领域需要补 `重大疾病` 字段。
- 抽取值要包含“保什么疾病”和“多少种疾病”的原文信息。

已做方向：

- 在医疗险字段体系中补充 `重大疾病`。
- 更新模块字段映射。
- 更新抽取聚合测试。
- 避免未进入 schema 的字段被随意写入。

### 11.3 跑数状态

已在 `0709` 项目上跑完产品资料：

- 先跑 3 个文件测试效果。
- 再跑剩余 10 个。
- 合计 13 个产品批次。
- `product_catalog` 下生成约 1112 个 Markdown 页面。
- 13/13 主产品页完成。

已验证：

- 目标 Vitest 通过。
- `npm run build:worker` 通过。

## 12. 关键文件索引

### 12.1 前端核心

| 文件 | 说明 |
| --- | --- |
| `frontend/src/lib/product-catalog-extractor.ts` | 产品目录抽取和字段聚合主逻辑 |
| `frontend/src/lib/product-catalog-modules.ts` | 产品模块、字段映射、险种白名单 |
| `frontend/src/lib/product-catalog-sync.ts` | 字段/主页/概念同步 |
| `frontend/src/lib/concept-aggregator.ts` | 概念聚合 |
| `frontend/src/lib/insurance-schema-registry.ts` | 保险 Schema 注册 |
| `frontend/src/lib/knowledge-schema.ts` | 知识域定义 |
| `frontend/src/lib/product-identity.ts` | 产品身份识别 |
| `frontend/src/components/sources/sources-view.tsx` | 来源和产品上传入口 |
| `frontend/src/components/review/review-view.tsx` | 审核视图 |
| `frontend/src/components/layout/app-layout.tsx` | 主布局 |
| `frontend/src/store/wiki-store.ts` | 前端状态和 view |

### 12.2 后端核心

| 文件 | 说明 |
| --- | --- |
| `backend/src/main.rs` | API 路由注册 |
| `backend/src/handlers/fs.rs` | 文件/OCR/预处理 |
| `backend/src/handlers/ingest.rs` | 产品批量导入和精炼 API |
| `backend/src/handlers/vector.rs` | 向量 API |
| `backend/src/handlers/rag.rs` | RAG API |
| `backend/src/handlers/chat.rs` | 对话 API |
| `backend/src/handlers/llm.rs` | LLM API |
| `backend/worker/ingest-worker.ts` | Node Worker 编排 |

### 12.3 文档

| 文件 | 说明 |
| --- | --- |
| `docs/PROJECT_HISTORY.md` | 项目历史和版本演进 |
| `docs/PROJECT_COMPARISON.md` | 项目对比 |
| `docs/ARCHITECTURE.md` | 当前项目架构说明 |
| `docs/INGEST_AND_WIKI_DATA_ARCHITECTURE.md` | Ingest 与 Wiki 数据流细化说明 |
| `deployment/README.md` | 部署目录说明 |
| `deployment/releases/llm-wiki-linux-amd64-docker20/API_REFERENCE.md` | Linux/Docker 发布包 API 参考 |
| `deployment/releases/llm-wiki-linux-amd64-docker20/DEPLOYMENT.md` | Linux/Docker 发布包部署说明 |

## 13. 当前项目的核心价值

当前项目已经从原通用 LLM Wiki 演进为一个保险产品知识生产系统，核心价值在于：

- 能把复杂保险资料批量编译成可编辑、可检索、可问答的知识库。
- 能保留字段原文证据，适合条款型、合规敏感型场景。
- 能按产品、险种、模块、字段组织知识。
- 能做增量更新，减少覆盖人工修订的风险。
- 能通过 Review 处理冲突和演化。
- 能服务端化批量导入，具备迁移到更大知识平台的基础。

## 14. 对 Claude 版本的完整性评估

结论：`docs/EVOLUTION_FROM_NASHSU.md` 适合作为高层对比初稿，方向基本正确，但不足以作为最终交付稿。它覆盖了代码、架构、功能、文档和 Ingest 的主线，不过对近期需求迭代、服务端批量导入、字段级产物、来源治理和当前分支相对 upstream 的差异说明不够完整。

本版相对 Claude 初稿的主要补充：

1. 增加从 2026-05 到 2026-07 的需求演进时间线，特别是 0708/0709 的 `保单贷款` 前置条件和医疗险 `重大疾病` 字段修复。
2. 把 Ingest 拆成产品目录管线、Section-Scan、字段聚合、模块页、字段页、主产品页重建、增量更新、删除清理和后台精炼，不只停留在流程图层面。
3. 补齐服务端 Product Batch API、Node Worker、SSE 状态、批次 manifest 和 refinement job 的运行模型。
4. 补齐 `value_source`、`value_sources`、`evidence_modules`、字段状态、知识缺口等字段级治理信息。
5. 补齐当前代码中的实际入口和关键文件索引，区分 `docs/` 文档、`deployment/` 发布文档和源码模块。
6. 明确当前分支可能没有完整跟进 upstream 的 MCP、Agent Skills、Deep Research、剪藏扩展等通用能力，避免把原项目最新能力误认为当前项目已有能力。

因此，若要给团队交付一版可作为后续迁移和需求复盘依据的文档，应以本文档和 `docs/INGEST_AND_WIKI_DATA_ARCHITECTURE.md` 为主，`docs/EVOLUTION_FROM_NASHSU.md` 可作为 Claude 初稿参考。
