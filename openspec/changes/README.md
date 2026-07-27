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
| 009 | concept-layer | 📋 历史规格已收口；当前不授权实施 | 旧迁移 0008 已撤号且不可复用；后续须按 033 Milestone 重新立项 |
| 010 | structured-import | ⚠️ T1～T4 历史范围已合入；旧续作路线撤销 | 已有能力不是当前生产证明；旧迁移 0007 已撤号且不可复用 |
| 011 | knowledge-health | 📋 历史规格已收口；当前不授权实施 | 旧迁移 0010 已撤号且不可复用；后续按修正案 Milestone C 重新立项 |
| 012 | qa-objects | 📋 历史规格已收口；当前不授权实施 | 旧迁移 0009 已撤号且不可复用；后续须按 033 Milestone 重新立项 |
| 013 | insurance-mcp | 📋 MVP core 可认领 | 先交付产品对齐/事实/证据与 snapshot/hash envelope；完整 compare/history 矩阵留 M2 |
| 014 | batch-orchestration | 📋 提案 | M3，暂不排 |
| 015 | feedback-flywheel | ✅ 已合入 main（PR #18） | 离线 trace→durable 飞轮；迁移 0012（三表单事务/Space 隔离）；Langfuse 直连与 ReviewItem 动作投影保持 gated |
| 016 | enterprise-knowledge-scope | ✅ 已交付 | |
| 017 | weknora-source-bridge | ✅ 软件交付；live NOT RUN | |
| 018 | release-snapshot-read-model | ✅ 已合入 main（PR #9，2026-07-17） | 独占迁移 0005 |
| 019 | golden-quality-gate | ✅ 已合入 main（PR #8） | |
| 020 | golden-v01-baseline-run | 🚧 13 产品 canonical admission BLOCKED；真实 D2～D4 未运行 | 企业 M2；不阻塞 030 的独立 23-entry 受控输入 MVP admission |
| 021 | source-lifecycle-ordering | ✅ 已合入 main（PR #23） | 迁移 0006，实际链 `0012 → 0006`；deterministic 1901，PG 25/skipped=0 |
| 022 | review-hardening | ✅ 已交付 | ⚠️ 编号冲突历史记录：与下行同号，两者均已合入，**目录不改名**，冲突就此冻结 |
| 022 | test-portfolio-rebalance | ✅ 已交付 | 同上 |
| 023 | local-weknora-live-environment | ✅ 已合入 main（PR #10） | 受信 live workflow |
| 024 | extraction-recall-uplift | ⚠️ 第一方软件范围已合入；真实收益未验证 | 028 可选择性复用；030 证明 MVP slice 效果，完整 020 验证留 M2 |
| 025 | merge-weak-value-guard | ⛔ 旧计划撤销 / history-only | 旧迁移 0011 已撤号且不可复用；后续须按 033 重新切片 |
| 026 | claim-data-quality-persistence | 🔒 已占号（目录未开） | `data_quality` 的 Claim/Revision/Snapshot/MCP 端到端字段+迁移+回填（12 号文档 #2 采纳项至今只在 pred 侧，主链未落——PR #11 四轮对账发现）；业务确需时立项，010/013 不预支承诺 |
| 027 | production-weak-model-boundary | ✅ 已合入；能力保留 | 历史交付能力，不再作为旧 Wave 路线状态源；后续由 033 DAG 消费 |
| 028 | template-compilation-runtime-mvp | ⛔ superseded / history-only | 旧 PR28/runtime 路线不得继续实现、重放或作为生产 authority |
| 029 | release-manifest-approval-mvp | ⛔ superseded / history-only | 历史规格仅供审计；由 033 后续 Release/Review 小 PR 重新交付 |
| 030 | enterprise-wiki-mvp-slice | ✅ 已合入；能力保留 | 历史交付能力，不再作为旧 Wave 路线状态源；后续由 033 DAG 消费 |
| 031 | operational-run-admission | ⛔ superseded / history-only | 旧 runtime/PR 路线冻结，不更新、不重放、不授予生产 authority |
| 032 | human-wiki-reader-mvp | ⛔ superseded / history-only | 历史规格仅供审计；后续消费面按 033 Milestone 重建 |
| 033 | production-architecture-reset | ✅ D0 已合入（PR #34/#35）；治理状态源继续有效 | 当前唯一生产架构治理状态源；不是迁移号 |
| 034 | c0-canonical-envelope | ✅ 已实现并合入（PR #36） | 033 §16 C0；纯 Python 包，无迁移 |
| 035 | p1-job-outbox | 规格 ✅ 已合入（PR #38）；实现由 **PR #53** 在最新 main 重落地 | 旧实现 PR #44 `CLOSED / ARCHIVED / NOT MERGED`，归档 tag `archive/pr44-p1-job-outbox-20260727-a6cdc9ae`；按 D-2026-07-27-15，#53 代码与该 tag 逐字节一致、仅重写治理文档（**取代 #52 的"实现回到 NOT STARTED、不得重放"条款**）；门禁在 #53 head 重跑，旧 head CI 不作证据；迁移 0015 Owner |
| 036 | capacity-contract | ✅ 已实现并合入（PR #46） | CAP0；CapacityProfile 合同已交付，八项 launch 问卷仍待业务确认；不是迁移号 |
| 037 | weknora-revision-contract-spike | ✅ 已执行并合入（PR #40）；双合同 `insufficient` | W0；已触发 W1（038），只读 spike，不是迁移号 |
| 038 | w1-weknora-revision-manifest | 规格 ✅ 已合入（PR #41）；Go 实现 `NOT STARTED` | W0 触发的 W1；Go patch 预算内 |
| 039 | p3-api-worker-shell | 规格 ✅ 已合入（PR #48）；实现 `NOT STARTED` | 033 §16 P3；零迁移零表；实现依赖 P1 |
| 040 | g0a-golden-asset-kernel | 规格 ✅ 已合入（PR #42）；`SPEC-ONLY / IMPLEMENTATION NOT STARTED` | 编号冲突已关闭；后续实现须独立 TDD/复审，不得称 G0a 已验收或产品已完成 |
| 041+ | （空闲） | | 先占号再开目录 |

## Alembic 迁移编号台账（harness/migrations/versions/）

| 号 | 归属 change | 状态 |
|---|---|---|
| 0001 | 003 product_domain | ✅ |
| 0002 | 007 knowledge_domain | ✅ |
| 0003 | 016 enterprise_knowledge_scope | ✅ |
| 0004 | 017 source_evidence_lineage | ✅ |
| 0005 | 018 release_snapshot_read_model | ✅（PR #9 已合入） |
| 0006 | 021 source-lifecycle-ordering | ✅ 已随 PR #23 合入；实际 down_revision=0012 |
| 0007 | 旧 010 structured-import 计划 | superseded / not reusable（D-2026-07-27-10） |
| 0008 | 旧 009 concept-layer 计划 | superseded / not reusable（D-2026-07-27-10） |
| 0009 | 旧 012 qa-objects 计划 | superseded / not reusable（D-2026-07-27-10） |
| 0010 | 旧 011 knowledge-health 计划 | superseded / not reusable（D-2026-07-27-10） |
| 0011 | 旧 025 merge-weak-value-guard 计划 | superseded / not reusable（D-2026-07-27-10） |
| 0012 | 015 feedback-flywheel（flywheel_checkpoints + flywheel_observations + knowledge_gaps） | ✅ 已随 PR #18 合入；down_revision=0005 |
| 0013 | 旧 029 计划 | superseded / not reusable；D0 不预占替代 migration |
| 0014 | 旧 028 runtime 计划 | superseded / not reusable；D0 不预占替代 migration |
| 0015 | 035 p1-job-outbox 实现 | 由 PR #53 交付；`down_revision="0006"` 已按最新 main 的真实 alembic head 复核，实际链 `0005 → 0012 → 0006 → 0015`，单 head |
| 0016+ | （空闲） | 先占号再开 migration |

> **迁移号≠链拓扑**：上表编号只是占号防撞（文件名/revision id 用它），
> **down_revision 链序由实际合入 main 的先后决定**，与数字大小无关。规则：
> 每个实现 PR 在最新 main 重放后，把自己的 down_revision 指向**当时 main 的
> 实际 head**；不允许产生 multi-head；合入后在本表“备注”记录实际链序。
> 数字顺序仅为可读性，不承载任何拓扑语义。

## 当前可执行入口（2026-07-27）

当前生产架构工作只以以下入口为准：

- [OpenSpec 033](033-production-architecture-reset/)；
- [已批准生产架构设计](../../docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md)；
- [当前 active execution plan](../../docs/insurance-kb/22-parallel-execution-blueprint.md)；
- [实时状态与决策板](../../docs/insurance-kb/23-mvp-control-board.md)。

`D0/C0/CAP0` 已合入，W0 已以双 `insufficient` 触发 W1。当前 Milestone A
仍 `IN PROGRESS`，B/C `NOT IMPLEMENTED`；不得按 PR 数量推断 MVP 已上线。

开放 PR custody：

- 治理收口 PR #50/#51 与 OpenSpec 040 编号收口 PR #42 均已合入；#42 仅交付
  G0a 规格，实施尚未开始。
- 旧 PR #44 已 `CLOSED / ARCHIVED / NOT MERGED`，annotated tag 为
  `archive/pr44-p1-job-outbox-20260727-a6cdc9ae`，**零代码合入**。按
  D-2026-07-27-15（业务方裁决），其实现内容由 **PR #53** 在最新 main
  同内容重落地——**该裁决取代 #52 写入的"实现回到 `NOT STARTED`、不得
  恢复或重放 #44"条款**。理由：#44 的 19 条评审 findings（2 Critical /
  10 Important / 7 Minor）已在归档代码内 RED-first 闭环并沉淀为 16 个以
  finding 编号命名的测试节点；从零重做会重新踩同一批陷阱、延长而非缩短
  循环。#53 是同内容重落地，不是重新实现，这 16 个节点是其验收清单的
  强制项。
- 旧 PR #26/#28/#33 已关闭，仅保留历史审计价值。
- A2 已把 worktree 登记从 66 收敛到 23：21 个 clean 历史 worktree 非 force
  移除、22 个 prunable 记录归零、13 个 dirty/frozen worktree 保留；仓外
  证据根 `../.cleanup-evidence/2026-07-27` 的总校验 SHA-256 为
  `7ffe022567b56a0a6020ae9b7f42476e26824ec8be25ae0c39d2bbe1b32ce14c`。

## SUPERSEDED / HISTORY-ONLY — NOT EXECUTABLE · 旧并行开工基线（2026-07-21）

> [!WARNING]
> 分类：`superseded / history-only`；**NOT EXECUTABLE**。以下 027/028/029/030/031/032、NS-0、030 admission 与 HANDOFF MVP-0 路线仅作历史审计，
> 不授予当前实现、迁移、运行、提交或合入权限，不得据此开工或恢复旧分支。

- 北极星与 Integration-first MVP 已批准；总体规划窗口先补齐 027～030、032 的正式 proposal/specs/tasks 和实现 plans，再交独立执行会话；
- `NS-RIGHTS=recorded`：LLM-wiki-black 是项目方第一方资产，可按 provenance + OpenSpec 选择性迁移；第三方许可证另行清点；
- 027 未 verified 前，现有强 judge/fallback/未知模型与任何真实生产编译、merge、release 入口 fail closed；
- 030 MVP admission READY 后只允许运行其 23-entry 受控输入 slice；不修改也不借用 020 canonical BLOCKED 的授权状态；
- S/K/M/I 的文件域、串行 migration lane 和合入顺序见 22；实时状态只在 HANDOFF MVP-0 控制板维护；
- 025、完整 010/013/008、020 D2～D4、P-1、011/014/015 均后置；032 只做独立只读消费面，不得顺手扩成审核或生产 Wiki UI。
