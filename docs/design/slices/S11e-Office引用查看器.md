# S11e 前端打开 Office 引用：沿用上游原文件预览，按块定位并高亮引文

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。计划见 #446，平台侧引用见 S11d（#483，已合并 `b8013c425`）。
> 真实调用：0（实现、验收测试与浏览器检查都只用测试内生成的合成文件）。

## 0. 背景

S11d 让引用接口回验并返回 Office 证据（`internal/enterprise/citation.go` 的 `blockCitation`，字段由 `internal/enterprise/office_citation_test.go` 逐键锁定）：200 响应**没有 `highlight` 键**，改为 `page{number}`、采集中块的 `locator`（PPTX `PPTX_SHAPE{slide}`、DOCX `DOCX_BLOCK{block_index}`、XLSX `XLSX_CELL_RANGE{sheet, "A<r>:XFD<r>"}`）与 `block{block_id, start, end}`；原文件接口按扩展名给 Office 媒体类型。

现在的 `CitationPanel` 默认每个非专家引用都有 `highlight`，并用 pdf.js 打开原文件：打开 Office 引用会抛错（读 `undefined.rects`），即使不抛错，pdf.js 也打不开 Office 文件。S11d 因此要求：S11e 上线前不在线上发布 Office 材料的知识。

## 1. 目标

1. 引用面板打开 Office 引用：显示原文件，滚动到引文所在的幻灯片 / 正文段落 / 工作表行，并高亮引文。
2. 无法打开时退化为"文档名 + 位置 + 引文"，不报错、不打开别的页或别的文件。
3. PDF 引用的行为与输出不变。

## 2. 选型（先调研成熟方案）

| 方案 | 结论 |
|---|---|
| **上游 v0.9.0 原文件预览 `components/document-preview.vue`**：`@vue-office/pptx`（MIT）渲染 PPTX，`docx-preview`（Apache-2.0）渲染 DOCX，SheetJS CE `xlsx`（Apache-2.0）渲染 XLSX，`jszip`（MIT 选项）；内置"结构定位 + 引文匹配"高亮（上游 #3700、#3794：幻灯片 → 引文，正文块 → 引文并在分页偏移时全局唯一回验，工作表行），用 CSS Custom Highlight API 标出文字、整块时标出区域，并回报 `located{found, precise, granularity, reason}` | **采用**。依赖已在上游 `package.json`，前端零新增依赖；上游维护，随升级同步；定位粒度与 S11b 采集一致（S11b 的块号本来就取自上游 `internal/sourceloc`，与 `docx-preview` 的正文块序同源） |
| 自写 Office 渲染与高亮 | 不做：重复上游已有能力，违背"先调研成熟方案" |
| 服务端转 PDF（LibreOffice/Gotenberg）后沿用 pdf.js 高亮 | 不做：需要新的服务与镜像，转换后的坐标与 S11b 块无对应，回验链要重做 |
| OnlyOffice / Collabora 在线预览 | 不做：AGPL、重量级服务，且不提供按块高亮接口 |

上游组件的 `knowledgeId` 取文件路径走上游知识库预览接口，不经发布版本的访问控制；本片**只用它的 `sourceBlob` 入口**：字节由我们按引用里的 `file`（发布版本原文件接口，带会话鉴权）下载，每次打开都向服务端请求，不复用浏览器缓存（与 PDF 查看器相同）。

## 3. 设计

### 3.1 引用到预览目标的映射（`frontend/src/enterprise/officeCitation.ts`，纯函数）

`officeTarget(locator, quote)` 把 S11d 的块 locator 映射为上游 `SourceLocator`（`mapping: 'exact'`，`quote` 为引文），并给出显示位置：

| S11d locator | 上游 `SourceLocator` | 显示位置 |
|---|---|---|
| `PPTX_SHAPE{slide}`，`slide` 为正整数 | `{type: 'slide', slide}` | 第 `slide` 张幻灯片 |
| `DOCX_BLOCK{block_index}`，`block_index` 为非负整数 | `{type: 'docx', block: block_index + 1}`（上游块号 1 起，S11b 为"上游块号 − 1"） | 正文第 `block_index + 1` 段 |
| `XLSX_CELL_RANGE{sheet, cell_range}`，`sheet` 非空、`cell_range` 恰为 `A<r>:XFD<r>`（同一行，`1 ≤ r ≤ 1048576`） | `{type: 'sheet', sheet, row_start: r, row_end: r}` | 工作表「`sheet`」第 `r` 行 |

其他任何情况（无 locator、未知 kind、字段类型或取值不对、`cell_range` 不是整行）→ `null`，走 §3.3 的退化显示。locator 中多出的键忽略（只读不信：S11d 已回验，前端只决定跳到哪里）。预览请求为 `{locators: [该 locator], quotes: [引文], token}`，每次打开换新 `token`。

### 3.2 Office 原文视图（`frontend/src/enterprise/OfficeSourceViewer.vue`）

- 用 `@/utils/request` 的 `get(file, {responseType: 'arraybuffer', timeout: 180000, signal})` 下载字节；切换引用或卸载时中止请求，过期结果不显示。
- 下载成功后先按 §3.2a 重建文件包，再渲染上游 `DocumentPreview`（异步组件，不进企业页首屏包）：`source-blob` 为**重建后**字节、带该格式 OOXML 媒体类型的 Blob，`file-type` 取 locator 的格式（`pptx`/`docx`/`xlsx`，不取文件名扩展名），`file-name` 为文档名，`active`、`source-mode`，`locate` 为 §3.1 的请求。
- 上游回报 `located` 后在预览下方给一行说明（`role="note"`）：
  - `found && precise`：不加说明（引文已逐字高亮）；
  - `found && !precise`：「已标出引文所在的位置，未能逐字高亮」（例如 XLSX 只标整行、引文在幻灯片里不唯一）；
  - `!found`：「未能在原文中定位这段引文，请对照上方引文」。原文件仍显示，不跳到别处。
- 下载失败：`role="alert"` 说明 + 重试按钮（与 PDF 查看器同一文案）；渲染失败由上游组件显示其错误与重试。
- 渲染出的 Office 内容不可信：`docx-preview` 把文件里外部链接的目标原样写进 `<a href>`，包括 `javascript:`。预览区域在捕获阶段拦下点击（含中键），链接协议不是 `http:`、`https:`、`mailto:` 的一律不跟随（实现中发现，2026-10-31 修订；上游知识库预览有同样问题，另行反馈上游）。
- 文件包被拒（§3.2a）：不渲染任何预览，也不给重试（同一文件重试结果相同），在原位置给一行说明（`role="note"`）「原文件含有无法安全显示的内容，未打开，请对照上方引文」；面板上方的文档名、位置与引文照常显示。

### 3.2a Office 文件是不可信的主动内容（审核 R1，2026-10-31 修订）

威胁：引用打开的是 Space 成员上传的原文件。上游渲染器会执行文件里的主动内容：`docx-preview@0.3.7` 默认 `renderAltChunks: true`，把 `w:altChunk` 经 `aFChunk` 关系指向的 HTML 写进**无 sandbox 的 iframe `srcdoc`**，打开引用即在应用同源执行脚本，无需点击（审核用真实 Chromium 复现）；外部目标（图片、模板、框架）会让浏览器向文件指定的地址发请求。点击拦截挡不住渲染时执行。

做法：**在字节交给渲染器之前**，由企业模块 `frontend/src/enterprise/officePackage.ts` 用上游已有的 `jszip` 按允许清单重建文件包；上游文件不改（G10 仍为 161），不用上游渲染器的配置开关（上游组件不暴露）。

1. **只留可达部件**：从包根的 `_rels/.rels` 出发沿关系遍历，只保留被保留关系指向的部件、这些部件的关系部件与 `[Content_Types].xml`；其他部件（包括未被引用的孤立部件、同名不同大小写的重复项）一律不进新包。关系部件与 `[Content_Types].xml` 由我们按解析结果重新生成，不沿用原文。
2. **丢弃的关系（连同目标部件）**：`aFChunk`；OLE `oleObject`；ActiveX `control`、`activeXControlBinary`；宏 `vbaProject`（及签名）、`wordVbaData`、`keyMapCustomizations`、`attachedToolbars`、界面扩展 `extensibility`；`attachedTemplate`、`frame`、`subDocument`；外部数据 `externalLink`、`externalLinkPath`、`slideUpdateInfo`。三种格式同一份清单。
3. **外部目标**：`TargetMode="External"` 的关系一律丢弃，只有 `hyperlink` 且目标协议为 `http:`、`https:`、`mailto:` 的保留（按浏览器 URL 解析判断，`java\tscript:` 之类同样丢弃）；§3.2 的点击拦截保留作纵深。
4. **丢弃的部件类型**：内容类型为 HTML/XHTML/MHT/RTF、VBA、ActiveX、OLE 的部件，以及扩展名为 `html/htm/xhtml/xht/mht/mhtml/rtf/bin/js/vbs/hta` 的部件，无论被哪种关系引用。
5. **DOCX 的 `w:altChunk` 元素**：所有 WordprocessingML 部件（正文、页眉页脚、脚注尾注、批注、词汇表）里的 `altChunk` 元素删除；删除后仍能找到 `altChunk` 元素即拒绝。块号不变：上游 `internal/sourceloc` 与 `docx-preview` 的定位都只数正文顶层段落与表格，`altChunk` 不占块号（浏览器检查覆盖：被引块前插入 altChunk，高亮仍在原块）。
6. **失败关闭**（抛 `OfficePackageRejected`，§3.2 的说明）：
   - `package`：不是 zip、zip 加密或损坏、部件读不出；
   - `size`：下载超过 128 MiB、条目超过 10 000、全部条目实际解压字节超过 256 MiB（边解压边计数，不信声明的大小，超限立即停止）；
   - `structure`：缺 `[Content_Types].xml`，包根没有恰好一个 `officeDocument` 关系，主部件内容类型不是该格式的标准主类型（如启用宏的 `docm` 主类型），名字仅大小写不同的条目，或 altChunk 删不干净。
7. 未改动且已压缩的部件原样复制压缩数据，不再解压一次。

纵深防御（后续，不在本片）：UI 镜像加不含 `unsafe-inline` 的 CSP（同样覆盖 `srcdoc`、内联事件与外部请求），另开切片；上游知识库预览的同类问题反馈上游。

### 3.3 引用面板（`CitationPanel.vue`）

| 引用 | 显示 |
|---|---|
| 专家修订记录 | 不变 |
| 有 `highlight`（PDF） | 不变：文档名、第 N 页、来源标记、引文、`SourcePageViewer` |
| 无 `highlight`，`officeTarget` 非空 | 文档名、§3.1 的位置、来源标记、引文、`OfficeSourceViewer` |
| 无 `highlight`，`officeTarget` 为空 | 文档名、第 N 页、来源标记、引文，加一行说明「这类出处暂不支持打开原文，请对照上方引文」；不渲染任何查看器 |

`enterpriseApi.ts` 的 `Citation` 类型：`highlight` 改为可选（PDF 才有），新增可选 `locator`、`block`；`page.width_points/height_points` 改为可选（S11d 的 Office 引用只有 `number`）。

### 3.4 文案

新增键（五种语言）：`enterpriseKnowledge.citation.slide/block/row`，`enterpriseKnowledge.viewer.officeRegion/coarse/notLocated/noViewer/unsafe`。

## 4. 改动范围

| 方 | 路径 |
|---|---|
| Claude（RED，受保护） | `frontend/src/enterprise/officeCitation.spec.ts`、`OfficeSourceViewer.spec.ts`、`citationPanelOffice.spec.ts` |
| Claude（实现） | `frontend/src/enterprise/{officeCitation.ts, officePackage.ts, OfficeSourceViewer.vue, CitationPanel.vue, enterpriseApi.ts}`、`frontend/src/enterprise/i18n/messages/*.ts`；测试 `frontend/src/enterprise/officeSourceLinks.spec.ts`、`officePackage.spec.ts`、`officeSourceSanitize.spec.ts` |
| Claude（受保护测试调整，单独披露提交） | `OfficeSourceViewer.spec.ts`：视图测试里的重建步骤替换为原样返回，说明标签加 `unsafe`，"不直接引入 Office 库"的断言改为渲染库一律不许、`jszip` 只许 `officePackage.ts` 引入；`citationPanelOffice.spec.ts`：说明标签加 `unsafe` |
| Claude（浏览器检查，非 CI） | `frontend/tests/enterprise-office-citation/`：合成 PPTX/DOCX/XLSX（测试内用 JSZip/SheetJS 生成）+ 检查页 + 无头浏览器脚本 |

不改：上游文件（`components/document-preview.vue`、`utils/sourceLocator*.ts` 原样使用，G10 不升）、`package.json`（不加依赖）、后端、Harness、受保护的 `CitationPanel.spec.ts`、`SourcePageViewer.spec.ts`。手写文件 ≤ 500 行。

## 5. 验收

- RED 三个文件全部通过：映射表的每一行与每种拒绝；查看器的下载、中止、过期结果、`DocumentPreview` 入参、三种 `located` 说明、下载失败与重试；面板的四种显示，PDF 引用仍只渲染 `SourcePageViewer`、且其入参不变。另断言企业代码不直接引入 Office 渲染库（只经上游 `DocumentPreview`）。
- 受保护的 `CitationPanel.spec.ts`、`SourcePageViewer.spec.ts` 不改且通过。
- 前端：`vue-tsc` 类型检查、`vitest`（企业目录全部 spec）、`tsx --test`（上游 node 测试，与 main 对比无新增失败）、`vite build` 通过。
- 浏览器检查（无头 Chromium，经真实 `CitationPanel` → 引用接口 → 原文件接口，接口由脚本拦截返回合成数据）：
  - PPTX 引文在第 2 张幻灯片：第 2 张被滚动到、引文逐字高亮，`precise`；
  - DOCX 引文在正文第 3 段：只高亮该段中的引文；
  - XLSX 引文在「Rates」工作表第 3 行：该行被标出，说明「未能逐字高亮」；
  - 引文在原文里找不到：原文仍显示，说明「未能在原文中定位」；
  - 无 locator 的引用：只有文档、页、引文与说明，没有查看器、没有报错；
  - DOCX 里带 `javascript:` 外部链接：引文照常高亮，点击该链接不执行任何脚本；
  - DOCX 在被引块之前带 `altChunk`（HTML 内联脚本）与外部图片：不点击任何内容，脚本不执行、页面里没有 `srcdoc` iframe、没有对外请求，被引块仍正确高亮；
  - 不是 zip 的"DOCX"：不渲染预览，给出 §3.2 的拒绝说明。
- 重建的单元测试：§3.2a 每一种丢弃（关系、外部目标、部件类型、孤立部件、altChunk 元素）与每一种拒绝；普通 DOCX/PPTX/XLSX 重建后正文部件逐字不变。
- `tests/architecture` 通过（G10 不升，G11 无新增）；`git diff --check` 干净。

## 6. 上线

前端镜像（UI）部署后，Office 引用可在页面打开；S11d 的运维约束（"不在线上发布 Office 材料的知识"）在 S11d 的 App 与本片 UI 都部署后解除。用业务样本做的端到端检查只在本机进行，样本、文字与截图不进仓库、Issue、PR 或日志。

## 7. 不做

PPTX 形状、DOCX 句子、XLSX 单元格级定位（S11b 只采到幻灯片 / 正文块 / 行）；在预览里切换同一文件的多条引用；Office 证据的 carry；MCP 引用输出（S11d 已定）；改上游预览组件。
