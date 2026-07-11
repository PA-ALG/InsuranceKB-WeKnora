# db — Harness 自有数据库层

- **生产**：PostgreSQL 16（`postgresql+psycopg://`），仓库根 `docker-compose.harness.yml` 一条命令起 dev 库；连接串经 `HARNESS_DB_URL`。
- **迁移**：Alembic（`harness/alembic.ini` + `harness/migrations/`）。`uv run alembic upgrade head` / `downgrade base`。
- **表结构权威**：docs/insurance-kb/03-knowledge-model.md §8；改表先改文档。
- **SQLite 仅测试用**。差异边界：迁移与 ORM 刻意只用跨方言类型（String/JSON/Date/DateTime）；
  生产特性（trgm 索引、部分唯一索引、JSONB、advisory lock）后续 change 以 Postgres-only 迁移引入，
  届时相关测试改打真实 Postgres（compose）。SQLite 不校验并发行为。
