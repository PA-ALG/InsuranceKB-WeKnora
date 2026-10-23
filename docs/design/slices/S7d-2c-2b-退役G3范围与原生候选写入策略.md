# S7d-2c-2b · 退役 G3 范围配置与原生候选写入策略

> 状态：Claude 2026-10-23 提出；用户 2026-10-23 决定 S7d-2c 一并退役旧 G3 Space，企业 Space 不受影响 ｜ 作者：Claude Code
> 依据：蓝图 §10、§11 S7；S7d-2c-1（#312）采集内核迁入企业包，S7d-2c-2a（#314）删除 G3 重解析链
> 实现方：Claude ｜ 审核方：Codex（Go 平台、配置、上游文件、企业来源与写入路径）｜ 真实模型调用：0
> 后续：S7d-2c-3 删除 830、SchemaWiki 与旧发布家族

## 1. 目标与现状

S7d-2c-2a 之后，G3 只剩"范围"本身：两段配置，以及读它们的几处开关。企业 Space 不依赖其中任何一个。

| 配置 | 读它的地方 | 作用 |
|---|---|---|
| `config.G3PlatformProcessing`（`g3_platform_processing.go`） | `g3FirstParseScope`（`captureFirstParse`、`enterpriseScannedPDF`） | G3 RAW 库的 PDF 走首次解析采集 |
| 同上 | `router.registerEnterpriseRoutes` 的 G3 回退 | 企业来源页接口在 Space 未配置时按 G3 范围读采集 |
| 同上 | `releasestore.reservedScopes` | 企业 Space 不得复用 G3 的 Space、RAW、Wiki 库 |
| `config.ProductIngestion` 的原生候选写入策略（`product_ingestion.go`） | `NativeWikiWritesDisabled`：`knowledge_post_process.go` 1 处、`wiki_ingest_batch.go` 4 处、`container/recover_pending_wiki_tasks.go` 1 处 | 对 G3 产品 RAW 库与 Wiki 库关闭原生 Wiki 生成，启动时也不恢复其待处理队列 |

`NativeCandidateScopeEnabled` 已无调用方。

## 2. 设计

### 2.1 删除

1. **配置**：
   - 删除 `config/g3_platform_processing.go`、`config/product_ingestion.go` 及其测试；
   - 删除 `config.go` 中的 `G3PlatformProcessing`、`ProductIngestion` 字段和 `validateProductWikiProducerPolicy` 调用。
   - 配置解码不拒绝未知键，部署环境 `config.yaml` 里残留的 `g3_platform_processing`、`product_ingestion` 段会被忽略。
2. **原生候选写入策略**：删除 6 处 `NativeWikiWritesDisabled` 判断，这些上游文件恢复原样。删除只测该策略的测试：
   - `native_wiki_policy_test.go`；
   - `container/reset_pending_tasks_test.go` 中的 `ProductIngestion` 子用例。
3. **采集范围**：
   - `captureFirstParse` 只看企业采集范围 `captureScope`；
   - `enterpriseScannedPDF` 去掉 G3 排除条件；
   - 删除 `g3FirstParseScope`。
4. **来源页接口**：删除 `registerEnterpriseRoutes` 的 G3 回退。Space 未在 `ENTERPRISE_SPACES` 中配置时返回 `source.ErrNotFound`，与 `releasestore.enterprisePages` 一致。
5. **保留范围**：删除 `releasestore.reservedScopes`，以及 `ParseSpaces`、`Production` 的保留范围参数。

### 2.2 迁移

**采集的解析器设置**：

- `g3FirstParseConfig` 移入企业包，成为 `capture.ParserConfig(eff)`，作用不变：在规则最前面插入 `pdf → builtin`。
- `knowledge_process.go` 的 `pdf_native_structure_capture` 改用 `capture.NativeCaptureMode`（与 `conceptNativeCapture830G2` 同值）。
- 这样采集链路不再引用 830 常量。

### 2.3 保留

- `failG3FirstParse` 及其错误码 `G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE`：企业采集失败路径在用，受保护测试断言了错误码。改名随 S7d-2c-3 处理。
- `G3FirstParseStore` 及其委托：企业来源与 releasestore 在用。迁出随 S7d-2c-3。

### 2.4 测试调整

只测 G3 范围的测试删除。借 G3 配置开启采集的测试改用 `captureScope`，断言不变。

| 测试 | 处理 |
|---|---|
| `config/g3_platform_processing_test.go`、`config/product_ingestion_native_test.go`、`service/native_wiki_policy_test.go` | 删除 |
| `router/enterprise_sources_test.go` | 删除只测 G3 配置校验与回退的 `…RejectOtherTenantAndDisabledCaptureScope`、`…RejectsInvalidPolicyLifetimeAfterMount`；`…MountScopesSourcesAndLeavesCandidatesUnavailable` 去掉 G3 配置，改为断言未配置的 Space 一律 404 且不读知识库，候选接口仍 503 |
| `router/enterprise_space_sources_test.go` | 删除 `TestEnterpriseSpacesKeepTheG3SourceFallback` |
| `releasestore/production_test.go`、`capture_scope_test.go` | 删除 `TestReservedScopesAlwaysIncludeTheConfiguredG3Scope`、`TestLoadSpacesKeepsTheG3Reservation` |
| `service/enterprise_capture_test.go` | 删除含 G3 配置的用例行（"G3 RAW KB beside Spaces""Space RAW KB beside G3""unrelated KB beside both""disabled G3 policy""G3 scanned page"）与 `g3CaptureConfig` |
| `service/enterprise_capture_boundaries_test.go` | `TestFirstParseKeepsHTMLAndLineEndingsInBothCaptureScopes` 去掉 G3 分支；`TestCaptureScopeExcludesURLImports` 的配置改为空配置 |
| `service/g3_first_parse_test.go` | `…ScopeConfigAndExactChunkContent` 删除 `g3FirstParseScope` 断言，解析器设置断言改测 `capture.ParserConfig`；`…ActualConvertScopesParserAndReusesResult`、`…ProcessDocumentWriteFailureClosesDocreader` 改用 `captureScope` |

## 3. 上游补丁

- 只减少，不新增文件。
- `knowledge_post_process.go`、`wiki_ingest_batch.go`、`container/recover_pending_wiki_tasks.go` 删除策略判断；`config.go`、`router.go` 删除 G3 字段与回退。
- 若某文件因此回到上游原样，G10 随之下降。
- `docs/design/upstream-patches.md` 追加一行 S7d-2c-2b 回退记录。

## 4. 验收（RED，Claude 编写，受保护）

**`tests/architecture/test_legacy_scope_policy_retired.py`** 检查：

1. 配置文件与只测它们的测试不存在：`g3_platform_processing{,_test}.go`、`product_ingestion.go`、`product_ingestion_native_test.go`、`native_wiki_policy_test.go`；
2. 以下文件不再出现 `G3PlatformProcessing`、`ProductIngestion`、`NativeWikiWritesDisabled`、`NativeCandidatesPolicy`、`DecodeG3PlatformProcessing`、`g3FirstParseScope`、`g3FirstParseConfig`、`reservedScopes`：
   - `config/config.go`；
   - `service/knowledge_process.go`、`knowledge_post_process.go`、`wiki_ingest_batch.go`、`g3_first_parse.go`；
   - `container/recover_pending_wiki_tasks.go`、`router/router.go`；
   - `releasestore/production.go`、`releasestore/spaces.go`；
3. `knowledge_process.go` 不再引用 `conceptNativeCapture830G2`；采集只由 `captureScope` 决定；`capture.ParserConfig` 存在。

**行为回归**：以下测试照常通过（G3 用例按 §2.4 调整后）。

- 企业采集：`enterprise_capture*_test.go`、`source_pages_test.go`、`internal/enterprise/capture`；
- 企业来源页：`router/enterprise_space_sources_test.go`；
- `releasestore` 全部；
- `container` 的待处理队列恢复。

## 5. 改动范围

- `internal/config/`：删除两个文件及其测试，修改 `config.go`；
- `internal/application/service/`：
  - 修改 `knowledge_process.go`、`knowledge_post_process.go`、`wiki_ingest_batch.go`、`g3_first_parse.go`；
  - 删除 `native_wiki_policy_test.go`；
  - 调整 §2.4 列出的测试；
- `internal/enterprise/capture/`：新增 `ParserConfig`（放在现有文件中）；
- `internal/container/recover_pending_wiki_tasks.go`、`reset_pending_tasks_test.go`；
- `internal/router/router.go` 及 §2.4 列出的两个测试文件；
- `internal/enterprise/releasestore/production.go`、`spaces.go` 及其测试；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/baseline.json`（若下降，按脚本下调）。

## 6. 上线与验证

换 App 镜像，与 S7d-2c-2a 一起部署，无迁移。部署另开 Issue，需用户确认。

**风险：旧 G3 库的原生 Wiki 生成会重新打开。** 原生候选写入策略删除后，G3 产品 RAW 库与 Wiki 库按普通知识库对待：

- 如果库开着 Wiki 索引，新上传与重解析会触发原生 Wiki 生成；
- 新 App 启动时，`recoverPendingWikiTasks` 会把这两个库里积压的待处理 Wiki 任务重新排队。

两者都会产生真实模型调用，不在任何预算内。所以部署 Issue 必须先做只读预检，结果由用户裁定：

1. 记录 G3 RAW 库与 Wiki 库的 Wiki 索引开关；
2. 统计 `task_pending_ops` 中这两个库的待处理 Wiki 任务数。

两项都为"关闭 / 0"才直接换镜像。否则由用户决定是否先关闭这两个库的 Wiki 索引、清空其待处理 Wiki 任务。这一步属于数据或设置变更，要单独批准并记录回滚方式。

**部署后**：

- 演示 Space 的出处照常；
- 旧 G3 Space 的来源页返回 404，这是预期的退役结果；
- App 日志中没有 G3 库的 Wiki 任务被恢复。
