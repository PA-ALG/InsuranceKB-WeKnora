# 017 任务

- [x] T1 先写 WeKnora metadata/chunk/download 契约失败测试，再扩充 adapter（B1）
- [x] T2 先写 SourceDocument/DocumentSource 行为测试，再实现 DTO 与 replay source（B2）
- [x] T3 先写 scope/hash/parse 状态失败测试，再实现 WeKnoraDocumentSource
- [x] T4 先写 Compiler 不再依赖 glob 的 pipeline 测试，再接入 DocumentSource（B3）
- [x] T5 先写 quote→chunk 唯一/零/多命中测试，再实现 lineage mapper（B4）
- [x] T6 先写 Evidence migration/import 测试，再持久化 source revision 与 lineage
- [x] T7 先写 source revision 变化与删除测试，再实现 stale/recompile/retract（B5）
- [x] T8 增加 live E2E、Runbook、validation-report 与 HANDOFF 对账

状态：T1–T8 软件实施完成，并通过规格/质量双审与主代理全量复验；真实 WeKnora/PostgreSQL live 执行因环境前置缺失记录为 `NOT RUN`，不视为 live 验收成功。

## T1 验证证据（2026-07-13）

- RED：新契约测试首次收集因 `WeKnoraDownloadTooLarge` 等下载契约尚不存在而失败；
- RED：naive `processed_at/updated_at` 首次运行 `2 failed`；改用 `AwareDatetime` 后通过；
- RED：caller `page_size=101`、服务端 cap=100、总计 101 chunks 时首次只返回 100；本地同步 cap 后完整拉取；
- GREEN：adapter/source focused（含 Wiki POST 非幂等回归）→ `88 passed`；
- Ruff：adapter/config/相关测试 focused check → `All checks passed!`；
- mypy：adapter/config/T1 测试 → `Success: no issues found in 9 source files`；
- 独立规格审查的两个 Important（时区感知时间戳、服务端分页 cap）均已按 TDD 修复，最终 `Spec compliant`；
- 独立质量审查的两个 Important（POST 自动重试、无限满页）与一个 Minor（file identity 严格性）均已按 TDD 修复，最终 `Quality approved`；
- 主代理最终复验：`526 passed, 3 deselected`，Ruff 全量通过，mypy `123 source files`，`git diff --check` 通过。

## T2 验证证据（2026-07-13）

- 初始边界 RED：`1 failed`；完整行为 RED：`14 failed, 1 passed`；实现初版 GREEN：`15 passed`；
- 规格审查的三个 Important（完整 attested scope 投影、chunk content hash、非空 pages）均按 TDD 修复，最终 `Spec compliant`；
- 质量审查第一轮的五个 Important/两个 Minor通过安全 snapshot、`asyncio.to_thread`、页码/metadata/batch/dead-letter 强校验关闭；第二轮两个 Important 通过 `O_NONBLOCK+fstat` 与 PAGE_PARSE 包装关闭，最终 `Quality approved`；
- focused：`.venv/bin/pytest tests/test_source_models_017.py tests/test_compiler_pipeline.py -q` → `51 passed`；
- 主代理最终复验：`560 passed, 3 deselected`，Ruff 全量通过，mypy `128 source files`，`git diff --check` 通过。
- 2026-07-14 · PR #4 复审：默认 `metadata={}` 绕过字段 validator、可在 frozen `SourceChunk` 上原地修改；先把默认值 mutation 加入既有深度不可变测试并得到 RED，再用 `Field(..., validate_default=True)` 统一默认值与显式输入的递归冻结路径。

## T3 验证证据（2026-07-13）

- 初始 RED：请求 DTO 因缺少 `sources.weknora` 收集失败；完整 materialization RED 因缺少 `WeKnoraDocumentSource` 收集失败；
- GREEN：attested scope、metadata/parse gate、download/hash/size、线程化 page parse、完整 chunks、二次 metadata drift 检查、multi-document `AsyncExitStack` 与 runtime path 生命周期全部通过；
- 规格审查的一个 Important（阻塞 page loader 使取消无法及时传播）先以 `TimeoutError` RED 复现，再改为立即传播取消并消费后台线程迟到结果，最终 `Spec compliant`；
- 质量审查以 `22 failed` 复现 knowledge ID 路径注入与批量资源无上限，以 `28 failed` 复现 chunk 宽松整数与同步 stat 阻塞；新增 adapter HTTP 前安全 ID、配置化文档/bytes/pages/chunks 批量上限、严格 chunk offsets 与 `to_thread` 完成修复；
- numeric identity 兼容性复审 RED 为 `1 failed, 2 passed`；统一规范化非负整数 ID 后 metadata→download 契约恢复，最终 `Quality approved`；
- 主代理 focused 复验：`230 passed`；最终全量门禁：`653 passed, 3 deselected`，Ruff 全量通过，mypy `130 source files`，`git diff --check` 通过。

## T4 验证证据（2026-07-13）

- 首个 RED 直接证明 `_node_load` 仍调用 `product_dir.glob("*.pdf")`；改造后只消费已物化 `SourceDocument`，`DocPayload` 字段集合保持不变；
- 初版 GREEN 覆盖每次 run/resume rematerialize、batch context 贯穿 graph、runtime-only fastpath path、manifest source audit、checkpoint revision/digest drift pre-model reject、成功/失败/取消清理与并发 ContextVar 隔离；
- CLI 分流从旧 parser 不识别 `--source/space/parser/knowledge/product/db` 和缺少 `extract-replay` 的 RED 起步；生产 `extract` 只构造 WeKnora source，Directory 仅属于 `extract-replay`；
- 规格审查三个 Important（scoped pipeline 接受 unscoped 文档、state patch 可写临时路径、Session 跨异步 run）与一个 Minor 均按 TDD 修复，最终 `Spec compliant`；
- 质量审查以 A～E RED/GREEN 收口 manifest patch 审计篡改、CLI 资源泄漏、checkpoint run identity 漂移、非原子 artifacts 与无效 PipelineConfig；随后补充 checkpoint path identity、已提交目录 fresh-run 拒绝、0600 nonblocking `flock`、并发 writer 和取消 waiter fd 清理，最终 `Quality approved`；
- source/compiler/template focused 最终 `120 passed`；主代理全量门禁：`750 passed, 3 deselected`，Ruff 全量通过，mypy `131 source files`，`git diff --check` 通过。

## T5 验证证据（2026-07-14）

- pure lineage 首个 RED 因 `insurance_harness.sources.lineage` 尚不存在而收集失败；表驱动实现后 pure GREEN 为 `12 passed`，覆盖仅移除空白、不 case-fold/不改标点、唯一/零/多/重复内容命中、空 quote、精确 UTF-8 SHA-256 与绝不从 chunk offset/index 推导 page；
- Compiler integration RED 为 `3 failed, 13 passed`，随后 verified-only、同文档 join、Directory replay 不伪造 knowledge/chunk、source audit 与原 page/quote 保持 GREEN；
- 规格审查 P1 以 `3 failed, 1 passed` 复现 doc 未命中、quote 未回验和 unknown 候选透传 forged audit；finalize 统一先剥离预载 audit、再只从匹配 `SourceDocument` 重派生后 `4 passed`，规格复审 `Spec compliant`；
- 质量审查 P1/P2 先以 `14 failed` 固化 Evidence legacy/unscoped/scoped 状态矩阵，再以 `1 failed` 固化重复 `chunk_id`；修复后矩阵选集 `24 passed`、source models `48 passed`，并新增 public `ExtractionPipeline.run()` materialize→graph→finalize→pred scoped linked 回归；
- T5 最终 focused：Evidence/source models/source pipeline/compiler pipeline/extract → `217 passed`；独立质量复审 Critical 0 / Important 0 / Minor 0，`Quality approved`；
- 主代理最终全量门禁：`796 passed, 3 deselected, 165 warnings in 56.88s`，Ruff 全量 `All checks passed!`，mypy `133 source files`，`git diff --check` 通过；
- 以上只证明 T5 完成；T6 的独立证据见下节。

## T6 验证证据（2026-07-14）

- 初始模型/导入 RED 从 `5 failed` 扩展为 `17 failed`，覆盖 8 个 Evidence audit/stale 字段、逐字段无损传播、生产拒绝文件名 placeholder、显式 `legacy_replay`、按 `(knowledge_id, source_revision)` 分区、pending `recompile`/`document` 复用、applied duplicate/no-op 与冲突状态 fail closed；实现后对应 `17 passed`；
- migration RED 首轮 `1 failed, 4 passed`，随后 fresh SQLite、`0003 → 0004` 历史行兼容、check/index、Alembic metadata check、`0004 → 0003` audit 丢失边界及 PostgreSQL offline DDL 全部 GREEN；页面 ref、revision-aware enrich 去重、filename placeholder 与损坏 DB lineage 也分别经历 RED/GREEN；
- 规格审查发现两个 Important：任意改名/路径型文件名仍可冒充 `knowledge_id`，以及 DB 可接受 partial/stale-only audit。新增 renamed/POSIX/Windows path 与 raw-KB-only/stale-only/PostgreSQL 约束测试后修复，复审 `Spec compliant`；
- 质量审查发现两个 Important：多 partition 后区失败可能留下半批副作用，以及 WeKnora ID 字符集/长度与 `model_construct()` 绕过不足。新增捕获异常后 outer commit 仍保持 ChangeSet/ChangeItem/Claim/ClaimEvidence 零 T6 新行、危险字符/超长 ID 与 constructed context 测试；改为全分区无副作用预检 + 单一 savepoint、canonical WeKnora ID 合同与深度二次验证；
- 主线程再发现 raw-dict outer + nested constructed identity 变体，精确 RED 后将边界统一为 `model_validate → model_dump → model_validate`；最终 13-case 安全边界 GREEN，质量复审 Critical 0 / Important 0 / Minor 0，`Quality approved`；
- 主代理 focused：`186 passed, 1 skipped, 207 warnings in 11.56s`；全量 non-live：`838 passed, 3 deselected, 209 warnings in 60.33s`；Ruff `All checks passed!`；mypy `134 source files`；`git diff --check` 通过；
- T6 只完成 Evidence migration/persistence/source-aware import 与 validated non-stale refs。T7 的 stale mutation、并发 recompile get-or-create、source-scoped retract，以及 T8 live E2E 仍未完成；`1 skipped`/`3 deselected` 不代表 live 成功。

## T7 验证证据（2026-07-14）

- 按 TDD 完成 source revision stale mutation、同 revision 并发 recompile get-or-create、source-scoped retract/tombstone，以及 legacy/source-aware 强隔离；
- 第一轮质量审查四组 finding 与 fresh rereview 新增的 applied-duplicate child aggregate P2 均以最小 RED 固化并修复；最终 fresh quality rereview 为 `Quality approved: yes`，无剩余 P0/P1/P2；
- 独立规格复审为 `Spec compliant`；最终质量复审 focused 为 `103 passed, 1 skipped`，仅记录非阻塞 N+1 观察项；
- 主代理扩大 focused：`201 passed, 2 skipped`；最终全量 non-live：`903 passed, 4 deselected, 209 warnings in 111.95s`；Ruff `All checks passed!`；mypy `138 source files`；`git diff --check` 通过；
- 真实 PostgreSQL 并发用例因未配置 `HARNESS_LIVE_POSTGRES_URL` 未运行，真实 WeKnora live E2E 也未运行；skip/deselected 不代表 live 成功；
- T7 只保证同 revision 幂等。不同 revision 并发/乱序、import/delete 竞争由 021 的 durable SourceHead、generation/processed_at 与 per-source lock/CAS 承接；021 当前仅为 proposed/pending，未实现。

## T8 验证证据（2026-07-14）

- 新增真实端点 `test_source_bridge_live_017.py`：只接受显式 WeKnora URL/API key、已迁移 PostgreSQL、bound Space、existing PDF knowledge ID 与 parser fingerprint；禁止 SQLite、Directory 与 mock/respx fallback；
- existing-knowledge 分支先对真实端点执行 `wait_for_parsed`，再完成 materialize→deterministic scripted Compiler→`pred.jsonl`→source-aware import→`ClaimEvidence` 回链断言；当前 adapter 无 uploader，因此不宣称覆盖 upload 创建；
- live 锚点必须来自真实 PDF 页并唯一命中非空真实 chunk；manifest 与实际物化 `SourceDocument` 做一一对应及完整身份互证，Evidence 直接对照物化文档，而非以 manifest 自证；
- client/session/engine、物化临时文件与 run 目录均有显式清理；Harness PostgreSQL 写入在断言后 rollback；API key 与数据库密码不进入 repr/error；
- 初始 TDD RED：5 个缺失编排 helper 失败，产品/version flush 补充 RED 1 个；第一轮质量审查未批准后，strict anchor `2 failed`、manifest attestation `3 failed`、独立 import-order subprocess `1 failed`、cleanup registration `1 failed` 均先 RED 后 GREEN；
- 017 source standalone 的既有 eager-import cycle 已以 compiler pipeline lazy re-export 最小修复，保持公共 API；独立运行 `49 passed`；
- 最终独立规格复审 `Spec compliant: yes`，最终独立质量复审 `Quality approved: yes`，均无 Critical/Important/Minor；
- 主代理 fresh T8 non-live：`12 passed, 1 deselected in 2.77s`；最终全量 non-live：`915 passed, 5 deselected, 209 warnings in 68.29s`；Ruff `All checks passed!`；mypy `139 source files`；`git diff --check` 通过；
- 主代理显式清空六个 live 变量后运行 live gate：`1 skipped, 12 deselected in 0.89s`，skip 精确列出 `HARNESS_LIVE_BASE_URL`、`HARNESS_LIVE_API_KEY`、`HARNESS_LIVE_DB_URL`、`HARNESS_LIVE_SPACE_ID`、`HARNESS_LIVE_KNOWLEDGE_ID`、`HARNESS_LIVE_PARSER_FINGERPRINT`。该结果记录为 `NOT RUN`，不是 live 成功。
