# S3h · 全文搜索与本版变化：读者能搜到字段内容，能看到这一版改了什么

> 状态：用户 2026-10-19 同意（"同意，继续吧"）｜ 作者：Claude Code
> 来源：对比 WeKnora 原生 Wiki 后提出的两项借鉴（原生 Wiki 有全文搜索和修订对比；企业知识页只能按名称搜索，看不到版本之间的变化）。
> 拆分：S3h-1 全文搜索 · S3h-2 本版变化。两片都只改前端，都改 `frontend/src/enterprise/`，按顺序实现：Codex 实现，Claude 审核。

## 1. 目标与不做的事

- **S3h-1**：首页搜索框除了按名称找产品和概念，还能找到字段内容。每条结果显示产品、字段、命中处的片段，点开跳到产品页的那个字段。
- **S3h-2**：首页显示"本版相对上一版：新增 / 修改 / 删除 N 项"，点开进入变化列表；产品页中这一版有改动的字段标"本版更新"，可以展开看上一版的取值。
- 两片都只用已经读取的发布版本数据，**不调用模型，不改平台接口**，人与 Agent 读取的仍是同一个发布版本。
- 不做：
  - 不做服务端搜索（规模上来后由蓝图 §7.8 的知识服务接口提供，到时替换本片的前端实现）；
  - 不做页面编辑；
  - 不做导航、展示设置、概念说明这类非字段成员的变化明细（只计数）。

## 2. S3h-1 全文搜索

### 2.1 匹配规则（`frontend/src/enterprise/releaseSearch.ts`，纯函数）

- 接口：`searchFields(release: Release, query: string, limit = 50): { hits: FieldHit[]; total: number }`。
  - `FieldHit = { entityId, name, slug, fieldKey, fieldTitle, parts: { text: string; mark: boolean }[] }`。
  - `name`：条目显示名。
  - `slug`：Claim 的 `logical_slug`。
  - `fieldKey`：谓词。
  - `fieldTitle`：profile 中的字段短标题，没有时用谓词。
  - `parts`：片段，命中处 `mark: true`。
- **范围**：只搜 `state = present` 且取值非空的 Claim。
  - 取值是数组时，用"；"连接；
  - `unknown` 与 `absent_explicitly` 不进入结果。
- **规范化**：查询与文本都先做 NFKC，再转小写；连续空白压成一个空格。
- **多个词**：查询按空白拆成词，每个词都要出现在该字段的取值或字段标题中。例如"犹豫期 20日"只命中犹豫期取值含 20 日的产品。
- **片段**：
  - 在取值中找第一个词的第一次出现，没有就找下一个词；所有词都只在标题里命中时，从取值开头截取。
  - 片段取命中处前 20 个字、后 40 个字，被截断的一侧加"…"。
  - 片段内所有词的出现都标 `mark`。
- **顺序**：
  - 产品顺序与概念页对照表相同：先按导航分组顺序，同组内按条目成员顺序，未分组的条目排最后；
  - 同一产品内，按 profile 中的字段顺序，profile 里没有的字段按成员顺序排在后面。
- **数量**：`total` 是全部命中数，`hits` 最多 `limit` 条；查询为空时返回空结果。

### 2.2 页面（`EnterpriseSpace.vue`）

- 搜索框保持原位，原有的产品与概念按名称过滤不变。
- 查询非空时，在产品与概念结果之后增加一节"字段内容" `[data-search-fields]`：
  - 每条结果 `[data-search-hit]` 显示：产品名 · 字段标题，下一行是片段，命中处用 `<mark>`；
  - 整条结果链接到 `{ name: 'enterpriseEntity', params: { spaceId, entityId }, query: { release }, hash: '#<fieldKey>' }`，固定在当前读到的发布版本；
  - 超过 50 条时，显示"共 N 条，显示前 50 条"。
- 产品、概念、字段内容都没有命中时，显示"没有找到包含“{查询}”的内容"。
- 结果是一个列表，可用键盘 Tab 到每条结果；不在输入时自动跳页。
- 文案：zh-CN，其余 4 种语言同步。

### 2.3 验收（RED，Claude 编写，受保护）

- `releaseSearch.spec.ts`：
  - 取值命中；
  - 多个词同时满足（标题加取值）；
  - 不搜 unknown 与 absent；
  - 全角与大小写；
  - 片段截断与标记；
  - `limit` 与 `total`；
  - 字段标题取自 profile；
  - 产品顺序按导航。
- `spaceSearch.spec.ts`：
  - 输入后出现字段内容结果，链接固定在当前版本并带锚点；
  - `<mark>` 标出命中；
  - 无结果文案；
  - 查询为空时不显示该节。

## 3. S3h-2 本版变化

### 3.1 数据

- `Release` 增加可省略的 `base_release_id`：平台已在返回，前端补上类型。
- 新增 `frontend/src/enterprise/releaseChanges.ts`，纯函数 `releaseChanges(current, base)`。
  - 只比较 `kind = claim` 的成员，按 `logical_slug` 对齐、按 `member_digest` 判断是否改变；
  - 返回 `{ added, changed, removed, otherChanged }`：
    - 前三项的每行带 `entityId`、`name`、`fieldKey`、`fieldTitle`、`slug`、`before`、`after`（`FieldView` 或 null）；
    - `otherChanged` 是非 Claim 成员的变化数。
  - 名称与标题：删除项取自 `base`，其余取自 `current`。
- 上一版就是 `base_release_id` 指向的版本。没有 `base_release_id`（第一版）时，没有变化可显示。

### 3.2 页面

- **首页**：
  - 读完当前版本后，若有 `base_release_id`，再按 ID 读取上一版；
  - Claim 有变化时，在版本号旁显示一行 `[data-space-changes]`："本版更新：新增 a · 修改 b · 删除 c →"，链接到变化页；
  - 没有 Claim 变化，或上一版读取失败时，不显示这一行，首页其余部分不受影响。
- **变化页**：`EnterpriseChanges.vue`，路由 `enterpriseChanges`：`enterprise/:spaceId/changes`，query `release`。
  - 标题："版本 N 相对版本 M 的变化"。
  - 按产品分组列出变化行 `[data-change]`：
    - 类型标签：新增、修改或删除；
    - 字段标题；
    - 修改项并列显示"上一版 / 本版"取值，用与产品页相同的字段组件；
    - 字段标题链接到产品页的该字段，固定在当前版本；删除项不链接。
  - 只有非字段成员变化时，显示"本版没有字段内容变化（更新了 K 项导航、展示设置或概念说明）"。
  - 状态：
    - 加载中 `role="status"`；
    - 读取失败 `role="alert"`，带重试按钮；
    - 第一版没有上一版时，显示"这是第一个发布版本"。
- **产品页**（`EnterpriseEntity.vue`）：
  - 读完当前版本后读取上一版；
  - 本版新增或修改的字段，在标题旁显示"本版更新" `[data-field-updated]`；
  - 点它展开"上一版"取值 `[data-field-previous]`，新增的字段显示"上一版没有这一项"；
  - 上一版读取失败时，不显示这些标记。
- 所有读取都按版本 ID 固定读，不读 Active 代替。切换页面时，丢弃旧请求的结果。
- 文案：zh-CN，其余 4 种语言同步。

### 3.3 验收（RED，Claude 编写，受保护；S3h-1 合并后提交）

- `releaseChanges.spec.ts`：新增 / 修改 / 删除 / 未变化、非 Claim 成员只计数、名称来源、没有上一版。
- `releaseChangesPage.spec.ts`：
  - 首页变化行的计数与链接；
  - 无变化时不显示；
  - 上一版读取失败时首页不受影响；
  - 变化页分组与"上一版 / 本版"；
  - 只有非字段变化时的文案；
  - 第一版的文案；
  - 失败重试；
  - 产品页的"本版更新"与展开上一版。

## 4. 改动范围

- `frontend/src/enterprise/`：
  - 新增：`releaseSearch.ts`、`releaseChanges.ts`、`EnterpriseChanges.vue`；
  - 修改：`EnterpriseSpace.vue`、`EnterpriseEntity.vue`、`EnterpriseField.vue`（如需挂标记）、`enterpriseApi.ts`（类型）；
  - 样式文件。
- `frontend/src/router/index.ts`：S3h-2 增加 1 条路由，在 `docs/design/upstream-patches.md` 追加一行登记。
- `frontend/src/i18n/locales/`：5 种语言。

## 5. 上线

两片合并后，与下一批前端改动一起构建 UI 1 次，构建前请用户批准。不调用模型，不改发布数据。
