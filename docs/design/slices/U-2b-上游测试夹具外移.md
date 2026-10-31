# U-2b 上游测试夹具外移：还原 8 个上游测试文件

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。属于 U-1 阶段 c（Issue #451），接 U-2a（#478）。
> 真实调用：0。不部署；只改测试文件与文档，无生产代码、无迁移。

## 1. 目标与规则

`main@71ea503dd` 上 G10 共 161 个上游补丁文件，其中 34 个是上游**测试**文件。本片把其中"只因我方补丁才改、且改法可以挪走"的测试文件恢复为固定基线 `f17ee8a8d`（v0.9.0）原样。

还原的前提（逐条都要满足）：

1. **不改生产代码**，生产侧的失败关闭语义一律不动（缺分类器、缺 `kgRepo`、PostgreSQL 报错等仍然失败）；
2. 我方新增的测试、夹具字段与方法搬到**同包的新测试文件**（G11 允许在上游包内新增测试文件；不新增非测试 Go 文件）；
3. 搬动的测试**断言原样**；只允许夹具层面的等价改写：用包装类型代替给上游桩加字段、在测试内自建 pin 表代替改上游夹具、去掉只写不读的字段；
4. 上游测试在当前生产代码下原样通过；与 main 同环境逐测试对比，不新增失败。

## 2. 34 个候选与结论

### 2.1 本片还原（8 个，G10 161 → 153）

| 文件 | 我方改动 | 外移到 |
|---|---|---|
| `cli/cmd/dryrun_coverage_test.go` | 漂移守卫的期望表加我方两个回填命令 | `cli/cmd/revision_source_dryrun_test.go`：`init()` 往同一张表登记（包级变量先于 `init` 初始化） |
| `docreader/client/client_test.go` | `docreader_integration` 构建标签（8 月时上游测试缺服务即失败） | 不需要：v0.9.0 上游测试在没有 DocReader 服务时自行 `t.Skip`，标签的原因已不存在；还原后上游新增的 `TestNewClientDoesNotChangeGlobalGRPCResolver` 也恢复运行 |
| `docreader/tests/test_pdf_router.py` | 我方 PDF 解析补丁的 11 个测试（数值表清洗 2、原生结构采集 9）；删了一个未用的导入 | `docreader/tests/test_pdf_native_structure_capture.py` |
| `internal/application/service/resource_test.go` | 夹具 `AutoMigrate` pin 表；1 个测试 | `resource_revision_pin_test.go`：测试内自建 pin 表（上游夹具无表时 `MarkDeleted` 按既有规则视为未钉住） |
| `internal/application/service/knowledge_create_test.go` | 入队桩加载荷字段；2 个测试；一个上游测试里追加 6 条断言 | `knowledge_create_revision_test.go`：自有入队桩（嵌入上游桩，额外记录载荷）；6 条断言放进同样准备步骤的新测试 |
| `internal/application/service/knowledge_move_wiki_test.go` | 仓储桩加字段与 `HasPinnedRevisionSource`；1 个测试 | `knowledge_move_revision_pin_test.go`：包装上游桩的类型 |
| `internal/application/service/knowledge_batch_reparse_test.go` | 仓储桩加 3 个方法与 3 个只写字段 | `knowledge_batch_reparse_revision_test.go`：在同包新文件里为上游桩类型声明这 3 个方法；只写字段去掉 |
| `internal/application/service/file/resource_catalog_test.go` | 两个桩加字段；1 个测试 | `resource_catalog_pin_test.go`：包装上游桩的类型 |

### 2.2 不还原（26 个）

| 原因 | 文件 | 说明 |
|---|---|---|
| 受管 KB 访问（KBPOLICY）：缺分类器/受管角色必须失败关闭 | `service/agent_browser_source_test.go`、`service/agent_tool_surface_test.go`、`mcpserver/scope_test.go`、`mcpserver/tools_read_document_test.go`、`mcpserver/tools_search_documents_test.go`、`router/router_api_key_capabilities_test.go`、`router/router_wiki_test.go`、`router/routes_mcp_endpoint_test.go`、`router/operations_test.go` | 生产注册签名或依赖已变，等上游接受通用 KB 访问策略接口（Tencent/WeKnora#4958） |
| 知识库删除缺 `kgRepo` 必须失败关闭（U-2a 已裁定） | `service/datasource_delete_sqlite_test.go`、`service/knowledgebase_delete_datasource_test.go`、`service/knowledgebase_task_cancel_test.go` | 不为还原测试放宽空依赖 |
| 我方补丁改变了上游断言的行为 | `service/knowledge_attempt_supersede_test.go`、`service/knowledge_process_index_retry_test.go`（W1 按精确 ID 清理）、`service/knowledge_process_status_test.go`（成功索引即清旧错误）、`service/wiki_ingest_test.go`、`service/wiki_ingest_retry_test.go`（Wiki 重试归属，WIKIINGEST） | 上游原断言在当前生产代码下不成立；随对应上游 PR 退出 |
| 上游 SQL 夹具缺我方列 | `repository/knowledge_finalize_test.go` | 手写 `CREATE TABLE` 需要 `current_parse_attempt`、`file_sha256` |
| 可还原但需先改我方测试夹具（下一片） | `service/knowledge_process_parent_child_test.go`（共用桩的字段被我方 `knowledge_attempt_cleanup_upgrade_test.go` 等使用）、`service/knowledge_replace_test.go`（夹具已移到我方 `knowledge_replace_fixture_test.go`，带我方测试断言用的字段） | 先把我方测试改为包装类型再还原，单独成片 |
| 封闭的 SSRF 测试（U-1a 保留） | `service/tenant_sandbox_config_test.go`、`service/file/oss_test.go`、`service/mcp_service_test.go`、`handler/tenant_secret_disclosure_test.go`、`models/embedding/protocol_test.go` | 上游版本解析真实域名，在本机假 IP 解析下每次本地运行都失败；拟作为上游测试修复提 PR |
| lint 行宽（U-1a 保留） | `repository/retriever/opensearch/repository_test.go` | 还原会让 4 行超过 120 列，`--new-from-merge-base` 会报为新问题 |

## 3. 验收

- RED（受保护）`tests/architecture/test_u2b_upstream_tests_restored.py` + `u2b_restored_upstream_tests.txt`：8 个文件与 `f17ee8a8d` 逐字节一致；G10 ≤ 161 − 8。
- 受保护测试调整（单独提交、写明原因）：`tests/architecture/test_u1a_upstream_lint_reverted.py` 的 `KEPT` 去掉 `cli/cmd/dryrun_coverage_test.go`（覆盖改由我方测试文件登记，不再需要改上游文件）。
- 测试数：各包顶层测试函数数不少于 main（`service` 多 1 个：原追加在上游测试里的 6 条断言独立成测试）；docreader 测试方法数相同（78）。
- 门禁：受影响 Go 包 `go vet` 与 `go test`（与 main 同环境逐测试对比）、`cli` 模块 `go test ./cmd/`、docreader `unittest`、golangci-lint `--new-from-rev=origin/main`、`pytest -q tests/architecture`、`git diff --check`。
- 基线只用 `record_baseline.py` 下调（G10 161 → 153，逐键取小）；`docs/design/upstream-patches.md` 追加一行退出记录。

## 4. 回滚

回退本片提交即可；无生产代码、无迁移、无数据变化。
