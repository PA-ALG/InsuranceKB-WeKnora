# S3d-3a · 企业知识页面：侧栏入口、Space 列表、产品页与引用抽屉

> 状态：用户已确认开工（2026-10-17，S3d 拆分方案；用户要求与 S3d-3b 并行） ｜ 作者：Claude Code
> 依据：蓝图 §5.1、§7.4、§7.5，硬边界 5、6、7，核心工程原则 6；S3d-1、S3d-2、S3d-3b Spec
> 分支：`slice/s3d3a` ｜ 工作目录：`.worktrees/s3d3a` ｜ 实现方：Claude ｜ 审核方：Codex（前端、改上游文件）

## 1. 目标

登录用户从侧栏"企业知识"进入：

1. 看到本租户可读的企业 Space；
2. 打开某个 Space 的当前发布版本，看到其中的条目（产品）；
3. 打开某个条目：字段按 pack 的展示分组与顺序显示，标明三态与来源，模型补充的内容单独成组；
4. 点任一出处，在抽屉里看到文档、页码、引文与带高亮的原文页（S3d-3b 组件）。

同一页面与它的全部引用读取同一个 Release（蓝图核心工程原则 6、硬边界 5）。

## 2. 现状（`main@cfbfcccbf`）

- 会话只读接口（S3d-1）：`GET /api/v1/enterprise/spaces`、`.../spaces/:sid/view/releases/active|:rid`、
  `.../:rid/citation?member=&evidence=`、`.../:rid/sources/:kid/attempts/:n/file`；只返回 `access_scope="space"` 的成员。
- 发布数据（S3d-2，PR #183）：`entity`、`presentation_profile` 与 `claim` 成员；读者规则见 S3d-2 Spec §3.1。
  之前发布的 Release 只有 claim 成员。
- 原文页查看器（S3d-3b，Issue #185）：`SourcePageViewer.vue`，props `file/page/rects/complete/labels`。
- `request.ts` 自动带登录凭据，不拆 `{success, data}`；HTTP 错误以 `{status, message, ...body}` 拒绝（body 含 `code`）。
- 路由 `src/router/index.ts` 与 5 个语言文件已登记为上游补丁（G10 不增）；侧栏 `src/stores/menu.ts`、`src/components/menu.vue` 尚未改过。

## 3. 设计

### 3.1 接口层 `frontend/src/enterprise/enterpriseApi.ts`

```ts
export class EnterpriseError extends Error { readonly code: string; readonly status?: number }
export function listSpaces(): Promise<string[]>                                   // GET /api/v1/enterprise/spaces
export function readRelease(spaceId: string, releaseId?: string): Promise<Release> // .../view/releases/active 或 /<rid>
export function readCitation(spaceId: string, releaseId: string, member: string, evidence: number): Promise<Citation>
```

- 路径段用 `encodeURIComponent`；citation 的查询串用 `URLSearchParams`（`member=<编码>&evidence=<n>`）。
- 返回体 `success === true` 时取 `data`；否则抛 `EnterpriseError(body.code ?? 'INVALID_RESPONSE')`。
- 请求被拒：抛 `EnterpriseError(error.code ?? 'REQUEST_FAILED', error.status)`。
- `Release`、`ReleaseMember`、`Citation` 类型照后端返回体书写（`Citation` 见 `internal/enterprise/citation.go`）。

### 3.2 视图模型 `frontend/src/enterprise/releaseView.ts`（纯函数）

```ts
export interface EntitySummary { entityId: string; name: string; labels: string[]; fieldCount: number }
export function entitySummaries(release: Release): EntitySummary[]

export interface FieldView { slug: string; title: string; state: string; value: string | string[] | null; origin: string; evidenceCount: number }
export interface SectionView { key: string; title: string; fields: FieldView[] }
export interface EntityView { entityId: string; name: string; labels: string[]; sections: SectionView[]; other: FieldView[]; generated: FieldView[] }
export function entityView(release: Release, entityId: string): EntityView | null
```

- 条目：先按成员顺序列出 `entity` 成员（`name = names[0]`，没有则用 `entity_id`；`labels = classification_labels`）；
  再按首次出现顺序列出没有 entity 成员的 claim 主体（`subject_ref`），`name = subject_ref`、`labels = []`。
  `fieldCount` = 该主体的 claim 数。旧 Release 没有 entity 成员时也能浏览。
- 条目页：
  - claim 按 `payload.subject_ref === entityId` 选出；都没有且无 entity 成员 → `null`；
  - profile 取成员顺序中第一个 `classification_labels` 与条目有交集的 `presentation_profile`；
  - `origin === 'MODEL_GENERATED'` 的 claim 一律进 `generated`，按 `predicate` 排序，不进任何分组（硬边界 6：模型补充与有原文依据的内容分开显示）；
  - 其余 claim：在 profile 中的按分组与字段顺序进 `sections`，`title = short_title`；没有 claim 的字段与空分组不显示；
    不在 profile 中（或没有 profile）的进 `other`，按 `predicate` 排序，`title = predicate`；
  - `generated` 中的字段若在 profile 中，`title` 也用 `short_title`；
  - `value`：只在 `state === 'present'` 时给出；字符串原样，数字与布尔转字符串，数组转字符串数组；其他情况 `null`；
  - `evidenceCount` = `payload.evidence` 数组长度（不是数组则 0）；`origin` 缺失为 `''`。

### 3.3 页面（`frontend/src/enterprise/`）

路由（`src/router/index.ts`，`/platform` 的 children，`meta: { requiresInit: true, requiresAuth: true }`，用 props 传参）：

| 路径 | name | 组件 | props |
|---|---|---|---|
| `enterprise` | `enterpriseSpaces` | `EnterpriseSpaces.vue` | — |
| `enterprise/:spaceId` | `enterpriseSpace` | `EnterpriseSpace.vue` | `spaceId` |
| `enterprise/:spaceId/entities/:entityId` | `enterpriseEntity` | `EnterpriseEntity.vue` | `spaceId`、`entityId`、`releaseId`（取 `?release=`） |

- **EnterpriseSpaces**：加载中 `[role="status"]`；失败 `[role="alert"]` + 重试；无 Space 显示空状态；
  每个 Space 一个链接 `{ name: 'enterpriseSpace', params: { spaceId } }`。
- **EnterpriseSpace**：读 Active；显示"发布版本 {epoch}"；`RELEASE_NOT_FOUND` 显示"该空间还没有发布版本"（不是错误）；
  其他失败 `[role="alert"]` + 重试；没有条目显示空状态；每个条目一个链接
  `{ name: 'enterpriseEntity', params: { spaceId, entityId }, query: { release: <已读到的 release.id> } }`，显示名称与"{count} 项"。
- **EnterpriseEntity**：有 `releaseId` 就按它读，否则读 Active；此后该页的全部引用都用**已读到的 release.id**。
  - 标题为条目名称；每个分组一个 `[data-section="<key>"]`，组内每个字段一个 `[data-field="<slug>"]`；
    `other` 在 `[data-other]`，`generated` 在 `[data-generated]`（标题"模型补充"）。
  - 字段显示：标题；`present` 显示值（数组逐项显示）；`absent_explicitly` 显示"材料明确没有"；`unknown` 显示"材料未提及"；
    其他状态原样显示。来源标签 `[data-origin]`：`SOURCE_SUPPORTED` 原文依据、`MIXED` 原文与整理、`MODEL_GENERATED` 模型补充、
    `EXPERT_REVISION` 专家修订、`STRUCTURED_IMPORT` 结构化导入，其他原样显示。
  - 每条证据一个按钮"出处 {n}"（n 从 1 起）；点击后在抽屉中显示 `CitationPanel`，props
    `{ spaceId, releaseId: <已读到的 release.id>, member: <slug>, evidence: <下标，从 0 起> }`。
  - 条目不在该版本中显示"该版本中没有这个条目"；读取失败 `[role="alert"]` + 重试。
- **CitationPanel**（props `spaceId`、`releaseId`、`member`、`evidence`）：
  - 读 citation；显示文档名、"第 {page} 页"、引文、来源标签；下面放 `SourcePageViewer`，props 为
    `file`、`page.number`、`highlight.rects`、`highlight.complete` 与多语言 `labels`（`region` 为"{document} 第 {page} 页"）。
  - 失败显示 `[role="alert"]` + 重试，不显示原文页：`EVIDENCE_MISMATCH` → "原文已变化，无法回跳"；
    `RELEASE_NOT_FOUND`、`MEMBER_NOT_FOUND`、`EVIDENCE_NOT_FOUND`、`SOURCE_NOT_FOUND` → "找不到被引用的原文"；
    `EVIDENCE_UNSUPPORTED` → "这类出处暂不支持打开"；其他 → "出处无法打开"。
  - props 变化即重新读取；先发的请求后到时丢弃。
- 文案全部走 i18n（命名空间 `enterpriseKnowledge`，另加 `menu.enterpriseKnowledge`），5 个语言文件键集一致；
  状态与来源的键在代码里显式映射（不拼接键名），以便键审计覆盖。zh-CN 文案以本节为准：

  | 用处 | zh-CN |
  |---|---|
  | 侧栏、列表标题 | 企业知识 |
  | 加载中 / 重试 | 正在加载… / 重试 |
  | Space 列表：空 / 失败 | 暂无可查看的企业知识空间 / 企业知识空间加载失败 |
  | Space 页：版本 / 无版本 / 无条目 / 失败 / 字段数 | 发布版本 {epoch} / 该空间还没有发布版本 / 该版本中还没有条目 / 发布版本加载失败 / {count} 项 |
  | 条目页：不在版本中 / 失败 / 其他 / 模型补充 / 出处按钮 | 该版本中没有这个条目 / 条目加载失败 / 其他 / 模型补充 / 出处 {n} |
  | 状态 | 材料明确没有 / 材料未提及 |
  | 来源 | 原文依据 / 原文与整理 / 模型补充 / 专家修订 / 结构化导入 |
  | 引用：页 / 失败类 | 第 {page} 页 / 原文已变化，无法回跳 / 找不到被引用的原文 / 这类出处暂不支持打开 / 出处无法打开 |
  | 查看器 labels | 正在打开原文… / 原文页无法显示 / 重试 / 高亮可能不完整 / {document} 第 {page} 页 |

### 3.4 侧栏（上游补丁，G10 459 → 461）

- `src/stores/menu.ts`：在"知识库"之后加 `{ title: '', titleKey: 'menu.enterpriseKnowledge', icon: 'enterprise', path: 'enterprise' }`。
- `src/components/menu.vue`：图标映射加 `enterprise`（复用已有资源 `zhishiku-thin.svg`，当前路由在 `/platform/enterprise` 下时用
  `zhishiku-green.svg`）；`TOP_MENU_PATHS` 加 `enterprise`。点击沿用默认的 `/platform/<path>` 跳转。
- 原因：企业知识需要一个与知识库并列的入口，侧栏没有扩展点。退出条件：上游提供侧栏注册扩展点后改为注册。
  在 `docs/design/upstream-patches.md` 追加两行；G10 基线由 Claude 审查后更新为 461。

### 3.5 不在本片

原文页渲染（S3d-3b）、Space 显示名（目前显示 Space ID）、搜索与筛选、历史版本切换与对比、
条目内的关系与概念链接、编辑与审核操作。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交，`frontend/src/enterprise/`）：
  - `releaseView.spec.ts`：
    - 条目列表含无 entity 成员的旧数据；
    - 分组与字段顺序、隐藏空字段与空分组、按标签匹配 profile；
    - `other` 与 `generated` 的归属和排序；
    - 值的格式与证据数。
  - `enterpriseApi.spec.ts`：路径与查询串编码、拆包、错误码。
  - `enterprisePages.spec.ts`：
    - Space 列表：加载、空、错误重试、链接；
    - Space 页：无发布版本、错误重试、条目链接带 release；
    - 条目页：按显式 release 读取、分组与三态与来源标签、模型补充单独成组、出处按钮打开的引用固定在已读到的 release。
  - `CitationPanel.spec.ts`：
    - 显示内容；
    - 传给查看器的 props 与文案；
    - 各错误码的文案且不显示原文页；
    - 重试；
    - 迟到响应丢弃。
- 门禁（在 `frontend/`）：
  - `npx vitest run --config vitest.config.ts src/enterprise` 全过；
  - `npm test`（含 i18n 键审计）、`npm run type-check`、`npm run build` 通过；
  - 架构守卫：G2、G3、G11 不增，G10 为 461 并已登记；CI 全绿。

## 5. 改动范围

- 允许：
  - `frontend/src/enterprise/` 新文件；
  - `frontend/src/router/index.ts`（只加 §3.3 的三条路由）；
  - `frontend/src/stores/menu.ts`、`frontend/src/components/menu.vue`（只做 §3.4 的改动）；
  - `frontend/src/i18n/locales/*.ts`（只加 §3.3 的键）；
  - `docs/design/upstream-patches.md`（追加两行）、`tests/architecture/baseline.json`（只改 G10 计数）；
  - `frontend/src/enterprise/` 下非受保护测试。
- 不改：Go、Harness、`src/utils/`、`src/api/`、`SourcePageViewer.vue` 与 `sourcePage.ts`（S3d-3b）、依赖与锁文件。
- 受保护：本片验收文件、`docs/design/`（上述登记行除外）、蓝图。

## 6. 依赖与环境

- 依赖 S3d-1（已在 `main`）、S3d-3b（`CitationPanel` 使用其组件；3b 合并后再接入并跑全部验收）。
- 依赖 S3d-2：新发布的版本才有分组；旧版本按 `other` 显示。
- 无模型调用、无迁移、无部署。部署到本机环境随 S3d 部署另行申请。
