# S7d-2c-2a · 退役 G3 重解析链（模型派发日志、DocReader 恢复、绑定重解析）

> 状态：Claude 2026-10-23 提出；用户 2026-10-22 同意删除 G3 产品导入链（已备份：标签 `archive/pre-s7-legacy-20261022`），2026-10-23 决定 S7d-2c 一并退役旧 G3 Space ｜ 作者：Claude Code
> 依据：蓝图 §10、§11 S7；S7d-1/2a/2b 已删除产品导入链与 G3 平台路由；S7d-2c-1（#312）把首次解析采集迁入 `internal/enterprise/capture`
> 实现方：Claude ｜ 审核方：Codex（Go 平台、上游文件 `knowledge_process.go` 与 `repository/knowledge.go`）｜ 真实模型调用：0
> 后续：S7d-2c-2b 删除 G3 范围配置与原生候选写入策略；S7d-2c-3 删除 830、SchemaWiki 与旧发布家族

## 1. 目标与现状

G3 产品导入（S7d-1/2a/2b 已删）在解析链上还留着三套只为它服务的机制。它们都由 G3 范围配置（`config.G3PlatformProcessing`）或 G3 绑定重解析回执开启，企业 Space 不经过任何一个：

| 机制 | 位置 | 作用 | 现在的调用方 |
|---|---|---|---|
| 模型派发日志 | `service/knowledge_model_dispatch.go` | G3 范围内每次模型请求先在 span 树里记账，结果未知时禁止重发 | `knowledge_process.go` 的 `withG3ModelDispatchParent`（2 处）、`ensureG3ModelDispatchJournal`（2 处）、`withModelDispatchWorkerRetry`（3 处）；非 G3 知识直接返回原 ctx |
| DocReader 恢复 | `service/g3_docreader_recovery.go` | G3 重解析时复用上一次解析的签封采集，不再调用 DocReader | `reparseKnowledge` 的 `selectG3DocReaderRecovery`、`convert` 的 `loadG3DocReaderRecovery`；`DocumentProcessPayload.DocReaderReuse` |
| 绑定重解析 | `service/g3_bound_reparse{,_gate}.go`、`types/g3_bound_reparse.go` | 平台路由发起、带回执与租约的重解析 | 发起方 `BoundReparseKnowledge` 已无调用方（平台路由 S7d-2b 已删）；剩下 `reparseKnowledge` 的 `bound` 参数、任务闸门 `g3BoundReparseTaskAllowed`、`RecoveryKey`、`interfaces.G3BoundReparseRepository` 与仓库方法 |
| 平台源快照服务 | `service/g3_platform_source_snapshot.go` 的 `G3PlatformSourceSnapshotService`，`knowledge_revision_source.go` 的 `ensureCurrentCompletedForScope` | 把采集、分块页码映射与模型派发回执签成快照交给平台路由 | S7d-2b 删除平台路由后没有生产调用方；它依赖模型派发日志的回执类型（实现时发现，2026-10-23 补入本片） |

## 2. 设计

### 2.1 删除

1. **模型派发日志**：
   - 删除 `knowledge_model_dispatch.go`；
   - 删除 `knowledge_process.go` 中的 7 处挂钩，以及挂钩失败时写"model dispatch journal unavailable"的分支。
2. **DocReader 恢复**：
   - 删除 `g3_docreader_recovery.go`；
   - `reparseKnowledge` 不再选恢复来源，`convert` 不再读恢复、不再记录 `origin_docreader`；
   - 删除 `DocumentProcessPayload.DocReaderReuse`；
   - 采集写入改为不带来源：`s.firstParse.save(id, convertResult, all)`；
   - 删除 `writeFirstParseArtifact`，它的唯一调用方是被删的恢复测试。
3. **绑定重解析**：
   - 删除 `g3_bound_reparse.go`、`g3_bound_reparse_gate.go`、`types/g3_bound_reparse.go`、`interfaces.G3BoundReparseRepository`；
   - 删除 `DocumentProcessPayload.RecoveryKey`；
   - 删除仓库中的 `AllocateG3BoundReparse`、`AdvanceG3BoundReparse`、`parseG3BoundReparseMetadata`、`mergeG3BoundRecoveryMetadata`、`g3BoundReparseMetadataKey`，以及 `UpdateKnowledge` 里按 `product_ingestion_upload` 分支的两处；
   - `reparseKnowledge` 去掉 `bound` 参数及其分支（含 `g3-reparse-` 任务 ID），并入 `ReparseKnowledge`，尽量回到上游形状。
4. **平台源快照服务**：
   - 删除 `G3PlatformSourceSnapshotService` 及其构造、签名、快照类型与摘要函数，以及 `ensureCurrentCompletedForScope`；
   - `g3_platform_source_snapshot.go` 只保留 830 引用家族仍在用的 `captureG3PlatformSource830G3`、`g3PlatformChunkPageMapping` 及其类型，随 S7d-2c-3 删除。守卫 `test_the_helpers_enterprise_capture_shares_stay` 对该文件存在性的断言因此不变。
5. **测试**：删除只测上述机制的测试：
   - `knowledge_model_dispatch_test.go`、`g3_docreader_recovery_test.go`、`knowledge_process_g3_bound_reparse_test.go`、`g3_platform_source_snapshot_test.go`；
   - `repository/g3_bound_reparse_test.go`；
   - `repository/knowledge_concurrency_upgrade_test.go` 中的子用例"allocate G3 bound reparse"。

   两个保留测试借用了被删测试里的夹具，只换夹具，断言不变：
   - `knowledge_attempt_cleanup_upgrade_test.go` 的 `TestReparsePinRaceDoesNotOpenAttemptBeforeAtomicAllocation`：测通用重解析，改用自带的知识、知识库与分配探针；
   - `g3_first_parse_test.go` 的 `TestG3FirstParseProcessDocumentWriteFailureClosesDocreader`：只借用了 span 表，改用本文件内的 span 表夹具。

### 2.2 保留

- **`types.DocumentDocReaderReuseReference` 与 `capture.Record.OriginDocReader`**：S7d-2c-1 冻结的磁盘格式。磁盘上已有带来源的采集仍要能读，读取时照旧复核来源采集。
- **通用模型派发接口**：`types/model_dispatch.go`、`models/api/model_dispatch.go` 及各模型客户端对它们的检查。
  - 本片之后它们不再有安装方，等于空操作；
  - `WithModelAutomaticRetryDisabled` 仍被 `wiki_ingest.go` 使用；
  - 它们织在多个上游模型客户端里，删除放到 S7e 的上游补丁收缩一起做，避免本片改动上游模型包。
- **G3 范围本身**：`g3FirstParseScope`、`config.G3PlatformProcessing`、原生候选写入策略、企业来源路由的 G3 回退。它们由 S7d-2c-2b 删除。本片之后，G3 范围内的重解析退化为普通的完整重解析：重新调用 DocReader，按新 attempt 采集。

### 2.3 已持久化的数据

只列出，不清理：

- 知识元数据中的 `product_ingestion_recoveries`、`product_ingestion_upload`；
- span 表中名为 `model-dispatch.*` 的记录；
- 队列中可能残留的 `docreader_reuse`、`recovery_key` 字段。JSON 解码会忽略它们，对应任务按普通任务执行。

## 3. 上游补丁

- 只删除已有接缝，不新增文件（G10 不变）。
- `knowledge_process.go`、`repository/knowledge.go`、`types/task.go`、`types/interfaces/knowledge.go` 的本项目改动都减少。
- `docs/design/upstream-patches.md` 追加一行 S7d-2c-2a 回退记录。

## 4. 验收（RED，Claude 编写，受保护）

**`tests/architecture/test_legacy_reparse_chain_retired.py`** 检查：

1. 上述服务、类型与测试文件不存在，包括 `g3_platform_source_snapshot_test.go`；
2. `knowledge_process.go`、`repository/knowledge.go`、`types/task.go`、`types/interfaces/knowledge.go`、`g3_first_parse.go` 中不再出现以下符号：
   - `withG3ModelDispatchParent`、`ensureG3ModelDispatchJournal`、`withModelDispatchWorkerRetry`；
   - `selectG3DocReaderRecovery`、`loadG3DocReaderRecovery`；
   - `g3BoundReparseTaskAllowed`、`G3BoundReparseRequest`、`G3BoundReparseRepository`、`AllocateG3BoundReparse`、`AdvanceG3BoundReparse`、`product_ingestion_recoveries`；
   - `RecoveryKey`、`DocReaderReuse `；
   - `writeFirstParseArtifact`；
   - 快照服务：`G3PlatformSourceSnapshotService`、`ensureCurrentCompletedForScope`（也检查 `g3_platform_source_snapshot.go` 与 `knowledge_revision_source.go`）；
3. 保留项仍在：
   - `types.DocumentDocReaderReuseReference`；
   - `capture.Record` 的 `origin_docreader` 标签；
   - `types.WithModelAutomaticRetryDisabled`。

**行为回归**：以下测试照常通过。

- `internal/enterprise/capture` 验收：带来源的旧采集仍可读，格式逐字节不变；
- `enterprise_capture*_test.go`、`source_pages_test.go`、`g3_first_parse_test.go`；
- 重解析相关的现有测试：`knowledge_reparse*`、`knowledge_process*`；
- `repository` 的并发升级测试（其余子用例）；
- `internal/models/...` 的模型派发测试。

## 5. 改动范围

- `internal/application/service/`：
  - 删除 `knowledge_model_dispatch.go`、`g3_docreader_recovery.go`、`g3_bound_reparse.go`、`g3_bound_reparse_gate.go` 及其测试，以及 `g3_platform_source_snapshot_test.go`；
  - 修改 `knowledge_process.go`、`g3_first_parse.go`、`g3_platform_source_snapshot.go`、`knowledge_revision_source.go`；
  - 测试夹具：`knowledge_attempt_cleanup_upgrade_test.go`、`g3_first_parse_test.go`；
- `internal/application/repository/knowledge.go`，以及第 2.1 节第 4 条列出的仓库测试；
- `internal/types/task.go`、`internal/types/interfaces/knowledge.go`，删除 `internal/types/g3_bound_reparse.go`；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/baseline.json`（若下降，按脚本下调）。

## 6. 上线与验证

- 换 App 镜像，无迁移。部署另开 Issue，与 S7d-2c-2b 合并上线，需用户确认。
- 部署后：
  - 演示 Space 的出处照常，读已有采集；
  - 任选一份企业 PDF 重解析，确认生成新 attempt 与新采集，原 attempt 的出处仍可读。
