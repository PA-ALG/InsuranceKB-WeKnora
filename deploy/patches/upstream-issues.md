# 上游 Issue 草稿（Tencent/WeKnora）

> 02-architecture.md §5 的三个通用补丁，先以 Issue 形式提交上游讨论，认领后提 PR。
> 状态跟踪：提交后把 Issue 链接回填到本文件与 02 §5 表格。

## P-1 Wiki release namespace 与原子 active alias

**标题**：feat(wiki): versioned release namespaces and atomic active-release activation

**正文要点**（英文提交）：
- 现状：页面唯一键是 `(kb, slug)`，REST 逐页 last-write-wins；`draft/published` 不能原子切换整套页面，且默认 Wiki 列表并不强制隐藏 draft。外部编译器发布多页知识时，普通 UI/RAG 可能在中途看到混合版本。
- 提议：增加按 `(tenant_id, target_wiki_kb_id, release_id, logical_slug)` 定址的 namespace 与 release-scoped 幂等 staging/manifest API；同一 release 的页面、目录、关系和索引可在不可见状态完整构建、回读并校验 manifest hash。target KB 只能绑定一个 Space，staging KB 同样不得跨 Space 复用。
- 提供 `seal-release(expected_write_etag, manifest_hash)`：在原子事务内重算页面/目录/关系/index generation 的物理 hash，成功后 namespace/index 禁止 PUT/DELETE，变更只能创建新 release；覆盖 seal-vs-write/delete race。
- `WikiConfig` 增加 `active_release_id/manifest_hash/etag`，提供 `activate-release(expected_active_release, release_id, manifest_hash)` CAS；activate 必须再次验证 target KB 归属、sealed manifest 与物理 index hash，单次激活/回滚改变 serving alias并关闭 approval-to-activation TOCTOU。
- 普通 list/get/search/index/graph/chunk/retrieval/UI 默认只解析 active release；staging 仅授权管理员通过显式管理 API 可见。activation 返回不可变 receipt/ETag，并产生通用审计/outbox 事件。
- 当前及仍具有效回滚资格的 sealed release/index/artifacts 必须 pin。GC 只允许失败未激活 staging，或经显式授权失去回滚资格且过审计保留期的 release，并追加不可变 GC event/receipt；rollback 前执行物理 manifest/index hash preflight，不重新生成。
- 向后兼容：未启用 release mode 的旧 KB 保持现有行为；release mode KB fail closed，不允许绕过 active alias 读取 staging。
- 我们可以提 PR（含测试）。

## P-2 知识生命周期出站事件（Outbox/Webhook）

**标题**：feat(knowledge): outbound webhook / outbox events for knowledge lifecycle

**正文要点**：
- 现状：`parse_status` 变化（completed/failed）无对外通知，外部系统只能轮询 `GET /knowledge/:id`；批量导入场景轮询成本高且有延迟。
- 提议：租户级可配置 webhook（或 outbox 表 + 投递器），事件：`knowledge.parse_completed / parse_failed / reparsed / deleted`，负载含 knowledge_id、kb_id、tenant_id、状态与时间戳；带签名头与重试。
- 参考现有 IM 入站 webhook 的鉴权风格，复用事件总线（internal/event）扩展为出站。

## P-3 Wiki 写入与自动生成解耦（`ingest_mode`）

**标题**：feat(wiki): allow API/manual wiki writes with built-in auto-ingest disabled (`ingest_mode`)

**正文要点**：
- 现状：`IndexingStrategy.WikiEnabled=false` 时 `validateWikiKB` 直接拒绝一切 wiki 路由（含 REST 读写）。外部系统若想"自己生成并写入 wiki 页、不要内置自动 ingest"，做不到：开 WikiEnabled 会让上传文档自动触发内置生成，与外部写入争用同一 slug 空间。
- 提议：`WikiConfig` 增加 `ingest_mode: auto | manual`。`manual` 下 wiki 存储/展示/检索/REST CRUD 全部可用，仅不自动 EnqueueWikiIngest。默认 `auto` 保持兼容。
- 用例：外部知识编译管线（结构化抽取→审核→发布）以 WeKnora Wiki 为发布视图。

## 提交清单

- [ ] P-1 Issue 提交（链接：）
- [ ] P-2 Issue 提交（链接：）
- [ ] P-3 Issue 提交（链接：）
- [ ] 认领后 PR（每个 patch 附兼容性测试；不含任何保险业务逻辑）
