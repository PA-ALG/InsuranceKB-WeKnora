# db — Harness 自有数据库层

- **生产**：PostgreSQL 16（`postgresql+psycopg://`），仓库根 `docker-compose.harness.yml` 一条命令起 dev 库；连接串经 `HARNESS_DB_URL`。
- **迁移**：Alembic（`harness/alembic.ini` + `harness/migrations/`）。`uv run alembic upgrade head` / `downgrade base`。
- **表结构权威**：docs/insurance-kb/03-knowledge-model.md §8；改表先改文档。
- **SQLite 仅测试用**。差异边界：迁移与 ORM 刻意只用跨方言类型（String/JSON/Date/DateTime）；
  生产特性（trgm 索引、部分唯一索引、JSONB、advisory lock）后续 change 以 Postgres-only 迁移引入，
  届时相关测试改打真实 Postgres（compose）。SQLite 不校验并发行为。

## KnowledgeSpace（change 016）

- `KnowledgeSpace` 是产品域和知识域共享的租户隔离根；bound Space 固定映射一个 tenant、KB-RAW 与 KB-WIKI。运行时服务必须接收由 `load_scope(session, space_id)` 从 bound 行加载的不可变 `KnowledgeScope`，并用 `require_current_scope` 证明 capability 来自当前 Session 的同一 Engine、当前行仍为相同 bound 值；不得从设置补默认 tenant/KB。
- private attestation 只在进程内保存 sentinel、Engine object identity 的弱引用与四元值，不序列化、不入日志。deep `model_copy` 保持 provenance，但 scope 不阻止 Engine 回收；弱引用失效后 capability fail closed。Engine 身份按 `KnowledgeSpace` mapper 解析并把 Connection 归一到 Engine：共享同一 mapper Engine 的不同 Session 可使用同一 loaded scope，不同 mapper Engine 即使默认 Engine、URL和数据相同也必须 reload。
- loader/当前值验证共用 `no_autoflush` 纯列查询，绕过 identity map 且不 refresh caller ORM entity；目标 Space 在 new/dirty/deleted UoW 中按 inspected persistent identity + current id 零业务查询拒绝并保留 pending state。该查询不是任意 committed-only 保证：绕过 admin service 的 direct SQL 或手工 flush 写入仍可能在同一事务可见，不属于 capability API 边界。
- migration 0003 只在历史业务行存在时创建 unbound `legacy-default` 并回填；空库不会创建默认 Space。downgrade 只允许唯一 `legacy-default` 且折叠到 0002 后无全局键冲突，否则在 DDL 前拒绝。
- DB 可表达的 child closure 包含 `ProductDocument(space_id, version_id) → ProductVersion(space_id, id)` 与 `Claim(space_id, superseded_by) → Claim(space_id, id)`；0001/0002 的单列 FK 保留为兼容冗余，0003 downgrade 删除复合 FK 后自然恢复旧 schema。
- `bind_space()` 是 caller-owned clean outer transaction 内的 mutation command，返回 `None`；成功写入后记录 caller outer `SessionTransaction` marker，marker active 时 `load_scope` 在查询前 fail closed。commit 后 marker 失效并允许重新加载；rollback 后重新加载仍为 unbound。PostgreSQL 使用 `FOR UPDATE`；SQLite CLI 因 legacy transaction control 显式建立物理 `BEGIN`，这不是生产并发语义替代品。

## ClaimEvidence lineage migration（change 017 / revision 0004）

- `0004_source_evidence_lineage.py` 串行承接 `0003`，为 `claim_evidence` 增加 nullable `raw_kb_id/source_revision/file_hash/original_digest/parser_version/chunk_hash/lineage_status/stale_at`。nullable 是历史行兼容边界；DB check 只接受“017 新字段全 NULL 的 legacy 行”或“带合法 status、完整 source audit、合法 linked/non-linked chunk shape 的 source-aware 行”，拒绝 partial/stale-only 状态。
- 索引 `ix_evidence_source_revision(knowledge_id, source_revision)` 支持修订定位，`ix_evidence_stale(stale_at, knowledge_id)` 支持 stale 扫描。Evidence 子表不复制 `space_id`；所有运行时查询必须 join `claims` 并用 `Claim.space_id` 限定 Space。
- fresh SQLite、`0003 → 0004` 历史行、Alembic metadata check、`0004 → 0003` 和 PostgreSQL offline DDL 均有契约测试。降级会保留旧 `knowledge_id/chunk_id/page/quote`，但不可逆地删除 017 audit/stale 字段；需要这些字段时必须先导出或禁止降级。

管理员 CLI 不提供默认数据库或默认 Space，只接受 `--db-url` 或 `HARNESS_DB_URL`：

```bash
python -m insurance_harness.db.scope_cli list --db-url "$HARNESS_DB_URL"
python -m insurance_harness.db.scope_cli show <space-id> --db-url "$HARNESS_DB_URL"
python -m insurance_harness.db.scope_cli bind <space-id> \
  --tenant-id <tenant> --raw-kb-id <raw> --wiki-kb-id <wiki> \
  --db-url "$HARNESS_DB_URL"
```

`list/show/bind` 是必须读取 unbound Space 的 admin 例外；不能作为普通业务查询入口。绑定失败统一 fail closed，不回显 DSN 或绑定值。
