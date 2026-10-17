# S3d-3b · 原文页查看器：打开被引用的那一页 PDF 并叠加多段高亮

> 状态：用户已确认开工（2026-10-17，S3d 拆分方案；用户要求与 S3d-3a 并行） ｜ 作者：Claude Code
> 依据：蓝图 §7.4（回跳顺序）、硬边界 7（定位失败返回 typed error，不跳第 1 页、不换版本）、核心工程原则 6（完整前端体验）；
> S4c-2b-2 与 S3d-1 Spec（citation 返回体与会话 file 路由）
> 分支：`slice/s3d3b` ｜ 工作目录：`.worktrees/s3d3b` ｜ 实现方：Codex（前端组件，与 S3d-3a 并行） ｜ 审核方：Claude

S3d-3 拆为两片并行：**S3d-3a**（Claude 实现：入口、Space 列表、产品页、引用抽屉）与**本片 S3d-3b**（一个独立的原文页查看器组件）。
本片只新增文件，不改路由、侧栏、多语言文件与已有组件；S3d-3a 在引用抽屉里使用本组件。

## 1. 目标

给定 citation 返回体中的 `file`（会话 file 路由）、`page.number` 与 `highlight`，显示被引用的那一页 PDF，并在其上叠加
全部高亮框。只显示被引用的页；任何失败都显示错误与重试，不改显示别的页或别的版本。

## 2. 现状（`main@cfbfcccbf`）

- citation 返回体（`internal/enterprise/citation.go`）：`page{number, width_points, height_points}`、`quote`、
  `highlight{coordinate_space: "normalized_0_1e6_top_left", complete, rects: [[x0, y0, x1, y1], ...]}`、`file`。
  `file` 是 `/api/v1/enterprise/spaces/<sid>/view/releases/<rid>/sources/<kid>/attempts/<n>/file`，字节经指纹核对才返回。
- `frontend/src/components/schema-wiki/pdfJsPort.ts`：`createPdfJsPort().open(bytes)` → `{pageCount, renderPage(n), close()}`，
  `renderPage` 以 scale 1 画到 canvas，越界页抛错。只收字节，鉴权由调用方负责。
- `frontend/src/utils/request.ts`：axios 实例自动带登录凭据；`get(url, {responseType: 'arraybuffer'})` 返回原始字节；
  不拆 `{success, data}`。
- `src/enterprise/` 下已有 3 个 vitest 组件测试（24 项，全过），但 CI 的前端作业只跑 `npm test`、类型检查与构建，不跑 vitest。

## 3. 设计

### 3.1 `frontend/src/enterprise/sourcePage.ts`

```ts
export type NormalizedRect = readonly [number, number, number, number] // x0, y0, x1, y1 in 0..1_000_000, top-left origin
export interface HighlightBox { left: string; top: string; width: string; height: string } // CSS percentages
export function highlightBoxes(rects: readonly NormalizedRect[]): HighlightBox[]
```

- 换算：百分比 = 坐标 / 10 000，写成 `${value}%`（如 `123456` → `12.3456%`）。
- 每个坐标先截到 `[0, 1_000_000]`；截后宽或高不为正、或含非有限数的框跳过；输出顺序与输入一致。

### 3.2 `frontend/src/enterprise/SourcePageViewer.vue`

```ts
props: {
  file: string                 // citation.file
  page: number                 // citation.page.number, 1-based
  rects: NormalizedRect[]      // citation.highlight.rects
  complete: boolean            // citation.highlight.complete
  labels: { loading: string; failed: string; retry: string; incomplete: string; region: string }
}
```

- **取字节**：`get<ArrayBuffer>(file, { responseType: 'arraybuffer', timeout: 180_000, signal })`（`@/utils/request`），
  每次加载一个新的 `AbortController`。
- **渲染**：`createPdfJsPort().open(new Uint8Array(bytes))`；`page` 不是 `[1, pageCount]` 内的整数 → 关闭刚打开的文档，进入错误状态，不渲染任何页；
  否则 `renderPage(page)`，把返回的 canvas 放进页容器（CSS 宽度随容器缩放），按 `highlightBoxes(rects)` 叠加高亮。
- **DOM 约定**（验收按此查找，样式自定）：
  - 加载中：`[role="status"]`，含 `labels.loading`；
  - 出错：`[role="alert"]`，含 `labels.failed` 与一个文字为 `labels.retry` 的 `<button>`，点击后对同一 `file` 与 `page` 重新加载；
  - 成功：页容器 `[data-source-page]`，`role="img"`，`aria-label` 为 `labels.region`，内含 canvas；
    每个高亮一个 `[data-highlight]` 元素（`aria-hidden="true"`，`style` 的 left/top/width/height 取自 `highlightBoxes`）；
  - `complete === false` 且成功时，另有 `[data-highlight-incomplete]`（`role="note"`），含 `labels.incomplete`。
  - 组件内不写死任何文案，文案全部来自 `labels`（多语言由 S3d-3a 提供）。
- **并发与资源**：
  - `file` 或 `page` 变化即重新加载，中止上一次请求；
  - 先发的请求后到时丢弃其结果；它若已打开文档，则关闭该文档，不显示；
  - 重新加载或卸载时关闭已打开的文档、中止未完成的请求。
- 成功后把第一个高亮滚动到可见区域（`scrollIntoView({ block: 'center' })`，测试环境不验证）。

### 3.3 CI

`.github/workflows/frontend.yml` 的前端作业在 `npm test` 之后加一步：
`npx vitest run --config vitest.config.ts src/enterprise`。从此 `src/enterprise` 下的组件测试进入 CI。

### 3.4 不在本片

引用抽屉与其文案（S3d-3a）、整份 PDF 翻页与缩放、旋转页的坐标校正（首期材料未见旋转页；如出现，另开切片）、
高 DPI 渲染、把 `pdfJsPort.ts` 移进 `src/enterprise/`（随 S7 清理旧 schema-wiki 代码时一并移动）。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交）：
  - `frontend/src/enterprise/sourcePage.spec.ts`：换算、截断、跳过无效框；
  - `frontend/src/enterprise/SourcePageViewer.spec.ts`：
    - 只取一次被引用的字节并只渲染被引用页，每个框一个高亮，位置正确；
    - 高亮不完整时有提示；
    - 被引用页不存在时报错且不渲染任何页；
    - 下载失败可重试；
    - 加载中换页时只显示最新一次，旧请求被中止；
    - 卸载时关闭文档、中止请求。
- 门禁（在 `frontend/`）：
  - `npx vitest run --config vitest.config.ts src/enterprise` 全过；
  - `npm test`、`npm run type-check`、`npm run build` 通过；
  - 架构守卫全过（G2、G3、G11 不增；本片不改上游文件，G10 不变）；CI 全绿。

## 5. 改动范围

- 允许：`frontend/src/enterprise/sourcePage.ts`、`frontend/src/enterprise/SourcePageViewer.vue`、`.github/workflows/frontend.yml`（只加 §3.3 一步）、
  `frontend/src/enterprise/` 下非受保护的测试。
- 不改：路由、侧栏、`src/i18n/`、`src/api/`、`src/utils/`、`src/components/`（包括 `pdfJsPort.ts`）、Go、Harness、`package.json` 与锁文件。
- 受保护：本片验收文件、`docs/design/`、蓝图。

## 6. 依赖与环境

依赖 S3d-1（已在 `main`）。无模型调用、无迁移、无部署、无新依赖。与 S3d-3a 写域不重叠，可并行。
