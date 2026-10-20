# Q1b · 已发布知识问答：按发布版本查产品、字段、概念，作为 Agent 工具，引用标"已发布知识（审核过）"

> 状态：用户 2026-10-19 批准方案 B（见 `Q1-问答接入发布版本.md` §1）｜ 作者：Claude Code
> 拆分：
> - Q1b-1 查询服务与 Agent 工具（本 Spec 主体）；
> - Q1b-2 快问快答的已发布知识检索（§5，另开 Issue）。
> 实现方：Codex ｜ 审核方：Claude ｜ 真实模型调用：不需要（问答实测另开 Issue）

## 1. 目标

在问答中选了企业 Space 的 Wiki 库时（Q1a 的 `Turn.WikiSpaces`），Agent 能按本轮固定的发布版本查到：

- 哪个产品：按名称、别名或编号找；
- 它的某些字段：取值、三态、出处；
- 字段内容里提到某个词的地方；
- 某个跨产品概念的说明。

回答中的引用标"已发布知识（审核过）"，点开时按该版本打开原文出处（与企业知识页同一个出处面板）。原文检索（Q1a）保持不变；两者都选时，系统提示要求先用已发布知识，查不到再用原文检索。

## 2. 查询服务（新包 `internal/enterprise/knowledge`，项目自有）

只读、无状态，所有方法都按"租户 + Space + release_id"读取，**不读 Active**：版本由调用方（Q1a 的 `Turn.Releases`）给出。

接口冻结如下（验收依据）：

```go
type Reader interface { // 生产实现：release.Service.SpaceReadView() 的发布读取（只含 access_scope = "space" 的成员）
	ReleaseByID(ctx context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error)
}
func NewService(reader Reader) *Service

type Evidence struct{ Index int; Quote string; Page int; SourceRef string }
type Field struct {
	ReleaseID, Slug, EntityID, EntityName, FieldKey, FieldTitle, State, Value, Origin, Review string
	Evidence []Evidence
}
type Entity struct{ EntityID, Name string; Names, Labels []string }
type Statement struct{ Text string; Refs []string }
type Concept struct {
	ReleaseID, Key, Title, Definition, Explanation string
	Statements []Statement
}

func (s *Service) FindEntities(ctx context.Context, tenantID uint64, spaceID, releaseID, query string, limit int) ([]Entity, error)
func (s *Service) EntityFields(ctx context.Context, tenantID uint64, spaceID, releaseID, entityID string, fields []string) ([]Field, error)
func (s *Service) SearchFields(ctx context.Context, tenantID uint64, spaceID, releaseID, query string, limit int) ([]Field, int, error)
func (s *Service) Concept(ctx context.Context, tenantID uint64, spaceID, releaseID, keyOrTitle string) (Concept, error)
```

### 2.1 通用规则

- **规范化**：NFKC、转小写、去掉空白。下文的"包含"和"相等"都在规范化之后比较。
- **字段标题**：取该产品所属 profile（`classification_labels` 相交）中的 `short_title`；没有时用谓词。
- **取值**：
  - `Value` 为字符串；
  - 原值是数组时用"；"连接；
  - `absent_explicitly` 与 `unknown` 的 `Value` 为空，`State` 原样给出，让 Agent 能说"材料明确没有"或"材料未提及"。
- **`Review`**：取 Claim 的 `review.mode`，值为 `machine`、`human` 或空。
- **`Evidence`**：按 Claim 中 `evidence` 的顺序编号（`Index` 从 0 起），`Page` 取 `locator.page`，`SourceRef` 取 `source_ref`。
- **错误**：
  - 版本读取失败原样返回；
  - 产品不存在：`*release.Error{Code: "ENTITY_NOT_FOUND"}`；
  - 概念不存在：`*release.Error{Code: "CONCEPT_NOT_FOUND"}`。
- **只读 Space 可见成员**：由 `Reader` 保证；本包不再放宽。

### 2.2 四个方法

1. **`FindEntities`**：
   - 命中条件：`query` 等于 `entity_id`；或被某个名称包含，或包含某个名称；或与某个名称共有至少 2 个相邻两字（字二元组）。
   - 排序：先"相等或包含"，再按共有二元组数从多到少，最后按条目成员顺序。
   - 返回最多 `limit` 个；`limit <= 0` 时取 5。查询为空时返回空结果。
2. **`EntityFields`**：
   - `fields` 为空时，返回该产品的全部 Claim；
   - 否则，每一项按谓词相等或字段标题相等匹配；都不相等时，取标题二元组全部出现在该项中的字段。没匹配上的项忽略，不报错。
   - 顺序：profile 字段顺序，不在 profile 中的按成员顺序排在后面。
3. **`SearchFields`**：
   - 与 S3h-1 相同：只搜 `present`；查询按空白拆成词，每个词都要出现在标题或取值中；产品按导航顺序，同一产品内按 profile 字段顺序。
   - 返回最多 `limit` 条（`limit <= 0` 时取 20）及命中总数。
4. **`Concept`**：
   - 按 `concept_key` 相等或 `title` 相等查找；
   - 返回定义、说明与带引用的陈述；`Refs` 是 Claim 的 `logical_slug`。

## 3. Agent 工具（Q1b-1）

- **注册时机**：本轮 `Turn.WikiSpaces` 非空时，注册 4 个项目自有工具：
  - `knowledge_find_entity(query)`；
  - `knowledge_get_fields(entity_id, fields[])`；
  - `knowledge_search_fields(query)`；
  - `knowledge_get_concept(name)`。
  - 一轮选了多个 Space 时，工具参数里加 `space_id`；只有一个 Space 时可省略。
  - 所有调用都用 `Turn.Releases[space]`，不读 Active。
- **结果格式**：
  - 给模型的文本：每个字段写"产品 · 字段：状态、取值"，以及出处的引文与页码；
  - 每个字段同时给一条可引用的结构化结果（`display_type: "search_results"`）：
    - `chunk_id` 为 `release:<release_id>:<logical_slug>`；
    - `metadata` 包含 `source_tier = "release"`、`space_id`、`release_id`、`logical_slug`、`evidence_index = 0`；
  - 模型引用它们的方式与 chunk 相同。
- **系统提示**：
  - 选了 Wiki 库时，替换 Q1a 的"已发布知识尚不可用"，改为说明：
    - 已发布知识优先；
    - 回答产品事实时引用字段结果；
    - 查不到或状态为"未知"时如实说明；
  - 同时选了原始材料库时，可以再用原文检索补充，并说明来源不同。
- **工具策略**：在 `modelcontext/tool_policy.go` 中为这 4 个工具登记可引用结果（上游文件，登记补丁）。
- **不变**：原文检索、普通知识库、其他工具的行为不变；Q1a 的轮次过滤只作用于原文结果。

### 3.1 实现口径（2026-10-19 按 #250 计划 1–6 确认）

1. **工具提供方式**：这 4 个工具是"选了 Wiki 库后派生出的只读来源能力"，按本 Spec 动态提供，不要求用户在 Agent 的工具白名单里勾选；其他工具的白名单规则不变。
2. **Q1a 的旧测试**：
   - `agent_chatsource_test.go` 中的 `TestQ1aAgentWikiOnlyRegistersNoRetrievalTools`，与 `chatsource/context_test.go` 中依赖"已发布知识尚不可用"提示的用例，描述的是 Q1b 之前的行为；
   - 允许实现方在**单独一个提交**里改为 Q1b 的新行为（只选 Wiki 库时注册 4 个知识工具；提示改为本 Spec §3），提交说明写明"Q1b 取代 Q1a 的 Wiki 不可用行为"；
   - 快问快答对只选 Wiki 库的提示保持不变（Q1b-2 才开放）。
3. **没有原文出处的字段**：
   - 照常返回三态、`Origin` 与 `Review`；
   - 只有带 Evidence 的行才给可引用的句柄（`evidence_index` 取 0，即第一条出处）；
   - 没有 Evidence 的行（如 `unknown`、模型补充）只在文本里说明状态，不给句柄，不标"审核过"；
   - 不制造第 0 条出处。
4. **概念**：
   - 定义、说明与陈述在工具文本中标"模型补充（概念说明）"，不标"审核过"；
   - 陈述引用的产品事实，只按精确 slug 指向本轮同一版本中可见的 Claim；
   - 陈述的 refs 不存在或不可见，或 `based_on` 的摘要与当前 Claim 的摘要不一致时，这条陈述不返回。可以给 `Concept` 增加只读字段（如 `OmittedStatements int`），在工具文本中说明有几条因过时或不可见被略去；
   - 没有 `based_on` 时不做摘要校验（RED 夹具即此情形）。
5. **规范化的优先级**：
   - `SearchFields` 严格沿用 S3h-1 的语义：空白压缩成一个空格，按空白分词；
   - 找产品、按名称选字段、找概念时，用去掉空白的规范化。
6. **出处的渠道**：
   - 本片验收登录态 Web 聊天中的精确回跳；
   - 嵌入、API、IM 渠道沿用现有的授权失败显示，不回落到 chunk，不借用浏览器凭据，不扩大路由权限。这些渠道的出处授权另行设计。
7. **整合顺序**：#248（S3h-2）已合并（`0cbd7bcbf`）。开工前先 merge 最新 main。

## 4. 前端（Q1b-1）

- `metadata.source_tier = "release"` 的引用（Q1a 已能显示标签）：
  - 点开时用企业知识的出处面板（`CitationPanel`，参数 `spaceId`、`releaseId`、`member = logical_slug`、`evidence = evidence_index`）；
  - 不按 chunk ID 去取 chunk；
  - 浮层显示"产品 · 字段"与取值摘要。
- Agent 事件与历史回放保留这些 metadata（Q1a 已保留 metadata 的链路，补上新的工具名）。
- 文案：zh-CN，其余 4 种语言同步。

## 5. Q1b-2 快问快答（另开 Issue，本 Spec 先定方向）

- 快问快答没有工具调用，需要按问题直接找字段：
  - 问题与产品名称共有二元组 → 产品；
  - 问题包含字段标题 → 字段；
  - 两者都有时，取这些产品的这些字段；只有字段时，取所有产品的该字段（对比类问题）；只有产品时，取该产品的速览字段（导航 `overview_fields`）。
- 命中结果作为"已发布知识（审核过）"引用，排在原文检索结果之前。
- 实测问题集出来后，再决定是否需要更强的匹配。

## 6. 验收（RED，Claude 编写，受保护）

`internal/enterprise/knowledge/acceptance_test.go`：用内存 `Reader` 覆盖 §2 的规则：

- 按固定版本读取，不读 Active；
- 找产品：编号、名称包含、二元组、排序、上限；
- 取字段：标题与取值、三态、出处编号与页码、按名称或谓词选字段、顺序；
- 产品不存在时报错；
- 搜字段：与 S3h-1 一致；
- 概念：按键或标题、引用；
- 概念不存在时报错；
- 读取失败原样返回。

工具接线、提示、前端由实现方测试覆盖。

## 7. 改动范围

- **项目自有**：
  - `internal/enterprise/knowledge/`（新增）；
  - `internal/enterprise/chatsource/`（工具注册与提示所需的扩展）；
  - `frontend/src/enterprise/`。
- **上游文件**（登记补丁）：
  - `internal/application/service/agent_service.go`：注册新工具；
  - `internal/modelcontext/tool_policy.go`；
  - `internal/container/container.go`：如需装配；
  - 前端引用浮层与抽屉：Q1a 已登记的文件，加上 `AgentStreamDisplay.vue`；
  - `frontend/src/i18n/locales/`。

## 8. 上线与实测

与 Q1a、S3h 一起构建与部署（需用户批准）。上线后的问答实测，用约 30 个问题比较三种模式（原文检索、已发布知识、混合）的答对率与出处；聊天模型调用预算另行申请。
