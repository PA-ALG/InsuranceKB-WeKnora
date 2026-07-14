# 016 任务

- [x] T1 KnowledgeSpace ORM、不可变 KnowledgeScope 与 fail-closed loader（S1）：严格 RED→GREEN；scope 10 passed，相关 DB 7 passed，Ruff/mypy 通过；规格审查与代码质量审查通过
- [x] T2 0003 migration、legacy backfill、scoped constraints 与安全 downgrade：严格 RED→GREEN；迁移/结构 27 passed，Task 1 回归 10 passed，Ruff/mypy/Alembic drift check 通过；规格审查与代码质量审查通过
- [x] T3 产品注册、路由、unassigned 与产品 CLI 强制显式 scope：严格 RED→GREEN；产品目标 29 passed、T1～T3 联合回归 66 passed，Ruff/mypy 通过；规格审查与代码质量审查通过
- [x] T4 Claim 导入、merge、review 与 retraction 强制显式 scope（S2）：严格 RED→GREEN；知识目标 67 passed、T1～T4 联合回归 133 passed，Ruff/mypy/diff check 通过；规格审查与三轮代码质量复审通过
- [x] T5 先写 publisher/current release 的双空间失败测试并实现每空间指针：严格 RED→GREEN；Task5 focused 47 passed/1 live skipped、全库非 live 362 passed/3 deselected，Ruff 全库、mypy 118 files、diff check 通过；规格审查与代码质量审查通过
- [x] T6 先写 unbound/scope mismatch 安全测试并实现 ScopeViolation（S1.3/S4）：严格 RED→GREEN；主代理 focused 88 passed、全库非 live 421 passed/3 deselected，Ruff 全库、mypy 120 files、diff check 通过；规格审查与三轮代码质量复审通过
- [x] T7 增加 `scope bind/list/show` CLI 与测试：严格 RED→GREEN；主代理 focused 65 passed、全库非 live 473 passed/3 deselected，Ruff 全库、mypy 122 files、diff check 通过；规格审查与两轮代码质量复审通过
- [x] T8 全门禁、migration round-trip、validation-report、HANDOFF/13/16/20 文档对账：质量复审修复后 016 focused 244 passed、全库非 live 495 passed/3 deselected，Ruff 全库、mypy 122 files、Alembic fresh drift、legacy round-trip、diff check 通过；规格与质量复审、主代理独立验收全部通过

状态：✅ T1～T8 完成，规格/质量复审与主代理独立验收通过；016 前置已解除，下一步 017。严格 RED→GREEN→REFACTOR；T8 复审按 TDD 修复 current-Engine capability、两条 scoped composite FK、loader pending state、public bind 未提交窗口与产品 CLI migration URL。

## 裁决记录

- 2026-07-13 · T1：`KnowledgeSpace` 的外部绑定三列允许 NULL，但用 CHECK 保证 unbound=全 NULL、bound=全非空；tenant/raw KB 与 tenant/wiki KB 使用复合唯一约束，为 0003 migration 提供 ORM 权威形态。
- 2026-07-13 · T1：missing、unbound、错误状态与 bound 但字段不完整统一抛 `UnboundKnowledgeSpace("knowledge space is unavailable")`，避免通过错误信息探测 Space 是否存在。
- 2026-07-13 · T1：测试 `bound_scope` 是必须显式传 tenant/raw/wiki 的 pytest factory fixture，不提供任何默认作用域。代码质量复审确认 fixture 被真实测试消费。
- 2026-07-13 · T2：0001/0002 历史非空库升级时统一回填到 `legacy-default` unbound Space；空库不创建默认 Space。聚合根直接持有 `space_id`，计划列明的跨聚合引用使用 shadow `space_id` + 复合外键。
- 2026-07-13 · T2：`CurrentRelease` 使用 `(space_id, id)` 复合主键并对 `space_id` 唯一，保留每空间一条指针且可无损回退旧 `id='current'` 结构。
- 2026-07-13 · T2：downgrade 允许空库或恰好一个 `legacy-default`，再枚举所有恢复到 0002 的全局唯一键冲突；其他 Space 形态与键冲突都在任何 DDL 前抛 `CommandError`，错误包含实际键值和计数。发布态 Claim 仅在旧唯一索引的所有可空列均非 NULL 时判冲突，保持 SQLite/PostgreSQL 的 NULL unique 语义。
- 2026-07-13 · T3：产品注册、版本/文档幂等查询与路由索引都显式接收 `KnowledgeScope`；`ProductAlias` 通过 join 父 Product 并按 `space_id` 过滤，避免跨空间全表读取和大型 `IN` 参数列表。
- 2026-07-13 · T3：`RouteResult`/`UnassignedDraft` 冻结携带 `space_id`；unassigned 写入前先校验 draft scope，再校验候选 Product 的 scoped id/code/name，任一不符统一抛不泄漏对象信息的 `ScopeViolation`，且在 `session.add()` 前零写失败。
- 2026-07-13 · T3：产品 `register-products`/`classify` CLI 均强制 `--space-id`，先迁移 schema，再从数据库 `load_scope`；missing/unbound 均 fail closed，不读取配置或默认 KB 补 scope。
- 2026-07-13 · T4：Claim importer、MergeEngine、review/retraction 的所有服务入口显式接收 `KnowledgeScope`；产品 code/UUID 先归一为产品 UUID，再参与记录级与批级幂等键，避免同一产品产生第二个空 ChangeSet。
- 2026-07-13 · T4：ChangeItem、Conflict、ReviewItem 的 JSON 引用不以“同 Space”作为充分条件；写入与消费均校验同一聚合锚点，并以数据库 Claim/Evidence 闭合 Item/Conflict 的规范化 proposal，协调篡改两份 JSON 也会在 mutation 前 fail closed。
- 2026-07-13 · T4：批量 conflict judgement 使用整批两阶段预检；任一跨 Space、错聚合或同批发布目标冲突会在所有状态/修订写入前失败。`create_claim`/`write_revision`/`supersede_claim`/`retract_claim` 收为私有 mutation helper，公开入口不能绕过 scope guard。
- 2026-07-13 · T4：publish 的新旧业务主语定义为 `product_version_id + concept_id + predicate`；`effective_from` 属于版本裁决维度，继续保留 K3.2 的 effective-date supersede 语义。
- 2026-07-13 · T5：publisher、rollback、page compiler 与 snapshot/current helpers 全部显式接收数据库加载的 bound `KnowledgeScope`；移除 free-form `kb_id`，Wiki I/O 只使用 `scope.wiki_kb_id`，ReleaseSnapshot/SnapshotClaim/CurrentRelease/rollback ChangeSet 均写入同一 Space。
- 2026-07-13 · T5：current pointer 读取闭合校验 scoped ReleaseSnapshot；rollback 只接受可从 scoped Product/ProductVersion 派生的 canonical unique slug，且非空 frozen Claim 在全快照精确出现一次。畸形页面、跨 Space/悬空指针、协调篡改与空 Claim 发布均在 I/O 和 mutation 前 fail closed。
- 2026-07-13 · T5：发布/回滚先完成输入、scope、聚合与 Wiki I/O，再写 DB pointer/trace；Wiki I/O 失败不留下可提交的新 Snapshot/ChangeSet/current pointer。I/O 成功后数据库极端并发失败的 reconciliation、跨进程发布串行化与多页部分外部写补偿明确归 018。
- 2026-07-13 · T5：label/published_by/actor/reason 按 DB 长度在 I/O 前校验；rollback reason 写入 ChangeSet `source_revision`，operation key 含 snapshot ID 与随机 UUID，允许同 snapshot/同 reason 重复回滚并保留审计。
- 2026-07-13 · T6：WeKnora `get_knowledge`/`wait_for_parsed`/`list_chunks` 移除旧 overload，强制显式、DB loader attested 的 `KnowledgeScope`；knowledge 响应闭合 requested ID + tenant + raw KB，chunk 再闭合 knowledge ID。身份字段只接受 StrictStr/StrictInt，bool/float/缺失/畸形 payload 均在返回内容前统一 `ScopeViolation("scope mismatch")`。
- 2026-07-13 · T6：`KnowledgeScope` 使用不序列化的进程内 PrivateAttr sentinel 与四元组 attestation；普通构造、`model_construct`、修改字段后的 `model_copy` 均不能调用 adapter，未修改 copy 保留 provenance。该 capability 用于防止进程内误用，不是对恶意同进程代码的安全沙箱；scope 反序列化后必须从 DB reload。Live 契约改用 `HARNESS_LIVE_DB_URL + HARNESS_LIVE_SPACE_ID` 调 `load_scope`。
- 2026-07-13 · T6：scoped ExtractionPipeline 的 fresh/resume/checkpoint/state patch/最终 manifest 全部重申 `space_id + tenant_id + raw_kb_id`；scoped↔unscoped、A↔B 恢复 fail closed。`scope_log_context` 严格 allow-list 三字段，不含 wiki/API key/token/secret。
- 2026-07-13 · T6：Pydantic/manifest parse helper 在 `except` 内只返回失败值、调用层再抛通用异常，确保 `__cause__`/`__context__` 均为空；manifest patch 在写 checkpoint 前替换为 validated canonical dump，top-level/nested extra secret 不进入 SQLite 历史且不修改 caller-owned patch。
- 2026-07-13 · T7：`bind_space` 是原子 mutation command，要求调用方已开启 active、clean outer transaction，在 SAVEPOINT 内锁定目标 Space 并写入绑定；返回 `None`，提交成功后必须重新 `load_scope`，避免回滚后仍持有未提交的 attested capability。dirty/new/deleted Unit of Work 在任何 flush 前 fail closed，Session 仍可用。
- 2026-07-13 · T7：`scope bind/list/show` 只接受显式 `--db-url` 或 `HARNESS_DB_URL`，bind 强制四个 opaque ID；CLI 在提交前完成读取和 JSON 序列化，提交后输出失败仍返回成功，避免自动重试误判。SQLite 命令路径因 legacy transaction control 显式建立物理 `BEGIN`；生产 service 仍保持标准 outer transaction + SAVEPOINT + PostgreSQL `FOR UPDATE`。
- 2026-07-13 · T7：Alembic 同时写入转义后的 main option 与原始 `x db_url`，保证 percent-encoded DSN 保真且 flag 高于环境变量；标识符拒绝首尾空白和 Unicode C 类控制/不可见字符，同时保留合法 Unicode opaque ID。list/show/bind 均输出稳定 JSON，不创建默认 SQLite 或默认 Space。
- 2026-07-13 · T8：真实临时 SQLite 覆盖 fresh `upgrade head + alembic check`，以及含十个 legacy 聚合根的 0002→head→0002→head 往返；安全 downgrade 的 Space/全局键前置校验会在 DDL 前拒绝并保持 revision、schema 与冲突数据不变。真实 PostgreSQL 与 live WeKnora 未验证，明确留给部署验收及 017/018。
- 2026-07-14 · PR #4 复审修复：先以 `test_s3_3_empty_install_round_trips_0003_to_0002` 复现空库无 `legacy-default` 时 downgrade 被错误拒绝，再放宽前置条件只接受“零 Space”或“唯一 legacy-default”；存量非空库 upgrade 后必须 bind 的运维步骤同步进入 Runbook、HANDOFF 与 DB README。
- 2026-07-13 · T8：查询审计确认 public 产品/知识/发布入口显式 scope；ProductAlias/ClaimEvidence/ClaimRevision/ChangeItem/Conflict 等 child 查询必须依赖先行 scoped 父聚合 guard。`scope_cli`/migration 是需要访问 unbound/全局 Space 的 admin 例外；既有 Wiki CRUD 是 free-form KB 的低层 transport primitive，016 publisher 是唯一生产调用点且只传 `scope.wiki_kb_id`；若新增 runtime consumer，018 必须提供 scoped facade。
- 2026-07-13 · T8：ExtractionPipeline 保留完全 unscoped 的离线回放/Golden legacy 模式；一旦以 scope 构造，fresh/resume/checkpoint/state patch/manifest 全程闭合，017 live bridge 再强制在线来源链始终 scoped。该兼容边界不得被描述成“所有 pipeline run 已强制 scope”。
- 2026-07-13 · T8 复审修复：`KnowledgeScope` private attestation 增加不可序列化、不入日志的进程内 Engine identity。共享 `require_current_scope(session, scope)` 先拒绝 forged/修改 copy/不同 Engine capability，再以 `no_autoflush` 纯列查询当前数据库 bound 行闭合四元值；同 Engine 的不同 Session 与未修改 copy 可用，不同 Engine 即使 URL/数据相同也必须 reload。目标 KnowledgeSpace 处于 new/dirty/deleted UoW 时零查询拒绝且不 refresh/覆盖 caller pending state。
- 2026-07-13 · T8 复审修复：所有 public product/knowledge/page/publish DB runtime 边界统一调用 `require_current_scope`；admin loader/bind/list/show 与 migration 仍为明确例外。private ProductAlias/ClaimEvidence/ClaimRevision/ChangeItem/Conflict helper 仅能依赖已验证 public 父入口或同函数内 scoped parent guard。
- 2026-07-13 · T8 复审修复：新增 `(product_documents.space_id, version_id) → product_versions(space_id, id)` 与 `(claims.space_id, superseded_by) → claims(space_id, id)` 复合 FK，补齐 DB 可表达的 child/self scope closure。保留 0001/0002 原单列 FK作为兼容冗余；0003 downgrade 只删除新增复合 FK，天然恢复旧 schema，避免高风险约束重建。
- 2026-07-13 · T8 质量复审修复：attestation 改为 deep-copy-safe sentinel + Engine weak reference；scope 不延长 Engine 生命周期，弱引用失效后 fail closed。DB bind 使用 `session.get_bind(mapper=KnowledgeSpace)` 并归一 Connection→Engine，支持 mapper-only Session，默认 Engine 相同但 mapper Engine 不同会在零业务查询时拒绝。
- 2026-07-13 · T8 质量复审修复：`load_scope` 与 `require_current_scope` 共用 `no_autoflush` 纯列读取，绕过 identity map；目标 Space 的 new/dirty/deleted 状态同时按 inspected persistent identity 与 current id 拒绝。`bind_space` 成功后记录 caller outer transaction marker，commit/rollback 前不签发 capability；旧 transaction inactive 后清 marker，再由数据库决定 bound/unbound。
- 2026-07-13 · T8 质量复审边界：纯列读取不等于任意 committed-only 隔离；直接 raw SQL 或手工 flush 的低层写入若绕过 admin service，仍可能在当前事务可见，不属于 capability API 保证。产品 CLI migration 与 scope CLI 对齐，使用 percent-escaped Alembic main option + 原始 `-x db_url`，显式 flag 不会被 `HARNESS_DB_URL` 覆盖。
