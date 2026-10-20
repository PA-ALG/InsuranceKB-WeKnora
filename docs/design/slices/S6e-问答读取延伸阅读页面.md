# S6e · 问答读取延伸阅读页面：原生 Wiki 页面作为第三类来源"模型整理（未逐条审核）"

> 状态：用户 2026-10-20 批准（"S6e 问答也读 Wiki 页面"）｜ 作者：Claude Code
> 依据：Q1b（#251）已发布知识工具、S6c（#254）`wiki_page` 成员、S6d（#257）延伸阅读页面
> 实现方：Claude（Go 与前端；用户 2026-10-20 同意本阶段由 Claude 实现）｜ 审核方：Codex ｜ 真实模型调用：0

## 1. 目标

字段只覆盖编译出来的那部分事实，很多条件、例外和流程说明不在字段里。原生 Wiki 页面已作为 `wiki_page` 成员进入发布版本（S6c），本切片让 Agent 问答也能读它们：

- **三类来源分开标注**：
  - "已发布知识（审核过）"：字段；
  - "模型整理（未逐条审核）"：Wiki 页面，本切片新增；
  - "原文检索（未经编译审核）"：原始材料。
- **查询顺序**：先查字段；字段查不到再查页面；仍不够时，选了原始材料库的再用原文检索。
- **固定版本**：页面与字段读同一个固定 Release，引用打开同一版本的原文出处（S6d 已能为 `wiki_page` 成员打开 `CitationPanel`）。
- 不做：快问快答读取页面（Q1b-2 再定）；页面的向量检索；页面编辑。

## 2. 平台（`internal/enterprise/knowledge`）

### 2.1 读取页面

发布版本索引读取 `kind = "wiki_page"` 的成员，payload 字段与 Harness 合同 `WikiPage` 一致：`page_key`、`entity_refs`、`title`、`page_type`、`summary`、`content`、`aliases`、`evidence`、`origin`。

- payload 不是合法 JSON 对象时，与其他成员一样返回 `INVALID_REQUEST`。
- 以下页面不进入检索，也不会被引用：
  - 成员 slug 不等于 `wiki/<entity_refs 中某个产品>/<page_key>`；
  - `page_type` 不是 `concept` 或 `entity`；
  - `origin` 不是 `MODEL_GENERATED`；
  - 标题为空。

### 2.2 查询

```go
type Page struct {
	ReleaseID, Slug, EntityID, EntityName, Title, Summary, Excerpt string
	Evidence                                                       []Evidence
}
func (s *Service) SearchPages(
	ctx context.Context, tenantID uint64, spaceID, releaseID, query, entityID string, limit int,
) ([]Page, int, error)
```

- 读取规则与 `SearchFields` 相同：必须给出版本 ID，不读 Active；Reader 失败原样返回。
- **词项**：沿用 `SearchFields` 的折叠与切分。查询没有词项时返回空结果。
- **匹配**：每个词项都出现在页面的标题、别名、摘要或正文（去掉链接标记后）中。
- **产品限定**：`entityID` 非空时，只取 slug 为 `wiki/<entityID>/…` 且 `entity_refs` 含该产品的页面；产品不存在时返回空结果，不报错。
- **排序**：
  1. 所有词项都在标题或别名中出现的页面在前；
  2. 再按产品在 `SearchFields` 中的产品顺序（产品没有 entity 或 claim 成员时，名称用产品编号，排在最后）；
  3. 同一产品内概念页在前、实体页在后；
  4. 最后按标题。
- **数量**：`limit <= 0` 时取 5；第二个返回值是匹配总数。
- **摘录 `Excerpt`**：
  - 正文去掉 `[[目标|文字]]` 链接标记（只留文字，没有文字时留目标最后一段），按空行分段；
  - 依次取含任一词项的段落，直到 800 个字符；
  - 没有段落命中（只命中标题、别名或摘要）时，从第一段开始取到 800 个字符；
  - 超过 800 个字符的段落截断，末尾加"…"。
- **出处 `Evidence`**：按原下标保留 `quote`、`locator.page`、`source_ref`；不合法的条目（quote 为空或页码不是正整数）跳过，但其余条目的下标不变。

### 2.3 工具 `knowledge_search_pages`

- `NewTools` 增加第 5 个工具：
  - 参数：`query`（必填）、`entity_id`（可选）、`space_id`（与其他工具相同：本轮只有一个 Wiki Space 时可省略）；
  - 描述："搜索本轮固定发布版本中的延伸阅读页面（模型整理，未逐条审核），可用 entity_id 限定产品。字段查不到的条件、例外和流程说明可用它补充。"
- **结果**：有出处的页面每页一行：
  - `chunk_id = "release:<release>:<slug>"`；
  - `knowledge_title = "<产品名> · <页面标题>"`；
  - `content`：以"模型整理（未逐条审核）："开头，依次是标题、摘要、摘录和引文（`引文：<quote>（第 n 页）`）；
  - `metadata = {source_tier: "wiki_page", space_id, release_id, logical_slug: <slug>, evidence_index: "<第一条合法出处的原下标>"}`。
- **没有合法出处的页面**：只进 notes，末尾注明"（无可回验出处，不作为出处）"，不给引用句柄。
- **结果形状**与字段工具相同（`display_type`、`results`、`count`、`total`、`notes`），沿用来源短句柄协议：`internal/modelcontext/tool_policy.go` 增加一行 `sourceOutput`。

### 2.4 提示

`chatsource.KnowledgeNotice` 在已发布知识说明之后、原文检索说明之前加一段：

> 字段查不到时，可用 knowledge_search_pages 查延伸阅读页面；页面是模型整理（未逐条审核），回答中如实标注，不当作审核过的事实；与字段冲突时以字段为准。

## 3. 前端

- `sourceTier.ts`：
  - `SourceTier` 增加 `'wiki_page'`，标签"模型整理（未逐条审核）"，5 种语言同步；
  - `referenceSourceKey` 对 `wiki_page` 与 `release` 同样带上完整来源身份。
- `releaseReferences.ts`：
  - `publishedKnowledgeTools` 增加 `knowledge_search_pages`；
  - `releaseCitationTarget` 接受两种 tier，且 tier 与成员类别必须一致：`release` 的成员不能以 `wiki/` 开头，`wiki_page` 的成员必须以 `wiki/` 开头；不一致返回 null；
  - `isReleaseReference` 对 `wiki_page` 同样为真，阻止落回普通文档引用。
- `citationMarkdown.ts` 与 `referenceSources.ts` 已按 `release:` 前缀识别固定版本引用，不改。

## 4. 验收（RED，Claude 编写，受保护）

- **`internal/enterprise/knowledge/pages_acceptance_test.go`**：
  - 按词项搜到页面，摘录含命中段落、不含链接标记；
  - 多词项同时匹配；
  - 标题命中排在正文命中之前；
  - 产品限定；
  - 不合格页面（slug 不符、非模型整理、类型不符）搜不到；
  - 出处保留原下标；
  - 读的是指定版本；
  - 工具：
    - 第 5 个工具存在且只读本轮版本；
    - 有出处的页面成为 `wiki_page` 来源行，`evidence_index` 指向第一条合法出处；
    - 无出处页面只进 notes；
    - 输出含"模型整理（未逐条审核）"。
- **`internal/enterprise/chatsource/pages_notice_test.go`**：提示含 `knowledge_search_pages` 与"模型整理（未逐条审核）"，并且排在原文检索说明之前。
- **`internal/modelcontext/tool_policy_pages_test.go`**：新工具走来源短句柄协议。
- **`frontend/src/enterprise/wikiSourceTier.spec.ts`**：
  - tier 与标签；
  - `releaseCitationTarget` 的 tier 与成员一致性；
  - `publishedKnowledgeReferences` 接受页面行；
  - 新工具被识别为已发布知识工具。

## 5. 改动范围

- `internal/enterprise/knowledge/`：新增 `pages.go`，修改 `index.go`、`tools.go`、`tool_result.go`；
- `internal/enterprise/chatsource/knowledge.go`；
- `internal/modelcontext/tool_policy.go`：已登记的上游文件，加 1 行；G10 基线如上升，由 Claude 单独提交；
- `frontend/src/enterprise/sourceTier.ts`、`releaseReferences.ts`；
- 语言包 5 种：已登记的上游文件，各加 2 行（来源标签、工具名）；
- `frontend/src/views/chat/components/AgentStreamDisplay.vue`：已登记的上游文件，工具名映射加 1 行（实现时补列）；
- `internal/application/service/agent_chatsource_test.go`：两处断言列出全部已注册工具，加入新工具（实现时补列，不放宽断言）；
- 实现方的单元测试。

## 6. 上线与验证

合并后需构建 App 与 UI 各 1 次（需用户批准）。真实问答效果纳入问答评测（30 题 × 3 种模式，预算另行批准），比较加入页面前后的覆盖率与错误率。
