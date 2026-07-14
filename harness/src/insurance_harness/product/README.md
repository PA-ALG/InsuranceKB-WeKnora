# product — 产品主数据、文档分类与路由（change 003）

解决 01 §2#1"多产品文档实体对齐"：一切事实归属先过产品主数据。

- `meta.py`：product_meta.json/.txt 解析（planCode→product_code 等对照见 db/models.py 注释）
- `aliases.py`：确定性别名生成（去括号/去"平安"前缀/剥险种后缀）
- `register.py`：`register_products()` 幂等注册产品/版本/文档/别名（spec P2）
- `classify.py`：文档类型分类（确定性特征优先，LLM 仅兜底，spec P3）
- `routing.py`：产品路由（exact/alias 自动归属；fuzzy 与别名歧义一律进 unassigned，spec P4）
- `cli.py`：`register-products` / `classify`（自动评分报告）

关联文档：docs/insurance-kb/03 §2.2/§8（表结构权威）、04 §7（与抽取管道的衔接）。
依赖：`db/`（迁移见 harness/migrations）、`schemas/`（险种 line_key）。

## KnowledgeScope 合同（change 016）

- `register_products(session, root, *, scope=...)`、`MatchIndex.from_session(session, scope)` 与 `persist_unassigned(session, scope, drafts)` 均要求显式、由当前 Session Engine reload 的 bound scope；入口先调用 `require_current_scope`，matching forged、另一 Engine capability 或 unbound Space 在业务查询/写入前统一拒绝。产品、版本、文档和 unassigned 直接写 `space_id`。
- `ProductAlias` 通过已 scoped 的 Product 父聚合继承作用域；批量路由查询会 join `InsuranceProduct.space_id`，不会建立跨 Space 的全局 alias 索引。
- 相同 `product_code`/version/document hash 可在不同 Space 共存，同一 Space 内仍保持幂等唯一。RouteResult/UnassignedDraft 携带 `space_id`，跨 Space candidate 在写入前拒绝且零写。
- ProductDocument 的 `version_id` 由 `(space_id, version_id)` 复合 FK 闭合同 Space ProductVersion；nullable version 语义不变。
- 产品 CLI 的 `register-products`/`classify` 强制 `--space-id`，迁移后从 DB `load_scope`；没有生产默认 Space。数据库解析顺序保持 `--db-url > HARNESS_DB_URL/settings > 测试 SQLite`，Alembic migration 同时使用 percent-escaped main option 与原始 `-x db_url`，避免环境变量覆盖显式 flag 并保持 percent DSN。
