# QA1 · 问答来源标注与范围说明：原文片段标产品，"没搜到"不等于"没有"

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
> 依据：
> - #286 复测 r2 的剩余错误 J006、J007、J056、J057，以及 2026-10-26 的根因分析：
>   - 原文片段不标所属产品；
>   - 字面搜索的结果被当成完整清单；
>   - Agent 工具里的 `unknown` 没有说明；
> - 用户 2026-10-26 批准修复第 1–3 项。第 4 项（按产品限定检索）要先做消融，第 5 项（C 方式自动查原文）暂不做。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0 ｜ 数据库迁移：无 ｜ 在 RV6b（#367）合并后开工（Go 平台同一时间只有一个实现切片）

## 1. 目标

问答（快问快答 E、wiki 库 Agent C、混合 Agent D）不再犯以下三类错误：

1. **把一个产品的原文当成另一个产品的规定**（J056、J057）。原文检索覆盖本轮固定的全部材料，几乎每个产品的条款文件都叫"保险条款.pdf"，模型分不清片段属于哪个产品。
2. **把"字面搜索没命中"当成"产品没有"**（J006）。`knowledge_search_fields` 是字面匹配，最多显示 20 条，不告诉模型一共命中多少，也不能按产品筛选。
3. **把"已发布知识未收录"当成"材料没有"**（J007）。Agent 工具把三态直接显示成英文 `unknown`，提示语里也没有"说没有必须有依据"的规则。

三处修复都是通用机制：
- 产品名来自发布版本里的实体与出处，Go 代码不出现任何险种词；
- 不针对具体题目或产品。

## 2. 修复 1：原文片段标出所属产品

### 2.1 材料与实体的对应

**新增（冻结）**：

```go
// SourceEntities maps each material cited by a claim or wiki page of the release (the knowledge
// ID of a source:v1 reference, parsed by release.ParseSourceRef) to the display names of the
// entities citing it, in navigation order, without duplicates. Malformed references are skipped.
func (s *Service) SourceEntities(ctx context.Context, tenantID uint64, spaceID, releaseID string) (map[string][]string, error)
```

- 位置：`internal/enterprise/knowledge`；
- 认哪些成员：
  - Claim 按 `subject_ref`；
  - wiki 页面按它的**全部** `entity_refs`，只算发布版本中存在的实体，不只算页面 slug 里的那一个。这只影响来源对应，页面搜索的单产品过滤规则不变；
- 显示名取实体的第一个名称，与字段标题中的名称一致；
- 先按导航顺序排列，再按**显示名**去重：两个实体同名时，名称只出现一次。

> 2026-10-27 修订（#371 审核 R2、R5）：补上页面的全部 `entity_refs`，以及按显示名去重。

### 2.2 本轮的标注表

**`chatsource.Turn` 新增字段（冻结）**：`RawEntities map[string][]string`，键是原文材料的 knowledge ID，值是引用它的实体名称。

- **何时填写**：解析器配置了已发布知识服务（`WithPublished`）时：
  - `Resolve` 结束后，以及快问快答自动补原文（`addAnswerRaw`）之后，为 `RawKnowledge` 中的**每一份**材料各写一项；
  - 每个 Space 只读一次 `SourceEntities`；
  - 没有任何实体引用的材料，值为空列表。
- **读取失败**：该 Space 的材料全部按"未识别"处理，即值为空列表。本轮不因此失败，因为标注是辅助信息，读不到时明确标"未识别"，比让整轮失败更安全。
- **未配置已发布知识服务时**：`RawEntities` 为 nil，一切与现在相同。

### 2.3 标注出现在哪里

`RawEntities` 非 nil 时，下面三处都要标注。名称用"、"连接；没有名称时写"所属产品未识别"。

**外部元数据不可信**：原生检索会把文档自带的 metadata 带进结果，其中可能已经有 `entity_names`，值可能是错的名字或空串。标注只以本轮的标注表为准，不读取、不信任结果自带的 `entity_names`。

1. **`Turn.Label`**（快问快答与检索管线）：
   - **元数据**：每一遍都按本轮标注表重写原文结果的 `Metadata["entity_names"]`，即名称串，未识别时为空串。外部预置的值一律替换，包括空串。未配置时（`RawEntities` 为 nil），删除外部带来的 `entity_names`。
   - **标题**：`KnowledgeTitle` 设为"名称串 · 原标题"或"所属产品未识别 · 原标题"。
   - **幂等靠本轮自己的记录**：
     - 同一个结果可能出现在 SearchResult、RerankResult、MergeResult 三个列表中，管线也会跑两遍；
     - 检索管线会复制结果，所以不能靠指针判断，更不能靠元数据键判断；
     - 做法：本轮第一次见到某个原文结果（按材料 ID 加片段 ID 识别）时，记下它当时的标题；之后每一遍都用记下的原标题重新计算，所以前缀只出现一次；
     - 这份记录随本轮的 `Turn` 一起存在（由解析器在填写标注表时建立），不进入结果本身。
2. **`WrapTool`**（D 方式 Agent 的原生检索工具）：
   - 保留下来的原文行，`metadata.entity_names` 与 `knowledge_title` 按同样规则改写；
   - 每次执行都从原生行的标题重新计算；
   - 外部的 `entity_names` 同样被替换，未配置时删除；
   - 重新渲染的输出带上这些属性。
3. **`AnswerPassage`**：原文段落第一行的产品名，**取自本轮标注表**（按结果的材料 ID 查），不读结果的元数据：
   - 有名称时："原文检索（未经编译审核）｜所属产品：名称串"；
   - 没有名称时："原文检索（未经编译审核）｜所属产品未识别"；
   - 本轮未配置，或结果不是本轮的原文材料时，保持原样："原文检索（未经编译审核）"。

> 2026-10-27 修订（#371 审核 R1，Owner 裁定）：原文本用"已有 `entity_names` 键就不再加前缀"判断幂等，相当于信任了外部元数据，已删除。

## 3. 修复 2：搜索结果写明范围

1. **按产品筛选**：
   - `knowledge_search_fields` 的参数增加可选的 `entity_id`（字符串，不必填），描述改为："按关键词搜索本轮已发布字段（字面匹配，只搜明确存在的字段值），可用 entity_id 限定产品。"
   - `Service.SearchFields` 的签名改为 `SearchFields(ctx, tenantID, spaceID, releaseID, query, entityID string, limit int) ([]Field, int, error)`（冻结）：
     - `entityID` 为空时搜索所有产品；
     - 产品不存在时返回 `ENTITY_NOT_FOUND`，与 `EntityFields` 一致；
     - 实现方同步修改 `service_test.go` 中的调用。
2. **范围说明**：查询至少有一个词时，结果的 notes 第一条是范围说明（冻结的模板）：
   - **字段搜索**：`检索范围：{范围}已发布字段中明确存在的值，按字面匹配；命中 {total} 条，显示 {shown} 条。没有命中或没有显示的，不代表材料没有；判断某产品有没有某项，用 knowledge_get_fields 读取该产品。`
     - `{范围}`：限定产品时，为按 `EntityFields` 规则（归一化 ID）匹配到的产品显示名加"的"；不限定时为空；
     - `{shown}`：本次返回的字段数。
   - **页面搜索**：`检索范围：{范围}延伸阅读页面，每个词都须字面出现；命中 {total} 页，显示 {shown} 页。没有命中不代表材料没有。`
     - 页面按产品 ID **精确**过滤，规则不变。`{范围}` 必须如实对应这个过滤：请求的 ID 与某个产品 ID 完全相同时，用该产品显示名加"的"；否则用请求的 ID 本身加"的"（如"b的"）。不能用归一化后匹配到的另一个产品的名字。

> 2026-10-27 修订（#371 审核 R3）：页面范围说明与页面的精确 ID 过滤保持一致。
   - **送达方式**：notes 已有的渲染路径会把说明送到模型。有结果时写在第一行的 `knowledge_metadata` 里，没有结果时写在输出文本里。所以命中为 0 时，模型也能看到这条说明。查询为空时行为不变。
3. 页面搜索的匹配规则不变。按产品限定检索属于第 4 项，要先做消融。

## 4. 修复 3："没有"必须有依据

1. **三态改用中文**：`knowledge.FieldText`（Agent 工具、MCP 工具、快问快答共用）对状态的显示改为：

   | 状态 | 显示为 |
   |---|---|
   | `present` | `名称 · 标题：值` |
   | `absent_explicitly` | `名称 · 标题：材料明确没有` |
   | `unknown` | `名称 · 标题：已发布知识未收录（不代表材料没有）` |
   | 其他值 | 原样 |

   这与快问快答现在的 `answerFieldText` 完全相同。`answerFieldText` 随之删除，快问快答直接用 `FieldText`。MCP 与 Agent 工具的输出继续保持一致（等价测试不变）。
2. **`KnowledgeNotice` 的新文本**（冻结）：
   - 第一部分（只有 wiki 时）：
     > 已发布知识优先：先用 knowledge_find_entity、knowledge_get_fields、knowledge_search_fields、knowledge_get_concept 查询本轮固定发布版本。回答产品事实时引用当前工具返回的字段句柄。只有字段为“材料明确没有”时，才能说该产品没有这项规定；字段为“已发布知识未收录”、搜索没有命中或页面没有结果，都不代表材料没有，只能说已发布知识未收录（不代表材料没有）。要说某个产品没有某项规定，先用 knowledge_get_fields 读取该产品的这一项。没有 Evidence 的内容不标审核过、不制造出处。概念定义、说明和概括是模型补充（概念说明），与已举证的产品字段分开，不把模型补充当审核事实。字段查不到时，可用 knowledge_search_pages 查延伸阅读页面；页面是模型整理（未逐条审核），回答中如实标注，不当作审核过的事实；与字段冲突时以字段为准。
   - 有原文时追加：
     > 已发布知识查不到时可用原文检索补充；原文仅限本轮固定材料，明确标注原文检索（未经编译审核），不能混淆两种来源。原文片段标题前标有所属产品，只能用于该产品；所属产品未识别的片段，不能当作任何具体产品的规定。
   - 最后的引用要求（Q2b）保持不变。

   引号是中文弯引号“”。准确字符以验收测试 `knowledge_notice_edges_test.go` 为准。

## 5. 改动范围

- `internal/enterprise/knowledge/`：
  - `index.go` 或新文件：`SourceEntities`；
  - `fields.go`：`SearchFields` 增加 `entityID`；
  - `tools.go`：参数、描述、范围说明；
  - `tool_result.go`：状态的中文显示、页面结果的 notes；
  - `service_test.go`：改调用签名。
- `internal/enterprise/chatsource/`：
  - `resolver.go`：`Turn.RawEntities`、`Label`；
  - `quick_answer.go`：`addAnswerRaw` 之后补标注表；
  - `tool.go`：原文行的标注；
  - `answer_context.go`：`AnswerPassage`，删除 `answerFieldText`；
  - `published.go`：改用 `FieldText`；
  - `knowledge.go`：提示语。
- 实现方自己的测试。

不涉及：
- 不改 Harness、`contracts/`、前端与上游文件；
- 不改检索排序；
- 不改 C 方式的检索范围。

## 6. 验收（RED，Claude 编写，受保护）

1. **`internal/enterprise/knowledge/scope_notes_test.go`**（合成数据，两个产品）：
   - **J006**："续保"在甲产品命中 22 条，乙产品的宽限期写"重新投保"：
     - 结果说明"命中 23 条，显示 20 条"、"按字面匹配"、"不代表材料没有"、"knowledge_get_fields"；
     - `entity_id` 限定乙产品后，只返回乙的字段，说明写明乙的显示名；
     - 产品不存在时返回 `ENTITY_NOT_FOUND`；
     - 零命中时，送给模型的文本里仍有说明。
   - **J007**：
     - 页面零命中时有"命中 0 页"与"不代表材料没有"；
     - 字段工具对 `unknown`、`absent_explicitly` 显示中文，不出现英文状态词。
   - **`SourceEntities`**：
     - 共用的材料对应两个产品，按导航顺序；
     - 页面的出处也算；
     - 格式不对的出处跳过。
   - **参数**：`knowledge_search_fields` 的 `entity_id` 是可选参数。
2. **`internal/enterprise/chatsource/product_labels_test.go`**（J056、J057）：
   - 两个产品的条款文件都叫"保险条款.pdf"；
   - `Resolve` 后 `RawEntities` 覆盖每份可检索材料，未被引用的材料为空列表；
   - `Label` 加前缀与 `entity_names`，并且幂等；
   - 读取失败时整轮不失败，材料标"未识别"；
   - 未配置已发布知识服务时不变；
   - `WrapTool` 的行与输出带产品名；
   - `AnswerPassage` 的第一行带产品；
   - 提示语含"没有"必须有依据的规则与原文产品规则，Q2b 的引用要求仍在。
3. 以下现有受保护测试**随 RED 提交更新**，理由是本切片有意改变了它们固定的行为：
   - `chatsource/knowledge_notice_edges_test.go`：提示语全文改为 §4.2；
   - `chatsource/answer_context_test.go`：工具文本不再保留英文状态，改为断言 `FieldText` 用中文；`answerFieldText` 被删除；
   - `knowledge/tools_test.go`：渲染结果从 `absent_explicitly` 改为"材料明确没有"。
   - `knowledge/acceptance_test.go`（Q1b）：`SearchFields` 的调用补上空的 `entityID` 参数，只改签名，不改断言。
4. **#371 审核后补充的 RED**（2026-10-27）：
   - **R1**：外部 `entity_names` 为错的名字或空串时，管线跑两遍、三个列表共用同一结果，元数据、标题与 `AnswerPassage` 都以本轮标注为准，前缀只出现一次；
   - **R2**：页面的全部 `entity_refs` 都算来源；
   - **R3**：页面按归一化后才能对上的 ID（如 `b`）筛选时，说明写请求的 ID；
   - **R5**：同名实体只出现一次。
   - 另有一个只调格式的提交，修正 RED 文件的 lint（gofumpt、行长、未使用的赋值），断言不变。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/... ./internal/application/service/... ./internal/modelcontext/...`；
- 守卫；
- 测试文件不超过 500 行。

## 7. 上线后的检查（另行批准）

部署后只重跑 #286 的 4 道题（q16、q21、q22、q23），每题三种方式，共 12 轮，约 40 次模型调用。用确定性规则判断，不需要评委：
- q16 不说"悦享版未见宽限期"，并引用该产品的宽限期字段；
- q21 不下否定结论；
- q23 不把"2 年"归到本品；
- q22 不把其他产品的原文片段当作本品的规定。

这项检查的部署与调用预算另行请用户批准，不在本 Issue 的预算内。
