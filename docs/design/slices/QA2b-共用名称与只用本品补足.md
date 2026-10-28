# QA2b · 共用系列名的产品识别，补足时不用其他产品的原文

> 状态：Claude 2026-10-28 提出 ｜ 作者：Claude Code
>
> 依据：
> - QA2 部署后线上复核（#385 comment 6460509760，记录在仓库外 `~/insurancekb-runs/qa2-recheck-20261028/`）：8 轮快问快答中 q16、q22、q24 通过，有两类失败与本切片相关：
>   - **q14**：线上 epoch 62 新增了第二款"安佑福"产品（平安安佑福重大疾病保险），"安佑福"同时出现在两款产品的名称里。按 QA2 的严格规则，共用片段不算点名，结果两款都没有被识别，原文也没有按产品检索。q19 同样漏识别，只是碰巧从全局结果补到了一段。
>   - **q23**：点名产品自己的条款正文没进前 k 条，全局补足填进了其他产品几乎一样的如实告知条款，答案把尊享版的条款当成了悦享版的规定。
> - 用户 2026-10-27 已把审批全部授权给 Claude。
>
> 实现方：**Claude** ｜ 审核方：Codex ｜ 真实调用 0 ｜ 部署后复核沿用 QA2 §7（8 轮快问快答，最多 30 次调用）

## 1. 共用系列名的产品识别

在 QA2 §3 的严格规则上增加一条。没有被实体 ID、名称、核心名或独有片段命中的产品，如果问题中有一段名称片段同时满足下列条件，就用它点名：

1. 不少于 3 个字符，且不出现在本版本任何字段标题中（同 QA2 §3 第 4 条）；
2. 出现在 **2–3 款**产品的名称中。3 款以上则视为太宽泛，一款也不点名；
3. 它是每一款带它的产品**核心名的开头**，即去掉"所有产品共有前缀"之后名称的开头。系列名、品牌名在这个位置，"医疗保险""终身寿险""重大疾病保险"这类险种词不在这个位置，因此不会因险种词点名；
4. 带它的产品中，没有一款已经被更具体地命中（实体 ID、名称、核心名或独有片段）。例如问"安佑福全能版"时，只点名全能版那一款。

满足条件时，带这段片段的产品全部点名，按导航顺序排列；检索侧仍由 `MaxNamedProducts`（3）封顶。`QuestionFields` 使用同一识别结果，所以字段选取也随之覆盖这几款产品。

## 2. 补足时不用其他产品的原文

只作用于问题点名了产品的快问快答，即 QA2 §2 的 `FILTER_TOP_K` 选取：

- 各点名产品轮流取完自己的片段后，用全局排序补足。补足时**跳过材料归属于其他产品的片段**：所在材料在固定版本中被归属于至少一款产品，且其中没有一款是本题点名的产品。
- 没有归属的材料仍可以用于补足。与点名产品共有的材料本来就在点名产品的片段里。
- 补不满 k 条就少于 k 条，**不拿其他产品的片段凑数**。
- `MergeResult`、`RerankResult` 按上面的规则选取。如果两者在选取后都为空，原生插件会改用 `SearchResult`，所以此时 `SearchResult` 也按同一规则选取，避免其他产品的片段从这条路回来。
- 没有点名任何产品时，一切照旧。

**材料归属**：与 QA2 §3 的 `Materials` 规则相同。claim 的材料归属于它的主体；页面的材料归属于它提到的、在版本中有可见 Entity 成员的实体。新增 `knowledge.Service.ForeignMaterials`：

```go
// ForeignMaterials returns the knowledge IDs the pinned release attributes to some product
// but to none of the named entity IDs. Unattributed materials are not foreign.
func (s *Service) ForeignMaterials(
	ctx context.Context, tenantID uint64, spaceID, releaseID string, named []string,
) (map[string]bool, error)
```

### 2a. 补充口径（Claude 2026-10-28，#399 审核 R1–R4）

1. **"未识别到产品"与"识别到但本轮没有可用的本品材料"要分开处理**：
   - 前者一切照旧（noop）；
   - 后者照样排除其他产品的片段。点名产品没有片段可取，就只用无归属的片段补足；补不满 k 条就少于 k 条。
   - QA2 的"交集为空不计"只用于追加检索目标和轮流队列。
2. **归属检查覆盖本轮所有已选的企业 RAW Space**：对每个有固定版本的 Space 调用 `ForeignMaterials`。没有点名产品的 Space，传入空列表，这样其中归属于产品的材料都算其他产品。这项检查与 `MaxNamedProducts`（3）无关：上限只限制追加的检索目标和轮流队列，不限制点名与归属的判定。
3. **失败关闭**：
   - 识别失败（`QuestionProducts` 读取失败）沿用 QA2 的做法，保持原检索并记 warn；
   - 已识别到产品、但归属读取（`ForeignMaterials`）失败时，只保留点名产品自己的片段，完全不补足，可少于 k 条，记 warn，不写查询文本。不能把归属未知的片段当作无归属来补足。
4. **共用系列名只看核心名**：按 QA2 §3 冻结的定义，核心名是首个名称去掉所有产品首名共有前缀后的部分。系列名必须是每款带它的产品的核心名开头，别名不算。别名仍可以按完整别名命中（QA2 §3 第 2 条）。

## 3. 改动范围

- `internal/enterprise/knowledge/question_products.go`：共用系列名规则。
- `internal/enterprise/knowledge/`：新增 `ForeignMaterials`（可放在 `question_products.go` 或新文件）。
- `internal/enterprise/chatsource/retrieval.go`：补足时排除其他产品的片段；在 `MergeResult` 与 `RerankResult` 都为空时选取 `SearchResult`。
- 实现方测试；QA2 实现方测试中断言旧补足行为的用例，按新规则调整。

不改 Harness、前端、`contracts/`、上游文件和迁移。

## 4. 验收（RED，受保护）

- `internal/enterprise/knowledge/question_products_shared_test.go`（合成数据，结构与 q14 一致）：
  - 共用系列名点名 2 款，按导航顺序；
  - 4 款共用的系列名一款也不点名；
  - 带共用片段的产品中，有一款被独有片段或全名命中时，只点名那一款；
  - 险种词不在核心名开头，不点名；
  - `QuestionFields` 返回两款产品各自被问到的字段。
- `internal/enterprise/chatsource/product_fill_test.go`：
  - 只点名乙，k=3：结果为乙的两段加一段无归属片段，甲的片段不进入；
  - k=5：只得到这 3 段，不用甲的片段凑数；
  - `MergeResult` 与 `RerankResult` 都为空时，`SearchResult` 同样排除甲的片段。
- QA2 冻结验收 `product_retrieval_test.go` 中 k=3 的期望从 `r4,r5,r1` 改为 `r4,r5,x`（`r1` 属于甲）。这是本切片有意改变的行为，修改单独说明。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/...`，以及 service 中 Quick/Product 相关测试；
- golangci-lint（`--new-from-merge-base=origin/main`）；
- 架构守卫；
- `git diff --check`。

## 5. 风险

- **共用系列名点名多款**：问题只想问其中一款、却只写了系列名时，答案会同时检索几款产品。答案按产品标注原文，不会混淆来源。
- **补足减少**：点名产品自己的片段很少时，上下文会少于 k 条，答案可能说"没有找到"。这比借用其他产品的规定安全。
