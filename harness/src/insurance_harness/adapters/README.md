# adapters

外部系统适配层。**边界纪律**（docs/insurance-kb/02-architecture.md §3、10 §3）：

- `weknora/`：WeKnora REST 客户端——全仓库**唯一**允许出现 WeKnora API 路径、头、响应结构的位置；
- 上游 API 变化只改这里，管道层（compiler 等）只依赖本层的模型对象与异常分型。

## KnowledgeScope 边界（change 016）

- `get_knowledge`、`wait_for_parsed`、`list_chunks` 只接受 DB loader attested 的 `KnowledgeScope`；private attestation 含不可序列化的进程内 Engine identity，但 adapter 不持有 Session，只校验 loader provenance/四元值。HTTP 前拒绝 forged/unbound scope，响应返回前闭合 requested knowledge ID、tenant、KB-RAW，chunk 再闭合 knowledge ID。任何跨 Engine 的 DB runtime service 使用前仍必须在当前 Engine reload。
- `scope_log_context()` 只允许 `space_id/tenant_id/raw_kb_id`，不包含 wiki KB、token、API key 或 secret；scope 序列化/跨进程后必须重新从 DB load。
- 既有 Wiki CRUD/folder 方法仍是接收裸 `kb_id` 的低层 transport primitive，不是 scoped 领域服务。016 的生产 publisher 是当前唯一源代码调用点，并固定传 `scope.wiki_kb_id`；新的 runtime consumer 不得直接使用该 primitive，应由 018 的 scoped publish/read facade 承接。
