# OpenSpec Change 编号注册表（权威占号处）

> **规则（2026-07-16 起生效）**：开新 change 或新 Alembic 迁移前，**先在本表占号**，与 change 目录同 PR 提交；两个 PR 抢同号时，以先合入 main 者为准，后者改号。
> 背景：022 曾被两个独立 change 同时使用（见下），多轨并行后必须先占号再开工。

## Change 编号台账

| 号 | change | 状态 | 备注 |
|---|---|---|---|
| 001 | harness-scaffold | ✅ 已交付 | |
| 002 | goldenset-s0 | ⏳ 7/9 | 真跑部分转 020 |
| 003 | product-master-routing | ✅ 已交付 | |
| 004 | extraction-pipeline-mvp | ⚠️ 第一方历史范围通过；不是当前生产证明 | 可由 028 记录 provenance 后选择性重构；真实效果由 030 验收 |
| 005 | eval-refinement-recall | ✅ 已交付 | 归因清单由 024 承接 |
| 006 | template-fastpath | ⚠️ 第一方历史范围通过；不是 TemplatePackage | 可作为 028 能力输入；PP-StructureV3 后置 |
| 007 | claims-changeset-publish | ✅ 旧范围已交付 | 不含 NS-C/P-1 seal/active alias；生产发布继续 fail closed |
| 008 | review-workbench | ✅ T1～T5/T7 已合入（PR #15）；W4/T6 follow-up 可认领 | 轨道 L2；018✅ 已解除整页/回滚前置；Owner 复审=A |
| 009 | concept-layer | 📋 规格已收口，**待 010 T5～T12 合入后认领** | 轨道 L4 第二件；021✅仅解除 010 ordering 前置；C3.4 混源防护；(space_id,canonical_key) 身份 + concept_revisions 定义版本化 + C6 冻结投影扩展合同；迁移 0008 |
| 010 | structured-import | 🚧 T1～T4 已合入；MVP 只实施已知 schema product_meta/FAQ 薄切 | 完整 T5～T12 保留 M2；MVP 仍走 SourceRevision/Evidence/ChangeSet/Review；迁移预分配 0007 |
| 011 | knowledge-health | 📋 PR #12 主规格 + PR #22 fast-follow 已收口，**011 本体可认领** | H1.3a 远端/输入/工具链独立证据轴、多信号并报、不可归因 degraded；H1.8 通过 020 registry 消费 024 attempt ledger，缺数据 degraded；迁移 0010；typed subject 接线 Owner-A |
| 012 | qa-objects | 📋 规格已收口，**待 010 T5～T12 的 qa_staging/冻结合同合入后认领** | qa_items/qa_revisions/qa_assertions/bindings 断言级绑定（复合 FK 闭 Space）+ 冻结事务内重验 + Q5 冻结投影扩展（SnapshotQA）；迁移 0009 |
| 013 | insurance-mcp | 📋 MVP core 可认领 | 先交付产品对齐/事实/证据与 snapshot/hash envelope；完整 compare/history 矩阵留 M2 |
| 014 | batch-orchestration | 📋 提案 | M3，暂不排 |
| 015 | feedback-flywheel | ✅ 已合入 main（PR #18） | 离线 trace→durable 飞轮；迁移 0012（三表单事务/Space 隔离）；Langfuse 直连与 ReviewItem 动作投影保持 gated |
| 016 | enterprise-knowledge-scope | ✅ 已交付 | |
| 017 | weknora-source-bridge | ✅ 软件交付；live NOT RUN | |
| 018 | release-snapshot-read-model | ✅ 已合入 main（PR #9，2026-07-17） | 独占迁移 0005 |
| 019 | golden-quality-gate | ✅ 已合入 main（PR #8） | |
| 020 | golden-v01-baseline-run | 🚧 13 产品 canonical admission BLOCKED；真实 D2～D4 未运行 | 企业 M2；不阻塞 030 的独立 23-source MVP admission |
| 021 | source-lifecycle-ordering | ✅ 已合入 main（PR #23） | 迁移 0006，实际链 `0012 → 0006`；deterministic 1901，PG 25/skipped=0 |
| 022 | review-hardening | ✅ 已交付 | ⚠️ 编号冲突历史记录：与下行同号，两者均已合入，**目录不改名**，冲突就此冻结 |
| 022 | test-portfolio-rebalance | ✅ 已交付 | 同上 |
| 023 | local-weknora-live-environment | ✅ 已合入 main（PR #10） | 受信 live workflow |
| 024 | extraction-recall-uplift | ⚠️ 第一方软件范围已合入；真实收益未验证 | 028 可选择性复用；030 证明 MVP slice 效果，完整 020 验证留 M2 |
| 025 | merge-weak-value-guard | ⏭ 后置 | 非 MVP 阻断；排在完整 010 与企业 merge hardening 后；迁移 0011 |
| 026 | claim-data-quality-persistence | 🔒 已占号（目录未开） | `data_quality` 的 Claim/Revision/Snapshot/MCP 端到端字段+迁移+回填（12 号文档 #2 采纳项至今只在 pred 侧，主链未落——PR #11 四轮对账发现）；业务确需时立项，010/013 不预支承诺 |
| 027 | production-weak-model-boundary | 🧭 已占号，待执行 OpenSpec | MVP S0；所有生产入口硬禁强/未知/rolling model；零真实模型前置 |
| 028 | template-compilation-runtime-mvp | 🧭 已占号，待执行 OpenSpec | MVP S1；TemplatePackage + CompilationJob/StageRun/Attempt/Receipt/Alert，复用现有主链 |
| 029 | release-manifest-approval-mvp | 🧭 已占号，待执行 OpenSpec | MVP K0；完整 manifest hash 真人批准、CAS CurrentRelease、P-1 前 Harness serving |
| 030 | enterprise-wiki-mvp-slice | 🧭 已占号，待执行 OpenSpec | 23 来源/5 产品 manifest、独立 admission、fixtures、真实 E2E 与验收报告 |
| 032 | human-wiki-reader-mvp | 🧭 已占号，待执行 OpenSpec | MVP M1；独立只读产品 Wiki，消费 029 serving，与 013 同 snapshot/hash；不复用 008 写工作台；031 保留给既有 operational-run-admission |
| 032+ | （空闲） | | 先占号再开目录 |

## Alembic 迁移编号台账（harness/migrations/versions/）

| 号 | 归属 change | 状态 |
|---|---|---|
| 0001 | 003 product_domain | ✅ |
| 0002 | 007 knowledge_domain | ✅ |
| 0003 | 016 enterprise_knowledge_scope | ✅ |
| 0004 | 017 source_evidence_lineage | ✅ |
| 0005 | 018 release_snapshot_read_model | ✅（PR #9 已合入） |
| 0006 | 021 source-lifecycle-ordering | ✅ 已随 PR #23 合入；实际 down_revision=0012 |
| 0007 | 010 structured-import（qa_staging 等） | 预分配 |
| 0008 | 009 concept-layer | 预分配 |
| 0009 | 012 qa-objects | 预分配 |
| 0010 | 011 knowledge-health（completeness_snapshots + health_runs/health_findings） | 预分配 |
| 0011 | 025 merge-weak-value-guard（suppressed_observations root + suppressed_observation_events 双表，append-only+触发器） | 预分配 |
| 0012 | 015 feedback-flywheel（flywheel_checkpoints + flywheel_observations + knowledge_gaps） | ✅ 已随 PR #18 合入；down_revision=0005 |
| 0013 | 029 release-manifest-approval-mvp | 预分配；合入时指向实际 head |
| 0014 | 028 template-compilation-runtime-mvp | 预分配；若 MVP 采用独立 runtime tables，合入时指向实际 head |
| 0015+ | （空闲；014 如需建表先来占号） | |

> **迁移号≠链拓扑**：上表编号只是占号防撞（文件名/revision id 用它），**down_revision 链序由实际合入 main 的先后决定**，与数字大小无关。规则：每个实现 PR 合入时把自己的 down_revision 指向**当时 main 的实际 head**（先合的 0007 可以在 0006 之前入链）；不允许产生 multi-head；合入后在本表"备注"记录实际链序。数字顺序仅为可读性，不承载任何拓扑语义。

## 并行开工基线（2026-07-21 MVP 批准后）

- 北极星与 Integration-first MVP 已批准；总体规划窗口先补齐 027～030、032 的正式 proposal/specs/tasks 和实现 plans，再交独立执行会话；
- `NS-RIGHTS=recorded`：LLM-wiki-black 是项目方第一方资产，可按 provenance + OpenSpec 选择性迁移；第三方许可证另行清点；
- 027 未 verified 前，现有强 judge/fallback/未知模型与任何真实生产编译、merge、release 入口 fail closed；
- 030 MVP admission READY 后只允许运行其 23-source slice；不修改也不借用 020 canonical BLOCKED 的授权状态；
- S/K/M/I 的文件域、串行 migration lane 和合入顺序见 22；实时状态只在 HANDOFF MVP-0 控制板维护；
- 025、完整 010/013/008、020 D2～D4、P-1、011/014/015 均后置；032 只做独立只读消费面，不得顺手扩成审核或生产 Wiki UI。
