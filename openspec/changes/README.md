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
| 008 | review-workbench | ✅ T1～T5/T7 已合入（PR #15）；W4/T6 follow-up 可认领 | 轨道 L2；018✅ 已解除整页/回滚前置；Owner 复审=A |
| 009 | concept-layer | 📋 规格已收口，**待 010 T5～T12 合入后认领** | 轨道 L4 第二件；021✅仅解除 010 ordering 前置；C3.4 混源防护；(space_id,canonical_key) 身份 + concept_revisions 定义版本化 + C6 冻结投影扩展合同；迁移 0008 |
| 010 | structured-import | 🚧 T1～T4 已合入（PR #14）；**T5～T12 已由 021✅解除前置，可从最新 main 认领** | 轨道 L4 首件；双通道（Q020 合规）+ structured 证据全消费链：快照 v2 判别联合、batch_fingerprint、mapping_manifest 四元组、双轴幂等；迁移预分配 0007；knowledge 域 Owner-A 复审 |
| 011 | knowledge-health | 📋 PR #12 主规格 + PR #22 fast-follow 已收口，**011 本体可认领** | H1.3a 远端/输入/工具链独立证据轴、多信号并报、不可归因 degraded；H1.8 通过 020 registry 消费 024 attempt ledger，缺数据 degraded；迁移 0010；typed subject 接线 Owner-A |
| 012 | qa-objects | 📋 规格已收口，**待 010 T5～T12 的 qa_staging/冻结合同合入后认领** | qa_items/qa_revisions/qa_assertions/bindings 断言级绑定（复合 FK 闭 Space）+ 冻结事务内重验 + Q5 冻结投影扩展（SnapshotQA）；迁移 0009 |
| 013 | insurance-mcp | 📋 规格就绪，可认领 | 轨道 L3；HTTP Streamable 主传输；018/PR #9 前置已满足 |
| 014 | batch-orchestration | 📋 提案 | M3，暂不排 |
| 015 | feedback-flywheel | ✅ 已合入 main（PR #18） | 离线 trace→durable 飞轮；迁移 0012（三表单事务/Space 隔离）；Langfuse 直连与 ReviewItem 动作投影保持 gated |
| 016 | enterprise-knowledge-scope | ✅ 已交付 | |
| 017 | weknora-source-bridge | ✅ 软件交付；live NOT RUN | |
| 018 | release-snapshot-read-model | ✅ 已合入 main（PR #9，2026-07-17） | 独占迁移 0005 |
| 019 | golden-quality-gate | ✅ 已合入 main（PR #8） | |
| 020 | golden-v01-baseline-run | 🚧 T1 零模型 run-admission 在 PR #24；真实 D2～D4 未运行 | 019✅+021✅；未 READY 前禁止真实模型调用 |
| 021 | source-lifecycle-ordering | ✅ 已合入 main（PR #23） | 迁移 0006，实际链 `0012 → 0006`；deterministic 1901，PG 25/skipped=0 |
| 022 | review-hardening | ✅ 已交付 | ⚠️ 编号冲突历史记录：与下行同号，两者均已合入，**目录不改名**，冲突就此冻结 |
| 022 | test-portfolio-rebalance | ✅ 已交付 | 同上 |
| 023 | local-weknora-live-environment | ✅ 已合入 main（PR #10） | 受信 live workflow |
| 024 | extraction-recall-uplift | ✅ 已合入 main（PR #13） | 轨道 L5；durable attempt ledger + E1～E7 + A10 双侧护栏；真实召回/非退化证据仍由 020 D4/D4b 承接 |
| 025 | merge-weak-value-guard | 📋 规格已合入（PR #17），021✅ 后实现前置已满足，可认领 | 合并前置弱值门槛：抑制=有资格前提的裁决 + SpecificityRelation + root/events 可恢复生命周期；G1～G9 strict；迁移 0011 |
| 026 | claim-data-quality-persistence | 🔒 已占号（目录未开） | `data_quality` 的 Claim/Revision/Snapshot/MCP 端到端字段+迁移+回填（12 号文档 #2 采纳项至今只在 pred 侧，主链未落——PR #11 四轮对账发现）；业务确需时立项，010/013 不预支承诺 |
| 031 | operational-run-admission | 🚧 设计复核修订中 | 解除 020 真实准入阻塞；两套最小 PTU 已由 operator 创建并验证身份，仍须预算/审批治理后才可 READY |
| 027-030、032+ | （空闲） | | 先占号再开目录 |

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
| 0013+ | （空闲；014 如需建表先来占号） | |

> **迁移号≠链拓扑**：上表编号只是占号防撞（文件名/revision id 用它），**down_revision 链序由实际合入 main 的先后决定**，与数字大小无关。规则：每个实现 PR 合入时把自己的 down_revision 指向**当时 main 的实际 head**（先合的 0007 可以在 0006 之前入链）；不允许产生 multi-head；合入后在本表"备注"记录实际链序。数字顺序仅为可读性，不承载任何拓扑语义。

## 并行开工基线（2026-07-16 裁决，三轮复审修订）

- 规格/文档工作：一律以当前 `main` 为基，**不等 PR #9**；
- 实现工作：不触碰 `knowledge/` 的部分（008 的 W1–W3、**010 T1~T4（通道一/登记/映射）**、024）即刻可从 `main` 开工；
- 触碰读模型/回滚/发布语义的部分（013 实现、008 W4、021 全部）在 **PR #9 合入后**从新 main 开工；
- **010 的 knowledge 域段（T5 起，structured 证据全消费链+冻结合同）基于 021 合入后的 main**——关键路径 018→021→020 不因新功能插队而改变；
- 总蓝图与轨道分工见 `docs/insurance-kb/22-parallel-execution-blueprint.md`，实时状态以 `HANDOFF.md` ⓪ 为准。
