# U-1 附录 B：阶段 b 合并 v0.9.0 的冲突处理

合并提交 `b6e3b3c52`（父：`slice/u1b` 基线 `31cd8ae43` 与上游 `v0.9.0` = `f17ee8a8d`），真实合并、不变基。
`git merge-tree` 复算的冲突文件 52 个（另有 MinerU 采集文件的修改/删除冲突）。原则按 Issue #451：上游已覆盖就取上游；
我们的增量挪进自己的文件、上游文件只留一行调用；语言包挪进自己的模块；锁文件用工具重新生成。

## B.1 冲突按处理方式分类

| 类别 | 数量 | 文件 | 理由 |
|---|---|---|---|
| 取上游 | 9 | `frontend/package.json`、`agent/tools/wiki_replace_text.go`、`service/extract.go`（prepareResources）、`file/resource_catalog_test.go`、`docparser/mineru_cloud_converter.go`、语言包 5 个中的 4 个之外见 B.3 | v0.9.0 已覆盖或我们的改动只为旧接口 |
| 双方并集（纯增量，无语义交叉） | 21 | `types/chunk.go`、`types/task.go`、`types/wiki_page.go`、`types/interfaces/knowledge.go`、`image_multimodal.go`、`knowledge_util.go`、`resource_test.go`、`knowledge_process_parent_child_test.go`、`go.sum`、`router/router.go`、`container/container.go`、`agent/tools/wiki_write_page.go`、`ChatCitationFloat.vue`、`ChatReferencesDrawer.vue`、`useCitationPopover.ts`、`useChatStreamHandler.integration.test.ts`、`utils/referenceSources.ts`、`views/chat/index.vue`、`menu.vue`、`docreader/tests/test_pdf_router.py`、`session.go` | 上游新字段/新路由/新 provider 与我们的并存 |
| 我们的钩子重放进上游新结构 | 15 | `session_knowledge_qa.go`（PrepareSelection / ResolveQuick / LegacyScope / FilterPipeline 落在 `runKnowledgeSearchPipeline` 新结构里）、`agent_service.go`、`chat_pipeline/references.go`、`chat_pipeline/into_chat_message.go`、`knowledge.go`、`knowledge_create.go`、`knowledge_replace.go`、`knowledge_process.go`（18 处）、`knowledge_post_process.go`、`wiki_ingest.go`、`wiki_ingest_batch.go`、`repository/chunk.go`、`docreader/parser/pdf_parser.py`、`KnowledgeBase.vue`、`AgentStreamDisplay.vue` | 行为不变；上游函数签名保持原样（见 B.2） |
| 保留我们（构建/部署） | 5 | `docker/Dockerfile.app`、`scripts/build_images.sh`、`scripts/build-anydoc-lib.sh`（保留上游 zip 9 补丁与 `anydoc_patch_id`）、`README.md`、`frontend/package-lock.json`（上游锁 + `npm install --package-lock-only` 重生成） | 固定来源构建链 |
| 语言包 | 5 | `frontend/src/i18n/locales/*.ts` | 取上游字节，我们的键挪出（B.3） |

## B.2 从上游签名里撤出的我们的参数（上游测试因此原样可编译）

| 原做法（main） | 现做法 | 位置 |
|---|---|---|
| `finalizeSubtaskDetached` / `finalizeWikiSubtask` 多一个 revision 参数 | 上游 7 参数原样；revision 绑定由仓库装饰器 `withRevisionSlot(repo, revision)` 带入 | `knowledge_revision.go` |
| `enqueueImageMultimodalTasks` / `releaseUnownedMultimodalSlots` / `enqueueKnowledgePostProcessTask` / `newWikiIngestPendingOp` 多一个 revision 参数 | 上游签名；revision 走 context（`withRevisionBinding` / `revisionBindingFromContext`） | `knowledge_revision.go` |
| `RegisterWikiPageRoutes(..., classifier)` 必填、缺 owner lookup 时 panic | 可变参数；缺分类器或 lookup 时请求级 fail-closed（503）；路由表回到上游字节，只改 Wiki 注册函数；托管守卫仍在角色守卫之前（受保护测试要求的 S1a/S1b 顺序） | `router/routes_knowledge.go` |
| GORM 敏感日志包在 `container.go` 内联 | `logger.WrapSensitiveGORMLogger` 一行调用 | `internal/logger/gorm_logger.go` |
| `SearchPagesAcross` 无托管检查（上游新接口） | 新文件按 kbID 逐个 `CheckRead`，无租户 fail-closed | `enterprise/managed/search_across.go` |

## B.3 语言包

上游 5 个语言文件取上游字节。我们的键用 esbuild 求值 base/ours 差集抽出（只有新增、无原地改、无键冲突）到
`frontend/src/enterprise/i18n/messages/<locale>.ts`；`withEnterpriseMessages()` 在 `src/i18n/index.ts` 与
`localeKeyAudit.ts` 各一行包裹；zh-TW 暂用简体（上游审计要求键集一致）。`src/enterprise/i18n/locales/<l>.ts`
导出与运行时一致的合并包，55 个我们的 spec 改为从这里取（公开披露的测试改动）。

## B.4 删除与收口

- MinerU 采集（830 时代）：`mineru_artifact_capture.go`、`mineru_cross_page_projection.go` 及其 4 个测试、
  `cmd/mineru-capture-596-1/`。服务端与 Harness 都不调用（仅该 cmd 与测试引用）；v0.9.0 重写了
  `mineru_cloud_converter.go`。不重新移植，代码可从 `4dbe227e3` 取回。
- `SCHEMA_WIKI_MVP_*` 运行时配置：S7b 后无人读取；`config.js`、`utils/index.ts` 回到上游字节，entrypoint 只留 DNS 补丁。
- #452 临时 `cargo audit --ignore` 三条删除：v0.9.0 的 anydoc 0.2.4 锁定 zip 9.0.4；下载锁改为 anydoc 0.2.4（sha256 已核）。
- 适配目标（`deploy/upstream/weknora-adoption-target.json`）移到 v0.9.0，`official_migration_head` 110 → 134；
  否则迁移执行器在官方链到 134 后会拒绝启动。UPG-07 的 000077 保留策略原样带到新目标（上游 000077 两版字节相同）。

## B.5 合并后跟进的语义修正

- `deleteUnindexedChunks`（v0.9.0 新增的配额失败清理）改为只按本次尝试的 chunk ID 删除，与其余 W1 清理一致。
- `managed.GuardWikiWrite` 在 gin 租户键缺失时接受 v0.9.0 的请求 Caller 租户（只用于确认已认证；托管分类按 KB 所属租户）。
- Wiki 结算吸收上游重试预算（`wikiMaxFailRetries`）：失败尝试计数，超限归档；被取消的批次保留预算（受保护测试）。
- mcp-go v0.52 → v1.1.1：隐藏工具在 `tools/call` 直接 “not found”；证据序号按字面整数校验（`1.0`、`1e2` 不再通过）。

## B.6 G10

`upstream_base` 改为 `f17ee8a8d`，`record_baseline.py --init`：G10 = 168（阶段 a 为 170）。其中为腾出预算，把我们加在
6 个上游测试文件里的测试函数与假对象方法挪到自己的文件；新增的上游测试补丁只在必须改断言或必须注入依赖处（见 PR）。

## B.7 留给阶段 c（U-2…U-5）

- 3 个前端上游白盒测试（`useChatStreamHandler.{collaboration,suspend}`、`useChildAgentStream`）为 `chatErrors` 加了模块映射；
  U-5 把聊天错误映射挪出 `useChatStreamHandler.ts` 后可撤。
- MCP 上游测试注入 unmanaged 分类器（3 处）、dead-letter 测试迁 `knowledge_revision_sources`（2 处）：U-2 受管 KB 策略统一后再评估。
- W1 尝试级清理与上游 Attempt 防护并存；`knowledge_process_index_retry_test`、`knowledge_attempt_supersede_test` 断言改为
  精确 ID 清理。两套防护的合一放在 U-4。
- 已知未过（见 PR）：上游 `TestWikiPersistentLookupFailureExhaustsRetryBudget`、`TestWikiInterruptedLookupRecoveryStress`
  期待上游对“知识查询失败”的结算；我们的 `TestACandidateWindowThatFitsOnlyAtTheThirdSplitIsReadInFull`、
  `TestACitationBatchThatFitsOnlyAtTheThirdSplitIsCitedInFull` 在 v0.9.0 的 map 改动后读到 0 个窗口。
