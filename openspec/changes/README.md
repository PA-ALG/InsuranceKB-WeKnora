# OpenSpec Change 编号注册表（权威占号处）

> **规则（2026-07-16 起生效）**：开新 change 或新 Alembic 迁移前，**先在本表占号**，与 change 目录同 PR 提交；两个 PR 抢同号时，以先合入 main 者为准，后者改号。
> 背景：022 曾被两个独立 change 同时使用（见下），多轨并行后必须先占号再开工。

## Change 编号台账

| 号 | change | 状态 | 备注 |
|---|---|---|---|
| 001 | harness-scaffold | ✅ 已交付 | |
| 002 | goldenset-s0 | ⏳ 7/9 | 真跑部分转 020 |
| 003 | product-master-routing | ✅ 已交付 | |
| 004 | extraction-pipeline-mvp | ✅ 已交付 | |
| 005 | eval-refinement-recall | ✅ 已交付 | 归因清单由 024 承接 |
| 006 | template-fastpath | ✅ 已交付 | PP-StructureV3 遗留 B9 |
| 007 | claims-changeset-publish | ✅ 已交付 | |
| 008 | review-workbench | 📋 已条款化，可认领 | 轨道 L2；W4 依赖 018 |
| 009 | concept-layer | 📋 提案（待基础对齐修订） | 轨道 L4；迁移预分配 0008 |
| 010 | structured-import | 📋 已条款化，可认领 | 轨道 L4 首件；迁移预分配 0007 |
| 011 | knowledge-health | 📋 提案（待基础对齐修订） | 轨道 L4 收尾 |
| 012 | qa-objects | 📋 提案（待基础对齐修订） | 依赖 010；迁移预分配 0009 |
| 013 | insurance-mcp | 📋 已条款化，可认领 | 轨道 L3；实现等 PR #9 合并 |
| 014 | batch-orchestration | 📋 提案 | M3，暂不排 |
| 015 | feedback-flywheel | 📋 提案 | M2，依赖 009 |
| 016 | enterprise-knowledge-scope | ✅ 已交付 | |
| 017 | weknora-source-bridge | ✅ 软件交付；live NOT RUN | |
| 018 | release-snapshot-read-model | ⏳ PR #9（live 收口中） | 独占迁移 0005 |
| 019 | golden-quality-gate | ✅ 已合入 main（PR #8） | |
| 020 | golden-v01-baseline-run | 📋 等 019✅+021 | 高 token 数据任务 |
| 021 | source-lifecycle-ordering | 📋 等 018 | 迁移预分配 0006 |
| 022 | review-hardening | ✅ 已交付 | ⚠️ 编号冲突历史记录：与下行同号，两者均已合入，**目录不改名**，冲突就此冻结 |
| 022 | test-portfolio-rebalance | ✅ 已交付 | 同上 |
| 023 | local-weknora-live-environment | ✅ 已合入 main（PR #10） | 受信 live workflow |
| 024 | extraction-recall-uplift | 📋 本次新开，可认领 | 轨道 L5；零真实模型调用；含 A10 抽取侧弱值/兼容性护栏（E6） |
| 025 | merge-weak-value-guard | 🔒 已占号（目录未开） | 合并前置弱值门槛：更粗略新值不开冲突（Q026 防审核队列垃圾）；小型，PR #9 合入后提案；可与 024 同一执行者顺手接 |
| 026+ | （空闲） | | 先占号再开目录 |

## Alembic 迁移编号台账（harness/migrations/versions/）

| 号 | 归属 change | 状态 |
|---|---|---|
| 0001 | 003 product_domain | ✅ |
| 0002 | 007 knowledge_domain | ✅ |
| 0003 | 016 enterprise_knowledge_scope | ✅ |
| 0004 | 017 source_evidence_lineage | ✅ |
| 0005 | 018 release_snapshot_read_model | ⏳ PR #9 |
| 0006 | 021 source-lifecycle-ordering | 预分配 |
| 0007 | 010 structured-import（qa_staging 等） | 预分配 |
| 0008 | 009 concept-layer | 预分配 |
| 0009 | 012 qa-objects | 预分配 |
| 0010+ | （空闲；011/014/015 如需建表先来占号） | |

> 迁移链是全局串行的：占了号的 change 若先于前号合入，须在 PR 中与前号 change 负责人协调 down_revision 顺序（原则：合入 main 的先后决定链序，注册表随之更新）。

## 并行开工基线（2026-07-16 裁决）

- 规格/文档工作：一律以当前 `main` 为基，**不等 PR #9**；
- 实现工作：不触碰 `knowledge/` 发布与快照读取路径的轨道（008 的 W1–W3、010、024）即刻可从 `main` 开工；
- 触碰读模型/回滚/发布语义的部分（013 实现、008 W4、021 全部）在 **PR #9 合入后**从新 main 开工；
- 总蓝图与轨道分工见 `docs/insurance-kb/22-parallel-execution-blueprint.md`，实时状态以 `HANDOFF.md` ⓪ 为准。
