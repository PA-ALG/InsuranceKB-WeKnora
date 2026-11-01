# S11h · Office 预览失败时仍能定位：文本视图与渲染兼容

> 状态：Claude 2026-11-01 提出 ｜ 作者：Claude Code ｜ 实现方 Claude，审核方 Codex（前端 + 不可信文件处理）
> 依据：蓝图 §7.4（定位失败返回 typed 结果，不猜、不跳页）、AGENTS 核心原则 6（完整前端体验）；
> S11e Spec `S11e-Office引用查看器.md`（沿用上游原文件预览，渲染前按默认拒绝重建包）。
> 真实模型调用：0；不部署；不改上游文件（G10 不增）。

## 1. 问题

线上第一条 Office 知识（#509 发布的一份私有 PPTX 材料，引用落在其中两张幻灯片上）在界面上打不开：
引用面板里上游预览报 `TypeError (appendChild …)`，幻灯片与文本块都没有显示，PDF 引用正常（#509）。

**根因**（本机只用私有课件复现，记录只含类型与计数）：

- `@vue-office/pptx` 1.0.1（npm 上的最新版，2025-01，MIT）内嵌的 pptx-preview 渲染器，在渲染**组合形状
  （`p:grpSp`）的子元素**时只处理形状、图片、嵌套组合三类；子元素是 `p:graphicFrame`（图表、表格、SmartArt）时
  渲染函数返回 `undefined`，随后 `appendChild(undefined)` 抛错，**整份课件一张都渲染不出来**。
- 四份私有课件逐一核对：只有这份课件含 1 个“组合里的图表”，正是唯一渲染失败的一份；其余三份正常。
- 独立的 `pptx-preview` 已发布到 1.0.7（2025-10，ISC），其组合渲染改为 `f && e.appendChild(f)`，即跳过不支持的
  子元素而不抛错；但 `@vue-office/pptx` 没有跟进新版本。换渲染器需要改上游 `document-preview.vue`（G10 +1）或自建
  渲染组件并新增 echarts 等依赖，超出本片；记为后续选项（§6）。

即便换了渲染器，第三方渲染器在不可预期的文件上仍可能失败或卡住。因此本片的目标是：**渲染器失败或超时时，
引用仍能定位到幻灯片 / 正文块 / 工作表行，并显示引文**。

## 2. 改动

### 2.1 渲染兼容：渲染前去掉“组合里的图形框”（`officePackage.ts`）

重建 PPTX 包时（S11e §3.2a 的同一步），在幻灯片、版式与母版部件中删除**位于 `p:grpSp` 之内**的 `p:graphicFrame`
元素（任意前缀；嵌套组合同样处理；版式与母版里用户绘制的形状走同一个组合渲染函数）。效果与 pptx-preview 1.0.7 的
跳过行为一致：其余幻灯片与该幻灯片的其余内容照常渲染，被删的图表/表格/SmartArt 不显示。顶层（不在组合内）的
图形框不动。组合内的图形框没有闭合（文件不完整）时，按默认拒绝拒收整个文件。

- 不改变定位：PPTX 引用按幻灯片定位，块号不受影响；被删表格里的引文在预览中找不到时，按 §2.2 显示文本视图。
- 仍是默认拒绝重建的一部分：只删除，不新增；删除后文档不再含组合内的图形框（有测试）。

### 2.2 文本视图（`officeText.ts`、`OfficeTextView.vue`）

当出现以下任一情况时，在预览位置下方显示被引位置的**文本视图**：

1. 上游预览报错（预览区出现上游的错误提示元素）；
2. 打开后 30 秒内上游预览既没有报告定位结果、也没有报错（渲染卡住）；
3. 上游预览报告“找不到引文”。

文本视图的内容**从本次已下载的同一份原文件里取**，不另调接口：按 S11e §3.2a 的同一套默认拒绝规则与上限重建后读取
XML 部件，但不做 §2.1 的删除（组合内表格的文字照样显示）。

| 格式 | 显示 | 与平台采集一致的依据 |
|---|---|---|
| PPTX | 被引幻灯片的全部段落（按演示顺序找到第 N 张），其后是该页备注的段落 | `internal/sourceloc/office.go` `pptxUnits` / `drawingParagraphs`：每个 `p` 元素一段，`t` 为文字，`br` 为空格 |
| DOCX | 被引正文块及其前后各 2 块（段落、表格；内容控件透明；表格逐行） | `docxUnits`：正文一级 `p`/`tbl` 各计一块，块号从 1 起；引用的 `block_index` 从 0 起 |
| XLSX | 被引工作表第 r 行的各单元格（如不是第 1 行，另列第 1 行作表头）；数值按存储值显示，不套用数字格式 | `xlsxUnits`：按工作表名与行号 |

- 引文在文本里查找时忽略空白差异；找到则用 `<mark>` 标出（只做文本插值，不用 `v-html`）；找不到则只标出被引的
  块/行，并说明“未能逐字定位”。
- 页头说明为什么显示文本视图（预览失败 / 未能在预览中定位），并提供**下载原文件**（用已下载的原始字节生成，
  不重新请求）。
- 状态完整：准备中、显示、该位置没有文字、文本视图也无法生成（同时保留引文与下载）。
- 五种语言的界面文字。
- 组合方式：`OfficeSourceViewer` 负责判断（上面三种情况），通过 `fallback` 插槽交出原因与原始字节；引用面板在插槽里
  放 `OfficeTextView` 并提供界面文字（与它组合 `OfficeSourceViewer` 的方式相同，S11e 冻结的查看器属性不变）。
  上游预览之后又报告定位成功（如用户在上游预览里点了重试）时，文本视图收起。

**为什么不用平台的来源页接口**：`/api/v1/enterprise/spaces/:space_id/sources/:knowledge_id/attempts/:attempt/pages`
是 Harness 读 RAW 材料的接口，按 API Key 策略开放、不按 Release 固定；界面若用它，会绕过“受管 KB 的读入口只读
Active 或 pinned Release”。本片只用引用面板已经取到的 Release 固定文件（同一个 ACL 检查过的引用文件路由）。

### 2.3 安全边界不变

- 文本视图读取的是按同一默认拒绝规则重建、上限检查已过的部件（只是不做 §2.1 的删除），只读 XML 文本并作为纯文本
  显示；不执行、不嵌入任何内容。下载给出的是原始字节（`application/octet-stream`，只下载，不在页面中打开）。
- 上游预览、PDF 引用、`OfficeSourceViewer` 的下载/切换/卸载中止与迟到结果丢弃、链接拦截保持 S11e 行为。
- 企业代码仍只通过上游 `DocumentPreview` 使用渲染库；`jszip` 仍只在 `officePackage.ts` 中使用
  （`OfficeSourceViewer.spec.ts` 保护断言不变）。

## 3. 改动范围

- `frontend/src/enterprise/officePackage.ts`：§2.1 兼容规则；新增读取重建后包内若干 XML 部件文本的函数。
- `frontend/src/enterprise/officeText.ts`（新）、`frontend/src/enterprise/OfficeTextView.vue`（新）。
- `frontend/src/enterprise/OfficeSourceViewer.vue`、`CitationPanel.vue`（新标签）。
- `frontend/src/enterprise/i18n/messages/*.ts`（5 种语言新增键）。
- 测试：`frontend/src/enterprise/officeText.spec.ts`、`officePackageCompat.spec.ts`、`officeSourceFallback.spec.ts`（新）；
  `frontend/tests/enterprise-office-citation/`（浏览器检查新增用例）。
- 不改：上游 `src/components/document-preview.vue`、依赖清单与锁文件、Go、合同、Harness。

## 4. 验收

- RED（单独提交）：
  - 幻灯片、版式、母版中组合内图形框被删除、组合外图形框与其余内容保留，嵌套组合与任意前缀同样处理；未闭合时拒收；
    文本视图读取的部件仍含组合内表格的文字；
  - PPTX 按演示顺序取第 N 张幻灯片的段落与备注；DOCX 块号与平台一致（内容控件透明、表格逐行、`block_index`
    从 0 起）；XLSX 按表名与行号取单元格并带表头；引文忽略空白匹配并标出；
  - 上游预览报错、30 秒无结果、报告找不到引文三种情况都显示文本视图；正常定位时不显示；下载按钮给出原始字节；
    该位置无文字、文本视图生成失败各有提示。
- 浏览器检查（合成文件，真实渲染器）：组合里放一个表格、被引文字在组合外 → 课件正常渲染并标出引文
  （去掉 §2.1 时该用例因渲染器抛错失败）；被引文字在组合里的表格中 → 预览找不到，文本视图显示并标出引文。
  原有 8 个用例不变。
- 本机私有检查（不入库，只记结论）：线上失败的那份课件用 §2.1 后能渲染全部幻灯片；两张被引幻灯片的文本视图能取出段落。
- 门禁：type-check、vitest、node tests、build、`pytest -q tests/architecture`、`git diff --check`。

## 5. 不做

- 不换渲染器、不改上游文件、不新增依赖。
- 不为 Office 引用画几何高亮（采集无坐标，S11d 设计如此）。
- 不改引用接口与平台。

## 6. 后续选项

- 渲染器升级：把 PPTX 预览换成 pptx-preview ≥1.0.6（独立包，ISC，依赖 echarts），需改上游 `document-preview.vue`
  或企业侧自建渲染组件；同时可向上游 WeKnora 报告此问题。
