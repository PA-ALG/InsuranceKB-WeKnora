# QA2 · 快问快答按产品检索与字段匹配

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
>
> 依据：
> - 用户 2026-10-26 批准问答修正 1–3，第 4 项"按产品限定检索"须先做消融。
> - 2026-10-27 线上复核（#369 comment 6444793441）：快问快答 q16、q22 都没有检索到被点名产品自己的内容。
> - 用户批准用真实调用做消融（"先用真实调用做消融，执行吧"）。结果见 #369 comment 6445982660，数据在仓库外 `~/insurancekb-runs/retrieval-ablation-20261027/`。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 实现阶段真实调用 0 ｜ 部署后复核另请用户批准（§7）

## 1. 消融结论（只摘本 Spec 用到的部分）

**原文检索**（#286 中点名产品的 24 道单轮题，36 条期望原文，严格判定）：

| 方式 | 期望原文 | 点名产品全覆盖 | 其他产品片段占比 | 平均条数 |
|---|---|---|---|---|
| 现状：全部固定材料一次检索 + 重排 | 11/36 | 19/24 | 0.44 | 9.2 |
| 只加大 k 到 20 | 22/36 | 22/24 | 0.62 | 20 |
| **每个点名产品各自检索 + 轮流合并，再用全局结果补足（采用）** | **21/36** | **24/24** | **0.27** | 9.8 |

采用的方式比现状好 9 题，没有一题变差。端到端离线复刻中，它修好了 q22、q24，q19、q21、q23 三道对照题仍然通过。

**q16 不是原文检索的问题，而是已发布字段选错了**：
- 问题里写的"（费率可调）"是惠享版产品名的一部分，恰好也是一个字段的标题；
- `QuestionFields` 于是只返回这一个字段，两款产品已发布的"保险期间和续保"字段都没有被选中。

**产品识别**（同 24 题）：

| 规则 | 精度 | 召回 |
|---|---|---|
| 现有二元组规则 `questionProducts` | 0.44 | 1.00 |
| 严格规则（§3 不含字段标题排除） | 0.94 | 1.00 |
| **严格规则 + 字段标题排除（§3 全文）** | **1.00** | **1.00** |

- 现有规则的问题：问"e生保悦享版"会把同系列的惠享、尊享一起带出来。
- 严格规则剩下的两个误报是"意外伤害"被识别成意外险产品、"重大疾病"被识别成重疾产品。这两个词同时是本版本字段标题里的词，见 §3 第 4 条。
- 题量只有 24，以上只说明规则方向正确，不作为质量结论。

## 2. 快问快答的原文检索按产品配额

只作用于快问快答，即 `chatsource.IsEnterpriseAnswer(ctx)` 为真、本轮有 RAW 目标的问答。Agent、搜索、MCP 不变。

新增 `chatsource.RetrievalScope(ctx, resolver, event, cm) func()`，在 `session_knowledge_qa.go` 中与现有的 `AnalysisScope` 一样包在每个阶段的 `Trigger` 外面：调用前修改 `cm`，返回的函数在阶段结束后恢复。

**问题文本**：取 `cm.RewriteQuery`，为空时取 `cm.Query`。点名的产品由 `knowledge.QuestionProducts`（§3）在本轮固定版本上算出。

**材料范围**：每个产品的材料，取它在版本中被归属的材料（§3 的 `Materials`）与本轮该 Space 已固定、可检索的 RAW 材料（`turn.RawKnowledge`）的交集。交集为空的产品不计。

**数量上限**：同一轮最多处理 **3** 个点名产品（`chatsource.MaxNamedProducts`），按导航顺序取前 3 个。

各阶段做的事：

1. **`CHUNK_SEARCH_PARALLEL` 和 `CHUNK_SEARCH`**：
   - 在原有目标之后，为每个点名产品追加一个目标：类型 `SearchTargetTypeKnowledge`，库为该 Space 的 RAW 库，`KnowledgeIDs` 为该产品的材料（排序），`TenantID` 为本轮租户。
   - 原生检索对每个这样的目标单独执行一次，取 `EmbeddingTopK` 条。所以每个点名产品多一次检索调用，重排仍然只有一次。
   - 阶段结束后恢复原目标列表，检索结果保留。
   - 同一片段被多个目标检出时只保留一份，按片段 ID 去重；原生合并已经去重的话，不需要另外处理。
2. **`CHUNK_RERANK`**：
   - 阶段内把 `RerankTopK` 临时提高到 `max(原值, len(cm.SearchResult))`，让重排只按阈值过滤、不在这一步截断。
   - 阶段结束后恢复原值。
3. **`FILTER_TOP_K`**：
   - 阶段开始前，把 `cm.MergeResult` 与 `cm.RerankResult` 重新排序：先按导航顺序在各点名产品之间轮流，每轮每个产品取一条（取该产品自己的片段中排名最前、尚未取过的一条）；某条片段的材料属于该产品，它就是该产品的片段，属于多个产品时只取一次。各点名产品都取完后，剩下的片段保持原有顺序排在后面。
   - 原生的 `FILTER_TOP_K` 随后按原 `RerankTopK` 截断。

**以下情况都不做任何改动，按现状检索**：
- 问题没有点名产品；
- 不是快问快答，或本轮没有 RAW 目标；
- `QuestionProducts` 读取失败。这种情况记一条 warn，不能因为识别失败而让问答失败。

已标注的产品名（QA1）、交付前的版本与固定校验（`Filter`）都不受影响：追加的目标限定在同一个 RAW 库、本轮已固定的材料之内。

## 3. 产品识别（替换 `questionProducts`）

新增并冻结以下接口：

```go
// NamedProduct is a product a question names, with the materials the release attributes to it.
type NamedProduct struct {
	EntityID  string
	Name      string   // the entity's first display name
	Materials []string // knowledge IDs cited by its claims and pages (the SourceEntities rule), sorted, unique
}

// QuestionProducts returns the products the question names, in navigation order. Only a pinned
// release is read (as QuestionFields).
func (s *Service) QuestionProducts(
	ctx context.Context, tenantID uint64, spaceID, releaseID, question string,
) ([]NamedProduct, error)
```

`QuestionFields` 与 `QuestionProducts` 共用同一个识别函数，旧的二元组规则删除。

**比较前的规范化**：问题和名称都先经过现有的 `normalize`，再去掉 Unicode 标点与符号（P* 和 S* 类）。

**判定规则**：满足下列任一条，即认为问题点名了该产品。

1. 问题包含该产品的实体 ID（不少于 2 个字符，沿用现状）。
2. 问题包含该产品的某个名称。
3. 问题包含该产品的**核心名**，且核心名不少于 3 个字符。核心名是首个名称去掉"本版本所有产品首个名称共有的最长前缀"之后剩下的部分；例如所有产品名都以公司名开头时，核心名就是去掉公司名后的部分。
4. 问题包含该产品某个名称（或核心名）中一段不少于 3 个字符的片段，且这段片段同时满足：
   - 不出现在其他任何产品的任何名称中；
   - 不出现在本版本任何字段标题（展示配置的 `short_title`）中。

   第二个条件的理由：字段标题里的词是在问话题，不是在点名产品。例如"意外伤害"出现在"意外伤害定义与认定标准"里，"重大疾病"出现在"保费豁免重大疾病清单"里。

**较长的名称优先**：若两个产品都按第 2 或第 3 条命中，且其中一个的命中名包含在另一个的命中名中，只保留较长的那个。若某产品只按第 4 条命中，而它的名称与另一个按第 2、3 条命中的产品互相包含，也不保留它。

**`Materials` 的归属**：与 QA1 的 `SourceEntities` 相同。claim 归属于它的主体；页面归属于它提到的、在版本中有可见 Entity 成员的实体。

## 4. 已发布字段的选取（`QuestionFields`）

原有规则不变：问题里出现了字段标题就取该字段；点名了产品就限定在这些产品；只点名产品、没问字段时，取这些产品的概览字段。

新增一条：若问题中出现的某个字段标题，同时也包含在某个被点名产品的名称里（如"费率可调"），那么在原有结果之后，按导航顺序补上各被点名产品的概览字段。补的时候去掉重复，受 `limit` 限制。

不选择"从问题里删掉产品名"的做法，理由是：用户明确问"惠享版的费率可调吗"时，这样会把该字段也删掉。

## 5. 改动范围

- `internal/enterprise/knowledge/questions.go`：识别函数（新文件可放在同一包内）、`QuestionProducts`、`NamedProduct`、§4 的规则，并删除旧规则；
- `internal/enterprise/chatsource/`：新文件，内容为 `RetrievalScope`、`MaxNamedProducts`；
- `internal/application/service/session_knowledge_qa.go`：在现有的 `AnalysisScope` 调用旁增加一行 `RetrievalScope` 调用。这是上游文件，在 `docs/design/upstream-patches.md` 追加一行登记，退出条件同 QA1 的接缝；
- 实现方自己的测试。

不改 Harness、`contracts/`、前端。

## 6. 验收（RED，Claude 编写，受保护）

1. `internal/enterprise/knowledge/question_products_test.go`：九个产品同一公司前缀，覆盖 #286 q05、q16、q17、q22 四种形态。
   - 点名精度：同系列产品不会被一起带出；字段标题里的词（意外伤害、重大疾病）不算点名；全名仍然算点名。
   - 核心名命中；较长的名称优先。
   - `Materials` 的排序与去重，以及只读固定版本。
   - §4：标题在产品名里时补概览字段；明确问该字段时仍保留它；标题不在产品名里时行为不变。
2. `internal/enterprise/chatsource/product_retrieval_test.go`：
   - 两个检索事件都为每个点名产品追加目标，并在阶段结束后恢复；
   - 重排阶段临时提高 `RerankTopK`，结束后恢复；
   - `FILTER_TOP_K` 前的轮流排序，包括单产品和双产品两种情况；
   - 没有点名产品、识别读取失败、非快问快答三种情况下都不做任何改动。
3. 现有受保护的 Q1b-2 验收测试（`question_acceptance_test.go`）不改，必须继续通过。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/... ./internal/application/service/...`（其中 `TestSkillPythonVerifier` 是本机已知问题，与本 Spec 无关）；
- 差异 golangci-lint；
- 守卫。

## 7. 部署后复核（另请用户批准）

- **题目**：q16、q22、q24，加 5 道对照题（q05、q14、q17、q19、q23），共 8 道，只跑快问快答。
- **预算**：每轮约 3 次调用（改写、作答，以及按每个点名产品多出的一次检索和重排），8 轮约 24–30 次，上限 30。
- **判定**：沿用 QA1 §7 的确定性规则，并加一条：被点名产品自己的规定是否答对。

只有这一步能说明线上真实效果；离线复刻和本 Spec 的测试不能代替它。

## 补充（Claude 2026-10-27，#385 R1）

原生 `FILTER_TOP_K` 插件（`chat_pipeline/filter_top_k.go`，上游文件，不改）先按分数重新排序，再截断，会打乱 §2 的产品轮流顺序。口径如下：

- **保证的是"入选"，不保证顺序**：在 `FILTER_TOP_K` 阶段之前，`RetrievalScope` 按产品轮流、再全局补足的规则，先选出最终的 k 条；然后把该阶段的 TopK 临时设为已选条数，阶段结束后恢复。原生插件只会重新排序，不会再删掉点名产品的条款。
- 最终上下文中各片段的先后顺序由原生插件按分数决定，可以接受：消融的指标是"是否入选"，不是名次。
- 验收：调用真实的 `PluginFilterTopK.OnEvent`，断言点名产品的片段**仍在结果中**，不断言名次。实现方自己的 `TestNamedProductOrderSurvivesNativeTopK` 按此调整断言即可，这是实现方测试，不是冻结的 RED。冻结 RED 不变。
