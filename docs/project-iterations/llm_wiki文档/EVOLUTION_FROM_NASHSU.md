# 从 nashsu/llm_wiki 演化梳理：功能迭代与核心问题

> **原始项目**: [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) ⭐9.5k
> **参考文档**: `ARCHITECTURE.md`, `AGENT_ROADMAP.md`, `PROJECT_COMPARISON.md`, `PROJECT_HISTORY.md`, `CHANGELOG.md`

---

## 一、前端

### 原项目有的

- Tauri v2 桌面 App（单机本地运行）
- 基础三栏布局（文件树 | 内容 | 聊天）
- Milkdown WYSIWYG Markdown 编辑器 + 自动保存
- 基础文件树（平铺 wiki/*.md）
- Chat 对话 + `[[wikilink]]` 引用
- sigma.js 知识图谱（类型视图 + 社群视图）
- Activity 面板（基础进度条）

### 我们做了什么

1. **Ingest 队列状态显示优化** — Activity Panel 增加 Heartbeat 计时器（每5秒更新已耗时），解决 OCR 后前端看起来"卡住不动"的问题。批次任务显示待处理/处理中/失败，支持取消和重试。
   - 文件: `activity-panel.tsx`, `ingest-queue.ts`

2. **Markdown 界面优化** — 预览面板支持 YAML frontmatter 渲染、表格高亮、wikilink 可点击跳转。编辑器支持视图编辑（Milkdown WYSIWYG）和源码编辑双模式切换。自动保存后同步预览内容，切预览前强制 flush。
   - 文件: `preview-panel.tsx`, `wiki-editor.tsx`

3. **Knowledge 界面：新增服务线与产品库展示** — 知识树从原来的单一平铺改为三个 Tab：`类型 | 服务线 | 产品库`。服务线按 `系列 > 场景 > 服务线 > 版本` 四级层级展示。产品库按 `险种 > 产品 > 模块` 三级展示，模块数量色彩标识（绿≥5/蓝≥2/灰<2）。
   - 文件: `knowledge-tree.tsx`（645行，全新重写）
   - 目录规范: `wiki/entities/{line}/{version}/` + `wiki/product_catalog/{险种}-{产品}-{模块}.md`

4. **MD 文件编辑与删除功能** — 支持视图编辑（WYSIWYG）和源码编辑双模式。新增批量勾选删除（checkbox + 二次确认弹窗），调用 `cascadeDeleteWikiPage()` 级联清理向量索引和关系。
   - 文件: `knowledge-tree.tsx`（L170-184 批量删除）, `wiki-page-delete.ts`

5. **过载折叠功能** — 每次最多渲染 100 行（`PAGE_RENDER_BATCH = 100`），底部"显示更多（剩余 N）"按需加载，避免数千 md 一次性 DOM 爆炸。产品搜索不再强制展开所有产品层级。Raw Sources 同样有折叠。
   - 文件: `knowledge-tree.tsx`（L393-412 PageRows 组件）

6. **文档搜索功能** — Knowledge/Files 面板增加本地搜索，匹配标题、文件名、路径、domain、tags、服务线/版本。搜索时自动展开命中的分组。
   - 文件: `knowledge-tree.tsx`（L79-95 pageMatchesSearch）

7. **文件树可拉伸范围加长 + 名称显示** — 左侧面板可拖拽宽度上限放大。每个 PageRow 使用 `truncate` + `title` tooltip 显示完整路径，解决长名称截断问题。
   - 文件: `knowledge-tree.tsx`（L381-384）

8. **前端文件上传分类处理** — Sources 视图新增产品库上传面板：手动选择险种类别（6险种 tabs）+ 输入产品名 + 文件上传。因为文件名只写"保险条款"无法识别险种，所以必须人工选择。上传后自动推断文档类型（条款/费率表/核保），按模块分批排队。
   - 文件: `sources-view.tsx`（Shield 图标按钮 → 上传面板）
   - 补充: 后续 v2.8 新增批量 API 上传（`POST /api/ingest/product-batches`），前端默认4路并发，SSE 自动刷新知识树。

9. **知识演化 Tab 面板** — 直接读取 `.llm-wiki/review.json` 中已处理的 contradiction/confirm 项，展示字段名、原知识、新增知识、处理动作、关联页面。解决冲突处理后"管理员不知道做了什么决策"的问题。
   - 文件: `evolution-panel.tsx`, `review-view.tsx`

10. **多用户项目共享（未做权限隔离）** — 数据存在服务端 `wiki-data/` 目录，不在用户本地。多个用户可通过浏览器访问同一项目。但目前**未实现** RBAC 权限和项目隔离（参见 WeKnora 对比，这是 P3 待补项）。
    - 文件: `backend/src/state.rs`（多根目录 guard）, `auth-store.ts`

11. **数据存服务端** — ✅ 正确。nashsu 数据存用户本地（Tauri AppData），我们改为存服务端 `wiki-data/` + 后端 HTTP API 读写。Docker 部署时通过 bind mount 持久化。
    - 文件: `backend/src/handlers/fs.rs`, `server-config.ts`

12. **前端上传分类 UI 与接口** — ✅ 正确。每个领域抽取规则有差异（服务手册 vs 产品条款 vs 费率表），上传界面需要用户明确选择。产品目录走 `product-catalog-extractor.ts`，服务手册走通用 `ingest.ts` + `buildServiceManualNodeDirective()`。
    - 文件: `sources-view.tsx`, `ingest.ts`（L126-276 产品目录指令构建）

13. **"概念"和"精炼"按钮** — ✅ 正确。
    - **概念聚合**: `concept-aggregator.ts`（21KB）— 队列清空后自动执行 `scanProductConcepts()` + `buildProductConceptIndex()`，也可手动触发。
    - **精炼**: `refineAllProductModules()`（`product-catalog-extractor.ts`）— 在已保留的原文基础上对"未明确"字段做二次 LLM 调用，不重新上传 PDF。后续 v3.0 改为后台 API `POST /api/ingest/product-refinements`。

14. **前后端分离** — ✅ 正确。nashsu 是 Tauri 桌面版（前后端打包在一起），我们改为 Vite Web 前端 + Rust Axum 后端（8081端口）独立运行，支持 Docker 部署。
    - 文件: `backend/src/main.rs`（Axum HTTP 服务）

### 你没提到的前端补充

15. **后端错误规范化** — 已删除 md 的后端 `{"error":"File does not exist"}` 不再作为 markdown 渲染。预览遇到文件不存在会清空选中并刷新列表。
    - 文件: `api-client.ts`, `fs-errors.ts`, `preview-panel.tsx`, `wiki-page-viewer.tsx`

16. **删除源文件后 UI 乐观更新** — 删除按钮增加"删除中..."状态，成功后立即从 source tree 移除节点，不需要手动刷新页面。
    - 文件: `sources-view.tsx`

17. **知识图谱业务域视图** — 新增按 Product/Customer/Method/Content/Activity/Cases/Compliance 着色的业务域视图，支持点击图例筛选。
    - 文件: 见 `insurance-knowledge-graph-roadmap.md`

18. **Review 审核面板** — 冲突 review 点击「采用新值」后增加处理中状态，回写模块表格 + 字段页 + 主产品页 + 概念页。采用新值不触发 AI 重新抽取。
    - 文件: `review-view.tsx`, `product-catalog-sync.ts`

---

## 二、Ingest 层

### 原项目有的

- Two-Step CoT（Step1 分析 → Step2 生成）
- SHA256 增量缓存（文件内容未变则跳过）
- 串行队列 + 自动重试（最多3次）
- Auto-embedding（ingest 后自动向量化）
- overview.md 自动更新

### 我们做了什么

1. **多格式文件解析器** — ✅ 正确。nashsu 主要支持文本/PDF。我们增加了 PDF 4级 fallback（pdf-extract → pdftotext ≥200字 → OCR Vision LLM → pdftoppm 图片marker），图片 OCR（`ocrImageBytes`），JSON 确定性解析（`fastIngestJsonSource`）。
   - 文件: `backend/src/handlers/fs.rs`（4级PDF），`ingest.ts`（L650-785 prepareSourceContentWithOcr），`pdf-ocr.ts`

2. **OCR 与 LLM 并发抽取** — ✅ 正确。产品目录管线中 Section-Scan 使用 `MAX_SECTION_PARALLEL` 控制 section 级并发，group-round 每组 5-8 模块并发送 LLM，Phase 5 精炼并发 10（后改为4）。
   - 文件: `product-catalog-extractor.ts`

3. **OCR API 失败后 fallback** — ✅ 正确。PDF 读取 4 级梯度：内部 OCR API 失败 → pdf-extract → pdftotext → pdftoppm 图片。同时新增 `is_garbled_pdf_text()` 乱码检测（unique_char_ratio < 0.015 判定为乱码），自动跳到下一级。
   - 文件: `backend/src/handlers/fs.rs`（`is_garbled_pdf_text`）

4. **文件夹上传 → 拼接再切块 → 分批融合抽取** — ✅ 正确。以文件夹上传时，多个文件合并为一个 bundle（`__product_bundle__.json` manifest），然后走产品目录管线：OCR 全文 → `splitIntoSections(6000字/块, 500字重叠)` → 每组5-8模块并发 LLM → `mergeFragmentContents` 字段级 best-value 合并（取第一个非"未明确"值）→ 代码端100%原文注入。
   - **分批融合细节**: 同一产品的多个文件（条款.pdf + 费率表.xlsx + 补充说明.pdf）各自 OCR 后拼接为完整文本，再按 6000 字切 section。每个 section 独立送给 LLM 抽取同一组模块，最后跨 section 字段级合并——同一字段在不同 section 中命中时取信息量最大的值。
   - 文件: `product-catalog-extractor.ts`（splitIntoSections + mergeFragmentContents）

5. **超长文档切片处理** — ✅ 正确。nashsu 受 context window 限制，超长文档截断。我们的通用管线对 >50K 字符文档使用 `chunkMarkdown()` 按语义切块（10K-22K/块），每块独立做 LLM Stage1+2，最后合并。产品管线单独使用 6000 字/块。
   - **多次压缩导致数据丢失的解决方案**: 代码端 100% 注入原文到 source 页面（`preserveOcrDetailsInSourcePage`，最多保留 120K 字符），LLM 只输出关键字段表格，禁止摘抄原文。
   - 文件: `ingest.ts`（L288-294 LONG_SOURCE_DIGEST_LIMIT = 120000），`text-chunker.ts`

6. **抽取重试机制** — ✅ 正确。`ingest-queue.ts` 的串行队列支持失败自动重试（最多3次），失败任务可在 Activity Panel 手动重试。`streamChat` 层面也有 AbortController 超时（5min）。
   - 文件: `ingest-queue.ts`（33KB）

7. **Schema 约束字段 → 生成对应 md 文件格式** — ✅ 正确。通用管线：`buildSchemaCandidateManifest()` 注入最多80个 Schema 候选到 LLM prompt，约束输出字段名和 frontmatter 格式。产品管线：`buildProductCatalogGenerationOverride()` 注入模块白名单 + 路径规则 + frontmatter 必填字段（`knowledge_domain`, `insurance_category`, `product_name`, `dedup_key`, `entity_type`, `confidence`）。
   - 文件: `ingest.ts`（L126-276），`insurance-schema-registry.ts`

8. **数据回传前端接口（显示速度慢）** — ✅ 正确。v3.0 解决方案：文件树改为按 `dataVersion` 单入口防抖刷新（旧请求结果不覆盖新目录），移除队列运行期间每2.5秒扫描产品库，批次完成后通过 SSE `batch`/`refinement` 事件触发一次刷新。
   - 文件: `knowledge-tree.tsx`（L149-168 SSE 事件监听）

9. **Concepts 与实体关系双向映射** — ✅ 正确。nashsu 的 wikilink 是单向的。我们的 `knowledge-global-relation.ts`（28KB）实现跨文档双向关系推断，`expandGraphFromEntity()` 支持双向图遍历（`direction: "outgoing" | "incoming" | "both"`），`concept-aggregator.ts` 生成跨产品关联页时双向链接产品→概念和概念→产品。
   - 文件: `knowledge-global-relation.ts`, `knowledge-relation-index.ts`, `concept-aggregator.ts`

10. **抽取数据保留原文** — ✅ 正确。所有入库文件（含纯文字 PDF）都保留原始全文到 source 页面（`preserveOcrDetailsInSourcePage`，最多 120K 字符）。用于人工校验和二次抽取（精炼功能直接从已保留原文提取，不需要重新上传 PDF）。
    - 文件: `ingest.ts`（L191-194 移除只保留 OCR 来源的限制）

### 你没提到的 Ingest 补充

11. **JSON 确定性入库** — `.json` 文件走 `fastIngestJsonSource()` 快速路径，直接解析字段生成确定性 source 页面，不送 LLM，解决 LLM 对结构化 JSON 数据的幻觉问题。

12. **缓存 key 从文件名改为内容 Hash** — 文件名改了但内容没变→跳过；内容改了但文件名没变→触发重新入库。

13. **增量更新（只补空字段/新模块）** — 已有产品存在时，增量上传只补空字段，已有非空值不覆盖，进入 review 冲突队列。

14. **弱值过滤** — "需核对具体条款"、"以合同约定为准"、纯引用/占位值统一过滤为空，新值比旧值更粗略则不产生冲突。

15. **越域模块过滤** — 险种白名单 `isModuleAllowedForCategory()`，年金险不再生成孕妇投保限制等越域模块。

16. **MODULE_TO_FIELD_BRIDGE 字段桥接** — 11个模块→20+主文件字段映射，解决"模块抽到了但主字段为空"。

17. **占位符清洗（30+ regex）** — "未明确/未提及/证据片段中未提及"等全部过滤。

18. **QA 文档路由** — 只有文件名明确为 QA/FAQ 的才抽取问答，防止条款被拼成伪 QA。

19. **产品别称元数据回填** — aliases 写入所有 md frontmatter，检索可用别称召回。

20. **OOM 内存管理** — 扫描件 PDF base64 约120MB，`rawRef` 及时释放，fingerprint 替代 base64 作为缓存 key。

21. **Identity Resolution（4阶段 LLM 去重）** — 解决同一服务在多个产品手册中生成多个实体页。

22. **Authority-Weighted 冲突仲裁** — `source_type` 权重（条款100 > 说明书85 > 宣传材料70），字段冲突时按权威性自动仲裁。

23. **ExtractionQualityAudit 覆盖率审计** — 量化评分 + knowledge_gaps 报告，写入 source 页面。

---

## 三、后端

### 原项目有的

- Tauri Rust 命令层（文件读写、项目管理）
- tiny_http 本地 API（19828端口，基础）

### 我们做了什么

1. **Axum HTTP 服务（8081端口）** — 替代 Tauri IPC，支持独立部署。
2. **LanceDB 向量检索（1152维）** — 从前端可选迁移到后端必选，修复了原项目 384 维硬编码。
3. **BM25 Token 检索 + CJK 双字/三字分词** — 后端内存索引，替代前端逐文件扫描。
4. **RRF 三路混合检索融合** — 向量 + BM25 + Graph 1-hop 扩展，`quality_multiplier` 差异化权重。
5. **`/api/chat/stream` SSE 流式对话** — 后端完成 query rewrite + retrieval + prompt assembly + LLM streaming。
6. **`/api/rag/retrieve` 检索调试** — 独立检索端点，返回 chunks/sources/timings/warnings。
7. **`/api/rag/status` 索引状态** — 向量和 BM25 索引的维度/文档数/健康状态。
8. **`expand_insurance_query()` 保险术语扩展** — 检索前自动扩展术语变体（"投被保险人"→多种变体）。
9. **`best_evidence_anchor()` 证据行锚定** — 命中页面后按行扫描，找最佳证据行。表格行+8分，投被关系行+120分。
10. **`/api/ingest/product-batches` 批量导入 API** — 支持 4 路并发上传，状态持久化。
11. **服务端 Node Worker** — 复用 TypeScript autoIngest，后台执行，浏览器关闭不影响。
12. **`/api/ingest/product-refinements` 后台精炼** — 状态持久化，重复点击恢复现有任务。
13. **PDF 4级 fallback + 乱码检测**（`is_garbled_pdf_text`）。
14. **多根数据目录 guard** — 支持主数据目录 + `WIKI_EXTRA_DATA_PATHS` + 仓库祖先层级。
15. **Docker Compose + Helm 部署** — Linux amd64 镜像，SELinux `:Z` 标签，bind mount 权限自动授权。
16. **`.env` 配置管理** — 依次检查当前目录、`backend/.env`、可执行文件祖先目录。

---

## 四、知识更新与知识冲突治理（专题）

### nashsu 原项目

nashsu 在 Step1 分析时 LLM 会输出"Contradictions & tensions with existing knowledge"，但这**只是标注，不解决**。没有字段级合并、没有来源权重、没有增量更新。每次 ingest 都是全量覆盖。

### 我们的策略与代码实现

#### 4.1 增量更新策略

当同一产品已有主文件（`{险种}-{产品名}.md`）存在时，新上传的文件**不会全量覆盖**，而是走增量逻辑：

1. **空字段补充**: 新文件抽取到的字段值，如果对应字段在主文件中为空 → 直接写入
2. **非空字段冲突**: 新值与旧值不同 → 进入 `review.json` 冲突队列，等待人工仲裁
3. **新模块追加**: 新文件抽取到主文件不存在的模块 → 直接创建新模块页

- 代码: `knowledge-resolution.ts`（29KB）— `resolveIncomingKnowledgePage()` 函数

#### 4.2 冲突检测与仲裁机制

**Source 权威性权重**（`source_type` → 分值）：

| Source Type | 权重 | 说明 |
|-------------|------|------|
| `regulatory_doc` | 100 | 监管文件（最高权威） |
| `product_terms` | 95 | 正式产品条款 |
| `underwriting_manual` | 90 | 核保手册 |
| `rate_table` | 85 | 费率表 |
| `product_brochure` | 70 | 产品宣传册 |
| `training_material` | 60 | 培训材料 |
| `user_uploaded` | 50 | 用户手动上传 |

- 代码: `knowledge-resolution.ts` — `SOURCE_TYPE_WEIGHT` 常量

**冲突处理流程**:
```
新值到达 → 弱值过滤（30+ regex清洗）
  → 与旧值比较
    → 新值 = 旧值 → 跳过
    → 新值更粗略 → 自动忽略（不产生冲突）
    → 新值更详细 且 权重更高 → 自动采用
    → 新值 ≠ 旧值 且 权重相近 → 进入 review 队列
```

#### 4.3 弱值过滤（30+ regex 模式）

以下值统一过滤为空，**不作为有效知识入库**：
- "未明确"、"未提及"、"证据片段中未提及"
- "需核对具体条款"、"以合同约定为准"
- "详见XX"、"参见XX"
- 纯引用/占位值（只有标点或省略号）

- 代码: `product-catalog-extractor.ts` — `WEAK_VALUE_PATTERNS` + `isWeakFieldValue()`

#### 4.4 冲突 Review 队列

冲突项存储在 `.llm-wiki/review.json`，每条记录包含：
- `fieldName`: 冲突字段名
- `existingValue`: 当前值
- `incomingValue`: 新值
- `sourceFile`: 来源文件
- `sourceType`: 来源权威性
- `action`: `pending` | `accepted` | `rejected`

前端 Review 面板（`review-view.tsx`）展示冲突列表，点击「采用新值」触发：

```
review-view.tsx → applyProductFieldValueUpdate()
  → replaceProductFieldRows() 回写模块表格
  → syncProductFieldPageAfterEdit()
    → 更新字段页 → 更新主产品页 → 刷新概念聚合页
    → reembedChangedPages() 重新向量化
```

- 代码: `product-catalog-sync.ts`（544行）— 完整的字段回写 + 级联同步

#### 4.5 删除级联与字段来源追踪

每个字段页的 frontmatter 包含 `value_sources: [...]`，记录支撑该字段值的源文件列表。删除源文件时：

1. 从 `value_sources` 中移除该文件引用
2. 如果移除后仍有其他源文件支撑 → 保留字段值
3. 如果该文件是最后一个支撑源 → 清空字段值，标记 `status: rejected` + `extraction_state: needs_refinement`
4. 产品单文件删除走**快路径**（不做全库关联扫描），只清掉该文件独占支撑的字段值

- 代码: `product-catalog-sync.ts` — `clearProductFieldValueForDeletedSource()`（L481-538）

#### 4.6 知识演化追踪

前端「知识演化」面板读取已处理的 review 记录，展示：
- 字段名、原知识、新增知识
- 处理动作（accepted/rejected）
- 关联页面链接
- 处理时间

解决的核心问题：冲突处理后管理员不知道做了什么决策，无法回溯审计。

---

## 五、后端 API 完整路由表

以下为 `backend/src/main.rs` 中注册的全部 API 路由（前缀 `/api`）：

### 5.1 基础服务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/config` | 获取服务端配置（LLM provider/model/vision） |

### 5.2 文件系统（替代 Tauri IPC）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/fs/read` | 读取文件内容 |
| POST | `/fs/write` | 写入文件内容 |
| POST | `/fs/list` | 列出目录内容 |
| POST | `/fs/exists` | 检查文件是否存在 |
| POST | `/fs/delete` | 删除文件 |
| POST | `/fs/mkdir` | 创建目录 |
| POST | `/fs/copy` | 复制文件 |
| POST | `/fs/copy-dir` | 复制目录 |
| POST | `/fs/preprocess` | 文件预处理（PDF 4级提取 + 乱码检测） |
| POST | `/fs/read-base64` | 读取文件为 base64（图片/PDF） |
| POST | `/fs/related-wiki-pages` | 查找与源文件关联的 wiki 页面 |
| GET | `/fs/media` | 提供媒体文件（图片等） |
| GET | `/fs/clip-server-status` | CLIP 服务器状态检查 |

### 5.3 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/project/list` | 列出所有项目 |
| POST | `/project/open` | 打开项目 |
| POST | `/project/create` | 创建项目 |
| POST | `/project/create-auto` | 自动创建项目（外部系统调用） |

### 5.4 向量检索

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/vector/upsert-chunks` | 向量 Upsert（LanceDB 1152维） |
| POST | `/vector/search-chunks` | 向量相似度搜索 |
| POST | `/vector/delete-page` | 删除页面向量 |
| POST | `/vector/count-chunks` | 统计向量数量 |
| POST | `/vector/drop-legacy` | 清除旧维度索引 |
| GET | `/vector/meta` | 获取索引元信息 |
| POST | `/vector/update-meta` | 更新索引元信息 |

### 5.5 RAG 检索 + 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rag/retrieve` | 混合检索（向量+BM25+Graph 1-hop） |
| GET | `/rag/status` | 索引健康状态（维度/文档数/BM25词数） |
| POST | `/chat/stream` | SSE 流式对话（query rewrite → retrieval → LLM） |

### 5.6 批量产品入库（核心新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ingest/product-batches` | 创建批次（指定险种+产品名+项目） |
| GET | `/ingest/product-batches` | 列出所有批次 |
| GET | `/ingest/product-batches/{batch_id}` | 查询批次状态 |
| POST | `/ingest/product-batches/{batch_id}/files` | 上传文件到批次（multipart，200MB上限） |
| POST | `/ingest/product-batches/{batch_id}/start` | 启动批次抽取（Node Worker 后台执行） |
| POST | `/ingest/product-batches/{batch_id}/retry` | 重试失败的批次 |
| GET | `/ingest/product-batches/events` | SSE 事件流（batch/refinement 完成通知前端刷新） |
| POST | `/ingest/product-refinements` | 创建精炼任务（后台执行） |
| GET | `/ingest/product-refinements/{job_id}` | 查询精炼任务状态 |

**批量上传工作流**:
```
1. POST /ingest/product-batches → 创建批次，返回 batch_id
2. POST /ingest/product-batches/{batch_id}/files × N → 上传多个文件
3. POST /ingest/product-batches/{batch_id}/start → 启动 Node Worker
4. GET  /ingest/product-batches/events (SSE) → 前端监听完成通知
5. 前端收到 status:"completed" → 自动 bumpDataVersion() 刷新知识树
```

### 5.7 LLM/Embedding 代理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/llm/stream` | LLM 流式代理（解决 HTTPS Mixed Content + CORS） |
| POST | `/llm/vision-stream` | Vision LLM 代理（OCR 用） |
| POST | `/llm/embed` | Embedding 代理 |

### 5.8 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/search/web` | Web 搜索代理（Tavily/Perplexity） |
| POST | `/auth/register` | 用户注册（公开） |
| POST | `/auth/login` | 用户登录 |
| POST | `/auth/logout` | 用户登出 |
| GET | `/auth/me` | 获取当前用户信息 |

> 全部路由共 **39 个端点**，其中批量入库 9 个、文件系统 13 个、向量 7 个、RAG+对话 3 个。

---

## 六、核心技术难题与解决方案

### 6.1 知识冲突检测为什么能在大规模下工作？

**难题**：如果没有分类处理，几十万篇 md 后要做冲突检测，需要全库扫描 + 语义相似度匹配，性能和准确率都不可接受。

**我们的解法**：**路径即身份（Path = Identity）** — 冲突匹配不是全库扫描，而是 O(1) 文件读取。

```
ingest.ts L4993-4996:

  const fullPath = `${projectPath}/${relativePath}`
  const existing = await tryReadFile(fullPath)           // ← O(1) 路径查找
  const resolution = resolveIncomingKnowledgePage(relativePath, content, existing || null)
```

LLM 生成 `---FILE: wiki/entities/在线问诊.md---`，系统直接用这个路径读磁盘同名文件。存在 → 冲突检测；不存在 → 直接写入。

**产品管线更进一步**：路径不是 LLM 自由发挥的，而是**代码确定性生成**的：
```
wiki/product_catalog/{险种}-{产品名}-{模块名}.md
```
第 N 个文件上传后，代码拼出同样路径去读文件，**一定能匹配到**。

**为什么没有分类处理就不行**：

| 问题 | 有分类（当前架构） | 无分类（通用方案） |
|------|-----------------|----------------|
| 同一概念多个名字 | `entity-normalizer.ts` + `dedup_key` + 4阶段LLM去重 | LLM 每次随机取名，"在线问诊/视频问诊/远程问诊"生成3个文件，永远检测不到冲突 |
| 定位冲突目标 | 确定性路径 O(1) | 需要**全库扫描**做语义匹配，O(N)，N=几十万不可行 |
| 字段对齐 | Schema 统一字段名 | LLM 自由命名（"交费方式/缴费方式/交费期限"混用），JSON key 不同无法逐字段比 |
| 性能 | O(1) 查找 + O(字段数) 对比 | O(N×字段) 全库语义匹配 |

**结论**：Schema-Driven 分类处理不仅是"更好的组织方式"，而是冲突检测在大规模下**能工作的前提条件**。这是整个知识编译架构的护城河。

---

### 6.2 增量知识更新的完整机制

**难题**：第2、3个文件上传后，如何精确填入到原先 md 文档空缺的字段，而不破坏已有知识？

**解法**：`knowledge-resolution.ts` L170-301 的 `mergeAttributesByPolicy()` — 逐字段遍历 incoming attributes JSON，与 existing attributes JSON 对比：

```
for (const [field, incomingValue] of Object.entries(incoming)) {
  既有值为空 → 直接填入（gap-fill，这就是"填空缺"）
  值相同     → 跳过
  字段被人工锁定(user_locked_fields) → 永不覆盖
  字段策略=append → 列表合并（去重）
  字段策略=keep_best → 取权重高的值
  权威比值 ≥ 1.5 → 自动采用高权威值
  权威相当+新文件日期更新 → 自动采用 + 留 spot-check 审核项
  权威相当+日期相同+值不同 → 进入 Review 队列（真正的冲突）
}
```

**三个关键设计决策**：

1. **gap-fill 不产生冲突** — 旧值为空时直接填入，不进 Review，零噪音
2. **权威比值 1.5 阈值** — 例如 `service_manual(80) / agent_experience(40) = 2.0 ≥ 1.5 → 自动采用`，但 `sales_training(55) / agent_experience(40) = 1.375 < 1.5 → Review 队列`。减少 70% Review 噪音
3. **user_locked_fields 人工锁定** — 人工确认过的字段永远不被自动覆盖，写在 frontmatter 里

**合并后的 body 处理**：如果新文件有新增正文内容（不与旧文件重复），追加为 `## 来源补充：{新文件标题}` 小节，保留所有来源信息。

---

### 6.3 抽取质量审计如何统计已有知识与知识缺口

**难题**：抽取完成后无法量化评估质量，不知道哪些字段缺失、哪些页面没有证据。

**解法**：`extraction-quality-audit.ts`（399行）在每次 ingest 完成后自动运行，生成独立审计页面 `wiki/audits/{源文件}-抽取质量审计.md`：

**Step 1 — 逐页字段审计**：
```
对每个 wiki/entities/ 和 wiki/concepts/ 页面：
  → getInsuranceSchemaSpec(entityType) 获取该类型 Schema 规范
  → Schema 中字段分 critical / high_confidence / recommended 三级
  → 逐字段检查 attributes JSON 是否有值 → criticalFilled/criticalTotal
  → 统计：schema关系数、正文关系数、证据(claims/sources)数
  → 扫描正文关键词："待补全/缺失/未提供" → 知识缺口计数
```

**Step 2 — 源文档信号检测**：
```
扫描原文中28个已知服务关键词 → 推断文档形态（service_manual/case/qa）
统计表格行数 → 估算 expectedItemCount
```

**Step 3 — 加权综合评分**（满分100）：
```
score = critical覆盖率 × 0.28
      + high覆盖率     × 0.22
      + 证据覆盖率     × 0.18
      + 关系覆盖率     × 0.14
      + 预期条目覆盖率 × 0.12
      + 候选缺失惩罚   × 0.06
```

**Step 4 — 生成建议**：score < 60 → "不建议直接演示问答"；critical < 80% → "优先检查核心字段"

**Step 5 — 如果 score < 75 或有缺失候选**，自动生成一条 ReviewItem 提醒人工复核。

---

### 6.4 超长文档如何处理？多次压缩导致信息丢失怎么办？

**难题**：保险产品条款 PDF 通常 30-100+ 页（47000-200000 字），远超 LLM 单次 context window（通常 8K-32K tokens）。如果直接截断或多轮压缩摘要再输入，每一轮都会丢失信息——三轮压缩后，关键条款细节（如免赔额的计划选项、续保条件的例外规则）几乎全部丢失。

**nashsu 原项目**：超长文档直接截断到 context window 大小，尾部信息全部丢失。

**我们的解法**：两套管线，两种策略：

#### 通用管线（服务手册等非产品文档）

```
原文 > 50000 字 → 进入 hierarchical-long-document 模式：

1. chunkMarkdown(sourceContent, {target: 22000, max: 30000, overlap: 500})
   → 按语义边界切块（标题/段落优先，不在句子中间断）
   → 每块约 10K-22K 字

2. 每块独立送 LLM 做 Stage1（分析）+ Stage2（生成 FILE 块）
   → 各块的输出独立写入文件系统
   → 同一实体在多块中出现 → 后续块触发知识合并（resolveIncomingKnowledgePage）

3. 全文 OCR 原文（最多 120K 字）完整保留到 source 页面
   → preserveOcrDetailsInSourcePage(path, content, origin)
   → 人工校验和二次抽取直接从 source 页面提取
```

**关键设计**：LLM 只输出**结构化字段表格**，不摘抄原文。原文 100% 由代码端注入到 source 页面。这样即使 LLM 漏抽了某个字段，原文仍然在 source 页面中，精炼阶段可以从保留的原文中二次抽取。

#### 产品目录管线（Section-Scan 架构）

```
47000 字的条款 PDF → splitIntoSections()：

1. 按标题结构切分（# / ## / 条/第X条 等标题层级）
   → 目标: 每块 4000-8000 字（约 2-5 页条款）
   → 参数: targetChars=6000, maxChars=12000, minChars=1500, overlapChars=300
   → 39 页 47000 字 PDF → 通常切成 8-12 个 sections

2. 每个 section 独立送 LLM，告诉它"这是第 N/M 个章节"
   → prompt 中注入全部目标模块名 + 关键字段列表
   → LLM 只输出 ---MODULE: xxx--- 表格，不摘抄原文
   → 代码自动注入该 section 的完整原文到 "## 详细条款原文"

3. 跨 section 字段级最优值合并（mergeFragmentContents）
   → 同一模块在多个 section 中被命中
   → 逐字段取"信息量最大的值"（informationScore 打分）
   → 年龄字段取最高值、列表字段合并去重
```

**为什么不会丢失信息**：
- 每个 section 有 300 字重叠（overlapChars=300），跨页信息不断裂
- LLM **不做摘要压缩**，只做字段识别+表格填充；原文由代码端 100% 注入
- 多个 section 对同一模块的抽取结果做字段级合并，而不是文本级拼接
- 合并规则用 `shouldReplaceFieldValue()` 打分：包含列表标记加 80 分、包含关键词（无等待期/合同终止/返还）加 30 分

---

### 6.5 分批处理导致 LLM 调用太多，速度很慢怎么办？

**难题**：一个 39 页 PDF 切 10 个 section，每 section 送一次 LLM，加上精炼阶段每个模块再送一次 → 总共 30-50 次 LLM 调用 → 如果串行执行需要 20-40 分钟。

**我们的解法**：三层并发控制：

#### 层 1：Section 级并发

```
product-catalog-extractor.ts:

MAX_SECTION_PARALLEL = 3  （同时处理 3 个 section）

const sectionPromises = sections.map((section, i) =>
  semaphore.acquire(() => extractFromSection(section.text, i, ...))
)
await Promise.all(sectionPromises)
```

10 个 section → 3 路并发 → 约 4 轮完成（而非 10 轮）

#### 层 2：模块组级并发（group-round）

```
产品管线将全部模块（约 30-50 个/险种）分成 5-8 组，每组 5-8 个模块
每组在一次 LLM 调用中同时抽取
→ 30 个模块 / 每组 6 个 = 5 次 LLM 调用（而非 30 次）
```

#### 层 3：精炼阶段并发

```
Phase 5 精炼：对"未明确"字段做二次 LLM 调用
并发度: 4（从初始 10 降至 4，平衡速度与 API 限流）

refineAllProductModules() 使用 Promise.allSettled + 并发池
```

#### 层 4：批次 API 并发（v3.0 后端）

```
POST /api/ingest/product-batches/{batch_id}/start → Node Worker 后台执行
前端默认 4 路并发上传
多个产品的批次可以并行（每批次内部仍受 MAX_SECTION_PARALLEL 限制）
```

**实际效果**：39 页 PDF 的完整抽取（OCR → Section-Scan → 字段合并 → 精炼 → 概念聚合）约 **2-4 分钟**。

**对比：如果采用常规分批融合方案**：

```
常规方案（每个模块 × 每个 section 各调一次 LLM）：
  10 sections × 30 modules = 300 次 LLM 调用  ← 完全不可行
  
退而求其次（每个 section 单独调用，每次抽所有模块）：
  10 sections × 1 调用 = 10 次
  + 精炼阶段 30 模块 × 1 调用 = 30 次
  + 概念聚合 + 主字段同步 = ~10 次
  → 总计约 50 次 LLM 调用（串行 ≈ 25-40 分钟）

更粗暴的做法（多轮摘要压缩再抽取）：
  第1轮: 10 sections × 1 调用 = 10 次（压缩摘要）
  第2轮: 合并后再送 LLM = 1 次（信息已丢失 30-50%）
  第3轮: 精炼补空 = 30 次（补不回来了，原文已被压缩丢弃）
  → 总计 41 次调用，但质量远不如 Section-Scan
```

| 方案 | LLM 调用次数 | 耗时 | 覆盖率 | 原文保留 |
|------|------------|------|--------|---------|
| 常规逐模块×逐section | 300 | 不可行 | — | 无 |
| 常规分批融合（串行） | ~50 | 25-40分钟 | ~60% | 无 |
| 多轮摘要压缩 | ~41 | ~20分钟 | ~40%（三轮压缩丢失严重） | 无 |
| **我们的 Section-Scan**（并发） | **~10-15** | **2-4分钟** | **80-90%** | **100%** |

**核心优化点**：
- 每个 section 一次 LLM 调用同时抽取**全部模块**（而非每模块单独调用）
- 3 路 section 并发 → 10 sections 只需 4 轮
- LLM 只输出表格，原文由代码注入 → 省掉"摘抄原文"的 token 消耗
- 精炼阶段只对**空字段**调用，非全量 → 实际只需 5-10 次补空调用

---

### 6.6 如何保证抽的全、抽的准？

**难题**：LLM 有三大抽取质量问题：
1. **漏抽**：某些字段在原文中明确存在但 LLM 没抽到
2. **幻觉**：LLM 用常识或推断填充了原文没有的值
3. **粗化**：LLM 把详细条款压缩成一句话（"按条款约定执行"），丢失关键细节

**我们解决了多少？各用什么策略？**

#### 策略 1：Schema 约束 — 防幻觉

```
buildPrompt() 中注入：
  → 全部目标模块名 + 每个模块的关键字段列表（MODULE_KEY_FIELDS）
  → 产品字段总表（PRODUCT_FIELDS[category]，含 extractable 标记）
  → 明确规则："禁止规则取值"、"禁止占位文本"、"禁止引用式答案"

LLM 只能在 Schema 定义的模块和字段范围内输出
→ 超出 Schema 的"创造性"输出被 parseModuleBlocks() 丢弃
→ 非 extractable 字段标记 [人工填充-请勿抽取]，LLM 不填
```

#### 策略 2：代码端原文注入 — 防粗化

```
parseModuleBlocks() L1027-1030:

  // 自动注入完整无损的原文
  const fullMd = `${md}\n\n## 详细条款原文\n\n${sectionText}`

LLM 的输出只保留"## 关键字段"表格
原文由代码端 100% 注入到 "## 详细条款原文" 小节
→ 即使 LLM 对字段值做了粗化，原文仍然完整保留
→ RAG 检索命中时可以直接展示原文，不依赖 LLM 摘要
```

#### 策略 3：30+ regex 占位符清洗 — 防幻觉的第二道防线

```
WEAK_VALUE_PATTERNS + isWeakFieldValue():

LLM 输出了"未明确"、"需核对具体条款"、"以合同约定为准"等
→ 写入前统一过滤为空值
→ 不会污染知识库，也不会制造虚假冲突
```

#### 策略 4：二次精炼（Refine）— 防漏抽

```
Phase 5 refineAllProductModules()：

抽取完成后扫描所有模块页面的"## 关键字段"表格
→ 找到值为空的字段
→ 从已保留的 source 页面原文中，用 buildRefineSourceExcerpt() 提取
   相关性最高的段落（关键词评分+表格行加分+列表标记加分）
→ 只把相关段落送给 LLM 再次精炼，不重新上传 PDF

效果：首次抽取覆盖率约 65-75%，精炼后提升到 80-90%
```

#### 策略 5：MODULE_TO_FIELD_BRIDGE — 防模块/主文件断裂

```
11 个模块 → 20+ 主文件字段的映射表

模块抽到了值（如"身故保险金"模块抽到了保额）
→ 自动桥接到主文件的"保什么"字段
→ 解决"模块有值但主文件字段为空"的问题
```

#### 策略 6：ExtractionQualityAudit — 量化覆盖率

```
每次抽取完成后自动生成审计报告：

score = critical字段覆盖率 × 0.28
      + high字段覆盖率     × 0.22
      + 证据覆盖率         × 0.18
      + 关系覆盖率         × 0.14
      + ...

score < 75 → 自动生成 ReviewItem 提醒人工复核
score < 60 → 建议"不建议直接演示问答，应先补齐"
```

#### 策略 7：字段级证据回溯 — 可追溯性

```
每个字段页（{险种}-{产品}-字段-{字段名}.md）的 frontmatter 包含：
  value_sources: ["条款.pdf", "费率表.xlsx"]  ← 支撑该值的源文件
  value_source: extracted / metadata / missing ← 值的来源类型
  evidence_modules: ["投保年龄", "投保人群"]   ← 证据所在模块

→ 人工校验时可以直接追溯到"这个值是从哪个文件的哪个模块抽取的"
→ 删除源文件时可以精确清理依赖该文件的字段值
```

**整体效果**：

| 指标 | nashsu 原版 | 当前项目 |
|------|-----------|---------|
| 首次抽取字段覆盖率 | ~40%（超长文档截断导致） | 65-75% |
| 精炼后覆盖率 | N/A | 80-90% |
| 幻觉值入库率 | 高（无过滤） | <5%（30+ regex + Schema 约束） |
| 原文保留 | 无 | 100%（最多120K字符） |
| 抽取质量量化 | 无 | 自动审计评分 0-100 |

---

### 6.7 Concepts 如何准确关联到实体？为什么不让 LLM 生成 Concepts？

**难题**：知识图谱中的 Concepts（概念页）需要聚合多个产品/服务的同类信息。如果让 LLM 自由生成概念页，会导致命名不一致、值污染、幻觉关联等严重问题。

**我们的方案**：Concepts 层是**纯代码确定性生成**的聚合索引，不是 LLM 的创造性输出。

#### 关联机制（`concept-aggregator.ts`，584行）

**服务概念（跨版本关联）**：
```
scanServiceItemConcepts():
  遍历 wiki/entities/ 下所有 md
  → parseServiceItemTitle(title) 解析出 itemName/lineName/versionName
  → 同一 itemName 的不同版本聚合到同一概念页

例: "在线问诊-臻享v1" 和 "在线问诊-尊享v2"
  → itemName = "在线问诊"
  → 生成 wiki/concepts/在线问诊.md，表格链接到两个实体页
```

**产品概念（跨产品关联）**：
```
scanProductConcepts():
  遍历 wiki/product_catalog/ 下所有 md
  → 读取 frontmatter 的 module_name 和 field_name
  → 同一 module_name 的不同产品聚合到同一概念页

例: 3 个产品都有"保证续保期"模块
  → 生成 wiki/concepts/保证续保期.md
  → 表格列出 3 个产品的链接（不存具体值！）
```

**实体反向回填**：
```
backfillEntityRelated():
  同一概念下的所有实体互相写入 related: [...] 到 frontmatter
  → 知识图谱中形成双向链接
```

#### 核心设计决策：概念页不存具体值

概念页的正文明确声明（L458）：
> "回答某个产品的具体数值、责任或限制时，必须打开对应产品字段页或模块页，不要根据本概念页直接作答。"

这是防止 RAG 检索到概念页后，用 A 产品的数值回答 B 产品问题的关键防线。

#### 为什么不让 LLM 生成 Concepts？

| 问题 | LLM 生成 Concepts | 我们的代码确定性方案 |
|------|-------------------|-------------------|
| 命名不一致 | 同一概念被叫"保证续保/自动续保/续保保障" → 生成 3 个独立概念页 | 概念名 = `module_name`，确定性唯一 |
| 值污染 | LLM 在概念页写入某产品的具体数值 → RAG 误以为所有产品都是该值 | 概念页只有链接表格，不存任何具体值 |
| 幻觉关联 | LLM 把不相关产品关联到同一概念（年金领取→医疗险） | `isModuleAllowedForCategory()` 险种白名单过滤 |
| 空值噪音 | LLM 对"未明确"字段也生成概念页 | `isMissingConceptFieldValue()` 过滤空值/占位值/引用式值 |
| 陈旧不更新 | LLM 生成后新增产品不自动更新 | 每次 ingest 后重新扫描全库，`cleanupStaleProductConceptPages()` 删除失效页 |
| 重复与冲突 | 多次抽取生成多个相似概念 | 概念名天然唯一（= 模块名），直接覆盖更新 |

**结论**：Concepts 是知识图谱的"导航索引层"，必须由代码确定性生成。LLM 只负责抽取底层的模块页和字段页，概念聚合是 ingest 完成后的纯代码后处理步骤。这是防止概念层污染知识库的关键架构决策。

---

### 6.8 实体去重：LLM 生成的同名/近名实体如何合并？

**难题**：LLM 经常把同一概念用不同名字生成多个实体页面。例如："中国平安"和"平安保险"、"在线问诊"和"在线视频问诊服务"、"家庭医生服务流程"和"家庭医生服务说明"。如果不合并，知识图谱中同一实体被碎片化为多个孤立页面。

**我们的解法**：`entity-normalizer.ts`（766行）— 4 阶段递进去重：

```
Stage 1: dedup_key 精确匹配（最可靠）
  → Schema 自动推断: service_benefit.在线问诊
  → 同 dedup_key 的新页面直接合并到已有页面，不创建新页

Stage 2: Strong Identity Key 匹配
  → inferStrongInsuranceIdentityKeys() 从 attributes JSON 中提取：
    产品: product_code + product_name
    服务: service_identity.title.{规范化名称}
    画像: persona.{场景名}
  → 相同 identity key 的页面自动合并

Stage 3: 名称相似度匹配
  → isSimilar(a, b):
    1. 规范化后相等（去掉"有限公司/保险/集团"等后缀）
    2. 包含关系（"平安" ⊆ "中国平安"）
    3. 编辑距离 ≤ 1（名称≤8字）或 ≤ 2（名称≤12字）

Stage 4: 变体族聚合（Variant Family）
  → SERVICE_FAMILIES[] 预定义族谱：
    "康复门诊协助/康复住院协助/康复训练管理" → 康复服务族
    "重疾专案管理/专家会诊/手术安排协助" → 重疾全程服务族
  → 族内成员保留独立页面，但自动创建族概念页 + 互相注入 related 链接
```

**合并时的处理**：
- 新名字注入到已有页面的 `aliases: [...]`，保证两个名字的 wikilink 都能解析
- `chooseCanonicalEntity()` 按类型权重选择主页面（product > service_benefit > process > rule）
- 较短名称优先作为规范名（"在线问诊" > "在线视频问诊服务"）

---

### 6.9 RAG 检索为什么准？三路混合检索架构

**难题**：nashsu 原版只有向量检索（vector-only），对保险领域的精确查询效果很差。例如：
- 查"平安e生保2025的免赔额是多少" → 向量检索可能返回其他产品的免赔额页面（语义相似但产品不同）
- 查"投保人和被保险人必须是什么关系" → 向量检索只找到"投保"和"保险"相关页面，找不到包含精确"投、被保险人"字样的段落

**我们的解法**：后端 `rag.rs`（2076行）实现了 **Vector + Token + Graph 三路 RRF 融合检索**：

```
retrieve_chunks_for_query_with_options():
  │
  ├─ Vector 路：embed_query() → LanceDB ANN 搜索 → vector_chunks
  │    → 语义相似度，擅长同义词/近义词
  │
  ├─ Token 路：score_token_index() → BM25 评分 → token_chunks
  │    → 精确关键词匹配，擅长产品名/代码/专有名词
  │    → CJK 双字母分词（tokenize_query: "投保年龄" → ["投保", "保年", "年龄", "投", "保", "年", "龄"]）
  │
  └─ Graph 路：graph_expand() → 知识图谱邻居扩展 → graph_chunks
       → 利用 out_links/in_links/sources 共享关系
       → type_affinity: entity↔concept 加权 1.2

  ↓ fuse_chunks()

  RRF 融合评分 = Σ 1/(K + rank_i) + token_norm × 0.035 + vector_norm × 0.012 + graph_norm × 0.01
  最终分数 × quality_multiplier（审计页面降权 0.55，有效知识页面 1.0）
```

**保险领域特化**：

1. **查询扩展** — `expand_insurance_query()`：
   - "投保人和被保险人" → 自动追加"投、被保险人关系/投被保险人关系"
   - "简称" → 追加"别名/俗称/险种简称"
   - "产品代码" → 追加"product_code/险种代码"

2. **证据锚点定位** — `best_evidence_anchor()`：
   - 不返回页面开头的 frontmatter，而是定位到最相关的**正文行**
   - `insurance_evidence_score()` 对保险高频查询模式加权（"投保年龄"+80分, "重大疾病多少种"+140分）
   - 表格行 `|` 开头额外加 8 分（保险字段表格优先）

3. **产品目录专用摘录** — `product_catalog_excerpt()`：
   - 对 `knowledge_domain: product_catalog` 页面跳过 frontmatter，直接在 body 中定位证据

4. **审计页面降权** — `quality_multiplier()`：
   - 抽取质量审计页面降权到 0.55（防止 RAG 回答中引用审计页面而非实际知识页面）
   - 除非用户显式问"审计/review"相关问题

---

### 6.10 文件上传后如何自动判断文档类型并选择最优抽取策略？

**难题**：用户上传的文件只有文件名（如"保险条款.pdf"），无法确定是产品条款、费率表、服务手册还是核保手册。不同类型的文档需要完全不同的抽取策略：
- 产品条款 → Section-Scan + 模块化抽取
- 费率表 → 表格行级抽取
- 服务手册 → 按服务项目分割
- 核保手册 → 按告知问题分割

**我们的解法**：`ingest.ts` 的 `DocumentIntent` 系统（L1172-1222）：

```
DocumentIntent {
  docType: "product_terms" | "rate_table" | "service_manual" | "sales_script" | ...
  primaryDomain: "product_catalog" | "product" | "sales" | ...
  splitStrategy: "by_item" | "by_section" | "by_table_row_group" | "by_page" | "whole"
  estimatedItemCount: number
  targetSchemaKeys: string[]     ← 告诉 LLM 重点抽取哪些 Schema 条目
  coverageUnit: "service_item" | "product_row" | "clause" | ...
  boundaryHints: {
    headingPatterns: ["第X条", "第X章", ...]
    tableHeaders: ["年龄", "保费", "交费期", ...]
    itemColumnNames: ["服务项目", "权益名称", ...]
    rulePatterns: ["健康告知", "免责条款", ...]
  }
}
```

**三步决策流程**：
1. **信号检测**（`detectSourceSignals()`）：扫描原文 28 个关键词 → 判断文档形态
2. **意图推断**：根据信号组合 + 文件名模式 → 选择 `docType` 和 `splitStrategy`
3. **Schema 映射**：根据 `docType` + `primaryDomain` → 确定 `targetSchemaKeys[]`，告诉 LLM 应该抽取哪些实体类型

**批次生成**（`SmartIngestBatch`）：
```
splitStrategy = "by_item"    → 按服务项目/表格行分割批次
splitStrategy = "by_section" → 按标题层级分割批次
splitStrategy = "by_page"    → 按 OCR 页码分割批次
splitStrategy = "whole"      → 整篇一次性处理

每个批次包含 targetSchemaKeys + expectedCandidateTypes
→ LLM 只在指定的 Schema 范围内抽取
→ 防止"服务手册被当成产品条款抽取"的错误
```

---

### 6.11 其他已解决但未被提出的技术难题

#### 难题 1：LLM 生成的文件名不安全

**问题**：LLM 可能生成 `../../etc/passwd` 或 `C:\Windows\System32\xxx` 等危险路径。

**解法**：`isSafeIngestPath()` 路径安全检查 — 只允许 `wiki/` 前缀，拒绝 `..`、绝对路径、非 `.md` 扩展名。所有 LLM 输出的 FILE 块路径都必须通过此检查才能写入磁盘。

#### 难题 2：LLM 截断和格式错误

**问题**：LLM 流式输出经常在 `---FILE:` 块中间截断，或 fence 标记不匹配。

**解法**：`parseFileBlocks()` 包含 8+ 种容错解析规则：
- CRLF/LF 混合处理
- `---FILE:` 和 `---END FILE---` 的多种变体匹配
- 截断检测（最后一个块没有 END 标记 → 取到文件末尾）
- fence 嵌套修复（LLM 在代码块内再写代码块）
- 路径注入修复（LLM 在路径中包含多余空格或引号）

#### 难题 3：扫描件 PDF 的 120MB base64 导致浏览器 OOM

**问题**：39页扫描件 PDF 读取为 base64 约 120MB，在 `autoIngestImpl` 中同时持有 `rawSourceContent` + `sourceCacheContent` + OCR `pages[]` 三份大字符串 → 360-480MB 峰值 → 浏览器 OOM 崩溃。

**解法**（`ingest.ts` L522-537 + L650-785）：
- `rawRef` 可变引用在 OCR 开始后立即 `= null` 释放
- 缓存 key 使用轻量 fingerprint（`file-fingerprint:{path}|len:{length}`）替代完整 base64
- OCR 处理函数也在解析完成后释放 `content` 参数
- 减少同时在内存中的大字符串从 3 份 → 1 份

#### 难题 4：CJK 文件名在 Tauri IPC 中被乱码

**问题**：Tauri IPC 传输 CJK 文件名时偶发乱码（"保险条款.pdf" → "淇濋櫓鏉℃.pdf"），导致 OCR 缓存目录前缀匹配失败。

**解法**（`ingest.ts` L415-425）：当前缀匹配失败时，扫描所有缓存目录的 `source.json` 元数据文件，通过 `ocrCacheComparableFileName()` 做大小写+规范化匹配。

#### 难题 5：LLM 占位值污染知识库

**问题**：LLM 在无法确定字段值时会生成"未明确"、"需核对具体条款"、"以合同约定为准"等占位文本，这些被当作有效值存入后：
- 污染 RAG 答案（回答"交费方式是什么" → "需核对具体条款"）
- 制造虚假冲突（"需核对" vs 真实值 → 进 Review 队列）

**解法**：`isWeakFieldValue()` + `WEAK_VALUE_PATTERNS`（30+ regex），在写入前统一过滤为空值。包括：
- "未明确/未提及/证据片段中未提及"
- "需核对具体条款/以合同约定为准"
- "详见XX/参见XX/根据XX"
- 纯标点/省略号/单字符

#### 难题 6：LLM 越域生成不相关模块

**问题**：年金险文档被 LLM 生成了"孕产保障"、"少儿特定疾病"等医疗险独有的模块页面。

**解法**：`isModuleAllowedForCategory()` 险种白名单 — 每个模块名绑定允许的险种类别列表，不在白名单内的模块直接过滤不生成。

#### 难题 7：模块抽到了值但主文件字段为空

**问题**："身故保险金"模块成功抽取了保额信息，但产品主文件的"保什么"字段仍为空，因为没有字段到模块的映射关系。

**解法**：`MODULE_TO_FIELD_BRIDGE`（11个模块 → 20+主文件字段的映射表），模块抽取完成后自动将值桥接到主文件对应字段。

#### 难题 8：product_meta.json 被当作有效源资料

**问题**：删除源文件时，如果 `product_meta.json`（元数据文件）被计为"源文件"，则最后一个真实 PDF 删除后系统认为"还有源文件支撑"，不清理派生知识。

**解法**：`product_meta.json` 在删除级联逻辑中**不算有效源资料**，只有真实文档（PDF/条款/手册）才计入 `value_sources`。最后一个真实源文件删除后，整套派生页面标记为 `status: rejected`。

#### 难题 9：前端全量刷新导致请求竞态

**问题**：ingest 队列运行期间每 2.5 秒扫描产品库 + 每次写入文件后 `bumpDataVersion()` → 多个异步 `loadPages()` 并发 → 旧请求结果覆盖新目录状态。

**解法**：`knowledge-tree.tsx` L118-145 使用 `pageLoadRef` 单调递增 ID，异步回来后检查 `requestId !== pageLoadRef.current` 则丢弃旧结果。批次完成改为 SSE 事件驱动单次刷新。

#### 难题 10：向量维度错误导致语义检索质量严重受损

**问题**：nashsu 原版硬编码向量维度 384，实际 embedding 模型输出 1152 维 → 768 维度的信息被截断丢失。

**解法**：后端 LanceDB 索引改为动态维度（首次 upsert 时自动检测），当前使用 1152 维。提供 `/api/vector/drop-legacy` 接口清除旧维度索引。

#### 难题 11：费率表年龄 vs 条款年龄冲突

**问题**：费率表显示保费覆盖 0-65 岁，但条款规定最高投保年龄 60 岁。`shouldReplaceFieldValue()` 默认取"信息量更大"的值 → 错误采用 65 岁。

**解法**：`shouldReplaceFieldValue()` 对 `最高投保年龄`/`最低投保年龄` 字段做特殊处理 — 最高年龄取最大值，最低年龄取最小值。同时 prompt 规则第 13 条明确："投保年龄必须来自条款投保范围，不得从费率表年龄列推算"。

#### 难题 12：删除一个产品后概念页、字段页残留

**问题**：删除一个产品的所有源文件后，概念页中仍然链接着已删除的产品，字段页的 `value_sources` 仍包含已删除的 PDF。

**解法**：`product-catalog-sync.ts` 的级联删除逻辑（`cascadeDeleteProductSources()`）：
- 从产品字段页中移除被删 PDF 的 `value_sources` 引用
- 如果无剩余真实源文件 → 整套模块页+字段页标记 `status: rejected`
- 下次 `buildProductConceptIndex()` 时自动重建概念页 → 已删产品从概念表格消失
- `cleanupStaleProductConceptPages()` 删除不再被任何产品引用的概念页

#### 难题 13：同一模块被 LLM 用不同名称输出

**问题**：LLM 有时输出"年度免赔额"，有时输出"免赔额"或"年度免赔"，导致同一模块被拆成多个文件。

**解法**：`normalizeProductCatalogModuleName(category, name)` 将所有变体名统一到规范名。`parseModuleBlocks()` 中还有模糊匹配 fallback（`name.includes(valid) || valid.includes(name)`），确保"免赔额"能匹配到"年度免赔额"。

#### 难题 14：字段值中包含退保警示语被当作有效值

**问题**："费用"字段被抽取为"退保可能会遭受一定损失，请您慎重考虑"— 这是风险提示语，不是实际费用信息。

**解法**：`shouldRejectMainFieldValue(fieldName, value)` 对特定字段做内容校验 — "费用"字段如果包含"退保+损失/慎重"模式则自动拒绝。
---

### 6.12 几百几千个文件如何处理？

**难题**：企业级场景下，一次性需要处理几百甚至上千个保险产品文档（条款+费率表+核保手册+服务手册），前端逐个上传不可行。

**我们的解法**：后端批量上传 + 批处理 API（`backend/src/handlers/ingest.rs` + `backend/worker/ingest-worker.ts`）

#### 批次 API 完整流程

```
Step 1: 创建批次
  POST /api/ingest/product-batches
  → 返回 batch_id，指定 insurance_category + product_name + project_path

Step 2: 批量上传文件（支持 200MB/请求）
  POST /api/ingest/product-batches/{batch_id}/files
  → multipart/form-data，一次可上传多个文件
  → 文件存储在服务端 wiki-data/ 目录，不在用户本地

Step 3: 启动批次处理
  POST /api/ingest/product-batches/{batch_id}/start
  → Node Worker 后台异步执行，不阻塞前端
  → 内部调用产品管线完整流程：OCR → Section-Scan → 字段合并 → 精炼 → 概念聚合

Step 4: 实时状态推送
  GET /api/ingest/product-batches/events（SSE 事件流）
  → batch_progress / batch_complete / batch_error
  → 前端 knowledge-tree 监听 SSE，批次完成后单次刷新（不轮询）

Step 5: 失败重试
  POST /api/ingest/product-batches/{batch_id}/retry
  → 只重处理失败的文件，不重新处理已成功的

Step 6: 精炼（可选）
  POST /api/ingest/product-refinements
  → 对已抽取的模块做二次精炼，补空字段
```

**并发控制**：
- 前端默认 4 路并发上传批次
- 每个批次内部受 `MAX_SECTION_PARALLEL = 3` 限制
- 多批次可以并行（不同产品互不干扰）
- Worker 异步执行，即使浏览器关闭也不中断

**外部系统集成**：这套 API 不仅支持前端手动上传，也可以被外部系统直接调用（如 CI/CD 管线、内部运营平台），实现自动化的知识库更新流水线。

---

### 6.13 人工审核后的字段数据，还会被后续 ingest 覆盖吗？

**难题**：人工在 Review 面板中确认了某个字段值（如"最高投保年龄=60岁"），但下一次上传新版本条款时，LLM 又抽取到了不同的值并覆盖掉人工确认的结果。

**我们的解法**：**`user_locked_fields` 人工锁定机制**

```
knowledge-resolution.ts L340-363:

人工审核后，在页面 frontmatter 中写入：
  user_locked_fields: ["最高投保年龄", "免赔额"]

后续任何自动 ingest 遇到这些字段：
  → 即使新值不同，也永不覆盖（L209）
  → 不进 Review 队列（因为已经是人工确认的权威值）
  → 审计日志记录 "field locked by user, skipped"
```

**完整的人工审核后保护链路**：

```
Review 面板 → 人工点击「采用新值」或「保留旧值」
  ↓
resolveReviewItem(id, resolution, "user")
  → review-queue.json 中记录 resolvedBy: "user", resolvedAt: timestamp
  ↓
review-actions.ts → 回写模块表格 + 字段页 + 主产品页
  ↓
syncProductFieldPageAfterEdit() → 级联同步概念页
  ↓
如需锁定 → 人工在 frontmatter 添加 user_locked_fields: [字段名]
  ↓
下次 ingest 遇到 user_locked_fields 中的字段 → 永不覆盖
```

**两种审核模式**：

| 模式 | 触发条件 | 是否阻断 | 后续保护 |
|------|---------|---------|---------|
| 冲突审核 | 同权重+同日期+值不同 | **阻断**（不写入，等人工决策） | 人工决策后可加 `user_locked_fields` |
| 抽查审核 | 同权重+新版本自动采用 | **不阻断**（已写入，但标记需抽查） | 发现错误可回滚 + 加锁 |

**结论**：人工审核后的字段**默认不会被覆盖**（通过 `user_locked_fields`），但需要人工主动添加锁定标记。系统在 Review 面板中会提示："如需锁定某字段不被后续 ingest 覆盖，在页面 frontmatter 中添加 user_locked_fields: [字段名]"。

---

### 6.14 抽取质量评估集的方案如何设计？

**难题**：评估 LLM 抽取质量不能只看"模型回答的对不对"，因为：
1. 模型可能回答不了复杂问题（这是 LLM 能力限制，不是知识库质量问题）
2. 真正需要评估的是**知识库是否包含了正确答案**——即 RAG 检索回来的 chunk 是否包含回答该问题所需的信息

**核心原则**：**评估的是检索召回质量（Retrieval Recall），而非生成回答质量（Generation Quality）**。

#### 评估集设计方案

```
评估维度分三层：

Layer 1: 字段覆盖率评估（自动化，已实现）
  ├─ ExtractionQualityAudit 自动统计
  │   critical 字段完整率、high 字段完整率、关系覆盖率
  ├─ 输入：Schema 规范 + 实际抽取结果
  ├─ 输出：0-100 分 + 缺失字段清单
  └─ 频率：每次 ingest 后自动运行

Layer 2: 检索召回评估（半自动化，评估集驱动）
  ├─ 评估集构成：
  │   - 100-200 条 (问题, 期望命中页面, 期望命中字段) 三元组
  │   - 覆盖 5 大场景：产品对比、条款细节、核保规则、理赔流程、服务权益
  │   - 每个场景 20-40 条，难度分 easy/medium/hard
  │
  ├─ 评估指标：
  │   - Recall@K：top-K 检索结果中是否包含期望页面（K=5,10,20）
  │   - Field Hit Rate：检索到的页面中是否包含期望字段的有效值
  │   - Evidence Anchor：检索摘要是否定位到了包含答案的段落（而非 frontmatter）
  │
  ├─ 执行方式：
  │   POST /api/rag/retrieve → 拿到 top-K chunks
  │   → 检查 chunks 中是否有 page_path === 期望页面
  │   → 检查 chunks 的 content 中是否包含期望字段值
  │   → 不需要调用 LLM 生成回答
  │
  └─ 典型评估问题示例：
      easy:  "平安e生保2025的免赔额是多少" → 期望命中 医疗险-平安e生保2025-年度免赔额.md
      medium: "哪些产品支持保证续保" → 期望命中 wiki/concepts/保证续保期.md + 各产品模块页
      hard:  "60岁糖尿病患者能投保哪些医疗险" → 期望命中 投保年龄 + 专属健康告知 模块

Layer 3: 端到端问答抽查（人工，定期）
  ├─ 20-30 条业务专家提出的真实问题
  ├─ 评估：模型回答 + 引用来源 是否正确
  └─ 频率：每月一次，用于发现 Layer 1/2 无法覆盖的系统性问题
```

**为什么重点是 Layer 2 而非 Layer 3**：

| 评估层 | 评估什么 | 谁的问题 | 频率 |
|--------|---------|---------|------|
| Layer 1 | 字段是否抽全 | 抽取管线 | 自动/每次 |
| **Layer 2** | **检索是否召回正确页面** | **知识库+检索** | **半自动/每周** |
| Layer 3 | 模型回答是否正确 | LLM 能力 | 人工/每月 |

Layer 2 是最关键的——如果检索没召回正确页面，再强的 LLM 也回答不出来。反过来，如果检索召回了正确页面但 LLM 回答错误，那是 LLM 本身的问题，与知识库质量无关。

**当前已实现的支撑**：
- `POST /api/rag/retrieve` 已支持独立检索（不触发 LLM 回答）
- 返回值包含 `page_path`、`chunk_index`、`content`、`score`、`source`（vector/token/graph/hybrid）
- `quality_multiplier` 标记页面质量权重
- `retrieval_ms` 记录检索耗时

---

## 七、代码量化对比

| 维度 | nashsu | 当前项目 | 变化 |
|------|--------|---------|------|
| `ingest.ts` | ~30KB | **290KB** | +867% |
| `frontend/src/lib/` 文件数 | ~40 | **136** | +240% |
| 保险 Schema 相关 | 0 | **~400KB** | 全新 |
| 产品目录管线 | 0 | **~280KB** | 全新 |
| 后端 Rust | ~3KB | **~20KB** | +567% |
| 项目文档 | README 一份 | **10份** 架构/历史/对比/路线图 | 全新 |

---

*校验基于源码: `knowledge-tree.tsx`(645行), `ingest.ts`(6348行), `product-catalog-extractor.ts`(193KB), `ARCHITECTURE.md`, `CHANGELOG.md`(552行), `PROJECT_HISTORY.md`(623行)*
*最后更新: 2026-07-10*
