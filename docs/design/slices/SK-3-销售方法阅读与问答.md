# SK-3 销售方法的阅读与问答

> 状态：Spec（2026-11-01，Claude）。设计依据：[SK-0](SK-0-销售方法与通用知识.md) §3.4、§6、§7、§9 SK-3 行；
> [SK-2](SK-2-方法登记准入与编译.md) §4.3–§4.4（方法成员合同）；[PV-4b](PV-4b-读取侧.md)（系列、问法意图）；S11e/S11h
> （Office 查看器与文本视图）。跟踪 Issue #507。实现 Claude，审核 Codex。真实调用 0（问答回归在部署后线上做）。

## 0. 范围

| 部分 | 内容 |
|---|---|
| 合同与 Harness 数据 | 展示配置可按实体类型服务并声明“方法知识”；方法展示配置随方法候选包发布；导航新增“销售方法”领域与 `method` 问法意图 |
| 平台读取（Go） | 方法实体与 Claim 带类型、适用范围标签、逐项证据进入知识读取与 MCP 工具，文本统一标注；产品专用的读取路径不再把方法当产品 |
| 发布检查与专家编辑（Go） | 激活时检查方法列表值与证据逐项对齐、只引来源原文（失败关闭）；专家编辑方法 Claim 返回 typed error |
| 材料日期（Go） | 出处读取带回来源材料该版本的入库时间 |
| 前端 | “销售方法”导航领域；方法页（摘要/步骤/关键句/适用情形/注意事项，逐项打开原文，提示，来源材料与日期）；产品页“相关销售方法”；5 种语言 |
| 问答（Go + 前端） | 怎么卖/怎么讲/异议类问题先取已发布的方法 Claim，标“销售方法（培训材料，非产品事实）”；产品事实仍只来自产品 Claim |

不做：方法的人工编辑入口（SK-0 §3.4，修正走撤下 + 改材料 + 重编译）；Space 首页目录里的方法列表（首页目录是产品总览，
方法从导航进入）；材料自身的出版日期（平台与 Harness 都没有这项数据，见 §4）；问答提示词正文改动（§6.4）。

## 1. 平台怎么知道“这是方法知识”

平台从不在代码里写领域类型（PV-4 §2.1）。方法知识的识别来自**随 Release 发布的展示配置**：

- `PresentationProfile` 新增可选属性：`entity_types`（这个配置服务哪些实体类型，不论标签）与 `knowledge_class`
  （目前只有 `"method"`：SK-0 §1 的方法知识——培训材料，不是产品事实）；方法知识的读者文案也在配置里：`reading_note`
  （方法字段文本的第一行，告诉模型这是什么、怎么用）与 `notices`（实体 `identifiers.notice` 的取值 → 追加的一句）。
  平台只按 `knowledge_class` 这个枚举分派行为，文案全部来自数据（AGENTS 硬边界 4：业务文案只在 Harness）。
  `knowledge_class` 必须与 `entity_types` 一起出现；`classification_labels` 改为可空，但配置必须给出标签或类型之一。
  旧配置不受影响。
- 读取规则（Go 与前端同一条）：实体先找 `entity_types` 含其类型的配置（取第一个）；没有时，只在**没有** `entity_types`
  的配置里按标签相交找（与今天相同）。所以方法实体（标签里也有 `medical_insurance` 等险种标签）不会落到产品配置上，
  产品实体的取法不变。
- 方法类型 = 该 Release（发布检查时再并上当前 Active）里 `knowledge_class = "method"` 的配置所列的类型。
- 为什么不用部署配置（如 `ENTERPRISE_VERSIONED_ENTITY_TYPES` 那样的环境变量）：前端与问答都要知道哪些条目是方法，
  环境变量到不了前端，两份声明会不一致；展示配置随方法成员一起进入候选包（§2.2），首个方法发布时声明就在，不依赖
  部署步骤。代价：发布检查信任 Harness 发布的配置——Harness 漏发配置时方法会按普通实体显示与问答，这由 Harness 测试
  （§7）锁住：编译出方法成员的候选包必带方法配置（Active 已有同一配置时除外）。

版本引用不变量：SK-0 §7 要求“仅 subject 非 product 时允许版本引用为空”。现行平台只在 identity refresh 中检查版本引用
（`checkVersionRefs`：只有版本化类型的 Claim 才带、也才必须带 `product_version_ref`），方法 Claim 不带版本引用正好满足，
**无需收窄**；PV-4a 验收夹具里每个 identity refresh 的目标都含非版本类型实体的 Claim（`M1/s1`，类型 `method`），已锁住“目标里含方法 Claim 时仍通过”，本片不另加测试。

## 2. 合同与 Harness 数据

### 2.1 合同（`contracts.export` 重新导出）

- `presentation_profile.schema.json`：`entity_types: list[非空] | null`、`knowledge_class: "method" | null`、
  `reading_note: 非空 | null`、`notices: {非空: 非空}`（默认空）、`classification_labels` 默认空列表；校验器：标签与类型至少
  一个非空，`knowledge_class` 需要 `entity_types`，`reading_note`/`notices` 只能随 `knowledge_class` 出现。
- `navigation_profile.schema.json`：`question_intents` 的键增加 `"method"`（与 `sales`/`service` 并列，§6.1）。

### 2.2 方法展示配置（`catalog/method_cards.json` + `compilers/methods/profile.py`）

`method_cards.json` 增加 `presentation`：`display_name: "销售方法"`、`reading_note:
"销售方法（培训材料，非产品事实）：只用于回答怎么卖、怎么讲、如何应对异议；产品事实以产品的已发布知识为准，两类来源分开
标注。"`、`notices: {"product_info": "其中的产品信息以条款与已发布知识为准。"}`（卡片内容与取值协议不变，卡片版本不升：
展示文案不进取值请求）。配置由卡片生成：

`profile_id = entity_type`（`sales_method`）、`profile_version = 卡片版本`、`schema_pack_id = review_pack`、
`display_name`、`entity_types = [entity_type]`、`knowledge_class = "method"`、`reading_note`、`notices`、一个分区，字段按
卡片顺序：`field_key = predicate`、`short_title = title`、`description = definition`；`profile_sha256` = 配置其余内容的
规范 JSON 的 SHA-256。

`compile` 组包时：本次有方法 Claim 或方法实体要发布，且 Active 里 `presentation/<profile_id>` 的摘要与本配置不同（含
没有）时，带上该配置成员；只有移出的候选包（方法退出、`withdraw`）不带配置。

### 2.3 导航（`catalog/navigation.json`，版本 `2026-11-01.2`）

- 新领域 `sales_method` / “销售方法”（`entity_types: ["sales_method"]`），分组手写（生成器对没有 Schema Pack 的领域保留
  手写分组）：先是与产品领域相同的 11 个险种分组（同样的显示名与标签，顺序相同），再是“通用”（`scope:general`），再是
  产品形态、人生阶段、销售环节分组（标签与显示名取 `sales_taxonomy.json` 的标签与第一个词）。一个条目只进第一个命中的
  分组（现行导航规则），后面的分组同时给方法页的标签提供显示名。
- `question_intents.method`：怎么卖/如何卖、怎么讲/如何讲、怎么介绍/如何介绍、怎么说服/如何说服、怎么推销/如何推销、
  话术、异议、销售技巧、销售方法、讲解、促成（Claude 按 SK-0 §6 起草，线上未验证）。
- 导航单独由 `publish_navigation` 发布（机器决定，不含事实）；导航未发布前方法条目落在“其他”，读取与标注不受影响。

## 3. 平台读取（`internal/enterprise/knowledge`）

- `Entity` 增加 `Kind`（实体类型）、`Method`（是否方法知识）、`Notice`（`identifiers.notice`）。`Field` 增加 `Method`
  与 `Items`：方法 Claim 的值是字符串列表且与证据等长时，`Items[i]` 配 `Evidence[i]`。
- 文本（Agent、MCP、快问快答共用 `fieldText`）：方法字段第一行是配置的 `reading_note`，实体的 `Notice` 在配置 `notices`
  里有对应句时接在后面；列表逐项编号，每项后跟它自己的引文：`1. 项（引文：…，第 n 页）`。产品字段的文本逐字节不变。
- `knowledge_find_entity` 的条目行：方法写作 `编号：…；名称：…；标签：…；<reading_note>`；产品行不变。工具说明不改
  （说明进入每个 Agent 回合的提示，§6.4）；方法字段也能经 `knowledge_search_fields`/`knowledge_get_fields` 读到。
- 产品专用路径排除方法实体：问法里的产品匹配（`questionProducts` 与对外的 `QuestionProducts`）、产品名片段的字段标题
  排除表（只取非方法配置的标题）、原文片段所属产品（`SourceEntities`：只引用培训材料的原文片段因此标“所属产品未识别”，
  不会被当成某个产品的规定）、快问快答的产品字段匹配与概览字段。
- MCP 端点复用同一组知识工具，方法因此带同样的标注；固定 Release、权限过滤与只读接口都不变。

## 4. 发布检查、专家编辑与材料日期

### 4.1 激活检查（`release/methods.go`，`activationMembers` 里在 materialize 之后）

对候选包里的每个 Claim：其 subject 在目标成员中是方法类型的实体（§1）时，要求

1. 值是列表时，每项是非空字符串，且证据条数等于项数（`evidence[i]` 支撑 `value[i]`）；
2. 每条证据都是来源原文定位（不是 `EXPERT_REVISION`），且 Claim 没有 `expert_lock`。

任一不满足 → `CANDIDATE_INVALID`（细节写 slug），整包不激活；审核前的预检与详情共用这一步，所以待审列表也会看到。
“每项证据是同一页/同一块内的一段连续原文”已由现行回验保证：PDF 证据是单页上的 `[start, end)`，Office 证据必须落在一个
块内（S11d），引文必须逐字等于该切片；所以本检查只补“逐项对齐”这一条方法约定。

### 4.2 专家编辑

`expert.Service.Edit` 读到被改 Claim 后，subject 是 Active 中的方法类型实体时返回 `EXPERT_EDIT_METHOD_KNOWLEDGE`
（HTTP 409），不写修订记录、不发候选（SK-0 §3.4）。前端方法页不显示编辑按钮。

### 4.3 材料日期

平台知道的“材料日期”只有该版本材料的入库完成时间（`knowledge_revisions.completed_at`，即这份文件的这个版本被平台读完的
时刻）。出处读取（PDF 与 Office 两种响应）在 `source` 里增加 `revised_at`（RFC 3339，UTC）。方法页把它写成“入库
YYYY-MM-DD”（业务日，UTC+8 固定偏移，同 PV-4b），**不称作材料日期**：旧材料晚入库时它晚于材料本身。材料自身的出版
日期没有任何数据来源，记为 SK-4 待定项。

## 5. 前端（`frontend/src/enterprise`）

### 5.1 识别与排除

- `releaseView.profileFor(release, entity)` 按 §1 规则取配置并导出；`releaseSearch`、`releaseChanges` 改用它（方法字段的
  标题因此来自方法配置）。新模块 `methodView.ts`：`methodEntityIds(release)`（方法类型的实体）。
- Space 首页目录（产品总览）不列方法条目，产品数不变；概念键（`conceptKeys`）不取方法实体的 Claim，方法谓词不会变成
  概念，概念页与关系图不变。

### 5.2 导航

“销售方法”领域与分组全部来自导航数据（§2.3），现有导航组件不需要按方法改写；条目展开时的字段列表用方法配置的标题。

### 5.3 方法页（同一路由 `enterpriseEntity`；实体是方法时渲染 `EnterpriseMethod.vue`）

- 标题 = 方法名；顶部固定提示“销售方法（培训材料，非产品事实）”（界面文案，5 种语言）；实体有 `Notice` 且配置 `notices`
  里有对应句时另显示一条提示：界面有该取值的译文（`product_info` →“含产品信息：以条款与已发布知识为准”）用译文，否则显示
  配置里的原句。
- 适用范围：标签显示为导航分组的显示名（任一领域里第一个以该标签分组的显示名），找不到时显示标签本身；`family:<key>`
  显示为“系列：<系列名>”，链接到同一 Release 中该系列的产品条目（PV-4b 的 `product_family`），系列不在本 Release 时只显示键。
- 五项按方法配置的字段顺序：文本项一段文字，后跟“来源 1…n”；列表项逐项编号，每项后跟“原文”，打开该项自己的证据
  （`evidence[i]`）。打开原文用现有 `CitationPanel`（PDF 查看器、Office 查看器与 S11h 文本视图），固定本页 Release。
  未收录的项显示现有的未知状态文案（“材料未提及”）。列表与证据不等长（只可能出现在检查之前发布的数据里）时按普通字段显示来源。
- 来源材料与日期：方法各 Claim 证据里出现的每份材料（按 `source_ref` 去重、按首次出现排序）读一次出处，显示
  “来源材料：<文件名>（入库 YYYY-MM-DD）”；读取中/读不到各有提示，读不到不影响正文。“更新于 YYYY-MM-DD”取方法 Claim 的
  `maintenance.changed_at` 中最新的一个（没有则不显示）。
- 加载、空（Release 里没有此条目）、失败（可重试）沿用实体页现有状态。

### 5.4 产品页“相关销售方法”

产品页字段之后、只在有相关方法时显示一个链接列表（只有方法名，不带方法内容；方法内容不进入产品字段页）：先列标签含
`family:<产品系列键>` 的方法，再列与产品分类标签相交的方法，各自按导航顺序。`scope:general` 不算相交。

### 5.5 文案

新增文案进 `enterpriseKnowledge.method.*` 与 `chat.sourceTierMethod`，5 种语言（zh-CN、en-US、ja-JP、ko-KR、ru-RU；
zh-TW 沿用 zh-CN）。

## 6. 问答

### 6.1 意图（数据）

`method` 意图只看导航 `question_intents.method` 的词组，匹配方法同 `question_terms`；它与销售/服务意图**互相独立**：销售/
服务决定产品版本范围（PV-4b，不变），方法意图只决定是否先取方法。Go 里只有意图键 `method`，没有问法词。

### 6.2 快问快答取哪些方法（`QuestionFields`）

方法意图命中时，先按下列得分挑方法（同分按导航顺序）：名称出现在问题中 3；与问题点名的产品相关（§5.4 的系列或标签
规则）2；问题里出现某个导航分组的显示名且方法带该分组的标签 1。都为 0 时，取与问题共享至少 2 个二元组（去掉命中的意图
词）的方法，按共享数排序。依次取各方法已发布、有证据的字段（按方法配置顺序），最多占本次上限的一半（12 条中的 6 条），
**放在产品字段之前**（SK-0：这类问题先查方法）；剩余名额按现行规则给产品字段。意图未命中时不取任何方法字段，产品结果与
今天相同。

### 6.3 标注

- 快问快答的方法命中仍是 `source_tier = release`（固定 Release 句柄、钉住校验与上游来源登记都按 release 处理），另带
  `knowledge_class = method`；段落前**不加**“已发布知识（审核过）”，正文第一行就是配置的 `reading_note`（§3），平台不写
  方法文案。
- Agent/MCP 工具结果的行同样带 `knowledge_class = method`；聊天界面的来源标签（`sourceTier`）对它显示“销售方法（培训
  材料，非产品事实）”，其余来源标签不变。

### 6.4 不改提示词正文

`AnswerRules`、`KnowledgeNotice` 与工具说明的正文不改（受保护测试锁定）。方法的用法说明只随方法段落出现（§3），没有方法
命中的问答与今天逐字节相同。

## 7. 验收测试（RED 提交先于实现）

Go：
- 读取：方法实体带类型/标签/提示；方法字段标题来自方法配置（不取产品配置）；`Items` 与证据逐项对应；文本带标注与逐项
  引文；产品字段文本不变；产品匹配、原文所属产品、产品名片段不受方法影响；`knowledge_find_entity` 方法行。
- 发布：列表与证据不等长、项不是字符串、证据为专家修订、带 `expert_lock` → `CANDIDATE_INVALID`；对齐的方法包通过；
  方法配置只在 Active 中时同样检查；没有方法配置时产品包不受影响；identity refresh 目标含方法 Claim 时仍通过。
- 专家编辑：方法 Claim → `EXPERT_EDIT_METHOD_KNOWLEDGE`，不写记录；HTTP 409。
- 出处：PDF 与 Office 响应带 `revised_at`。
- 问答：方法意图命中 → 方法字段在前、最多一半；名称/产品/分组/二元组四种挑选；意图未命中 → 不含方法；方法命中带
  `knowledge_class` 与段落标签；与销售/服务意图独立。

前端（vitest）：配置按类型选取；方法页（提示、标签名、系列链接、逐项原文打开第 i 条证据、来源材料与入库日期、更新于、
状态）；产品页相关方法（系列优先、无相关时不显示、不含方法内容）；首页目录与概念不含方法；聊天来源标签；5 种语言键齐全。

Harness：合同校验器；方法配置生成与摘要；编译带配置（Active 已有同一配置时不带）；导航方法领域分组与产品领域、词表一致；
`method` 意图词组合法。

## 8. 改动范围与门禁

- Harness：`contracts/knowledge.py`（导航模型移到新的 `contracts/navigation.py`，使其保持 500 行以内）、`contracts/export` 产物、`catalog/method_cards.*`、`catalog/navigation.json`、
  `compilers/methods/{profile,compile}.py` 与测试。
- Go：`internal/enterprise/{knowledge,release,expert,source,capture,chatsource}` 与 `internal/enterprise/{mount,citation}.go`。
- 前端：`frontend/src/enterprise` 内（新文件 `methodView.ts`、`EnterpriseMethod.vue`、`RelatedMethods.vue`、样式）。
- 不改上游文件（G10 不升）；新文件都在企业目录（G11 不升）；文件 ≤ 500 行。
- 门禁：受影响 Go 包逐个 build/vet/test、`golangci-lint --new-from-rev`；前端 type-check/vitest/build；Harness
  pytest/ruff/mypy；`tests/architecture`；`git diff --check`。非测试代码超过 1500 行时拆成 SK-3a（§1–§5）与 SK-3b（§6）。
