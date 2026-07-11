# 上游 Issue 草稿（Tencent/WeKnora）

> 02-architecture.md §5 的三个通用补丁，先以 Issue 形式提交上游讨论，认领后提 PR。
> 状态跟踪：提交后把 Issue 链接回填到本文件与 02 §5 表格。

## P-1 Wiki 页面更新支持乐观锁（防并发覆盖）

**标题**：feat(wiki): optimistic locking for wiki page updates (`expected_version` / `If-Match`)

**正文要点**（英文提交）：
- 现状：`PUT /api/v1/knowledgebase/{kb}/wiki/pages/*slug` 为 last-write-wins；请求体中的 `version` 不参与冲突检查，仅作变更计数。内部 wiki ingest 有 Redis slug 锁保护，但外部 REST 写入方（自动化管线、多实例集成方）与内置管线并发写同一 slug 时会静默互相覆盖。
- 提议：Update 请求支持可选 `expected_version`（或 `If-Match: <version>` 头）；不匹配返回 409 + 当前 version。向后兼容：不传则维持现行为。
- 附带：创建/更新支持可选 `Idempotency-Key` 头，网络重试不产生重复页面。
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
