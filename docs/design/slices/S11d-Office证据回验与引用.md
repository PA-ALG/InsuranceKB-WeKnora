# S11d Office 证据的发布回验与引用

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。计划 #446。
> 真实调用：0。测试只用测试内生成的合成 Office 采集；用户的业务样本不进仓库、Issue、PR 或日志。

## 0. 背景

- S11b（#469，已合并）：企业 RAW KB 的 `.pptx/.docx/.xlsx` 在解析时生成 Office 采集（`enterprise-ooxml-structure.v1`）。来源页按页返回逐字文本与块：页文本是本页各块文本以 `\n\n` 连接，块的 `start/end` 是它在页文本中的码点区间（半开），块带 locator：PPTX 为 `PPTX_SHAPE{slide}`（无 `shape_id`），DOCX 为 `DOCX_BLOCK{block_index}`，XLSX 为 `XLSX_CELL_RANGE{sheet, "A<r>:XFD<r>"}`。
- S11c（#479，审核中）：Harness 读 Office 页、按块切分，证据不跨块；Office 证据的 locator 为**所在块的 locator 字段加 `page`、`start`、`end`**（页文本码点，半开）。平台支持前，Harness 以 `EVIDENCE_LOCATOR_UNSUPPORTED` 拒绝提交这类证据（S11c Spec §2.3）。
- 现在平台的发布回验（`releasestore.EvidenceVerifier`）对 `PDF_TEXT_SPAN` 以外的 kind 一律返回 `EVIDENCE_UNSUPPORTED`；引用接口（HTTP、MCP）只打开 PDF 文本区间，其他 kind 返回 422 `EVIDENCE_UNSUPPORTED`。

## 1. 目标

1. 发布回验接受三种 Office 证据：在所引修订（knowledge × parse attempt，文件指纹一致）的采集中找到唯一的块，引文与该块内的页文本切片**逐字相同**；任何不符都以类型化错误拒绝。
2. 引用接口对 Office 证据重新核对同一事实，返回引文、页与块 locator，供查看器跳转（高亮属于 S11e）。
3. PDF 证据的回验顺序、拒绝理由与引用输出**逐字节不变**；只改 `internal/enterprise`，不加上游补丁（G10 不升）。

## 2. Office 证据（冻结）

### 2.1 形状

| kind | locator 中取值非 null 的键，必须恰为 |
|---|---|
| `PPTX_SHAPE` | `kind`、`slide`、`page`、`start`、`end` |
| `DOCX_BLOCK` | `kind`、`block_index`、`page`、`start`、`end` |
| `XLSX_CELL_RANGE` | `kind`、`sheet`、`cell_range`、`page`、`start`、`end` |

- 取值为 `null` 的键视为不存在（Harness 按契约把未用字段序列化为 `null`）。
- 多出任何键（如 `shape_id`：采集只定位到幻灯片，没有形状号；`bbox`、`row`、`column`、`chunk_id` 等）或缺少任何键 → `EVIDENCE_UNSUPPORTED`（理由 `Office locator fields`）。平台不核对它无法核对的位置。
- `match` 缺省或 `EXACT`；其他 → `EVIDENCE_UNSUPPORTED`（与 PDF 相同）。
- 其余字段（`source_ref`、`file_sha256`、`quote`、`quote_sha256`）含义与 PDF 相同；契约（`contracts/`）不改。

### 2.2 发布回验的顺序

逐条证据按下列顺序检查，遇到第一个不满足的即拒绝；`Detail` 为证据的 JSON 指针加理由类别，**从不回显来源文本**。第 1–3、5–6 步与 PDF 共用。

1. `source_ref` 不是 `source:v1:<knowledge>:<attempt>:<sha256>` → `EVIDENCE_UNSUPPORTED`。
2. `file_sha256` 与 `source_ref` 中的指纹不同（不区分大小写）→ `EVIDENCE_MISMATCH`。
3. kind 不是 `PDF_TEXT_SPAN`、`PPTX_SHAPE`、`DOCX_BLOCK`、`XLSX_CELL_RANGE` 之一，或 `match` 不受支持 → `EVIDENCE_UNSUPPORTED`。
4. （Office）§2.1 的键集合不符 → `EVIDENCE_UNSUPPORTED`。
5. 读取所引修订的采集（同一次提交中每个 knowledge × attempt 只读一次）：未采集、修订不存在、完整性失败 → `EVIDENCE_UNVERIFIABLE`；存储故障 → 提交失败（非类型化错误）。
6. 采集文件指纹与 `source_ref` 不同 → `EVIDENCE_MISMATCH`。
7. **采集格式**：证据 kind 必须等于采集的 locator kind——Office 采集为其块的 kind，PDF 采集为 `PDF_TEXT_SPAN`。不同 → `EVIDENCE_MISMATCH`（理由 `captured format`）。这对 PDF 是新增的拒绝，但只影响"`PDF_TEXT_SPAN` 指向 Office 采集"：以前它会按页文本核对并可能通过，现在拒绝；PDF 证据指向 PDF 采集时这一步总是通过，行为不变。
8. （Office）`page` 在 `1..页数` 内，`0 ≤ start < end ≤ 页文本码点数` → 否则 `EVIDENCE_MISMATCH`（`page` / `code-point range`）。
9. （Office）该页恰有一个块满足 `block.start ≤ start` 且 `end ≤ block.end`（块互不重叠，所以至多一个）。没有（跨块、落在块间的 `\n\n`、该页无块）→ `EVIDENCE_MISMATCH`（`block`）。
10. （Office）该块的 locator 与证据逐字段相同：`kind`、`slide`、`block_index`、`sheet`、`cell_range`（字符串逐字比较，`$A$1:$XFD$1` 与 `A1:XFD1` 不同）→ 否则 `EVIDENCE_MISMATCH`（`block locator`）。
11. 引文等于页文本 `[start, end)` 的码点切片，不做任何归一化（与 PDF 相同）→ 否则 `EVIDENCE_MISMATCH`（`quote`）；有 `quote_sha256` 时必须等于 `release.QuoteDigest(quote)` → 否则 `EVIDENCE_MISMATCH`（`quote digest`）。

第 7–10 步是共用的块定位：`source.PageSet.Locate(locator, page, start, end)`，发布回验与引用都调用它，保证两处判断一致。

### 2.3 引用

`GET …/releases/:release_id/citation?member=&evidence=`，证据为 Office kind 时：

- `page`、`start`、`end` 缺任一 → 422 `EVIDENCE_UNSUPPORTED`（与 PDF 相同）。
- 重新读取采集（来源失败沿用 PDF 的映射，如未采集 409 `PARSE_ARTIFACT_NOT_CAPTURED`）；采集指纹、证据指纹、§2.2 第 7–10 步、引文任一不符 → 409 `EVIDENCE_MISMATCH`。与 PDF 引用一样不重复核对 `quote_sha256`（提交时已核对，成员不可变）。
- 200 响应（Office 没有几何信息，因此**没有 `highlight` 键**；`locator` 是采集中块的 locator，按 S11b 的规范编码）：

```json
{
  "release_id": "…", "member": "…", "evidence_index": 0, "origin": "SOURCE_SUPPORTED",
  "source": {"knowledge_id": "…", "parse_attempt": 2, "document": "….pptx", "file_sha256": "…"},
  "page": {"number": 1},
  "start": 6, "end": 11, "quote": "…",
  "locator": {"kind": "PPTX_SHAPE", "slide": 1},
  "block": {"block_id": "s1/p2", "start": 6, "end": 11},
  "file": "/api/v1/enterprise/spaces/…/releases/…/sources/…/attempts/2/file"
}
```

- 原文件接口：按文件名扩展名（不区分大小写）给 `Content-Type`：`.pptx`、`.docx`、`.xlsx` 为各自的 OOXML 媒体类型，其他一律 `application/pdf`（PDF 不变）。
- MCP `knowledge_read_citation`：仍返回 `{document, page, quote}`，Office 的 `page` 为页码（PPTX 为幻灯片号，XLSX 为工作表页序号，DOCX 为 1）。

### 2.4 不变的部分

- PDF 证据：第 1–6、8、11 步的条件、顺序与理由不变；`EvidenceVerifier` 对 PDF 采集的结果不变。
- PDF 引用的 HTTP 与 MCP 输出、`source.Service.Span`、来源页接口不变。
- 受保护测试不改：`releasestore/evidence_verify_test.go`、`release/evidence_acceptance_test.go`、`mount_citation_test.go`、`citation_shared_test.go`、`source/*_test.go`。

## 3. 改动范围

| 方 | 路径 |
|---|---|
| Claude（实现） | `internal/enterprise/release/evidence.go`（`Locator` 增加 Office 字段；`EvidenceCheck.LocatorKeys` 记录取值非 null 的键）；新 `internal/enterprise/source/locate.go`（`PageSet.LocatorKind`、`PageSet.Locate`、`BlockView`）；`internal/enterprise/releasestore/verify.go`（Office 分支）；`internal/enterprise/citation.go`（Office 引用与媒体类型）；`internal/enterprise/mcptools/citation.go` |
| Claude（RED，受保护） | `internal/enterprise/releasestore/office_evidence_verify_test.go`、`internal/enterprise/office_citation_test.go` |

不改：`contracts/`、上游文件、前端、Harness。手写文件 ≤ 500 行。

## 4. 与 Harness、前端的衔接

- S11c 的 `EVIDENCE_LOCATOR_UNSUPPORTED` 闸门按 S11c Spec §2.3 在本片**合并并部署后**移除，单独一个小 PR（Harness 改动与测试），不在本 PR。
- 现在的前端 `CitationPanel` 默认每个非专家引用都有 `highlight` 并用 PDF 查看器打开原文件。Office 引用要等 S11e 的 Office 视图（或至少一个"无高亮时只显示引文"的保护）才能在界面上打开；因此**移除 Harness 闸门的时间不早于前端能显示 Office 引用**。在此之前平台已能回验 Office 证据，但不会收到它。

## 5. 验收

- RED 两个文件全部通过；受保护的 PDF 测试不改断言且通过。
- `go build ./...`、`go vet`、受影响包 `go test`（与 main 同环境逐测试对比）；golangci-lint 对改动行 0 问题；`tests/architecture` 通过（G10 不升）；`git diff --check` 干净。

## 6. 不做

PPTX 形状、DOCX/XLSX 单元格级定位；Office 高亮与查看器（S11e）；引文归一化；Office 证据的 carry；Harness 闸门移除（见 §4）；已发布的、指向 Office 采集的 `PDF_TEXT_SPAN` 证据的引用（S11b 起 `Span` 返回 `INVALID_REQUEST`，本片不改；S11b 上线说明已要求 S11c 前不导入 Office 材料）。
