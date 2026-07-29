# 24 · 存量资产处置清单

> [!IMPORTANT]
> **2026-07-29 Amendment 2 优先**：本文的逐包/逐迁移历史盘点继续有效，但
> P2b/P8/P11/P12、PostgreSQL serving pointer 与 Projector 的目标归属已被
> [Authority Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)
> 取代。旧 publisher、SnapshotReader、`current_release`、表和 migration
> 继续冻结审计；只按首个纵切真实调用改接，物理清理不是 MVP 前置。
>
> 状态：D0 治理文档。业务方 2026-07-26 批准架构评估后立项
> （裁决记录见 [23 · 控制板 §8 D-2026-07-26-3](23-mvp-control-board.md)）。
>
> 权威关系：本文从属于
> [033 生产架构重置设计](../superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md)
> §15（保留/改造/废弃）与 §16（所有权），把其概念级裁决落到**逐包、逐迁移、
> 逐 OpenSpec** 的唯一处置口径。每个 Pn 实现窗口的 Contract Card 必须引用
> 本文对应行，声明本 PR 取代哪些旧表/旧模块及切换方式；不得在实现窗口内
> 临场重新裁决。本文与 033 冲突时以 033 为准并先修订本文。
>
> 盘点基线：`origin/main = 8a755fdc`（2026-07-26）；harness 源码约 5.4 万行、
> 测试约 8.6 万行；Alembic 链 `0001→0002→0003→0004→0005→0012→0006`。

## 1. 处置分类定义

| 分类 | 含义 | 约束 |
|---|---|---|
| **复用** | 继续作为新路线的活权威，由其在 §16 中的唯一 Owner PR 演进 | 演进只能发生在该 Owner 窗口内 |
| **移植** | 概念/代码经 provenance 记录进入指定 Pn；完成后旧模块转冻结 | 移植 PR 必须记录 source commit/path 与接受/拒绝的旧行为 |
| **冻结审计** | 留在仓库作审计与测试素材；不再获得新功能，不构成实现授权 | 引用其行为需经新 OpenSpec 重新验收 |
| **废弃** | 明确不进入新路线 | 删除只走后续显式清理 PR，不夹带在功能 PR 内 |

"拆分"表示同一包内不同模块分属不同分类，逐行注明。

## 2. 逐包处置表（harness/src/insurance_harness/）

| 包 | 来源 change | 行数 | 新路线对应 | 处置 | 条件/备注 |
|---|---|---|---|---|---|
| `adapters` | 001/016/023 | 2182 | P4a/P4c 的 WeKnora REST 边界 | **复用** | 唯一允许知道 WeKnora REST 形状的边界，符合"只走版本化 REST"；新增合同（attempt/manifest）按 W0/W1 结论重验；`admin_client` 仅限 provisioning/live 用途 |
| `sources` | 017/021 | 1164 | P4a/P4c | **移植** | 全 DB-free DTO 与五阶段物化；双读/完整性逻辑必须按 W0/W1 的 authoritative manifest 合同重验后进入 P4c，当前实现不构成"绝不混版"证明（033 §4.4） |
| `product` | 003 | 1054 | P5a0 实体解析 adapter 的直接基础 | **复用** | 033 §8.2 明文复用；`source="auto"` alias 不自动获得权威资格，P5a0 按冻结生成规则重验后才入 allowlist |
| `db` | 003/016 | 687 | P3/P2d 基础 | **复用** | `base/scope` 继续作 Harness DB 层；`knowledge_spaces` 的 binding/ACL 演进唯一归 P2d（KnowledgeSpaceBinding + ACL digest） |
| `schemas` | 002/024 | 370 | P5a1 SchemaVersion Registry | **冻结为内容种子** | YAML 基线数据（07 号 + v1.1 扩展）继续有效；但该 loader 无 content hash/不可变性/版本域，正式 registry 由 P5a1 按 033 §8 重建 |
| `knowledge` | 007/016/017/018/019/021 | 10370 | P2a/P5a2/P2b/P7/P8（表域）、P4a（021 段） | **冻结审计 + 定向移植** | 见 §3 表权威切换。定向移植：`source_lifecycle/source_keys/source_aggregates`（021 段）→ P4a；033 §15.1 明文保留的对抗测试场景随各 Pn 移植并记 source path。可变 Claim 状态、ReviewItem 人工批准表、`current_release` 指针、018 逐页补偿 saga 均按 §15.2/§15.3 被取代或废弃 |
| `goldenset` | 002/005/019/020 | 15995 | G0a evaluator / P2c approval registry | **拆分** | `eval/profile/baseline/assemble/validate/keypoints`（019 内容寻址 artifact、approval、fingerprint、回归比较）作为 **G0a 种子移植**——033 §14.1 明文"种子资产，非已批准 G0 baseline"；`admission_*`/`run_020`/`execution_artifacts_020`（020/031 式审批与预算机械）**冻结审计**；`wip-gs-v0.1` 数据 = 标注种子 |
| `run_admission` | 030 | 1408 | 审批模型由 P2c/P7（ReviewPolicy + QualityProfileApproval + AutomationScope）取代 | **冻结审计** | 完全隔离包（仅依赖 model_policy），无下游耦合，冻结无风险 |
| `model_policy` | 027 | 3754 | P2d CompilationSecurityProfile | **复用至 P2d 接管，后转移植** | 现行弱模型白名单/强模型签名拒绝/部署名语法/provider 硬门（百炼）是过渡期唯一模型执法，继续有效；P2d 合同冻结后，其执法内核按 provenance 移植为 P2d 的版本化 adapter，硬编码 provider 改为版本化 profile 配置 |
| `compiler` | 004/005/006/017/024/027 | 7033 | P5b1（抽取）、P6a（模板） | **拆分** | 叶子能力可按 provenance 移植：`cleaning/sections/routing_data/parsing/templates`（tables 提取、fastpath 判定逻辑）；**废弃**：LangGraph 管线编排（§12 固定 Job Store 取代）、`judge.py` claude-session 强模型队列（ADR-002 禁止）、`attempts.py` SQLite ledger（§15.3 同类）；`variants/experiment` 冻结审计 |
| `runtime` | 028b + S1 | 2221 | C0（digest 实践输入）、§12 Job Store、P6b | **冻结审计** | 零生产消费者。`compilation_manifest` 的 canonical digest/重复键拒绝/路径安全实践是 C0 与 P6b 的直接参考输入（033 §15.1"manifest canonical digest 思想"）；immutable DTO 模式可参考。注意与 `sources.MaterializedBatch` 同名不同物 |
| `template_packages` | 028a | 969 | P6a WikiTemplateVersion | **复用/收窄**（033 §8 明文） | 内容寻址 TemplateVersion + 4 级 overlay resolver 保留为 P6a 基础；**必须对账**：其自有 domain separator（`insurancekb.template-package.content.v1`）与 C0 CanonicalEnvelopeV1 的 `hash_schema_version` 关系由 C0/P6a 合同裁决，不得两套并行长期共存 |
| `workbench` | 008 | 1481 | P13 Evidence + Review UX | **冻结审计** | 零表所有权、读 0002 表（将被取代）；其 auth 模式（Bearer+签名会话、双提交 CSRF、fail-closed 零回显）作 P13 设计参考；"Release 级一键批量审核"交互与 033 §9.5 一致，可参考不可复用代码路径 |
| `flywheel` | 015 | 1354 | Milestone C 后按新 Query/Release 模型回归 | **冻结保留** | 表（0012 三表）保留只读；F1.1b Langfuse 直连、F2.4 ReviewItem 投影维持 gated 不变；不在新关键路径上 |
| `live_env` | 023 | 3536 | W0 试验台 + 开发期"细线程"集成信号 | **复用** | 非生产运行时。W0 spike 直接在此环境运行；每个 P 阶段合入后跑非门禁 smoke（23 号 §8 D-4 配套） |
| `structured_import` | 010 | 578 | 通道一：产品登记 bootstrap；通道二：`trusted_import` + ExternalAttestation（P2a/P7）取代 | **拆分** | 通道一（meta bootstrap，零 Claim，经 003 registry 写入）**复用**；通道二合同（registry/mapping/transformers 版本权威）**冻结审计**——新路线的可信导入必须绑定不可变 ExternalAttestation，调用方自报 trusted 无效 |
| `mcp` | 013 | 4 | P9b Thin MCP Adapter | **废弃** | 4 行占位空包，013 从未实现；无可移植物 |

依赖方向备注（防止移植顺序踩空）：`knowledge → goldenset`（quality_gate 消费
QualityProfile/ApprovalRecord）、`knowledge → compiler`（`snapshots.py`/`pages.py`
引 `routing_data`，`importer.py` 引 `compiler.models`）、
`knowledge → adapters/sources/schemas`、`flywheel → knowledge`（只读 Claim）、
`flywheel → goldenset/product`、`compiler → model_policy/sources/goldenset`、
`compiler → adapters/db`、`run_admission → model_policy`。
冻结 `knowledge` 前，须先解除 `flywheel`/`workbench` 对它的读依赖或将二者一并
冻结（当前即是：二者均冻结/保留，无新增消费）。冻结审计的 `knowledge` 自身
依赖“拆分”处置的 `compiler`（含废弃件），因此 compiler 的移植/清理 PR 必须把
`routing_data`/`models` 保留或先行移植为独立模块，不得在 knowledge 冻结解除前
删除其被 knowledge 引用的部分。

## 3. 迁移与表权威切换

现链：`0001 → 0002 → 0003 → 0004 → 0005 → 0012 → 0006`，head = `0006`
（文件编号非单调；新路线迁移一律从**真实 head** 续接，禁止复用旧占号——
与 22 号蓝图 §4 一致）。

| 迁移 | 表 | 处置 |
|---|---|---|
| `0001`（003） | 5 张产品主数据表 | **保留权威**：P5a0 复用，仅加 adapter/receipt；若 P5a0 需新表由其唯一 migration 独占 |
| `0002`（007） | `claims/claim_evidence/claim_revisions/change_sets/change_items/conflicts/review_items/release_snapshots/snapshot_claims/current_release` | **被取代**：P2a（Evidence/Provenance）、P5a2（root+revision）、P5b2（ConflictSet）、P2b（WikiRelease + active pointer）、P7（ReviewDecision）分别接管对应概念；新路线不写这些表 |
| `0003`（016） | `knowledge_spaces` | **保留**；binding/ACL 演进唯一归 P2d |
| `0004`（017） | 无新表（`claim_evidence` 加 lineage 列） | 随 0002 一并由 P2a EvidenceAnchor 合同取代 |
| `0005`（018） | `snapshot_facts/release_operations/publish_attempts/reconciliation_jobs` | **被取代**：P2b/P8 接管 Release 权威与激活；018 逐页补偿 saga 按 033 §15.3 废弃 |
| `0012`（015） | 3 张 flywheel 表 | **冻结保留**（只读），随 flywheel 包处置 |
| `0006`（021） | `source_heads/source_events/source_lifecycle_backfill_issues` | **合同保留、实现重验**：去重/排序/不猜 head 语义按 033 §15.1 保留；P4a 按 W0/W1 结论决定接管现表或以其唯一 migration 重建（内部事件身份须扩展 `lifecycle_kind` 等 033 §4.3 字段） |

**切换规则（无双权威窗口原则）**：

1. 任何时刻，每个领域概念只有一个写权威表集。Pn 合入即接管其概念；旧表
   立即停写。当前无生产流量，切换天然无停机问题，但规则仍须写进各 Pn 的
   Contract Card；
2. Contract Card 必须声明：取代哪些旧表/旧模块、读路径切换方式、旧数据是否
   导入。**默认不导入**；确需导入历史数据时按 033 §15.3 使用绑定 legacy
   commit 与 importer version 的单向幂等工具，闭包不完整进 quarantine；
3. 旧表的物理删除只走后续显式清理迁移 PR，功能 PR 不得夹带 drop；
4. 033 §15.1 保留的对抗测试场景（跨 Space、乱序、重复、stale CAS、tamper、
   takeover）在移植到新表结构时逐条记录 source path，不得静默丢场景。

## 4. 旧 OpenSpec 处置表

| Change | 实施状态（2026-07-26） | 处置 |
|---|---|---|
| 001 scaffold / 002 goldenset-s0 / 003 product | 完成 | 复用（003 是 P5a0 基础；002 数据为 G0a 种子） |
| 004 compiler / 005 eval / 006 templates | 完成（旧规格口径） | 历史审计；叶子能力经 §2 按 provenance 移植 |
| 007 claims mainchain | 完成 | 被 P2a/P5a2/P2b/P7 取代（§3） |
| 008 workbench | 核心合入 | 冻结审计；P13 取代其职责 |
| 009 concept / 011 health / 012 QA / 014 batch / 026 data_quality | 规格占号，未实现 | **撤销占号**；需求经新路线重新立项（014 由 §12 Job Store + P4b 取代；011 观测并入 §12/§17 指标） |
| 010 structured-import | T1–T4 合入 | 拆分：通道一复用；通道二由 trusted_import + ExternalAttestation 取代 |
| 013 insurance-mcp | 未实现 | 废弃；P9b 取代 |
| 015 flywheel | durable foundation 合入 | 冻结保留，其余维持 gated |
| 016 scope / 017 bridge / 021 ordering | 完成 | 016 复用（P2d 演进）；017/021 移植进 P4a/P4c（W0/W1 重验） |
| 018 release snapshot | 合入 | 概念保留（不可变 snapshot、固定读、回滚不调模型）；逐页 saga 废弃 |
| 019 quality gate | 完成 | 内容寻址 artifact/approval/fingerprint 思想与工具移植 G0a/P2c |
| 020 baseline run | T1 合入，canonical BLOCKED | 冻结为企业阶段资产；不阻塞新路线 |
| 022 ×2（测试组合/复审硬化） | 完成 | 复用（三 lane、JUnit 反伪绿等 CI 基础设施继续有效） |
| 023 live env | 完成 | 复用（W0 试验台 + 细线程） |
| 024 recall uplift | 合入，效果未证 | 叶子能力可移植 P5b1；不得把旧"完成"当召回证据 |
| 025 weak value guard | 规格合入，未实现 | 撤销占号；需求在 P5b1/P7 合同内重新评估 |
| 027 weak model boundary | 完成 | 复用至 P2d 接管（§2 model_policy 行） |
| 028a/028b + S1 | 合入，零消费者 | 028a 由 P6a 复用/收窄；028b/S1 冻结审计（C0/P6b 参考输入） |
| 029 release approval / 031 operational admission | 029 部分合入；031 无独立目录 | 按 033 §15.3 **废弃**（filesystem sealing、CLI ceremony、硬编码人工终审、SQLite/PTU/Ed25519 控制器） |
| 030 mvp slice | run admission 段合入 | 冻结审计；MVP 语义由 033 Milestone A/B/C 取代 |
| 032 human wiki reader | 规格合入 | 撤销占号；人类读取由 P9a + P13（及 P-1 取代物 P11/P12）承接 |
| 033 reset | D0 进行中 | 当前权威 |

## 5. 执行规则

1. **Contract Card 引用义务**（23 号 §8 D-3）：每个 Pn 实现 PR 开工前引用
   本文对应行；发现本文与实际代码不符时，先以小 PR 修订本文再开工。
2. **移植 provenance**：迁移 PR 记录 source commit/path、接受与拒绝的旧行为
   清单；第三方许可证边界不变（第一方声明不覆盖第三方实现）。
3. **禁止反推授权**：不得从旧分支、旧 worktree 或本表"复用/移植"字样反推
   实现授权；实现授权只来自 23 号控制板当前放行状态 + 对应 OpenSpec。
4. **删除纪律**：废弃项的物理删除（含 `mcp` 空包、旧表 drop）集中到独立
   清理 PR，逐项列出并过文档门禁；功能 PR 不夹带删除。
5. **本文维护**：每个 Pn 合入后，把受影响行的处置状态从"计划"补记为
   "已接管/已冻结"，与 HANDOFF 收尾更新同步进行。
