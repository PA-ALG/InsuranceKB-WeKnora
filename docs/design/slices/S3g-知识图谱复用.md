# S3g · 知识图谱：复用 WeKnora 原生图谱，数据只来自已发布版本

> 状态：用户 2026-10-18 选定方案 ①（"按1的做吧"）：复用 WeKnora 自带的 Wiki 图谱界面，受管库只放开图谱需要的只读接口，数据只来自已发布版本 ｜ 作者：Claude Code
> 依据：蓝图硬边界 3（跟随上游）、4（平台通用）、5（受管读入口只读 Active 或 pinned Release）；修订 S1b §6 的非目标"不为受管库提供原生页面的只读投影"
> 拆分：S3g-1 Harness 投影（Claude 实现）· S3g-2 平台只读适配（Go，Codex 实现）· S3g-3 前端入口（Codex 实现）

## 1. 目标

- 业务人员在企业空间对应的 Wiki 知识库里打开 WeKnora 自带的"图谱"页签，看到已发布的产品、概念以及它们之间的关系：
  - 节点：产品、概念；
  - 连线：产品陈述了该概念（字段）。
- 图谱的布局、拖拽缩放、搜索、展开邻居、图例、侧边详情，全部沿用 WeKnora 原生实现；前端的 `WikiBrowser.vue` 不改，以后 WeKnora 升级图谱，我们直接跟上。
- 底线不变：
  - 受管库里能看到的只有 Active Release 的内容，不读原生 `wiki_pages`；
  - 其他原生 Wiki 入口和所有写操作，照旧返回 409。

## 2. 设计

### 2.1 S3g-1 Harness：Wiki 投影成员（新成员种类 `wiki_projection`）

- **合同** `WikiProjection`（`contracts/knowledge.py`，导出 `wiki_projection.schema.json`）：
  ```json
  {"projection_id": "enterprise", "projection_version": "2026-10-18.1",
   "pages": [{"slug": "entity/1828", "title": "平安安佑福（全能版）重大疾病保险", "page_type": "entity",
              "summary": "重疾险 · 投保年龄 0–55 周岁", "content": "<markdown>", "out_links": ["concept/waiting_period", "…"]}]}
  ```
  - `page_type` 只能是 `entity` 或 `concept`（原生图例中已有这两种）。
  - slug 唯一；`out_links` 只能指向本投影中的 slug，且不能指向自己。
  - `content` 是 Markdown，使用原生的 `[[slug|名称]]` 双链语法。
- **生成规则**（`compilers/graph/projection.py`，纯函数，输入是一个 Release）：
  - **产品节点**：每个 entity 一个节点，slug 为 `entity/<entity_id>`。
    - `summary` 写险种名，加上 1 个短字段（投保年龄），超过 40 字截断。
    - `content` 依次写：险种、几项短字段（投保年龄、保险期间、等待期、犹豫期，有取值才写，每项截到第一句）、"相关概念"的双链列表，以及一行"在企业知识中查看完整产品页"的链接（`/platform/enterprise/<space>/entities/<id>`）。
  - **概念节点**：每个概念（被 ≥ 2 个条目陈述的字段，规则同前端 `conceptKeys`）一个节点，slug 为 `concept/<field_key>`。
    - `summary` 用概念说明的 `definition`（有 concept 成员时），否则用 profile 中的字段说明，截到 60 字。
    - `content` 写定义，以及"涉及产品"的双链列表；有模型生成的内容时标注"模型补充"，并附一行概念页链接。
  - **连线**：产品 → 概念（该产品对该字段的 Claim 为 present 或 absent_explicitly）。
  - 只用 `access_scope == "space"` 的成员；不放入任何证据原文。
- **发布命令** `python -m insurance_harness.compilers.graph.publish --space S --reason TEXT`：
  - 读 Active，生成投影；投影与 Active 中现有投影的成员摘要相同时什么也不做；
  - 否则以 Active 为 base，提交只含这一个 `wiki_projection/<projection_id>` 成员的候选包，由人工决定并激活；
  - 输出一行 JSON；失败时输出一行 `{"stopped": <code>}` 并以 2 退出。
  - 产品或概念重新发布之后执行一次。

### 2.2 S3g-2 平台：受管库的原生 Wiki 只读适配（Go，项目自有包）

- **放开的只读接口**（仅 GET，仅对受管的 Wiki KB）：`/wiki/graph`、`/wiki/pages/*slug`、`/wiki/pages`、`/wiki/search`、`/wiki/stats`、`/wiki/index`、`/wiki/folders`。
  - 这些是原生图谱页加载与交互时会调用的接口（核对见调研：`WikiBrowser.vue` 挂载时会请求 index、pages、folders、stats，图谱请求 graph、pages/:slug、search）。
  - 其余原生 Wiki 路由，包括 `/wiki/issues`、`/wiki/lint`、`/wiki/revisions/*` 和全部写路由，对受管库仍返回 409 `RELEASE_MANAGED_KB`。
- **鉴权顺序**：先走原有的 `Viewer` 与 `KBAccessRead` 权限守卫，权限通过后，才由适配器回答。受管库守卫只负责放行这 7 个 GET，不能在权限检查之前就返回数据。
- **数据**：
  - 读该 KB 所属 Space 的 Active Release 中的 `wiki_projection` 成员，转换成原生 `types.WikiPage` 列表：InLinks 由 OutLinks 反推，`status` 为已发布。
  - 再复用原生的纯函数 `computeGraphSubset`（overview 与 ego 两种模式、limit、types 过滤）和原生的响应格式，前端无需区分。
  - 没有投影成员时，返回空图与空列表（200），不回退去读原生 `wiki_pages`。
  - search 在标题、slug、summary 上做子串匹配；stats 与 index 返回由投影计算的最小数据（页面数、无进行中的任务、无问题）。
- **平台通用**：适配器只认识通用的投影页面（slug、标题、类型、摘要、Markdown、链接），不解释险种、字段或 Claim（硬边界 4）。
- **上游文件**：
  - `routes_knowledge.go` 已在上游补丁登记中，本片只把这 7 条路由的处理函数换成"受管库走适配器、非受管库走原生 handler"的包装，原生 handler 本身不改；在 `upstream-patches.md` 追加一行。
  - 受保护测试 `native_wiki_guard_test.go` 由 Claude 单独提交修正：把这 7 个 GET 从"必须 409"中排除，其余断言不变。
- **会话 Space 列表**：`GET /api/v1/enterprise/spaces`（项目包 `session.go`）每项增加 `wiki_kb_id`，供前端跳转到图谱。

### 2.3 S3g-3 前端：入口

- 受管库的知识库页允许"图谱"页签（`useReleaseCustody.ts` 不再把 `graph` 强制切回 `schema`，`materials` 仍然禁止）；`KnowledgeBase.vue` 在受管库只挂载 WikiBrowser 的图谱视图。
- 企业空间页增加"关系图"链接，指向该 Space 的 Wiki KB 的图谱页签。
- 前端的 `WikiBrowser.vue` 不改。

## 3. 验收

- **S3g-1**（RED，Claude 编写）：投影的合同校验；节点、连线与 summary 规则；只用 space 范围的成员；不含证据原文；概念规则与前端一致；发布命令只提交投影成员、无变化时跳过。
- **S3g-2**（RED，Claude 编写，项目包内的适配器测试）：
  - 受管库的 7 个 GET 由投影回答，overview、ego、page、search 的结果与原生格式一致；
  - 没有投影时返回空；
  - 其余路由与所有写操作仍返回 409；
  - 无权限时先被权限守卫拒绝；
  - 非受管库仍走原生 handler。
- **S3g-3**：
  - 受管库可以打开图谱页签，`materials` 仍然禁止；
  - 空间页的"关系图"链接指向正确的 KB 与页签。
- **上线**：App 与 UI 各构建 1 次，与 S6a、RV4、S3f、RV4b 合并为同一次构建，届时请用户批准。
