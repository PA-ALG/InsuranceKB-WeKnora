# 016 · 企业 KnowledgeScope 验证报告

> 原始验证日期：2026-07-13；PR #4 增量补验：2026-07-14
> 验证范围：OpenSpec 016 本地确定性实现与 SQLite migration 语义
> 结论：本地门禁与规格证据齐备，规格/质量复审及主代理独立验收通过；未执行 live WeKnora 或真实 PostgreSQL 验证。

## 1. 结论与边界

016 已把 Harness 的产品、Claim/ChangeSet/Review、发布快照与 current pointer 隔离到显式 `KnowledgeSpace`，并提供数据库加载的不可变 `KnowledgeScope`、legacy backfill、安全 downgrade 与显式 `scope bind/list/show`。双 Space 的同业务键、跨空间读取/写入、publisher Wiki KB 所有权、WeKnora knowledge/chunk 响应闭合和 scoped manifest 恢复均有自动化测试。

本报告只证明本地非 live 路径。WeKnora SourceDocument bridge/Evidence revision 属于 017；SnapshotFact、跨进程发布状态机与 reconciliation 属于 018；Golden QualityProfile/Gate 和真实 13 产品运行分别属于 019/020。

最终质量复审仅保留一个非阻断生命周期建议：pending-bind marker 在外层事务结束后惰性保留到同 Space 下次 `load_scope` 或 Session 回收。短生命周期管理 CLI 不受影响，inactive transaction 不会被误判为 pending；若未来引入长期复用的批量 admin Session，可改为 `after_transaction_end` 或 transaction weak reference 主动清理。

## 2. 原始门禁证据（2026-07-13）

以下是 016 首次收尾时的历史结果，不是 PR #4 修复后的 fresh 重跑计数。工作目录：`harness/`；使用仓库既有 `.venv`。

| 门禁 | 命令 | 真实结果 |
|---|---|---|
| 016 focused | `.venv/bin/pytest tests/test_scope_016.py tests/test_scope_cli_016.py tests/test_scope_migration_016.py tests/test_scope_product_016.py tests/test_scope_knowledge_016.py tests/test_scope_publisher_016.py tests/test_client_scope_016.py -q` | `244 passed, 161 warnings in 14.76s` |
| 全库非 live | `.venv/bin/pytest -m 'not live' -q` | `495 passed, 3 deselected, 165 warnings in 52.77s` |
| Ruff | `.venv/bin/ruff check . --no-cache` | `All checks passed!` |
| mypy | `.venv/bin/mypy --no-incremental src tests` | `Success: no issues found in 122 source files` |
| migration/schema focused | `.venv/bin/pytest tests/test_scope_migration_016.py tests/test_product_db.py tests/test_knowledge_db.py -q` | `29 passed, 165 warnings in 5.81s` |
| diff whitespace | `git diff --check`（仓库根） | 无输出，退出码 0 |

warning 均为 Python 3.12 `sqlite3` 默认 datetime adapter 的弃用提示，不是测试失败。3 个 deselected 是 `live` 标记用例；没有把它们记录为已验证。

### 2.1 PR #4 复审补验（2026-07-14）

- RED：`test_s3_3_empty_install_round_trips_0003_to_0002` 在修复前稳定抛出 `expected exactly one knowledge space`；放宽为零 Space 或唯一 `legacy-default` 后转绿；
- migration + Source model focused：`69 passed`；
- 全库 non-live：`916 passed, 5 deselected, 209 warnings in 113.68s`；
- Ruff：`All checks passed!`；mypy：`Success: no issues found in 139 source files`；`git diff --check` 无输出。

## 3. Migration round-trip

### 3.1 Fresh install 与 drift

质量复审修复后，在全新的 `/private/tmp/insurancekb-016-quality-rereview-019f59fa.db` 执行：

```bash
.venv/bin/alembic \
  -x db_url=sqlite:////private/tmp/insurancekb-016-quality-rereview-019f59fa.db \
  upgrade head
.venv/bin/alembic \
  -x db_url=sqlite:////private/tmp/insurancekb-016-quality-rereview-019f59fa.db \
  check
```

结果：upgrade 成功；`alembic check` 输出 `No new upgrade operations detected.`。空库没有自动创建 `legacy-default`，由 `test_s3_3_empty_install_does_not_create_default_space` 证明；`test_s3_3_empty_install_round_trips_0003_to_0002` 进一步证明零 Space 的 0003 空库可无损回退到 0002。

### 3.2 Legacy 数据往返

`test_s3_4_legacy_data_round_trips_head_to_0002_and_back_to_head` 使用真实临时 SQLite 文件：

1. upgrade 到 0002，写入产品、版本、文档、unassigned、Claim、ChangeSet、ReviewItem、ReleaseSnapshot、SnapshotClaim 与 current pointer；
2. upgrade 到 head，验证十个聚合根均回填 `legacy-default`；
3. downgrade 到 0002，验证 `knowledge_spaces`/`space_id` 被移除、旧全局唯一约束恢复、业务行与 `current_release.id='current'` 保留；
4. 再 upgrade 到 head，验证十个聚合根重新回填、业务行/指针仍在、Alembic revision 为 0003，并恢复 `(space_id, product_code)` 唯一约束。

该场景随 migration focused suite 通过。0001/0002 历史 backfill 分别由 `test_s3_1_upgrade_from_0001_backfills_product_rows` 和 `test_s3_1_upgrade_from_0002_backfills_product_and_knowledge_rows` 覆盖。

复审补充的 DB scope closure 由 `test_s2_2_product_document_rejects_cross_space_version` 与 `test_s2_2_claim_rejects_cross_space_superseded_by` 在 `PRAGMA foreign_keys=ON` 下验证：`ProductDocument(space_id, version_id)` 必须指向同 Space ProductVersion，`Claim(space_id, superseded_by)` 必须指向同 Space Claim。ORM/migrated schema 测试同时检查两条命名复合 FK。0001/0002 原单列 FK保留为兼容冗余；downgrade 只删除 0003 新增复合 FK并恢复旧结构。

### 3.3 Unsafe downgrade 必须在 DDL 前失败

零 Space 是可安全回退状态，不属于 unsafe downgrade。其余拒绝场景包括：

- 多 Space：`test_s3_4_downgrade_rejects_multiple_spaces_before_ddl`；
- 唯一一个但不是 `legacy-default`：`test_s3_4_downgrade_rejects_single_non_legacy_space`；
- 0002 全局键折叠冲突：`test_s3_4_downgrade_lists_global_key_conflicts_before_ddl`，覆盖 ProductVersion、ProductDocument、published Claim 与 SnapshotClaim；
- NULL unique 语义：`test_s3_4_downgrade_allows_published_claim_key_with_null_component`。

拒绝用例在异常后重新检查 Alembic revision、表集合、`space_id` 列以及冲突行，确认 revision 仍为 0003、schema/data 未被 DDL 或清理破坏。migration 不会为了 downgrade 丢弃或合并数据。

## 4. S1～S5 规格映射

| 条款 | 主要证据 |
|---|---|
| S1.1 Space 绑定形态/唯一性 | `test_scope_016.py::test_s1_1_*`；`test_scope_migration_016.py::test_s1_1_*` |
| S1.2 只从当前 DB bound 行加载、不可变、无默认 | loader/immutable 用例；deep copy/Engine GC；mapper-only 与不同 mapper Engine；matching forged、dirty/new/deleted Space UoW、public bind pending transaction、同 Engine 跨 Session 用例；空库 migration 用例 |
| S1.3 unbound 禁止在线读/发布 | publisher unbound 零 I/O/零写测试；client forged/unbound 请求前拒绝测试 |
| S2.1～S2.2 聚合根/父子完整性 | migration scoped columns/composite FK 测试，含 Document→Version 与 Claim→superseded Claim；知识 aggregate JSON/父锚点闭合测试 |
| S2.3 跨空间 fail closed | `test_scope_product_016.py`、`test_scope_knowledge_016.py`、`test_scope_publisher_016.py` 的 A/B 读取与 mutation 用例 |
| S2.4 scoped unique/current | migration unique tests；双 Space product/ChangeSet/review/release label/current pointer 用例 |
| S2.5 双 Space 互不影响 | product、merge/review、publish/rollback 双 Space 故事 |
| S3.1～S3.4 迁移与 bind | migration round-trip/unsafe downgrade；`test_scope_016.py::test_s3_2_*`；`test_scope_cli_016.py` |
| S4.1～S4.2 WeKnora 边界 | `test_client_scope_016.py`：loader attestation、requested knowledge ID、tenant/raw KB、chunk knowledge/KB 全闭合 |
| S4.3 audit/secret | `test_s4_3_scope_log_context_*`；scoped pipeline fresh/resume/checkpoint/state patch tests；异常链与 checkpoint secret 测试 |
| S5 工程门禁 | focused 244、全库 495/3、Ruff/mypy/diff check；双 Space 测试均显式创建 scope |

## 5. 查询与 mutation 审计

使用以下可复现命令枚举运行时查询和作用域使用点，再逐项核对函数入口与父聚合 guard：

```bash
rg -n "session\\.(get|execute|scalar|scalars|query)|select\\(|update\\(|delete\\(" \
  harness/src/insurance_harness/{product,knowledge,db,adapters/weknora,compiler} -g '*.py'
rg -n "select\\((InsuranceProduct|UnassignedItem|Claim|ChangeSet|ReviewItem|ReleaseSnapshot|CurrentRelease)\\)" \
  harness/src/insurance_harness -g '*.py'
rg -n "\\.(get|create|update|delete|move)_wiki_page|\\.list_wiki_folders|\\.create_wiki_folder" \
  harness/src harness/tests -g '*.py'
```

首条命令得到 112 个候选位置（包含非 DB 的 `dict.update` 等误报）。最终复审再次按 public API 清单核对，结论：

- 产品 public DB 入口 `register_products`、`MatchIndex.from_session`、`persist_unassigned` 都显式接收 scope，并在任何业务查询/mutation 前调用 `require_current_scope`；Product、Version、Document 查询含 `space_id`。`ProductAlias` 没有重复 `space_id`，只在 scoped Product 已加载后按父 `product_id` 查询，路由批读则直接 join scoped Product。
- knowledge public mutation/read 入口（两个 importer、MergeEngine 构造/open/apply、claim helper、review resolve/overturn、judgement apply、retract、page build、publish/rollback/current/snapshot helper）显式接收 scope，并在 public 边界调用 `require_current_scope`。Claim/ChangeSet/ReviewItem/ReleaseSnapshot/CurrentRelease 直接按 `space_id`，ChangeItem/Conflict 通过 scoped ChangeSet join 闭合。
- private child helper `_evidence_for_claim` 只按 `claim_id` 查询 ClaimEvidence，但调用者先经 `_require_scoped_claim` 或从 scoped Claim 集合迭代；ClaimRevision 在发布/回滚校验中 join scoped Claim；ProductAlias 同样依赖已闭合的 scoped Product。子表没有把“同 Space”当成充分条件，ChangeItem/Conflict/JSON proposal 还校验同一父聚合与 canonical proposal。
- `CurrentRelease` 使用 `(scope.space_id, "current")` 复合主键读取，并再次闭合指向的 ReleaseSnapshot；Wiki 发布调用只使用 `scope.wiki_kb_id`。
- adapter 的 `get_knowledge`、`wait_for_parsed`、`list_chunks` 要求数据库 attested scope，并在返回内容暴露前闭合 requested ID、tenant、raw KB/knowledge ID。
- scoped ExtractionPipeline 在 fresh/resume/checkpoint/state patch/manifest 全程重申 `space_id + tenant_id + raw_kb_id`；scope 与 secret 均使用 allow-list/canonical dump。

`require_current_scope` 的 capability 规则是：private attestation 包含进程内 deep-copy-safe sentinel、Engine object identity 的弱引用与 scope 四元值；不同 Session 共享同 mapper Engine 时可复用，另一 mapper Engine 即使默认 Engine、URL、Space ID 和 bindings 完全相同也会在零 SQL 时拒绝并要求 reload。scope 的 deep copy 保留 provenance，但不延长 Engine 生命周期；Engine weakref 失效后 adapter 与 DB guard 都 fail closed。Engine identity 不进入 Pydantic dump、日志或 manifest。

`load_scope` 与 current guard 共用 loader：先按 SQLAlchemy inspected persistent identity + current id 拒绝目标 KnowledgeSpace 的 caller `new/dirty/deleted` UoW，再在 `session.no_autoflush` 内查询纯列 tuple，不读取 identity map、不加载/refresh ORM entity。public `bind_space` 成功后还会记录 caller outer `SessionTransaction`；marker active 时 loader 零查询拒绝，commit/rollback 使旧 transaction inactive 后清 marker并重查，分别得到 bound capability 或 unbound。

### 5.1 明确允许的例外

1. `scope_cli list/show/bind` 和 migration 必须能读取 unbound Space 或遍历全部 Space，因此是 admin/migration 入口，不接收 bound `KnowledgeScope`。bind 只在调用方 clean outer transaction + SAVEPOINT 内 mutation，并用 outer transaction marker 保证 commit/rollback 前不能 `load_scope`。
2. `load_scope(session, space_id)` 自身按裸 Space ID 读取，这是 capability loader；missing/unbound/incomplete 均返回同一 fail-closed 错误，不能作为业务对象查询入口。
3. WeKnoraClient 的既有 Wiki CRUD/folder 方法仍是接收 free-form `kb_id` 的低层 transport primitive。016 没有把它描述成 scoped domain service：生产发布的唯一源代码调用点在 `knowledge/publisher.py`，固定传 `scope.wiki_kb_id`，且对应测试证明 caller 不能注入 KB。直接 transport 契约/live 测试仍会传裸 KB；若后续要向其他 runtime consumer 暴露 Wiki 写入，应由 018 提供 scoped facade，而不是绕过 publisher。
4. ExtractionPipeline 继续允许完全 unscoped 的本地回放/Golden legacy run；一旦以 scope 构造，fresh/resume/checkpoint/manifest 必须全部 scoped，scoped↔unscoped 或 A↔B 恢复会拒绝。017 的 live SourceDocument bridge 才负责强制在线编译来源链始终 scoped。
5. 首版没有 PostgreSQL RLS；应用层 scope guard + scoped unique/composite FK 是 016 的边界。
6. 纯列查询绕过 identity map 且不 autoflush，但不是“任意 committed-only”承诺。同一 Session/事务内，绕过 admin service 的 direct SQL 或手工 flush 低层写入仍可能被 SELECT 看到；这类直接绕过不属于 capability API 保证。public `bind_space` 的未提交窗口已由 transaction marker 闭合。

以上例外都不是可以绕过 public product/knowledge/publish runtime service 的第二条路径。

## 6. Fail-closed 安全性质

- missing、unbound、错误状态、绑定字段不完整、matching forged 或来自另一 Engine 的 scope 在 runtime 统一 `ScopeViolation("scope mismatch")`，不暴露存在性差异；
- adapter 只接受进程内 DB loader attestation；序列化后必须重新从 DB load，forged/model_construct/修改后的 copy 在 HTTP 前拒绝；
- product/knowledge/page/publish public DB runtime 还要求 attested Engine 与当前 Session Engine 同一，并重新闭合当前 DB row；scope 失败不会触发业务查询、Wiki I/O、mutation 或 caller UoW refresh；
- 跨空间 ID、JSON 引用、父子对象或 snapshot pointer 在 I/O/mutation 前拒绝；
- bind 冲突/无效输入/dirty Unit of Work 不产生部分绑定；public bind 在 outer transaction 结束前不能签发 capability，commit 后才可 reload，rollback 后仍 unbound；
- publish/rollback 在输入、scope、聚合和 Wiki I/O 失败时不移动 current pointer；
- scope 错误、manifest parse 与 CLI 数据库错误不回显 tenant payload、token、API key 或 DSN secret。

## 7. 已知未验证项

- 未提供 live WeKnora 测试实例/凭据，因此没有执行 `-m live`；knowledge/chunk 与 Wiki CRUD 的真实上游 payload 契约仍需 017/018 live 验收。
- 未连接真实 PostgreSQL 16；本轮 migration round-trip 使用 SQLite。PostgreSQL 的行锁、并发 bind、部分唯一索引与复合 FK 需部署环境验证。
- 016 不提供跨进程 publisher 串行化、部分外部写补偿、SnapshotFact 或 reconciliation；由 018 交付。
- 016 不实现 SourceDocument 下载/hash/chunk lineage；由 017 交付。
- 019/020 尚未完成，不能据此开启无人审核自动发布，也不能声称 Golden 13/13 或全量 baseline 已完成。

## 8. Git/边界检查

收口执行 `git status --short`、`git status --ignored --short`、`git check-ignore -v`、对 adapter scope 文件的 `git check-ignore -q`，以及 `git diff -- internal frontend docreader`：

- migration、scope/service/CLI、016 tests 与 validation report 都以 `??` 可见，没有核心新增文件被吞；
- `git check-ignore -v` 对 `adapters/weknora/scope.py` 显示 `.gitignore:66:!harness/**/weknora/**` 的显式反忽略规则，`git check-ignore -q` 退出码为 1，确认文件未被忽略；
- ignored 项只有 `.venv`、mypy/pytest/Ruff cache 与 `__pycache__`；
- `git diff -- internal frontend docreader` 和 `git diff --name-only -- internal frontend docreader` 均为空，未侵入 WeKnora Go/Vue/docreader 核心；
- 工作树原有 T1～T7 与 017～020 规格/计划改动全部保留，没有清理、暂存、commit 或 push。
