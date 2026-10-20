# S6d · 延伸阅读页面：在产品导航下看到原生 Wiki 整理的页面

> 状态：用户 2026-10-20 要求"部署完毕后，我就能在［产品导航中］看到自由抽取的 wiki"｜ 作者：Claude Code ｜ 关联 #253、S6c（#254）
> 实现方：Codex（前端）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 目标

- **导航**：企业知识左侧导航中，每个产品展开后，在最后一个字段分组之后增加一组"延伸阅读（模型整理）"，后面跟页数。
  - 默认折叠，展开后列出该产品的全部 `wiki_page` 页面：先概念页，再实体页，各自按标题排序；
  - 链接固定在当前版本。
- **页面视图**：新路由 `enterpriseWikiPage`，路径 `enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug`，query `release`。页面依次显示：
  - 标题；
  - 醒目的"模型整理，未逐条审核"标签；
  - 摘要；
  - 正文：Markdown 渲染后经 DOMPurify 清洗；
  - 出处列表："出处 1…n"，点开用 `CitationPanel` 按版本打开原文；
  - 返回产品页的链接。
- **页面之间的链接**：正文中的 `[[wiki/<entity>/<type>/<slug>|文字]]` 渲染为站内链接，点击跳到同一版本的那个页面。其他 `[[…]]` 只显示文字。
- 不做：问答读取页面（另开，作为第三类来源"模型整理（未逐条审核）"）；页面编辑；页面搜索。

## 2. 数据（`frontend/src/enterprise/wikiPagesView.ts`，纯函数）

```ts
export interface WikiPageEntry { key: string; pageType: 'concept' | 'entity'; title: string; slug: string }
export function wikiPages(release: Release, entityId: string): WikiPageEntry[]
export interface WikiPageView {
  key: string; pageType: 'concept' | 'entity'; title: string; summary: string; aliases: string[]
  content: string; slug: string; evidence: { index: number; quote: string; page: number }[]
}
export function wikiPageView(release: Release, entityId: string, pageKey: string): WikiPageView | null
```

- 只取 `kind = "wiki_page"`、`logical_slug` 以 `wiki/<entityId>/` 开头、`access_scope = "space"`、且 `entity_refs` 含该产品的成员。
- `key` 取 payload 的 `page_key`，形如 `concept/xxx`；`slug` 是成员的 `logical_slug`。
- 排序：概念在前、实体在后，各自按标题的 `localeCompare('zh')` 排序。
- `wikiPageView`：找不到时返回 null。`evidence` 按顺序编号，`page` 取 `locator.page`。

## 3. 页面与状态

- 只按 `release` 参数读取；没有该参数时读 Active，之后的所有链接都带读到的版本 ID。
- 状态：
  - 加载中：`role="status"`；
  - 读取失败：`role="alert"` 加重试；
  - 页面不存在：显示"该版本中没有这个页面"。
- **正文安全**：`marked` 转 HTML 后用 DOMPurify 清洗，不允许脚本、事件属性与外链脚本；站内链接用 `data-wiki-link` 标记，由点击处理器调用 `router.push`。
- **数据钩子**（验收依据）：
  - 导航分组 `<details data-nav-wiki>`，与字段分组同样用 `<details>`，但默认不带 `open`；
  - 页面根 `[data-wiki-page]`；
  - 标签 `[data-wiki-generated]`；
  - 站内链接 `a[data-wiki-link=<slug>]`；
  - 出处按钮 `[data-wiki-source]`。
- 文案：zh-CN，其余 4 种语言同步。
  - 中文文案："延伸阅读（模型整理）""模型整理，未逐条审核""该版本中没有这个页面""出处 {n}"。

## 4. 验收（RED，Claude 编写，受保护）

- `wikiPagesView.spec.ts`：
  - 只取该产品的页面；
  - 排序；
  - 不取其他产品与非 Space 成员；
  - 页面视图的字段与出处编号；
  - 不存在时为 null。
- `enterpriseWikiPage.spec.ts`：
  - 按版本读取；
  - 标题、标签、摘要、正文；
  - 站内链接跳到同一版本；
  - 脚本被清除；
  - 出处打开 `CitationPanel`，参数正确；
  - 页面不存在；
  - 失败重试。
- `navigationWiki.spec.ts`：
  - 有页面的产品显示"延伸阅读（模型整理）"与页数，链接固定版本；
  - 没有页面的产品不显示。

## 5. 改动范围

- `frontend/src/enterprise/`：
  - 新增 `wikiPagesView.ts`、`EnterpriseWikiPage.vue`；
  - 修改 `NavigationEntry.vue` 与样式。
- `frontend/src/router/index.ts`：1 条路由，在 `upstream-patches.md` 追加登记行。
- 语言包：5 种语言。

## 6. 上线

S6c 发布三款产品的页面后，与下一批前端改动一起构建 UI 1 次（需用户批准）。
