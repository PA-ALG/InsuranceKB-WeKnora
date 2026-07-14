# 017 验证报告

更新时间：2026-07-14

当前状态：T1–T8 软件实施完成，并通过规格/质量双审与主代理全量复验；真实 WeKnora/PostgreSQL live 执行因六项环境前置缺失记录为 `NOT RUN`。本报告不把 skip/deselected 解释为 live 验收成功。

## T1 · WeKnora metadata / chunks / download

实现范围：

- metadata 消费 file identity 与 timezone-aware source timestamps；
- chunk 消费 offsets、metadata、content hash；
- metadata/download/chunks 的 timeout、408、429、5xx 重试，其他 4xx 永久失败；
- chunk 分页任一页失败后整轮从 page 1 重试，并同步 WeKnora `page_size<=100` 上限；
- async context-managed 安全临时文件；完整 attempt 覆盖 response open、stream、大小/长度、MD5；
- WeKnora MD5 校验与 Harness SHA-256 原件摘要；截断/hash mismatch 完整预算重试；
- success/error/cancellation 均关闭响应并清理临时文件；scope mismatch 在 HTTP 前 fail closed。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_weknora_source_contract_017.py tests/test_client_chunks.py tests/test_client_knowledge.py tests/test_retry.py tests/test_client_scope_016.py tests/test_client_wiki.py -q
88 passed in 6.76s

.venv/bin/ruff check src/insurance_harness/adapters src/insurance_harness/config.py tests/test_weknora_source_contract_017.py tests/test_client_chunks.py tests/test_client_knowledge.py tests/test_retry.py --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src/insurance_harness/adapters src/insurance_harness/config.py tests/test_weknora_source_contract_017.py
Success: no issues found in 9 source files
```

TDD 证据：

1. 初始 RED 在测试收集阶段暴露缺失下载模型与异常；
2. naive source timestamps RED 为 `2 failed`，随后以 `AwareDatetime` fail closed；
3. server pagination cap RED 首次返回 `100/101`，随后 client 本地 cap=100 完整翻页；
4. 规格审查修复完成时 T1 focused 为 `79 passed`；
5. 质量审查继续补充非幂等 POST 单次请求、chunk 页数/条目硬上限、严格非负 file size 与 32 位 MD5，最终 T1 focused 为 `88 passed`。

独立审查：

- 实施计划复审：Critical 0 / Important 0 / Minor 0，`Plan approved`；
- T1 规格审查：Critical 0 / Important 0 / Minor 0，`Spec compliant — Ready for quality review`；
- T1 质量审查：两个 Important 与一个 Minor 已按 TDD 修复，最终 `Quality approved — Ready for main verification`；
- 主代理最终复验：

```text
.venv/bin/pytest -m 'not live' -q
526 passed, 3 deselected, 165 warnings in 60.11s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 123 source files

git diff --check
passed
```

## T2 · SourceDocument / DocumentSource / Directory replay

实现范围：

- 深度不可变 `SourceRevision`、`SourceChunk`、`SourceDocument` 与递归冻结 metadata；
- source revision 对 file hash、UTC processed time、parser fingerprint 做 canonical JSON SHA-256，并拒绝伪造值；
- 完整四元 `SourceScope` 只能从 database-attested `KnowledgeScope` 投影；
- `MaterializedBatch` 的 runtime paths 不序列化，且与唯一 source IDs 精确闭合；
- Directory replay 显式 identity/parser/request，确定性排序，原件复制为安全只读 snapshot；hash、page parse、runtime path 全部基于同一 snapshot；
- root/PDF symlink 与 FIFO fail closed；发现/hash/PDF parse 在 worker thread 执行；取消及时传播并清理 snapshot；
- pages 连续 1-based，metadata JSON-safe；空/扫描/损坏 PDF 与无文件均为 typed all-or-nothing dead-letter；
- dead-letter canonical key 使用不碰撞的 null/identity 编码，错误消息不泄露部署绝对路径。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_source_models_017.py tests/test_compiler_pipeline.py -q
51 passed in 1.77s

.venv/bin/pytest -m 'not live' -q
560 passed, 3 deselected, 165 warnings in 56.24s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 128 source files

git diff --check
passed
```

独立审查：

- T2 规格审查：三个 Important 按 TDD 修复，最终 Critical 0 / Important 0 / Minor 0，`Spec compliant — Ready for quality review`；
- T2 质量审查：两轮 findings 全部按 TDD 修复，最终 `Quality approved — Ready for main verification`；
- 主代理最终全量门禁通过。

## T3 · WeKnoraDocumentSource materialization

实现范围：

- `WeKnoraSourceRequest` 冻结、可序列化、非空唯一，并拒绝路径/查询注入型 ID；adapter 的 metadata/download/chunks 三入口在 HTTP 前使用同一安全规范化；
- `WeKnoraDocumentSource` 只接受 database-attested `KnowledgeScope` 与显式 parser fingerprint，不接受 free-form KB ID；
- 按 metadata → completed gate → revision → context-managed download → SHA/MD5/size/file identity → page parse → complete chunks → metadata drift check 构造不可变 `SourceDocument`；
- `AsyncExitStack` 保持所有成功下载到整个 batch 退出；第二文档失败、任一阶段异常或取消均零 yield，并逆序清理全部临时文件；
- page loader 与下载文件身份检查均在线程执行；阻塞 page loader 不延迟调用方取消，后台迟到结果/异常被消费；
- batch 的文档数、累计 bytes/pages/chunks 均有配置化上限；超限按对应 typed stage fail closed；
- chunk identity/content/hash/metadata/offset 无损映射，整数严格、非负且 offsets 有序；source revision 冻结 file hash、UTC processed time 与 parser fingerprint；
- materialization 结束前二次读取 metadata，file hash、processed time 或 parse status 漂移均拒绝产出。

TDD 与审查证据：

1. 请求和完整 materializer 分别从缺少模块/类的收集失败开始；初版契约 GREEN 为 `25 passed`；
2. 规格审查的阻塞 loader 取消问题以短超时 RED 复现并修复，最终 Critical 0 / Important 0 / Minor 0，`Spec compliant`；
3. 质量审查两组 RED 分别为 `22 failed`（安全 ID/批量 limits）和 `28 failed`（strict chunk/stat nonblocking）；numeric identity 回归 RED 为 `1 failed, 2 passed`；
4. 全部 findings 修复后独立复审为 Critical 0 / Important 0 / Minor 0，`Quality approved`；最终规格回归仍为 `Spec compliant`。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_source_weknora_017.py tests/test_source_models_017.py tests/test_weknora_source_contract_017.py tests/test_client_chunks.py tests/test_client_knowledge.py tests/test_client_scope_016.py tests/test_retry.py tests/test_compiler_pipeline.py -q
230 passed in 7.21s

.venv/bin/pytest -m 'not live' -q
653 passed, 3 deselected, 165 warnings in 66.20s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 130 source files

git diff --check
passed
```

## T4 · Compiler source boundary / production-replay CLI

实现范围：

- Compiler 构造时必须显式注入 `DocumentSource`；`run()` 必须显式传 source request，每次 fresh/resume 都重新 materialize；
- `_node_load` 只把 `SourceDocument.pages` 投影成既有 `DocPayload`，不再 glob 或解析 PDF；`DocPayload` schema 未改变；
- `DocManifestEntry` 冻结 source ID、knowledge ID、source revision、file hash、original digest 与 parser fingerprint；load checkpoint 即写入完整来源身份；
- run-scoped `ContextVar` 保存 source ID→runtime path 与 runtime documents，fast path 不再拼接 `product_dir/doc`；同名文档 fail closed，并发 run 隔离；
- batch context 覆盖完整 graph 与 artifacts read；成功、graph failure、取消、resume reject 均清理临时文件；路径不进入 state/checkpoint/manifest；
- immutable RunIdentity 同时绑定 run/checkpoint/product 目录、产品、line、model、schema、prompt 与 judge；checkpoint state、manifest 和当前调用双侧核验，任何漂移在模型前拒绝；
- `state_patch` 只允许已知 `fail_nodes`；manifest/source/任意额外字段在写 checkpoint 前拒绝；
- 同一 run directory 使用 0600 nonblocking `flock`，已提交 fresh run、替代 checkpoint 与并发 writer fail closed；等待锁取消安全关闭 fd；
- artifacts 全量写入 staging，replace 失败回滚，`manifest.json` 最后作为 commit marker；
- 生产 CLI 只接受 `extract --source weknora`，从仍存活的 Engine 加载 attested Space 并传递 T3 limits；`extract-replay` 独占 Directory；主模型/judge/source/Engine 统一由 `AsyncExitStack` 清理；
- replay `pred.jsonl` 的业务字段保持语义等价，新增来源审计字段只进入 manifest。

TDD 与独立审查：

1. 无 glob 首个 RED 为 `1 failed`；source/checkpoint/lifecycle 初版 GREEN 为 `7 passed`；
2. 旧 implicit Directory helpers 适配前为 `18 failed, 23 passed`，改为显式 Directory source/request 后恢复；初版 T4 focused 为 `43 passed`；
3. 规格 findings 修复后 focused 为 `48 passed`，独立复审 `Spec compliant`；
4. 质量 A～E 分别以可复现 RED 锁定审计 patch、资源清理、run identity、atomic artifacts 与 strict config；最终 run-lock/checkpoint-path 回归完成后 focused 为 `120 passed`，独立复审 `Quality approved`；
5. 最终规格回归仍为 `Spec compliant`。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_source_pipeline_017.py tests/test_compiler_pipeline.py tests/test_template_fastpath.py -q
120 passed in 3.27s

.venv/bin/pytest -m 'not live' -q
750 passed, 3 deselected, 165 warnings in 58.31s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 131 source files

git diff --check
passed
```

## T5 · Pure quote-to-chunk lineage / source-aware pred evidence

实现范围：

- `sources.lineage` 以纯函数执行 quote→chunk 匹配：只移除空白，不 case-fold、不做 Unicode compatibility 或标点改写；唯一 chunk 包含为 `linked`，零命中为 `page_only`，多 chunk 命中（含重复内容）为 `ambiguous`；
- linked chunk hash 固定为原始 chunk content UTF-8 的 SHA-256；mapper 不接收或产出 page，也不读取 `chunk_index/start_at/end_at` 推导页码；
- Compiler finalize 保留 PDF 已验证的原 page/quote，只按 `cand.doc` 对应的 runtime `SourceDocument` 匹配 chunks；任何预载 source/chunk audit 先剥离，doc 未命中、unknown 或 quote 未回验时只能保留 bare page evidence；
- scoped verified evidence 冻结 knowledge/raw KB、source revision、file hash、original digest、parser version 与可选唯一 chunk；Directory replay 不制造 knowledge/chunk identity；page-only/ambiguous 仍可作为 page evidence 输出；
- Evidence audit 使用明确状态矩阵：legacy 全部 audit/status 为 null；unscoped replay 必须有完整 revision audit 且无 knowledge/raw/chunk；scoped 必须有成对非空 knowledge/raw 与完整 revision audit；只有 linked 允许且要求唯一非空 chunk ID + SHA-256；
- `SourceDocument` 在 lineage 前拒绝重复 `chunk_id`；public `ExtractionPipeline.run()` 回归覆盖 materialize→ContextVar→graph→finalize→pred 与 batch cleanup；
- 保留历史 Evidence 的 page 与 extra-field 宽容输入，只收紧 017 新增 audit 字段；`LineageResult` 保持 frozen/extra-forbid。

TDD 证据：

1. pure 首个 RED 在收集阶段因 `insurance_harness.sources.lineage` 缺失失败；表驱动 pure GREEN 为 `12 passed`；
2. integration RED 为 `3 failed, 13 passed`，实现 verified-only 同文档 join 与 source-aware output 后 GREEN；
3. 规格审查 P1：forged audit 绕过 RED 为 `3 failed, 1 passed`；统一 strip→trusted rederive 后 `4 passed`，复审 Critical 0 / Important 0 / Minor 0，`Spec compliant`；
4. 质量审查 P1/P2：Evidence matrix RED 为 `14 failed`；duplicate chunk ID RED 为 `1 failed`；修复后矩阵选集 `24 passed`、完整 evidence `45 passed`、source models `48 passed`；public run 集成测试首次运行即通过，确认缺口是覆盖而非另一个生产行为缺陷；
5. 质量复审 Critical 0 / Important 0 / Minor 0，`Quality approved`。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_evidence_lineage_017.py tests/test_source_models_017.py tests/test_source_pipeline_017.py tests/test_compiler_pipeline.py tests/test_compiler_extract.py -q
217 passed in 4.46s

.venv/bin/pytest -m 'not live' -q
796 passed, 3 deselected, 165 warnings in 56.88s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 133 source files

git diff --check
passed
```

边界说明：该证据只关闭 B4/T5；T6 的独立证据见下节。上述 `3 deselected` 不得解释为 live 验收成功。

## T6 · Evidence schema migration / source-aware import

实现范围：

- `ClaimEvidence`/`ProposedEvidence` 冻结 `raw_kb_id/source_revision/file_hash/original_digest/parser_version/chunk_hash/lineage_status/stale_at`，add/enrich/review 与页面读取无损传播；
- `0004_source_evidence_lineage.py` 串行承接 `0003`：历史行的新 audit 字段全 NULL 可读，source-aware 行必须完整；提供 revision/stale 索引、SQLite upgrade/downgrade、Alembic check 与 PostgreSQL offline DDL 契约；downgrade 保留旧证据字段但不可逆删除 017 audit/stale；
- 生产 importer 默认要求 scope-attested `SourceImportContext`，逐条交叉校验 Evidence/context/scope；仅命名的 `legacy_replay=True` 路径接受历史文件名 identity/旧参数；
- 生产 `knowledge_id` 复用 WeKnora 1–128 位安全单路径段合同，任意 outer/nested constructed model 均经深度二次 validation，禁止文件名、路径、控制/分隔/查询字符冒充 ID；
- 按 `(knowledge_id, source_revision)` 分区，每区一个 ChangeSet；复用零 ChangeItem 的 pending `recompile`/`document`，applied 同 revision 为 duplicate/no-op，其他冲突状态 fail closed；所有分区先无副作用预检，再由单一 savepoint 覆盖 create/merge/flush；
- 所有 Evidence 运行时查询 join `Claim.space_id`；enrich 去重包含 revision/chunk lineage；发布 `source_refs/chunk_refs` 只来自完整、已验证且非 stale 的 lineage，legacy ref 只在显式 replay 开放。

TDD 与独立审查：

1. 初始模型/导入 RED 由 `5 failed` 扩展到 `17 failed`，实现后 `17 passed`；migration 首轮 `1 failed, 4 passed` 后全绿；页面 refs、revision-aware enrich、placeholder/corrupt DB lineage 均有独立 RED/GREEN；
2. 规格审查两个 Important：改名/路径型文件名 placeholder、DB partial/stale-only audit。新增 renamed/POSIX/Windows path、raw-KB-only/stale-only 与 PostgreSQL DDL 断言后复审 `Spec compliant`；
3. 质量审查两个 Important：多 partition 非原子、ID/constructed context 边界不足。RED 精确证明后，以全区预检 + 单一 savepoint、canonical WeKnora ID 和深度二次验证修复；
4. 主线程补充 raw dict + nested `SourceImportIdentity.model_construct()` 绕过 RED；统一 `model_validate → model_dump → model_validate` 后 13-case boundary GREEN，质量复审无剩余发现，`Quality approved`。

验证命令与结果：

```text
cd harness
.venv/bin/pytest tests/test_evidence_lineage_017.py tests/test_knowledge_importer.py tests/test_knowledge_db.py tests/test_scope_migration_016.py tests/test_source_evidence_migration_017.py tests/test_knowledge_pages.py tests/test_knowledge_e2e.py tests/test_scope_knowledge_016.py tests/test_knowledge_merge.py tests/test_knowledge_review.py tests/test_knowledge_publisher.py -q
186 passed, 1 skipped, 207 warnings in 11.56s

.venv/bin/pytest -m 'not live' -q
838 passed, 3 deselected, 209 warnings in 60.33s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 134 source files

git diff --check
passed
```

边界说明：T6 不创建/标记 stale，不实现并发 recompile get-or-create，也不改变 source-scoped retract；这些属于 T7。T8 live E2E 仍未完成。focused 的 `1 skipped` 与 non-live 的 `3 deselected` 只记录条件跳过/显式排除，不能解释为 live 成功；PostgreSQL 证据仍是 offline DDL，不是真实 PostgreSQL/live 环境运行。

## T7 · Source revision / stale / recompile / retract（已完成）

实现范围：

- `notify_source_revision()` 深度重校验 scoped identity；同一 active revision no-op，新 revision 只条件更新同 Space/source 的 active source-aware Evidence，保留首次 `stale_at`，并在调用方事务内创建或精确复用 pending `recompile`；
- `(space_id, source_kind, external_record_id, source_revision)` 唯一键与 nested savepoint 关闭同 revision 并发重复创建；共享 aggregate validator 额外闭合 Space、kind、external record、revision 与精确单元素 `knowledge_ids`，调用方分别约束 pending/applied state 与 ChangeItem 数量；
- source-aware retract 删除同 Space/knowledge 的 active 与 stale Evidence，以其他 active Evidence 决定 Claim 保留；同 knowledge/revision 重放精确复用 applied tombstone，零 Evidence 删除也留下 tombstone，迟到的同 revision import fail closed；
- source-aware 与 legacy retract 强隔离：identity 与 `legacy_replay=True` 在任何 SQL 前拒绝；legacy 字符串只删除 audit 全 NULL 的历史 Evidence，若已存在 source lineage 或带真实 revision 的 document/recompile ChangeSet，则在 mutation 前拒绝；
- tombstone replay/import 共用 parent/child aggregate 校验：scoped 唯一 Claim、`retract` action、`auto_applied` decision、dict proposal，以及 `type(removed_evidence) is int and > 0`。任意缺失、错误类型、bool/零/负数、重复 Claim 或跨 scope 均报同一 `ScopeViolation`，Session 可继续使用且零副作用；
- applied exact source ChangeSet 作为 duplicate 返回前，merge 层 public `validate_scoped_change_set_items()` 遍历全部 ChangeItem，并复用既有 `_require_scoped_item_aggregate` 闭合 claim、existing/placeholder、proposal、Conflict 与 product-version 引用；不是简单要求 `claim_id` 非空，合法零 item 和 winner-existing `claim_id=NULL` conflict 均保持通过；
- notify/retract/import 不改变 ReleaseSnapshot、SnapshotClaim、CurrentRelease 或已物化页面。

TDD 与第一轮独立审查修复：

1. T7 初版 focused 完成后，规格复审为 `Spec compliant`；第一轮质量审查未批准，并给出四组可修 finding 与一项架构 residual；
2. legacy/source-aware 模式隔离 RED 为 `5 failed, 37 deselected`，修复后 `5 passed, 37 deselected`；覆盖 identity+legacy 零 SQL、Evidence/document/recompile 冲突、事务零副作用与正常 source-aware import 不可被 legacy retract；
3. source ChangeSet aggregate 矩阵 RED 为 `9 failed, 29 deselected`，修复后 `9 passed, 29 deselected`；覆盖 notify pending 与 importer pending/applied 的 null/other/multiple `knowledge_ids`；
4. tombstone child aggregate 扩展 RED 为 `10 failed, 6 passed, 32 deselected`，修复后 `16 passed, 32 deselected`；replay 与 importer 共用 16 组 malformed matrix；
5. live PostgreSQL harness 的 bounded timeout/cleanup 契约 RED 为 `1 failed, 1 skipped`，修复后 offline 契约 `1 passed, 1 skipped`；设置 connect/statement/lock/future timeout，并以 `try/finally` 覆盖 worker/admin engine、schema create/drop。由于未配置 `HARNESS_LIVE_POSTGRES_URL`，真实并发用例未运行，skip 不代表 live 成功。
6. fresh quality rereview 发现 applied duplicate 只校验 source parent/count，未校验 ChangeItem child scope。两条最小 RED（Space A add item 的 `claim_id` 指向 Space B；合法 winner-existing 形态的 `claim_id=NULL` conflict 通过 existing/proposal/Conflict 引用 Space B）均为 `DID NOT RAISE ScopeViolation`，合并运行 `2 failed, 48 deselected`；公共 child aggregate validator 接入 applied duplicate preflight 后，两条恶意用例、合法同 Space winner-existing conflict 与既有 zero-item duplicate 合计 `4 passed`。
7. 最终 fresh quality rereview 为 `Quality approved: yes`，无剩余 P0/P1/P2；复审 focused 为 `103 passed, 1 skipped`，仅记录非阻塞 N+1 观察项。独立规格复审保持 `Spec compliant`。

扩大 focused 验证命令：

```text
cd harness
.venv/bin/pytest tests/test_source_revision_017.py tests/test_source_retract_017.py tests/test_source_revision_postgres_017.py tests/test_knowledge_importer.py tests/test_knowledge_merge.py tests/test_scope_knowledge_016.py tests/test_knowledge_publisher.py tests/test_scope_publisher_016.py -q
201 passed, 2 skipped
```

最终封板门禁（2026-07-14）：全量 non-live `903 passed, 4 deselected, 209 warnings in 111.95s`；Ruff `All checks passed!`；mypy `Success: no issues found in 138 source files`；`git diff --check` 通过。

质量状态：第一轮四组可修 finding 与 fresh rereview 新增的一组 P2 均已按 TDD 闭合；最终 fresh quality rereview 已批准，`tasks.md` 的 T7 已勾选。

明确 residual：017 只保证同 revision 幂等，**不保证不同 revision 的并发或乱序安全**。revision 是不可排序的 SHA-256；不得用 hash 比较新旧。SourceImportIdentity/Evidence/ChangeSet 也没有 durable current-head/代际 CAS，因此旧 B notification 可能在 C 之后把 C 的 Evidence 标 stale，import/delete 仍存在跨 key 竞争。在 change 021 的 durable SourceHead、`processed_at`/generation 与统一 per-source lock/CAS 落地前，生产只允许同一 Space/source 串行 lifecycle，并且 notification 必须来自当次实时读取的当前 metadata；缓存或延迟旧 metadata、并发不同 revision、import/delete 竞争均不在支持范围。

## T8 · Live source bridge E2E / Runbook / handoff（软件实施完成，真实 live NOT RUN）

实现范围：

- live gate 要求六个显式变量：真实 WeKnora URL/API key、已迁移 PostgreSQL URL、bound Space、existing PDF knowledge ID 与 parser fingerprint；配置不全逐名 skip，SQLite 直接拒绝，绝无 Directory/mock fallback；
- 当前 adapter 无上传 API，按已批准计划走 existing-knowledge 分支并调用真实 `wait_for_parsed`；因此覆盖 parse wait→download/pages/chunks→bridge→Compiler→pred/import，不把该分支写成 upload 创建覆盖；
- Compiler 使用本地确定性 scripted client，零真实 LLM/模型凭据；live Evidence 必须由真实页锚点唯一 linked 到非空真实 chunk；
- RunManifest 与物化 `SourceDocument` 按文档集合一一对应，并闭合 scope/source/knowledge/revision/hash/digest/parser；Importer 后的 Evidence 直接对照物化文档与真实 chunk；
- Harness PostgreSQL 临时产品、ChangeSet、Claim 与 Evidence 全部在测试事务内回滚；client/session/engine、物化文件和 run 目录在成功/失败路径清理；
- 修复 source standalone eager-import cycle：compiler pipeline 公共导出改为 lazy resolve，`from insurance_harness.compiler import ExtractionPipeline` 与 star import 兼容。

TDD 与独立审查：

1. 初始编排 RED 为 `5 failed`（缺 prerequisite/anchor/context/scripted helper）；产品/version parent flush 补充 RED 为 `1 failed`，实现后 T8 non-live 为 `6 passed, 1 deselected`；
2. 第一轮规格审查 `Spec compliant: yes`；第一轮质量审查未批准，指出 permissive page-only、manifest self-oracle、standalone import cycle，并建议补双凭据脱敏与失败清理；
3. strict anchor RED `2 failed`、manifest attestation RED `3 failed`、subprocess import-order RED `1 failed`、cleanup registration RED `1 failed`；最小修复后 T8 non-live 扩大为 `12 passed, 1 deselected`，source standalone 为 `49 passed`；
4. 修复后规格复审 `Spec compliant: yes`、质量复审 `Quality approved: yes`，均无 Critical/Important/Minor。

主代理最终命令与证据：

```text
cd harness
.venv/bin/pytest tests/test_source_bridge_live_017.py -m 'not live' -q
12 passed, 1 deselected in 2.77s

.venv/bin/pytest tests/test_source_weknora_017.py -q
49 passed in 2.04s

/usr/bin/env -u HARNESS_LIVE_BASE_URL -u HARNESS_LIVE_API_KEY -u HARNESS_LIVE_DB_URL -u HARNESS_LIVE_SPACE_ID -u HARNESS_LIVE_KNOWLEDGE_ID -u HARNESS_LIVE_PARSER_FINGERPRINT .venv/bin/pytest tests/test_source_bridge_live_017.py -m live -q -rs
1 skipped, 12 deselected in 0.89s

.venv/bin/pytest -m 'not live' -q
915 passed, 5 deselected, 209 warnings in 68.29s

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 139 source files

git diff --check
passed
```

live 状态：`NOT RUN`。skip 精确列出 `HARNESS_LIVE_BASE_URL`、`HARNESS_LIVE_API_KEY`、`HARNESS_LIVE_DB_URL`、`HARNESS_LIVE_SPACE_ID`、`HARNESS_LIVE_KNOWLEDGE_ID`、`HARNESS_LIVE_PARSER_FINGERPRINT`；没有真实端点成功证据，也没有 upload 创建证据。

## 尚未验证

- 真实 WeKnora existing-knowledge bridge E2E 与真实 PostgreSQL import（T8 gate 已实现但环境缺失，`NOT RUN`）；
- WeKnora upload 创建分支（当前 adapter 无 uploader，不在已实现分支内）；
- 真实 PostgreSQL T7 并发用例（未配置 `HARNESS_LIVE_POSTGRES_URL`）；
- 021 不同 revision lifecycle ordering（当前仅 proposed/pending，未实现）。
