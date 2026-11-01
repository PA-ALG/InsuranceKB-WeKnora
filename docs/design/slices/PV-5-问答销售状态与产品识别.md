# PV-5 问答中的销售状态、登记标识识别与同一产品线的跨年版本

> 状态：Spec（2026-11-01，Claude）。设计依据：[PV-0](PV-0-产品版本与生命周期.md) §3、[附录 A](PV-0-附录A-身份发布同步与迁移.md)
> §1.4；[PV-4b](PV-4b-读取侧.md) §2、§4；[SK-3](SK-3-销售方法阅读与问答.md) §6（方法知识不进产品问答）。跟踪 Issue #501。
> 实现 Claude，审核 Codex。真实调用 0（问答回归在部署后线上做，§7）。

## 0. 问题与范围

11-01 线上问答版本回归（epoch 173，导航 `2026-11-01.1`，20 道版本题 + 30 道回归题，结果在 #501）：回归题不退化；版本题
9 道符合、4 道部分、7 道不符或被阻塞。本片处理其中四个确定性缺口：

| 项 | 现象 | 根因 |
|---|---|---|
| B1 | 点名一款停售产品问“推荐/能买”，回答当作可买；版本不明的产品（无 `lifecycle`）回答时无从知道状态未知 | 状态只是已发布字段标题与首段里的括号标注，模型容易略过；无 `lifecycle` 的实体按 PV-4b §2 不加任何标注 |
| B2 | 未点名产品的销售比较（“现在在售的护理险有哪些”）只拿到原文，回答说无法确认状态，甚至把停售产品推荐为可买 | 原文片段的标题只带产品名、不带状态；比较范围的“排除停售/未开售”（PV-4b §4.2）只作用于已发布字段，原文不按状态过滤 |
| D | 问题里的险种代码或版本号（如“产品代码 2635”）认不出产品 | 产品识别只比较实体 ID 与名称；`sc-` 实体的 ID 是摘要，登记的代码在 `identifiers` 里，识别不读 |
| C | 在保服务类问题带投保日期时，选不到同一产品线的另一个年份版本（问 2024 版名称、2025 年底投保，应为 2026 版） | 年份版本是不同的报备编码，PV-0 只给同编码版本建 `supersedes`；问答的“同一产品的版本”只认同名或 `supersedes` |

不做：
- “现在还能买吗”被上游问题理解判为联网搜索、关闭联网后不检索（回归缺口 A，另立切片 QA5，不在本片）；
- 提示词正文与 AnswerRules（受保护测试锁定，PV-4b §0）；
- 已发布字段文本的现有标注规则（PV-4b §2：无 `lifecycle` 的实体文本逐字节不变）；
- 按年份标记把不同编码合并成一个实体。版本仍是挂载单位，本片只补关系与读取。

## 1. B1 销售类问题给出点名产品的销售状态

### 1.1 平台读取（`internal/enterprise/knowledge`）

新方法 `Service.QuestionStatuses(ctx, tenant, space, release, question) ([]StatusLine, error)`：

- 只在问题的问法意图为**销售类**（导航 `question_intents`，PV-4b §4.1，规则不变）时返回；其余（服务类、两类都中或都不中、
  导航没有意图）返回空，不改变今天的行为。
- 对象是问题点名的产品（`questionProducts`，含 §3 的登记标识），按导航顺序，每款一行；只取有 Entity 成员的条目（无成员的
  Claim 主语占位条目没有可固定的引用）。方法实体不在其中（SK-3 §3）。
- `StatusLine{EntityID, Slug, Title, Text}`：`Slug` 是该实体成员的 logical slug；`Title` = `<名称> · 销售状态`；
  `Text` = `<名称> · ` + 与 `knowledge_find_entity` 行同一套版本描述（PV-4b §2）：
  `销售状态：停售；销售期：2024-04-23 至 2024-09-01；系列：…；后续版本：<ID>（<名称>）`（有值才出现）。
  **无 `lifecycle` 时写 `销售状态：未知`**（工具行与字段文本不变，只有这一行显式说明未知）。状态的评价日与 PV-4b 相同。
- 抽出 `entityLine` 的版本描述为共用函数，工具行文本逐字节不变（PV-4b 验收继续通过）。

为什么另起一行而不是加强字段标注：回归中点名停售产品的字段首段已经带“（停售；销售期…）”，回答仍未提及；独立的一条
“销售状态”内容是数据层最直接的信号，而且能说出“未知”，不需要改提示词。

### 1.2 快问快答（`internal/enterprise/chatsource`）

- `publishedHits` 对每个 Wiki Space 先放状态行，再放字段命中；两者合计仍受 `maxPublishedHits`（12）约束。
- 状态命中：`ID = release:<release>:<Slug>`，`KnowledgeTitle = Title`，`Content = Text`，元数据
  `{source_tier: release, space_id, release_id, logical_slug: <Slug>, knowledge_class: sale_status}`，**没有
  `evidence_index`**（销售期来自登记表固定的产品仓库提交，不是材料原文，不能伪造出处）。元数据由 `knowledge.StatusMetadata`
  生成（与 `FieldMetadata` 同处）。
- 本轮固定版本校验不变：`pinnedOnly` / `ownsPinned` 只认 `release:<本轮版本>:<slug>`，旧版本的状态命中照样被去掉。
- 送入模型的分层标签（`AnswerPassage`）：`knowledge_class = sale_status` 的 release 命中标为
  `销售状态（已发布版本的产品登记数据）`，不标“已发布知识（审核过）”。

### 1.3 前端（引用显示）

- `sourceTier`：`source_tier = release` 且 `knowledge_class = sale_status` → 新层级 `sale_status`，标签
  `chat.sourceTierSaleStatus`（5 种语言：中文“销售状态（产品登记数据）”）。
- `releaseReferences.ts` 新增 `releaseStatusReference(reference)`：只在完整元组成立时为真——`source_tier = release`、
  `knowledge_class = sale_status`、`logical_slug` 以 `entity/` 开头、**没有** `evidence_index`、`release_id` 不是 `active`、
  `id = release:<release_id>:<logical_slug>`。`releaseCitationTarget` 对它仍返回 `null`（没有可打开的原文）。
- `releaseCitationPreview`：同一 chunk 的匹配全部是同一状态引用时返回其标题与内容（不报错）；状态引用与其他引用混在
  同一 chunk 上仍按现有规则报错。
- `ReleaseCitation.vue`：状态引用显示一句说明 `chat.releaseStatusNote`（“销售状态由本版本的产品登记数据计算，没有原文出处。”），
  不显示“无法打开”的告警，也不打开出处面板。

## 2. B2 原文片段带版本标注；未点名的销售比较不给停售/未开售产品的原文

### 2.1 原文标签（`SourceEntities`）

`SourceEntities` 返回的名称改为“名称 + 版本标注”（`versionLabel`，PV-4b §2 的同一函数，只在实体带 `lifecycle` 时有标注），
去重按带标注的名称。于是原文分层标签与片段标题成为
`原文检索（未经编译审核）｜所属产品：丁护理保险（停售；销售期 2023-01-01 至 2024-09-01）`。没有版本数据的产品文本不变。

### 2.2 销售比较的原文范围（`OffSaleMaterials` + `RetrievalScope`）

- 新方法 `Service.OffSaleMaterials(ctx, tenant, space, release, question) (map[string]bool, error)`：问题为销售类、且
  **没有点名产品**时，返回“只属于停售或未开售产品”的材料：材料被至少一款产品引用（`productMaterials` 的归属规则），且
  引用它的每款产品状态都是 `discontinued` 或 `not_yet_on_sale`。被任一在售/状态未知产品引用的材料、未归属的材料都不在
  其中。其余情况返回空。规则与已发布字段的 `forSale` 一致（PV-4b §4.2）；点名的产品一律不删。
- `namedScope` 在问题没有点名产品时向每个选中的 RAW Space 取这份集合（`productScope.offSale`，按 `materialKey`）。
  `RetrievalScope` 在 `CHUNK_MERGE` 与 `FILTER_TOP_K` 去掉这些材料的片段（同时处理原生阶段的回退列表：重排列表为空时的
  检索列表；合并与重排都为空时的检索列表），检索阶段不改目标。读取失败时记一条不含问题文本的告警并保持原检索（与产品识别
  失败的处理相同）。
- 有点名产品时走现有 QA2 路径，不变。

## 3. D 用登记标识识别产品

- 实体成员的 `identifiers`（合同已有：`additionalProperties: string`）进入读取索引。平台不认识任何键名：**全部取值**都
  作为该实体的登记标识（硬边界 4；`product_code`、`version_key`、`filing_no` 由 Harness 写）。
- `questionProducts`：问题（`normalize` 后，保留连字符等标点）中出现某个标识值、且该处是**完整记号**（`wholeToken`，
  PV-4b 投保日期用的同一函数：前后紧邻 ASCII 字母数字，或“连接符 + 字母数字”，就是更长编号的一部分）时，该实体按“编号
  命中”点名（与实体 ID 命中同级）。标识值去空白后少于 3 个字符的不用。多个实体共用一个标识值时都点名，由版本规则与标注区分。
  于是“2635”点名 2635-1，“2635-1”点名该版本，“26351”“2635-0001”不点名。
- `knowledge_find_entity`（`FindEntities`）：查询串（`normalize` 后）等于某个标识值时按直接命中排序，与 ID 相同。
- 已知局限（与现有的实体 ID 子串匹配相同）：纯数字代码可能与金额等数字相撞（如“596 元”）。本片不改 ID 匹配，标识匹配
  已比 ID 更严（完整记号）。

## 4. C 同一产品线的跨年版本

### 4.1 Harness：登记表前驱规则（修订 PV-0 附录 A §1.4，蓝图 §14 新增一行）

`product_versions.predecessors(versions, lines)` 先用现有规则（同 `plan_code`、`p.sale_end == v.sale_start`、恰好一个）；
**没有时**再用产品线规则：

- **产品线名**（`line_of(name, policy)`）：规范名 `fold` 后，去掉归属策略 `product_year_patterns` 每个匹配范围内的数字，再去掉
  因此变空的括号，casefold。“平安智盈倍护（2026）终身护理保险”与“平安智盈倍护终身护理保险”同线；“尊享版26”→“尊享版”。
  规则是现有的年份数据，不按产品编号特判。
- 候选 `p`：与 `v` 同产品线名；`p.sale_end` 与 `v.sale_start` 都已知，且 `p.sale_end ≤ v.sale_start`（**先停售、后开售，
  销售期不重叠**）；两者都有年份标记时 `p` 的更早。候选中取 `sale_end` 最晚者，最晚者不唯一则不连。
- 一个 `p` 若成为两个 `v` 的产品线前驱，两条都不连（失败关闭）。
- 同时在售或销售期重叠的同线产品（线上 1806 与 1816(2026)）**不连**：它们并存，不是接替。

`registry._link` 与迁移（`plan_migration`，含 `--refresh`）传入每个条目首个名称的产品线名。链仍只表达“谁接替谁”，不撤回
旧版本知识（PV-0 §3.2）。线上按本规则预期新增 1 条：2635-1 → 2648-1（2024-09-01 停售，2025-10-22 开售）；运维计划若出现
其他新链，逐条核对再发布。

### 4.2 平台问答：带投保日期的服务类问题沿版本链取候选

PV-4b §4.2 的“在保服务”规则不变，只扩大候选：服务类问题含投保日期时，候选 = 点名的版本 + 与它们由 `supersedes`（两个
方向、可传递）相连、且是本 Release 可见实体的版本；仍按“同名或 `supersedes` 相连”分组，组内保留销售期覆盖该日期的版本；
一组都不覆盖时只保留该组**点名的**版本（未点名的链上版本不加入）。没有日期、不是服务类、或导航没有意图时与今天相同。

`QuestionProducts`（原文按产品检索与归属，QA2）改用同一份选择结果，使原文范围与已发布字段一致：问 2024 版名称、2025 年底
投保时，原文检索 2026 版的材料，2635-1 的材料按“其他产品”处理，不填充。

## 5. 改动范围

- Go：`internal/enterprise/knowledge/{index.go,entities.go,question_products.go,question_versions.go,questions.go,
  sources.go,versions.go,tool_result.go}`，新文件 `knowledge/question_status.go`；`internal/enterprise/chatsource/
  {published.go,answer_context.go,retrieval.go}`。
- 前端：`frontend/src/enterprise/{sourceTier.ts,releaseReferences.ts,ReleaseCitation.vue}`、`i18n/messages/*`（5 种语言）。
- Harness：`ingest/{product_versions.py,registry.py,registry_migration.py}`。
- 文档：本 Spec；蓝图 §14 一行。
- 不改：合同 `contracts/`、导航数据与版本、提示词、发布与审核路径、上游文件（G10 不变）。

## 6. 验收（RED，单独提交）

- **Go knowledge**（`question_status_acceptance_test.go`）：销售类问题对点名停售产品返回状态行（含销售期与后续版本），无
  `lifecycle` 返回“未知”，服务类/无意图/未点名返回空；`SourceEntities` 的名称带版本标注、无版本数据的不变；
  `OffSaleMaterials` 只含全部所属产品停售或未开售的材料，点名/服务类/无意图时为空；险种代码与版本号按完整记号点名，
  “26351”“2635-0001”不点名，`FindEntities` 按标识直接命中；带投保日期的服务类问题沿 `supersedes` 选到未点名的新版本，
  日期落在旧版本时选旧版本，无日期或都不覆盖时只留点名版本，`QuestionProducts` 结果一致。
- **Go chatsource**（`sale_status_acceptance_test.go`）：状态命中排在字段之前，元数据无 `evidence_index`、带
  `knowledge_class = sale_status`，分层标签为“销售状态（已发布版本的产品登记数据）”；原文分层标签带版本标注；未点名的销售
  比较在 `FILTER_TOP_K` 去掉停售/未开售产品材料的片段，保留在售、状态未知与未归属的片段；非销售问题不变。
- **前端**（`releaseStatusReferences.spec.ts`）：状态引用的识别要求完整元组；`releaseCitationTarget` 为 `null`；预览返回标题
  与内容；`sourceTier` 为 `sale_status`；5 种语言都有两个新键。
- **Harness**（`tests/ingest/test_line_predecessors.py`）：年份版本先停后开 → 连；同时在售 → 不连；同编码规则优先；同线
  多个候选取最晚停售、并列不连；一个前驱对两个后继 → 都不连；新版本无年份标记而旧版本有 → 不连；迁移计划带出产品线前驱。
- 现有验收（PV-4b、QA2、SK-3 等）不改断言并继续通过。
- 门禁：Go build/vet/受影响包测试、golangci-lint（new-from-rev）、前端 type-check / vitest / node 测试 / check-i18n /
  build、Harness pytest/ruff/mypy、`tests/architecture`、手写文件 ≤ 500 行、`git diff --check`。

## 7. 上线与回归

1. 部署 App + UI（运维 Issue，Codex 执行；契约不变）。
2. 编译线：`uploads migrate-registry --refresh`（固定提交不变）先干跑，确认只多出产品线前驱；再 `uploads refresh-identity`
   先计划后上线（只新增 `supersedes`）。
3. 问答回归：沿用 11-01 题集（20 + 30），平台调用按每轮 2 次计（问题理解 + 回答），上限在运维 Issue 写明；缺口 A 修好前
   “现在还能买吗”类题仍会被阻塞，结果分开统计。
