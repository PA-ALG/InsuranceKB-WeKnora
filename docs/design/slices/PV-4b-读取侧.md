# PV-4b 读取侧（销售状态、品牌系列分组、版本链与问答）

> 状态：Spec（2026-11-01，Claude）。设计依据：[PV-0](PV-0-产品版本与生命周期.md) §5.3、§5.4；
> [附录 A](PV-0-附录A-身份发布同步与迁移.md) §3.2（销售状态评价）；[PV-4](PV-4-发布与读取.md) §0、§4（PV-4a 已合并：
> 产品实体可带 `lifecycle`、`product_family`，版本之间有 `supersedes` 关系）。跟踪 Issue #501。实现 Claude，审核 Codex。
> 只读不写：不改合同里已发布的成员，不改发布与审核路径。真实调用 0（问答回归留到部署后，见 §6）。

## 0. 范围

| 部分 | 内容 |
|---|---|
| 平台读取（Go，`internal/enterprise/knowledge`） | 读取时计算销售状态；实体带销售期、系列、前驱/后继；工具与问答文本标注版本 |
| 前端（`frontend/src/enterprise`） | 导航按系列聚合、状态标签、默认隐藏停售可切换；版本页显示销售期、状态、前驱/后继链接 |
| 问答（Go + Harness 导航数据） | 销售类问题的全量比较范围排除停售/未开售；点名产品不删、标注版本；在保服务按投保日期选版本 |

不做：Space 级时区配置（首期固定 `Asia/Shanghai`，PV-4 §4）；问答提示词改动（受保护测试锁定提示词全文，本片只改
送入模型的数据与标注）；按角色可见性。

## 1. 销售状态（平台与前端同一规则）

### 1.1 评价日

评价日 = 读取时刻在 Space 业务时区的日历日。首期业务时区固定为 `Asia/Shanghai`，按 **UTC+8 固定偏移**计算（中国自 1991
年起无夏令时；不依赖运行环境的时区数据库，Go 与浏览器结果一致）。平台读取服务注入时钟（默认当前时间，测试可固定）。

### 1.2 四态（附录 A §3.2 的可执行形式，按顺序取第一条成立的）

输入：实体的 `lifecycle`（可缺）与评价日 `D`。日期按 `YYYY-MM-DD` 字符串比较（合同已保证合法日历日）。

1. 无 `lifecycle` → `unknown`；
2. `sale_start` 已知且 `D < sale_start` → `not_yet_on_sale`；
3. `sale_end` 已知且 `D ≥ sale_end` → `discontinued`（日期明确时以日期为准，来源状态是固定提交时的快照）；
4. `sale_start` 已知且 `sale_start ≤ D`，并且满足其一 → `on_sale`：
   - `sale_end` 已知（此时 `D < sale_end`）且来源状态不是 `discontinued`；
   - `sale_end` 未知且来源状态为 `on_sale`（显示“在售（据 `basis_date` 数据）”，无 `basis_date` 时不加括号）；
5. 其余 → `unknown`（未匹配、日期缺失、来源状态与日期矛盾）。**`sale_end` 为空本身不推出在售。**

共享测试向量：`internal/enterprise/knowledge/testdata/sale_status_vectors.json`，Go 测试与前端测试读同一文件，结果必须
逐条一致（含边界：开始当日、结束当日、空结束、来源停售而结束在未来、无开始）。

### 1.3 显示用语（前端 5 种语言；平台中文）

| 状态 | 中文 | 说明 |
|---|---|---|
| `on_sale` | 在售 | 结束日未知时附“据 YYYY-MM-DD 数据” |
| `discontinued` | 停售 | |
| `not_yet_on_sale` | 未开售 | |
| `unknown` | 销售状态未知 | |

销售期文本：`YYYY-MM-DD 至 YYYY-MM-DD`；结束未知时 `YYYY-MM-DD 起`；开始未知时 `至 YYYY-MM-DD`；都未知不显示。

## 2. 平台读取（Go）

- `knowledge.Entity` 新增：`Lifecycle *Lifecycle`、`Family *Family`、`Status`（读取时计算）、`Predecessors`、
  `Successors`（同一 Release 内 `predicate = supersedes` 的关系：`from` 为新版本、`to` 为前驱；只认两端都是该 Release
  可见实体的关系，关系 ID 不另作校验——发布时已由 PV-4a 校验）。
- 新文件 `knowledge/versions.go`：`Lifecycle`、`Family`、状态计算、评价日、版本标注文本；`Service` 增加时钟
  （`WithClock`，默认 `time.Now`），工具执行时新建的只读服务沿用同一时钟。
- **版本标注只在实体带 `lifecycle` 时出现**：没有版本数据的实体（线上全量元数据发布之前的全部条目、非产品实体）文本与
  今天逐字节相同，避免发布前的问答回归。标注形如 `（停售；销售期 2024-04-23 至 2024-09-01）`（结束日未知的在售写作
  `（在售，据 2026-10-20 数据；销售期 2025-10-01 起）`，避免括号套括号），用于：
  - 字段文本首段：`<实体名><标注> · <字段>：…`（Agent 工具、MCP、快答共用 `fieldText`）；
  - 引用标题 `knowledge_title` / 快答 `KnowledgeTitle`：同一形式；
  - `knowledge_find_entity` 的每行：`产品编号：…；名称：…` 之后追加 `；销售状态：…；销售期：…；系列：…；前一版本：…；
    后续版本：…`（有值才出现）。
- 不改：索引的成员校验、可见性与 Release 固定读取、MCP 工具名与参数。

## 3. 前端

- 新模块 `productVersions.ts`：读取实体的 `lifecycle` / `product_family`、按 §1.2 计算状态（同一向量文件验收）、前驱/后继
  （按 `supersedes` 关系，名称取实体首个名称，无名称时显示 ID；与 §2 相同，一端不在本 Release 的关系不显示）、导航条目按系列聚合。
- 导航（`navigationView.ts`、`EnterpriseNavigation.vue`、`NavigationEntry.vue`）：
  - 每个险种分组内，同一 `product_family.key` 且 ≥ 2 个条目的聚合成一个系列小标题，组内按 `sale_start` 降序（未知在后），
    其余条目照旧；前端不读登记表、不另写品牌规则，缺系列的条目不聚合；
  - 带 `lifecycle` 的条目显示状态标签；
  - 默认隐藏 `discontinued`，筛选框旁出现“含停售（N）”开关（只在本 Release 有停售条目时出现）；**当前打开的条目即使停售
    也始终显示**；搜索时同样受开关约束。
- 版本页（`EnterpriseEntity.vue` 只加一行组件）：新组件 `ProductVersionMeta.vue` 显示状态标签、销售期、系列名称、前一版本与
  后续版本链接（链接留在同一 Release）；无任何版本数据时不渲染。
- i18n：`enterpriseKnowledge.version.*` 五种语言同步新增。
- 引用（PDF / Office）行为不变。

## 4. 问答

### 4.1 问题类型是导航数据

导航成员新增可选 `question_intents`：`{"sales": [[词…]…], "service": [[词…]…]}`，与 `question_terms` 同形（每组 1–3
个词、全部出现才算命中）。词表写在 Harness `catalog/navigation.json`（版本升 `2026-11-01.1`），合同
`NavigationProfile.question_intents` 可选、`extra=forbid` 不变，导出 `contracts/navigation_profile.schema.json`。
平台只按这份数据判断，不写任何业务词（硬边界 4）。同一问题两类都命中或都不命中 → 不按类型过滤。

### 4.2 `QuestionFields` 的版本规则

- **销售类**：问题没有点名产品、按字段比较全部产品时，比较范围排除状态为 `discontinued`、`not_yet_on_sale` 的实体；
  `unknown` 与无版本数据的实体保留（标注由 §2 给出）。**点名的产品不删**（点名问一款停售产品能不能买，应答出它已停售）。
- **点名产品**：同名多版本已全部命中（现有匹配规则），不默认选最新；各版本由 §2 的标注区分。
- **在保服务**：问题含投保日期（`YYYY年M月D日`、`YYYY-MM-DD`、`YYYY/M/D`、`YYYY年M月`、`YYYY年`，取第一个）且点名
  产品有多个版本时，只保留销售期覆盖该日期的版本（按日期精度：年/月覆盖即算；日期未知的一端不排除）；一个都不覆盖时保留
  全部（由标注让模型追问）。“同一产品的版本”＝首个名称相同或由 `supersedes` 相连的点名实体，按这一分组各自选择，问题点名的
  其他产品不受影响。没有日期或没有点名产品时不过滤。
- 读取仍固定在本轮 Active / pinned Release；权限与可见性不变。

## 5. 验收（RED，单独提交）

- **共享向量**：Go `TestSaleStatusVectors` 与前端 `productVersions.spec.ts` 读同一 JSON，逐条一致。
- **Go**：实体带/不带 `lifecycle` 的 `FindEntities` / 工具行文本；字段文本与引用标题在无版本数据时与旧版逐字节相同、有数据时
  带标注；前驱/后继（含一端不可见的关系被忽略）；固定时钟下评价日在 UTC+8 跨日边界正确。问答：销售类问题全量比较时停售与
  未开售被排除、unknown 保留、点名停售产品保留；两类都命中不过滤；在保服务按日期（日/月/年精度）选版本、全不覆盖时保留全部；
  无 `question_intents` 的导航行为与旧版相同。
- **前端**：导航系列聚合与排序、状态标签、默认隐藏停售与开关、当前条目始终可见、搜索受开关约束；版本页显示状态、销售期、
  系列与前驱/后继链接，无数据时不渲染；五种语言键齐全。
- **Harness**：`question_intents` 合同校验（组 1–3 个非空词；只允许 `sales` / `service`）；导航文件版本与导出 `--check`。
- 门禁：Go build/vet/受影响包测试、golangci-lint（new-from-rev）、前端 type-check / vitest / node 测试 / build、Harness
  pytest/ruff/mypy、合同导出 `--check`、`tests/architecture`、手写文件 ≤ 500 行、`git diff --check`。

## 6. 上线与回归

部署本片后、首次全量元数据发布（PV-4 §3.4）之前，线上实体都没有 `lifecycle`：页面与问答文本与今天相同。元数据发布后再跑
问答回归（已发布问答集，DeepSeek 生产模型，预算随部署 Issue 申请），重点看停售产品与同名多版本的回答。
