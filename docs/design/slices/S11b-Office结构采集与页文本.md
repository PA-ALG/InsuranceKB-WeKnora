# S11b Office 结构采集与页文本（采用上游 sourceloc）

> 状态：Spec 冻结（2026-10-30，Claude）。实现方 Claude，审核方 Codex。Issue #447。
> 真实调用：0。用户提供的业务 PPTX/DOCX/XLSX 样本只在本机私有目录做验证，**不进仓库、Issue、PR 或日志**；测试只用测试内生成的合成文件。
>
> **取代** 2026-10-29 冻结的版本（分支 `slice/s11b`，Spec `9322b0595`/`a8fff6ca1`，RED `df2ddf061`，未实现、未合并）。
>
> 2026-10-30 修订（PR #469 审核 R1、R2）：§2.3 增加"包完整性"（上游读取器遇坏部件或缺部件会静默返回已读部分）；§4 的 `format` 只接受三个冻结字面值。

## 0. 为什么改

旧版准备自写 OOXML 提取器（PPTX 到 shape、表格到单元格）。2026-10-29 的调研（#446）发现上游 WeKnora 在我们原固定版本之后已经实现了 Office 结构定位（上游 #3700、#3794，`internal/sourceloc/office.go`），许可证宽松；用户要求优先采用成熟方案。U-1（#460）已把上游 v0.9.0 合入 main，`sourceloc` 现在就在本仓库。Owner 裁定（#446）：

- **采用上游 `sourceloc.StructureUnits`，按上游粒度定位**：PPTX 到幻灯片（每个文本段落一个单元），DOCX 到正文顶层块（段落；整张表格为一个块），XLSX 到工作表的行。
- **我方只做薄适配**：在上游之前加我方需要的输入安全限制，把上游单元组装成我方采集结构，存入既有采集记录，来源页接口返回块。
- 更细的粒度（PPTX 形状、DOCX 单元格、XLSX 单元格）以后真正需要时再做，不在本片。

与旧版的差别：

| 项 | 旧版（作废） | 本版 |
|---|---|---|
| 提取 | 自写 OOXML 解析 | 上游 `sourceloc.StructureUnits` |
| PPTX locator | `PPTX_SHAPE`，`shape_id` 必填，表格单元格带 `row/column` | `PPTX_SHAPE`，只有 `slide`；**`shape_id` 不填**（上游单元是段落级，没有形状号） |
| DOCX | 段落 `DOCX_BLOCK` + 表格单元格 `DOCX_TABLE_CELL` | **只有 `DOCX_BLOCK`**：段落一个块，整张表格一个块（上游按行出单元，本片按块合并） |
| XLSX | 单元格 `XLSX_CELL_RANGE` | `XLSX_CELL_RANGE` 覆盖**整行**：`A<r>:XFD<r>` |
| 采集方式 | Office 走首次解析采集模式（替换 docreader 结果） | **附加采集**：上游解析流程不变，另外用原文件字节生成 Office 采集并封存 |
| 提取失败 | 整次解析失败 | **只是不采集**：知识照常入库，来源页返回 `PARSE_ARTIFACT_NOT_CAPTURED`，日志记类型码 |

为什么改成附加采集：PDF 首次解析模式会关掉图片存储与 Markdown 归一化，并要求解析结果没有图片；业务 PPT 每份有几十到上百张图片，按 PDF 模式会全部采集失败，而且会改变这些文件的问答切块。Office 采集不依赖 docreader 的 Markdown 与结构对齐，附加采集不改上游解析与问答行为。

契约说明：`contracts/locator.schema.json` 本身不规定各 kind 的必填字段；Harness 的 `Locator` 模型目前要求 `PPTX_SHAPE` 带 `shape_id`。Harness 何时读取 Office 块由 S11c 决定，届时把 `PPTX_SHAPE` 的必填项放宽为只有 `slide`（S11c 的改动，不在本片）。`cell_range` 的 `A<r>:XFD<r>` 符合契约里的 A1 模式。

## 1. 目标

企业 RAW KB 上传的 `.pptx`、`.docx`、`.xlsx`，每次解析时平台都从**原文件字节**确定性生成 Office 结构，作为该次解析（knowledge × parse attempt）的采集记录封存。来源页接口按页返回逐字文本与块，每个块带 Office locator。Harness、回验与回跳之后都基于这份采集，不再解析。

## 2. 结构（新包 `internal/enterprise/capture/ooxml`）

### 2.1 冻结接口

```go
package ooxml

const Contract = "enterprise-ooxml-structure.v1"      // 采集结构的 schema 版本
const ExtractorIdentity = "enterprise.ooxml.sourceloc.v1" // 解析器身份；上游 sourceloc 输出变化时升版本

const (
	ErrorUnsupported = "OFFICE_UNSUPPORTED" // 不支持的格式、OLE/加密包或旧版二进制格式
	ErrorTooLarge    = "OFFICE_TOO_LARGE"   // 超出包限制
	ErrorMalformed   = "OFFICE_MALFORMED"   // zip 损坏、必需部件缺失或非法、DTD/实体声明、非法 UTF-8
	ErrorEmpty       = "OFFICE_EMPTY"       // 没有任何文本块
)

type Error struct{ Code, Detail string } // Detail 只写部件名或计数，不写文档文本
func (e *Error) Error() string

type Locator struct {
	BlockIndex *int   `json:"block_index,omitempty"` // DOCX：正文顶层段落/表格的 0 起序号
	CellRange  string `json:"cell_range,omitempty"`  // XLSX：A<r>:XFD<r>
	Kind       string `json:"kind"`                  // PPTX_SHAPE | DOCX_BLOCK | XLSX_CELL_RANGE
	Sheet      string `json:"sheet,omitempty"`       // XLSX：工作表名
	Slide      *int   `json:"slide,omitempty"`       // PPTX：1 起幻灯片号
}

type Block struct {
	ID      string  `json:"block_id"`
	End     int     `json:"end"` // 页内 Unicode 码点区间 [start, end)
	Locator Locator `json:"locator"`
	Start   int     `json:"start"`
}

type Page struct {
	Blocks     []Block `json:"blocks"`
	Number     int     `json:"page_number"`
	TextSHA256 string  `json:"page_text_sha256"`
	Text       string  `json:"text"`
}

type Structure struct {
	Contract             string `json:"contract"`
	Extractor            string `json:"extractor"`
	Format               string `json:"format"` // "pptx" | "docx" | "xlsx"
	Pages                []Page `json:"pages"`
	ParserIdentitySHA256 string `json:"parser_identity_sha256"` // SHA-256(ExtractorIdentity)
	SourceSHA256         string `json:"source_sha256"`          // SHA-256(原文件字节)
}

func Supports(fileType string) bool                       // pptx、docx、xlsx（大小写不敏感，可带点）
func Extract(fileType string, data []byte) (*Structure, error)
func Encode(s *Structure) ([]byte, error)                 // 规范编码：字段按 JSON 键字母序，不转义 HTML，无结尾换行
func Decode(data []byte) (*Structure, error)              // 严格解码（拒绝未知字段、尾随数据）并做 §4 全部校验
```

结构体字段按 JSON 键的字母序声明，所以 `Encode` 的输出就是规范字节；采集校验要求存储字节与重新编码逐字节相同（与 PDF 原生结构同一做法）。

### 2.2 由上游单元组装页与块

`Extract` 先做 §2.3 的安全检查，再调用 `sourceloc.StructureUnits(format, data)`，按格式组装：

- **PPTX**：页数等于 `ppt/presentation.xml` 中 `sldIdLst` 的条目数（含隐藏幻灯片），第 i 张为第 i 页；没有文本的幻灯片仍占一页（页文本为空串、无块），保证页码与幻灯片号一致。上游的每个段落单元（含备注页段落，排在本页正文段落之后）为一个块，`PPTX_SHAPE{slide: 页码}`，块 ID `s<页码>/p<k>`（k 为本页第 k 个段落，1 起）。
- **DOCX**：整份文档为第 1 页（DOCX 没有可靠的物理页）。上游按正文顶层段落出单元、表格按行出单元且同一表格各行共用块号；本片把同一块号的连续单元合并为一个块，行与行之间用 `\n` 连接。`DOCX_BLOCK{block_index: 上游块号 − 1}`，块 ID `b<block_index>`。
- **XLSX**：每个工作表一页，按 `xl/workbook.xml` 中 `sheets` 的顺序；没有非空行的工作表仍占一页。上游的每个非空行为一个块，`XLSX_CELL_RANGE{sheet, cell_range: "A<r>:XFD<r>"}`，块 ID `x<页码>/r<r>`。
- **页文本**：本页各块文本按顺序以 `\n\n` 连接；块的 `start/end` 为该块文本在页文本中的码点区间；`page_text_sha256` 为页文本 UTF-8 字节的 SHA-256 小写十六进制。
- **整份没有任何块** → `OFFICE_EMPTY`。上游单元数达到其上限（20 万）时视为被截断 → `OFFICE_TOO_LARGE`，不保存不完整的结构。
- **确定性**：相同字节两次提取，`Encode` 结果逐字节相同。

图片、图表、SmartArt、OLE 对象中的文字不在本片（图片文字属于 S10 OCR）。

### 2.3 输入安全（上传文件不可信）

检查顺序：格式 → OLE 头 → zip 结构 → 包限制 → 上游提取。

- 格式不是 pptx/docx/xlsx → `OFFICE_UNSUPPORTED`；以 OLE 复合文档头开头（加密 OOXML、旧版 `.ppt/.doc/.xls`）→ `OFFICE_UNSUPPORTED`。
- zip 无法打开 → `OFFICE_MALFORMED`。
- 包限制（逐条目实际解压计数，不信任声明大小）：条目数 ≤ 10,000；解压后总字节 ≤ 512 MiB；任一 XML 部件（`.xml`、`.rels`）≤ 64 MiB。超出 → `OFFICE_TOO_LARGE`。解压出错 → `OFFICE_MALFORMED`。
- 任一 XML 部件含 DTD 或实体声明（`<!DOCTYPE`、`<!ENTITY`）→ `OFFICE_MALFORMED`。
- 上游提取报错（必需部件缺失或非法）→ `OFFICE_MALFORMED`；块文本不是合法 UTF-8 或含 NUL → `OFFICE_MALFORMED`。
- 上游自身另有每条目 64 MiB 的读取上限，保留不动。
- **包完整性**：上游读取器遇到 XML 错误就停止，找不到声明的幻灯片、备注页或工作表就跳过，两种情况都不报错，只返回已读到的部分。所以信任上游结果之前，先证明包是完整的；任一项不满足 → `OFFICE_MALFORMED`，不保存采集，原解析不受影响：
  - 条目名唯一（上游按名取第一个条目）；
  - 每个 XML 部件（`.xml`、`.rels`，不论上游是否读取）用上游同一个解码器读到结尾：合法 UTF-8，不含 XML 字符范围以外的字符（含 NUL），元素配对，恰好一个根元素；工作表中的每个单元格，其类型化字段（样式序号、公式与内联字符串的类型化属性）按工作簿读取方流式读取时的方式能解码，因为读取方会丢弃这个解码错误，单元格文本也随之丢失；
  - DOCX：`word/document.xml` 存在；
  - PPTX：`sldIdLst` 中每张幻灯片都有关系，目标部件也存在；一张幻灯片至多一个备注关系，有则目标部件存在；
  - XLSX：至少一个工作表；表名在读取方的大小写折叠规则下唯一；每个工作表用读取方自己的调用流式读到结尾，读取方不报错（包括部件缺失、单元格引用非法、行号越界）。
  - 不在此校验的：解码成功后单元格值如何呈现（例如共享字符串序号越界时读取方给出空值）。这属于读取方的语义，随 `ExtractorIdentity` 版本化。

## 3. 采集接线（附加采集）

- 触发条件：企业 RAW KB（`captureScope.RawKB`）中非 URL 上传，`ooxml.Supports(fileType)`；每次解析（含重新解析）都触发。PDF 首次解析采集（`captureFirstParse`）不变，Office 不进入首次解析模式。
- 时机：`convert()` 在 docreader 成功返回、上游 `attachStructureBlocks` 之后，用同一份原文件字节调用我方方法 `captureOffice`（实现放在我方文件 `g3_first_parse.go`；上游文件 `knowledge_process.go` 只加一行调用，该文件已是登记的上游补丁，不新增上游文件）。
- 身份与绑定：只在 `payload.Revision` 存在、其 `ParseAttempt` 等于知识的当前解析次数（payload 指定 attempt 时也须相等）、且 `Revision.FileSHA256` 等于原文件字节的 SHA-256 时保存；`capture.Identity` 的 `SourceSHA256` 即该摘要。
- 保存：`capture.Office(fileType, data)` 返回 `ReadResult{MarkdownContent: 各页文本以 "\n\n" 连接, NativeStructure: Office 结构}` 与每个非空页一个的区间块，交给既有 `Store.Save`。采集记录的冻结布局（`Contract`、键、签名域、JSON 字段）不改；`NativeStructure.SchemaVersion` 为 `ooxml.Contract`。
- 失败：不保存不完整的采集，知识照常处理（上游解析与问答不变）；记录 `OFFICE_*` 或采集错误类型码到日志（不含文档文本）。来源页对该次解析返回 `PARSE_ARTIFACT_NOT_CAPTURED`。
- `capture.ValidateNative` 增加 Office 分支：`SchemaVersion == ooxml.Contract` 时，用 `ooxml.Decode` 校验结构，并要求存储字节与 `Encode` 结果相同、`source_sha256` 等于采集身份、`parser_identity_sha256` 等于记录的解析器身份、原始与清洗摘要一致、`MarkdownContent` 等于各页文本以 `\n\n` 连接。PDF 分支逐字节不变。

## 4. 来源页接口

- `source.Service` 读到 `contract` 为 `enterprise-ooxml-structure.v1` 的原生结构时走 Office 分支，页与块**直接取自结构**（不从 Markdown 切）；其他（PDF）走现有分支，行为与输出逐字节不变。
- Office 校验（任一不满足 → `PARSE_ARTIFACT_INTEGRITY`），由 `ooxml.Decode` 统一实现：
  - `contract`、`extractor`、`parser_identity_sha256 == SHA-256(extractor)` 一致；`format` 必须是 `pptx`、`docx`、`xlsx` 三个字面值之一（`Supports` 接受的输入别名，如大写、带点号或首尾空白，在存储结构中一律无效），locator 校验按这个字面值分派，其他值不进入任何格式分支；`source_sha256` 等于采集文件摘要；
  - 页码从 1 连续，至少一页；每页 `page_text_sha256` 等于页文本摘要；
  - 块按 `start` 升序、互不重叠、`0 ≤ start < end ≤ 页文本码点数`；块文本去空白后非空；同页块 ID 唯一；
  - locator 与 `format` 匹配：pptx 只允许 `PPTX_SHAPE` 且 `slide == 页码`、无其他字段；docx 只有 1 页、只允许 `DOCX_BLOCK` 且 `block_index` 非负并严格递增；xlsx 只允许 `XLSX_CELL_RANGE`、`sheet` 非空且同页一致、不同页互不相同、`cell_range` 为同一行的 `A<r>:XFD<r>` 且行号严格递增。
- 另外核对 `source_sha256 == Artifact.FileSHA256`、`parser_identity_sha256 == Artifact.ParserIdentitySHA256`。
- `Page` 增加 `Blocks []ooxml.Block json:"blocks,omitempty"`：PDF 页 JSON 不变（无 `blocks` 键）；Office 页带块（没有块的空页同样不带该键）。
- `Span`（PDF 高亮矩形）对 Office 采集返回 `INVALID_REQUEST`；Office 的块视图属于 S11d。

## 5. 改动范围

| 方 | 路径 |
|---|---|
| Claude（实现） | 新包 `internal/enterprise/capture/ooxml/`；`internal/enterprise/capture/`（`native.go` Office 分支、新 `office.go`）；`internal/enterprise/source/`（Office 分支、`Page.Blocks`、`Span` 拒绝）；`internal/application/service/g3_first_parse.go`（`captureOffice`）及其测试 `office_capture_test.go`；`internal/application/service/knowledge_process.go` 一行调用 |
| Claude（RED，受保护） | `internal/enterprise/capture/ooxml/acceptance_test.go`、`internal/enterprise/source/office_pages_test.go`、`internal/enterprise/capture/office_capture_test.go` |

不改：`contracts/`、`internal/sourceloc/`（上游原样）、docreader、前端、Harness、发布回验与引用（S11c–S11e）。手写文件 ≤ 500 行。

## 6. 验收

- RED 三个文件全部通过；`go test` 受影响包通过，既有 PDF 来源页与采集测试不改断言；golangci-lint 对改动行 0 问题；守卫不新增违例（G10 不升）。
- 私有验证（Claude 在本机执行，结果只写抽象摘要）：对用户的 4 份 PPTX、1 份 DOCX、1 份 XLSX 调用 `ooxml.Extract` 全部成功；PPTX 页数等于幻灯片数；同一文件两次提取 `Encode` 结果相同；`Decode` 校验通过。

## 7. 上线说明

- 采集只在解析时生成：已上线的 Office 知识要重新解析后才有采集。
- S11b 让 Office 来源页可读；Harness 对 Office 材料的角色、可作证据的字段与归属规则属于 S11c。**S11c 合并前，不向线上企业 RAW KB 上传或重解析业务 Office 材料**，避免 Harness 在规则就绪前读取这些页。

## 8. 不做

PPTX 形状、DOCX/XLSX 单元格级定位；图片/图表/SmartArt 文字（S10）；`.ppt/.doc/.xls` 旧格式（`OFFICE_UNSUPPORTED`）；`pptm/docm/xlsm` 宏格式；发布回验、引用与查看器（S11d、S11e）；Harness 消费与归属（S11c）。
