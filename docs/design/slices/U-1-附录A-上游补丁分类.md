# U-1 附录 A：上游补丁逐文件分类（2026-10-29）

> 基于 `slice/s7f1@cae56f960`（S7f-1 回退 129 个只改格式/注释的文件之后）相对上游基线 `3e8b0bfc8` 的 G10 集合，共 349 个。
> 分类方法：逐文件 diff + 去格式的 token 级差异 + 引用我方新增符号 + 提交历史；L 类为 v0.8.2 升级期 lint/校验提交独占且未引用我方符号的文件。
> 列：本方增删行、v0.9.0 上游改动行（冲突风险）、类别、族、去耦路径。

| 文件 | 本方 +/- | 上游改动 | 类别 | 族 | 去耦路径 |
|---|---|---|---|---|---|
| `internal/router/routes_knowledge.go` | +165/-67 | 59 | W 接线 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/types/interfaces/chunk.go` | +21/-3 | 17 | W 接线 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/types/interfaces/knowledge.go` | +7/-1 | 13 | W 接线 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/types/interfaces/task_queue.go` | +21/-0 | 7 | W 接线 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `cmd/download/duckdb/duckdb.go` | +284/-16 | 0 | W 接线 | WIRING | collapse into one enterprise registration (container option + route group + migration runner call) |
| `internal/container/container.go` | +37/-0 | 371 | W 接线 | WIRING | collapse into one enterprise registration (container option + route group + migration runner call) |
| `internal/database/migration.go` | +6/-0 | 0 | W 接线 | WIRING | collapse into one enterprise registration (container option + route group + migration runner call) |
| `internal/router/router.go` | +151/-65 | 18 | W 接线 | WIRING | collapse into one enterprise registration (container option + route group + migration runner call) |
| `internal/agent/finalize.go` | +2/-0 | 290 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/application/service/agent_service.go` | +248/-46 | 723 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/application/service/chat_pipeline/into_chat_message.go` | +16/-8 | 63 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/application/service/chat_pipeline/references.go` | +7/-2 | 28 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/application/service/session.go` | +6/-4 | 465 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/application/service/session_knowledge_qa.go` | +106/-19 | 290 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/modelcontext/model_output.go` | +13/-3 | 190 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/modelcontext/sources.go` | +66/-0 | 264 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `internal/modelcontext/tool_policy.go` | +8/-3 | 85 | H 钩子 | ANSWER | re-express as chat_pipeline Plugin (EventManager.Register) + agent ToolRegistry registrations from enterprise.Mount; one agent-turn hook (upstream PR for a turn/system-prompt extension) |
| `docreader/client/client_test.go` | +2/-0 | 16 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `docreader/parser/pdf_parser.py` | +269/-2 | 1009 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `docreader/tests/test_pdf_router.py` | +268/-1 | 477 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `internal/infrastructure/docparser/grpc_parser.go` | +219/-2 | 28 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `internal/infrastructure/docparser/mineru_cloud_converter.go` | +1287/-83 | 158 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `internal/types/docparser.go` | +13/-0 | 31 | H 钩子 | CAPTURE | adopt upstream v0.9.0 sourceloc/preview where it overlaps; keep artifact capture behind one parse-result callback (our capture package); MinerU capture code moved to our own file |
| `internal/agent/tools/wiki_delete_page.go` | +3/-0 | 1 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_flag_issue.go` | +3/-0 | 8 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_rename_page.go` | +3/-0 | 6 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_replace_text.go` | +59/-31 | 17 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_replace_text_test.go` | +8/-2 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_source_refs_test.go` | +2/-0 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_update_issue.go` | +3/-0 | 6 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_write_page.go` | +16/-0 | 22 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/agent/tools/wiki_write_page_test.go` | +2/-0 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/application/service/knowledgebase.go` | +69/-9 | 261 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/handler/knowledgebase.go` | +5/-0 | 735 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/im/cmd_search.go` | +6/-0 | 3 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/mcpserver/scope.go` | +19/-2 | 89 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/mcpserver/scope_test.go` | +1/-0 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/mcpserver/server.go` | +28/-0 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/mcpserver/tools_ingest.go` | +10/-0 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/mcpserver/tools_retrieve.go` | +17/-6 | 85 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/router/router_api_key_capabilities_test.go` | +2/-2 | 50 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/router/router_wiki_test.go` | +6/-2 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/types/mcp_endpoint_tools.go` | +34/-17 | 0 | H 钩子 | KBPOLICY | upstream PR: generic KB access/write policy interface (agent wiki tools, MCP, IM, routes) injected via container; fallback: one guard call per entrypoint kept as registered seam |
| `internal/database/migration_versions_test.go` | +33/-0 | 0 | H 钩子 | MIGRATION | revert our edit to upstream historical migration; express any needed change as an enterprise migration |
| `migrations/versioned/000077_remove_wiki_log.down.sql` | +6/-23 | 0 | H 钩子 | MIGRATION | revert our edit to upstream historical migration; express any needed change as an enterprise migration |
| `migrations/versioned/000077_remove_wiki_log.up.sql` | +14/-11 | 0 | H 钩子 | MIGRATION | revert our edit to upstream historical migration; express any needed change as an enterprise migration |
| `internal/application/repository/chunk.go` | +112/-21 | 114 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/knowledge.go` | +1191/-5 | 44 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/knowledge_finalize_test.go` | +37/-0 | 56 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/knowledge_list_filter_test.go` | +1/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/knowledge_transfer.go` | +17/-3 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/knowledge_transfer_test.go` | +1/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/resource.go` | +82/-5 | 55 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/repository/task_queue.go` | +228/-8 | 19 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/agent_browser_source_test.go` | +2/-1 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/agent_tool_surface_test.go` | +10/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/datasource_delete_sqlite_test.go` | +1/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/document_write_access_test.go` | +1/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/extract.go` | +115/-65 | 43 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/file/resource_catalog.go` | +22/-5 | 70 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/file/resource_catalog_test.go` | +29/-4 | 11 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/image_multimodal.go` | +1/-0 | 821 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge.go` | +21/-9 | 83 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_batch_reparse_test.go` | +32/-2 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_clone_move.go` | +6/-0 | 125 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_create.go` | +115/-28 | 197 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_create_test.go` | +48/-1 | 35 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_delete.go` | +19/-0 | 76 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_move_wiki_test.go` | +35/-2 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_multimodal_slot_release_test.go` | +8/-8 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_post_process.go` | +63/-15 | 27 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_process.go` | +470/-90 | 791 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_process_parent_child_test.go` | +39/-6 | 8 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_process_status_test.go` | +12/-4 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_replace.go` | +3/-1 | 7 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_replace_test.go` | +79/-218 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledge_util.go` | +15/-10 | 70 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledgebase_delete_datasource_test.go` | +2/-0 | 11 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/knowledgebase_task_cancel_test.go` | +5/-0 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/application/service/resource_test.go` | +35/-1 | 77 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/handler/knowledge.go` | +301/-42 | 878 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/models/embedding/protocol_test.go` | +2/-1 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/router/task.go` | +6/-0 | 34 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/router/task_processing_scope_test.go` | +1/-1 | 0 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/types/chunk.go` | +3/-0 | 61 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/types/knowledge.go` | +6/-0 | 55 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/types/task.go` | +32/-9 | 110 | H 钩子 | PINNING | keep as the blueprint §4.3 source-fixation seam; move logic into our own files in the same packages, leave one call per site; upstream PR for parse-attempt fencing + source SHA binding (generic concurrency correctness) |
| `internal/middleware/logger.go` | +14/-1 | 47 | X 可上游化修复 | LOGGING | request-log redaction: upstream PR (generic secret redaction) or keep as registered seam |
| `internal/middleware/logger_test.go` | +39/-1 | 126 | X 可上游化修复 | LOGGING | request-log redaction: upstream PR (generic secret redaction) or keep as registered seam |
| `internal/models/chat/chat.go` | +40/-8 | 0 | X 可上游化修复 | MODELS | upstream PR (thinking-model output budget, transport error classes); else keep |
| `internal/models/chat/concurrency_wrapper.go` | +1/-0 | 0 | X 可上游化修复 | MODELS | upstream PR (thinking-model output budget, transport error classes); else keep |
| `internal/models/chat/langfuse_wrapper.go` | +1/-0 | 19 | X 可上游化修复 | MODELS | upstream PR (thinking-model output budget, transport error classes); else keep |
| `internal/models/chat/llm_debug_wrapper.go` | +1/-0 | 0 | X 可上游化修复 | MODELS | upstream PR (thinking-model output budget, transport error classes); else keep |
| `internal/application/service/retriever/keywords_vector_hybrid_indexer.go` | +3/-0 | 96 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/retriever/keywords_vector_hybrid_indexer_test.go` | +49/-0 | 0 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest.go` | +351/-265 | 272 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_batch.go` | +199/-174 | 302 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_cite.go` | +381/-99 | 27 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_dedup.go` | +19/-3 | 0 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_language_test.go` | +1/-1 | 0 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_retry_test.go` | +27/-82 | 0 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_ingest_test.go` | +25/-4 | 61 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/application/service/wiki_page.go` | +106/-24 | 369 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/anthropicmessages/client.go` | +4/-2 | 2 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/endpoint.go` | +9/-1 | 59 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/googlegenai/client.go` | +4/-2 | 16 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/openaicompletions/client.go` | +4/-2 | 112 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/openairesponses/client.go` | +4/-2 | 18 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/models/api/retry.go` | +4/-0 | 0 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `internal/types/wiki_page.go` | +9/-8 | 122 | X 可上游化修复 | WIKIINGEST | genuine native-wiki fixes (source tables, incomplete-generation report, citations, retry ownership): send upstream PRs; until merged keep as registered seam |
| `frontend/src/components/ChatCitationFloat.vue` | +2/-0 | 28 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/components/ChatReferencesDrawer.vue` | +21/-1 | 167 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/composables/useChatCitationPopover.ts` | +5/-1 | 0 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/composables/useChatStreamHandler.integration.test.ts` | +2/-0 | 25 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/composables/useChatStreamHandler.ts` | +7/-4 | 563 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/composables/useCitationPopover.ts` | +16/-0 | 10 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/utils/citationMarkdown.ts` | +9/-2 | 3 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/utils/referenceSources.ts` | +16/-14 | 86 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/views/chat/components/AgentStreamDisplay.vue` | +76/-43 | 978 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/views/chat/components/docInfo.vue` | +10/-1 | 0 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/views/chat/index.vue` | +4/-2 | 517 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/views/knowledge/KnowledgeBase.vue` | +24/-12 | 528 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/src/views/knowledge/wiki/WikiBrowser.vue` | +8/-0 | 1150 | F 前端 | FE-CITE | adopt upstream v0.9.0 citation/preview/highlight; keep only source-label rendering hook (upstream PR for a citation-label slot) |
| `frontend/Dockerfile` | +2/-0 | 0 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/docker-entrypoint.sh` | +34/-2 | 2 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/nginx.conf` | +50/-13 | 0 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/package-lock.json` | +1271/-0 | 925 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/package.json` | +5/-0 | 3 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/public/config.js` | +3/-0 | 2 | F 前端 | FE-DEPLOY | move project deploy config (nginx, entrypoint, config.js) to our own overlay files; deps (package*.json) unavoidable |
| `frontend/src/api/mcp-endpoint.ts` | +1/-1 | 0 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/api/wiki/index.ts` | +1/-0 | 12 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/assets/theme/theme.css` | +4/-1 | 18 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/components/menu.vue` | +6/-2 | 150 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/i18n/locales/en-US.ts` | +344/-0 | 4068 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/i18n/locales/ja-JP.ts` | +344/-0 | 4056 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/i18n/locales/ko-KR.ts` | +344/-0 | 1934 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/i18n/locales/ru-RU.ts` | +344/-0 | 1928 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/i18n/locales/zh-CN.ts` | +344/-0 | 1929 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/router/index.ts` | +103/-0 | 110 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/stores/menu.ts` | +2/-0 | 1 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `frontend/src/utils/index.ts` | +3/-0 | 0 | F 前端 | FE-ENTRY | one enterprise routes/menu module imported once; enterprise i18n strings in our own locale files merged at startup (mergeLocaleMessage) |
| `.dockerignore` | +1/-0 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `.gitignore` | +8/-0 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `.golangci.yml` | +395/-0 | 6 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `Makefile` | +9/-14 | 16 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `README.md` | +122/-368 | 606 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `THIRD_PARTY_NOTICES.md` | +6/-0 | 64 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `docker/Dockerfile.app` | +237/-116 | 23 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `docker/Dockerfile.docreader` | +2/-2 | 19 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `go.mod` | +8/-1 | 10 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `go.sum` | +12/-0 | 1275 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `packages/dsh-weknora/test/e2e/run-in-dsh.mjs` | +37/-4 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/build-anydoc-lib.sh` | +42/-26 | 31 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/build_browserskill.sh` | +66/-27 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/build_images.sh` | +50/-35 | 16 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/check-license-bundle.sh` | +1/-1 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/copy-licenses.sh` | +2/-0 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/get_version.sh` | +32/-66 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/migrate.sh` | +14/-44 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/test-license-bundle.sh` | +2/-0 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `scripts/test_embed_nginx.py` | +2/-1 | 0 | K 构建部署（保留） | DEPLOY | keep minimal (go.mod/go.sum unavoidable); move project build steps to our own Dockerfile/scripts |
| `internal/config/config.go` | +279/-0 | 91 | K 保留（原 D 遗留） | CONFIG | 阶段 a 保留：KnowledgeRevisionSource 配置仍被 service/knowledge_revision_source.go 读取；修订版本源回填去留另行裁定 |
| `cli/cmd/dryrun_coverage_test.go` | +4/-0 | 0 | K 保留（原 D 遗留） | LEGACYTEST | 阶段 a 保留：覆盖修订版本源回填命令 |
| `internal/handler/tenant_secret_disclosure_test.go` | +5/-0 | 11 | X 通用修复（原 D 遗留） | LEGACYTEST | 阶段 a 保留：SSRF 测试隔离，上游版在假 IP 解析下失败；提上游 PR |
| `cli/cmd/doc/doc.go` | +2/-0 | 0 | K 保留（原 D 遗留） | PINNING | 阶段 a 保留：注册修订版本源回填命令（服务端仍在用） |
| `internal/application/service/chat_pipeline/memory_affinity.go` | +1/-1 | 0 | L lint/校验 | ANSWER | 回退到上游 |
| `internal/application/service/chat_pipeline/memory_recall.go` | +5/-2 | 0 | L lint/校验 | ANSWER | 回退到上游 |
| `internal/application/service/chat_pipeline/memory_recall_test.go` | +5/-5 | 0 | L lint/校验 | ANSWER | 回退到上游 |
| `internal/modelcontext/registry_test.go` | +88/-20 | 203 | L lint/校验 | ANSWER | 回退到上游 |
| `internal/infrastructure/docparser/resolve_remote_html_images_test.go` | +1/-1 | 0 | L lint/校验 | CAPTURE | 回退到上游 |
| `internal/config/auth_legacy_env_test.go` | +21/-4 | 15 | L lint/校验 | CONFIG | 回退到上游 |
| `internal/router/router_files_test.go` | +60/-21 | 10 | L lint/校验 | KBPOLICY | 回退到上游 |
| `cli/cmd/chat/chat_test.go` | +7/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `cli/cmd/message/list_test.go` | +7/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `cli/cmd/session/ask_test.go` | +8/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `cli/cmd/session/resume_test.go` | +6/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `cli/cmd/session/view_test.go` | +7/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `cli/internal/mcp/tools_test.go` | +14/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `client/knowledge.go` | +16/-4 | 129 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/approval/gate_test.go` | +1/-1 | 336 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/grounding_prompt_test.go` | +6/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/observe.go` | +2/-1 | 166 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/prompts.go` | +8/-6 | 112 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/prompts_wiki.go` | +23/-8 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/loader.go` | +2/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/manager.go` | +11/-9 | 17 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/shell_staging.go` | +9/-3 | 6 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/shell_staging_test.go` | +7/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/skill_frontmatter.go` | +1/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/skills/skill_frontmatter_test.go` | +5/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/definitions.go` | +2/-1 | 141 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/output_links_test.go` | +45/-10 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/persist_test.go` | +6/-3 | 25 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/python_syntax.go` | +3/-3 | 9 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/read_file.go` | +20/-6 | 94 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/read_file_test.go` | +38/-10 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/sandbox_edit.go` | +19/-9 | 19 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/sandbox_ls.go` | +13/-7 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/sandbox_write.go` | +19/-12 | 16 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/shell_env_extract_test.go` | +2/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/shell_exec.go` | +107/-48 | 107 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/shell_exec_test.go` | +32/-9 | 11 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/skill_file.go` | +7/-7 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/web_fetch.go` | +36/-19 | 183 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/web_search.go` | +27/-21 | 89 | L lint/校验 | OTHER | 回退到上游 |
| `internal/agent/tools/workspace_reader.go` | +24/-5 | 231 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/agent_share.go` | +39/-11 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/agent_share_source_test.go` | +2/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/memory.go` | +77/-44 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/memory_lifecycle.go` | +146/-91 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/memory_vector.go` | +1/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/model_usage.go` | +1/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/retriever/opensearch/repository_test.go` | +35/-11 | 37 | X 通用修复（原 L lint/校验） | OTHER | 阶段 a 保留：带 nolint 指令（S7f-1 行为注释例外）；随 opensearch 测试上游化 |
| `internal/application/repository/retriever/qdrant/repository.go` | +38/-11 | 149 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/wiki_page.go` | +34/-10 | 244 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/agent_service_test.go` | +11/-3 | 254 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/agent_share.go` | +58/-13 | 22 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/artifact_collector.go` | +4/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/artifact_collector_test.go` | +146/-22 | 23 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/datasource_sweep_wiring_test.go` | +15/-7 | 35 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/file/oss_test.go` | +85/-25 | 0 | X 通用修复（原 L lint/校验） | OTHER | 阶段 a 保留：SSRF 测试隔离，上游版在假 IP 解析下失败；提上游 PR |
| `internal/application/service/fork_bootstrapper.go` | +4/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/knowledge_auto_tag.go` | +8/-6 | 38 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/knowledge_content_binding_test.go` | +1/-1 | 26 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/knowledgebase_search.go` | +22/-5 | 171 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/mcp_service_test.go` | +4/-4 | 223 | X 通用修复（原 L lint/校验） | OTHER | 阶段 a 保留：SSRF 测试隔离，上游版在假 IP 解析下失败；提上游 PR |
| `internal/application/service/memory/consistency_test.go` | +116/-21 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/consolidate.go` | +6/-5 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/consolidate_test.go` | +22/-22 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/extract.go` | +45/-8 | 17 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/persistence_consistency_test.go` | +30/-6 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/retrieval_test.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/review_consistency_test.go` | +7/-7 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/topic_resolve.go` | +0/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/topic_resolve_test.go` | +7/-7 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/vector_scope_test.go` | +3/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/memory/vector_test.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/message_artifact_versions.go` | +8/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/model_delete_test.go` | +50/-5 | 40 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/resource.go` | +2/-1 | 84 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/sandbox_terminal_service.go` | +4/-4 | 7 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/session_sandbox_entry_test.go` | +5/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/session_sandbox_pin.go` | +3/-2 | 98 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/tenant_member_test.go` | +27/-3 | 4 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/tenant_sandbox_config.go` | +3/-2 | 351 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/tenant_sandbox_config_test.go` | +78/-77 | 673 | X 通用修复（原 L lint/校验） | OTHER | 阶段 a 保留：SSRF 测试隔离，上游版在假 IP 解析下失败；提上游 PR |
| `internal/application/service/tenant_skill_install.go` | +67/-51 | 71 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/tenant_skill_reaper_test.go` | +13/-1 | 12 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/user_env_resolver.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/user_env_resolver_test.go` | +4/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/service/user_env_test.go` | +4/-11 | 33 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/blocks.go` | +6/-5 | 317 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/client.go` | +43/-28 | 407 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/client_retry_test.go` | +3/-3 | 220 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/connector_error_reason_test.go` | +9/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/helpers_test.go` | +6/-20 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/core/types.go` | +36/-65 | 19 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/drive/connector.go` | +34/-18 | 166 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/drive/drive_blocks_test.go` | +29/-16 | 222 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/drive/helpers_test.go` | +6/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/wiki/connector_convergence_test.go` | +8/-5 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/wiki/connector_golden_test.go` | +67/-21 | 64 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/wiki/connector_stream_test.go` | +39/-27 | 43 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/feishu/wiki/connector_test.go` | +176/-68 | 355 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/gitlab/client.go` | +15/-3 | 135 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/gitlab/client_test.go` | +22/-4 | 287 | L lint/校验 | OTHER | 回退到上游 |
| `internal/datasource/connector/notion/client.go` | +18/-5 | 316 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/auth.go` | +33/-8 | 29 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/auth_change_password_test.go` | +4/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/chunk.go` | +23/-12 | 84 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/custom_agent.go` | +2/-2 | 376 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/faq.go` | +12/-2 | 75 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/initialization.go` | +52/-10 | 51 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/initialization_model_tenant_test.go` | +3/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/list_pagination.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/mcp_service.go` | +4/-4 | 376 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/me_env_var.go` | +13/-8 | 10 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/memory.go` | +12/-11 | 32 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/message_suggestion.go` | +1/-1 | 10 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/model.go` | +17/-3 | 267 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/sandbox_check.go` | +9/-9 | 11 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/sandbox_config.go` | +20/-16 | 113 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/sandbox_skill.go` | +6/-2 | 108 | K 保留（原 L lint/校验） | OTHER | 阶段 a 保留：swag 注解影响生成的 OpenAPI 文档（S7f-1 行为注释例外） |
| `internal/handler/session/agent_stream_handler.go` | +18/-16 | 239 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/session/artifact_download.go` | +15/-14 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/session/helpers.go` | +4/-1 | 57 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/session/qa.go` | +159/-56 | 348 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/session/temporary_document.go` | +14/-4 | 7 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/session/types.go` | +33/-18 | 69 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/tenant.go` | +46/-24 | 168 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/tenant_invitation.go` | +30/-15 | 6 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/tenant_invitation_accept_by_token_test.go` | +10/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/handler/tenant_member.go` | +8/-8 | 6 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/feishu/longconn.go` | +4/-2 | 105 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/feishu/longconn_test.go` | +4/-2 | 84 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/service.go` | +260/-46 | 66 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/service_lifecycle_test.go` | +18/-5 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/yunzhijia/websocket.go` | +17/-5 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/im/yunzhijia/websocket_test.go` | +2/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/chunker/splitter.go` | +10/-4 | 57 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/chunker/strategy_diagnostics_test.go` | +23/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_fetch/fetcher.go` | +28/-6 | 115 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_search/bocha.go` | +17/-7 | 6 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_search/bocha_test.go` | +41/-12 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_search/exa.go` | +9/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_search/metaso.go` | +23/-7 | 39 | L lint/校验 | OTHER | 回退到上游 |
| `internal/infrastructure/web_search/metaso_test.go` | +8/-6 | 154 | L lint/校验 | OTHER | 回退到上游 |
| `internal/logger/logger_test.go` | +4/-1 | 89 | L lint/校验 | OTHER | 回退到上游 |
| `internal/middleware/kb_access_test.go` | +99/-17 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/router/files.go` | +105/-19 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/router/task_inspector.go` | +27/-12 | 7 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/config_identity.go` | +6/-6 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/config_identity_test.go` | +4/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/cube_mock_test.go` | +47/-30 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/cube_remote_client.go` | +19/-1 | 29 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/cube_terminal_test.go` | +8/-6 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/e2b_exec_timeout_test.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/e2b_remote_client.go` | +22/-4 | 109 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/e2b_remote_client_test.go` | +99/-20 | 163 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/filesystem_identity_test.go` | +7/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/gateway_transport.go` | +10/-8 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/manager.go` | +4/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/mkdir.go` | +4/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/remote_errors_test.go` | +9/-4 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/remote_fake_test.go` | +3/-3 | 101 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/tenant_resolver.go` | +5/-3 | 11 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/terminal.go` | +10/-5 | 10 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/terminal_ttl_test.go` | +3/-3 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/sandbox/websocket_dialer.go` | +2/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/searchutil/chunkmerge_test.go` | +5/-2 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/builtin_agent_localization_test.go` | +1/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/chat_manage.go` | +1/-1 | 143 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/context_clone_coverage_test.go` | +2/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/context_helpers_test.go` | +5/-5 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/mcp.go` | +10/-4 | 76 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/memory.go` | +39/-15 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/message.go` | +9/-5 | 166 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/tenant.go` | +13/-3 | 43 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/tenant_env_vars.go` | +9/-6 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/types/token_usage_test.go` | +1/-1 | 0 | L lint/校验 | OTHER | 回退到上游 |
| `internal/application/repository/chunk_revision_test.go` | +1/-1 | 14 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/repository/knowledge_duplicate_test.go` | +55/-31 | 0 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/repository/knowledge_folder_test.go` | +3/-4 | 0 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/repository/knowledge_span_repo_test.go` | +131/-15 | 0 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/repository/knowledge_tag.go` | +14/-3 | 0 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/repository/task_queue_test.go` | +50/-11 | 41 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/service/knowledge_process_embedding_failure_test.go` | +10/-7 | 25 | L lint/校验 | PINNING | 回退到上游 |
| `internal/application/service/wiki_ingest_dedup_test.go` | +55/-12 | 0 | L lint/校验 | WIKIINGEST | 回退到上游 |
| `internal/container/engine_factory.go` | +3/-1 | 0 | K 保留（原 L lint/校验） | WIRING | 阶段 a 保留：带 nolint 指令（S7f-1 行为注释例外）；阶段 c 与容器装配一起收口 |

## 阶段 a 结果（2026-10-29，`slice/u1a`）

- 回退 178 个（L 类 184 + D 类 4 共 188 个，除下表 10 个），清单 `tests/architecture/u1a_reverted_files.txt`，逐字节等于上游；两个已登记钩子（`agent_service.go`、`session_knowledge_qa.go`）的调用改回上游名称 `NewUserEnvResolver`、`types.MEMORY_RECALL`，与上游更接近。
- 10 个改判保留（上表已更新类别与理由）：3 个带行为注释（S7f-1 例外）、4 个 SSRF 测试隔离（回退后在假 IP 解析环境下失败，属可上游化的测试修复）、3 个修订版本源回填相关（配置仍被服务读取，不是死代码）。
- G10：348 → 171（含临时 `.golangci.yml`），收尾 PR 后 170。v0.9.0 试合并冲突：83 → 53（含 `.golangci.yml` 1 处）。
- 行为：根/cli/client 三个模块全量 `go test -json` 与 main 同环境逐测试对比无变化（本机假 IP DNS 导致的既有失败相同）。

## 阶段 c 起点盘点（2026-10-31，`main@62d2f804b`，基线 `f17ee8a8d` = v0.9.0）

G10 共 169 个文件（含 #471 新登记的 `retriever/postgres/repository.go`）。按族（族名沿用上表；"新增"为本表之后才出现的适配）：

| 族 | 文件 | 约改动行 | 说明 |
|---|---|---|---|
| PINNING 来源固定接缝 | 44 | 3,787 | 其中 21 个是测试适配 |
| DEPLOY 构建部署 | 19 | 2,608 | K 类 |
| KBPOLICY 受管 KB 访问 | 18 | 320 | 生产改动均为上游处理函数内一行守卫或注册签名 |
| 新增（阶段 b 适配） | 15 | 54 | 测试注入分类器/建表、前端语言包合并入口等 |
| WIKIINGEST | 15 | 1,799 | X 类，待上游 PR |
| FE-CITE 前端引用 | 13 | 253 | |
| ANSWER 问答挂接 | 9 | 532 | |
| FE-ENTRY / FE-DEPLOY | 6 / 5 | 121 / 1,123 | |
| WIRING / CAPTURE | 5 / 5 | 570 / 787 | |
| OTHER / MODELS / LEGACYTEST / MIGRATION / CONFIG / LOGGING | 5 / 4 / 2 / 2 / 1 / 1 | — | |

对阶段 c 拆分的修正：

- 守卫 G11 禁止在上游包内新增 Go 源文件（测试文件除外），所以"把新增代码挪到同包自有文件"不能用于生产代码；生产侧只有两条路能让文件**真正恢复上游原样**：上游已有扩展点（插件、ToolRegistry、路由分组、DI 注入），或上游接受我方的扩展点 PR。
- KBPOLICY（原 U-2）的生产改动都是上游处理函数内部的一行守卫，上游没有对应扩展点，搬动只缩短行数不减文件数；改为先提上游 PR（通用 KB 访问/写策略接口），合入前保持"一处一行"。
- 测试适配类补丁（约 30 个）往往只因我方守卫要求的夹具（建表、注入依赖）。凡能在**不放宽生产失败关闭语义**的前提下让上游测试原样通过的，单独成片先做：第一片 U-2a（修订来源只读守卫，−6）。
- U-3（问答挂接改插件）、U-4（来源固定接缝收拢）、U-5（前端入口与语言包）、U-6（部署覆盖层）的范围不变，按"每片能实际恢复的上游文件数 / 审核行数"排序推进。
