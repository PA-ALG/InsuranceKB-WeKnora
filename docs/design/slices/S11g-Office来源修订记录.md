# S11g · Office 材料的来源修订记录（线上阻断修复）

> 状态：Claude 2026-11-01 提出 ｜ 作者：Claude Code ｜ 审核：Codex
> 依据：蓝图 §6.2（发布固定来源）、§7.4（多格式定位）；S4c-2b-1（提交登记 released、发布固定）；S11b–S11e（Office 定位、回验、引用、查看）。
> 真实调用：0；不部署（部署与线上补录另开运维 Issue）。

## 1. 问题

线上首次发布引用 Office 证据的 Release 时，激活返回 HTTP 409 `SOURCE_UNAVAILABLE`（“a cited source is unavailable”）。
激活要在同一事务里固定（pin）所有被引用的来源修订：`PinRevisionSources`（`internal/application/repository/knowledge.go`）
按 `tenant + knowledge_id + parse_attempt` 读 `knowledge_revision_sources`，缺行即 `ErrRevisionSourceUnavailable`。

线上只读核对：所有 PDF 修订都有这一行；6 份 Office 上传（PPTX / DOCX / XLSX）都有 `knowledge_revisions` 行，**但都没有**
`knowledge_revision_sources` 行。

根因：修订提交时登记来源的 `recordRevisionSourceLocked`（`knowledge.go`，S4c-2b-1 引入）只登记 PDF——

```go
if !strings.EqualFold(strings.TrimSpace(resource.MimeType), "application/pdf") {
	return nil
}
```

S11 让 Office 材料能被采集、回验与引用，却没有放开这处“提交时登记来源”的格式门槛，于是引用 Office 的 Release 永远无法激活。
另一个可能叠加的因素：资源的 MIME 由 `mime.TypeByExtension` 按主机 MIME 表得出（`service/file/resource_catalog.go`），
容器缺少 `/etc/mime.types` 时 Office 资源的 `mime_type` 为空串。

## 2. 改动

### 2.1 提交时登记：PDF 不变，增加三种 Office 格式

新增 `types.RevisionSourceMIME(resourceMIME, originalName string) (string, bool)`（`internal/types/knowledge_revision.go`，项目自有文件），
决定一个已登记资源能否在提交时登记来源、登记成什么 MIME：

| 资源 MIME（去空白、小写） | 资源原始文件名扩展名 | 结果 |
|---|---|---|
| `application/pdf` | 任意 | 登记，MIME `application/pdf`（**与现状逐字节相同**） |
| 空串，或等于该扩展名的标准 MIME | `.docx` / `.pptx` / `.xlsx` | 登记，MIME 用固定表中的标准 OOXML MIME |
| 其他（含 MIME 与扩展名不一致，如 `image/png` + `.docx`） | 任意 | 不登记（同现状对非 PDF 的处理：提交照常成功，无来源行） |

固定表（代码内常量，不读主机 MIME 表）：

| 扩展名 | MIME |
|---|---|
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.pptx` | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

`recordRevisionSourceLocked` 把原来的 PDF 判断换成这个函数；其余校验（资源 active、persistent、size > 0、`source_file` 绑定恰好
一条、内容摘要与修订 SHA 一致或补写空摘要）与写入的字段（released、`binding_digest` 为空、`page_count` 为空）完全不变。
提交时登记的行**不封存**——封存（`binding_digest`、`page_count`）仍只服务 PDF 的固定修订读取（exact3 等），本片不改。

### 2.2 补录：已提交但缺来源行的修订

线上已有 6 份 Office 上传在修复前提交，缺来源行。重新解析会产生新的 attempt，进而改变登记表材料修订、需要重新归属与重新编译；
因此提供**补录**，不重解析。

- 仓库新方法 `RecordMissingRevisionSource(ctx, tenantID, knowledgeID, parseAttempt, dryRun)`（`knowledge.go`）：在一个事务里锁定
  knowledge，要求 `parse_status = completed`、`current_parse_attempt = parseAttempt`、`file_sha256` 非空；读取该 attempt 的
  `knowledge_revisions` 行（必须存在且 `file_sha256` 相同）；
  - 已有来源行 → 结果 `present`，**不做任何修改**（PDF 的既有行不会被触碰）；
  - 否则走与提交时**同一个**准备函数（2.1 的格式与资源校验）；不支持的格式或校验失败 → `ErrRevisionSourceUnavailable`，不写；
  - `dryRun` → 结果 `would_record`，返回准备好的行，不写任何东西（也不补写资源的空摘要）；
  - 否则写入，结果 `recorded`。
- 服务方法 `KnowledgeRevisionSourceService.RecordMissingSource`（`internal/enterprise/revisionsource/record_missing.go`，新文件）：
  与既有补录同一授权（人工租户管理员、非 API Key、`knowledge_revision_source.backfill_enabled`），先按当前完整修订解析资源、
  **读取对象字节并核对 sha256 等于修订的 `file_sha256`**（以及资源已有摘要），再调用仓库方法；任何不符 → `REVISION_SOURCE_MISMATCH`。
- 路由 `POST /api/v1/knowledge/:id/revisions/:attempt/source/record?dry_run=true|false`（既有自有路由文件，与 `/source/backfill`
  同一组守卫：拒绝 API Key、Admin、知识写权限）。回执合同 `knowledge-revision-source-record.v1`：结果（`present` /
  `would_record` / `recorded`）与行的身份字段（不含文件内容与路径）。

### 2.3 不做

- 不改 `PinRevisionSources`、`ReleaseRevisionSources`、封存与 exact3；不放开其他格式（Markdown、图片等仍不登记）。
- 不改资源 MIME 的推断（主机 MIME 表问题由 2.1 的固定表绕开）。
- 不在本片执行线上补录。

## 3. 线上补录计划（另开运维 Issue，部署后执行）

1. 部署含本片的 App（无迁移）。确认 `knowledge_revision_source.backfill_enabled` 在线上配置中为 true（不读取含凭据的配置文件，由部署方核对）。
2. 对 6 份 Office 上传逐一调用补录接口，先 `dry_run=true`：期望 `would_record`，MIME 为对应 OOXML；任何 `present`/错误先停下。
3. 再 `dry_run=false`：期望 `recorded`；PDF 不调用。
4. 重试卡住的发布（同一 publish 运行从已记录 attempt 继续），激活后在接口与界面核对一条 PPTX 引用。

## 4. 验收（RED）

- 仓库：提交一份 DOCX / PPTX / XLSX（资源 MIME 为标准值，或为空串）→ 有 released 来源行、MIME 为标准值、`binding_digest` 为空；
  MIME 与扩展名不一致 → 无来源行且提交成功；PDF 行逐字节不变（既有受保护测试不改）；`PinRevisionSources` 对 Office ref 成功、
  状态变为 pinned。
- 补录：删除来源行后 `dryRun` → `would_record` 且不写；真实 → `recorded`；再次调用 → `present` 不改；已有 PDF 行 → `present`；
  attempt 不是当前、修订缺失、资源摘要不符、不支持格式 → 拒绝不写。
- 服务：非管理员 / API Key / 未开启补录 → `REVISION_SOURCE_BACKFILL_DISABLED` 且不读权威与对象；对象字节摘要不符 → 拒绝、不调用仓库写。
- 门禁：受影响包 `go test`、`go vet`、golangci-lint（new-from-rev）、ParadeDB 通道、`tests/architecture`、`git diff --check`。
  `knowledge.go` 是已登记的上游补丁文件（S4c-2b-1 行），本片在登记表追加说明行，不新增补丁文件，G10 不变。
