# HANDOFF — 交接文档

> 写给完全没有上下文的新会话/新成员。任何变更请持续更新本文。
> 最后更新：2026-07-14（PR #6 已合入 `main`，merge commit `27c36641`；业务方最新排期裁决：合并后收尾优先，随后 018/019 可独立或并行，021 等 018，020 等 019+021）

## ⓪ 当前最优先事项（接手先看这里）

0. **基础建设已合入 main（PR #1，2026-07-13）**：此后一律按 17 号规范从 main 切 `feat/NNN-*` 分支，PR 双查 + **CI 绿才算绿**（坑 9a）。上游 workflow "Build and Push Docker Image" 已在 GitHub 界面手动禁用（fork 无腾讯 registry 凭据必失败，属继承性噪音）；其余上游 workflow 有路径/标签过滤暂无干扰，误触发照此禁用，不影响版本列车跟版。

0a. **016 企业 KnowledgeSpace 与 017 SourceDocument Bridge 软件实施已收尾**：总设计见 `docs/insurance-kb/20-enterprise-runtime-foundation.md`，分支 `codex/016-enterprise-foundation`。017 T1～T8 已按 TDD 完成，最终规格复审 `Spec compliant: yes`、质量复审 `Quality approved: yes`，无剩余 finding；主代理 T8 non-live **12 passed / 1 deselected**、source standalone **49 passed**、最终全量 non-live **915 passed / 5 deselected**，Ruff、mypy 139 files 与 diff check 全绿。T8 live gate 已实现真实 `wait_for_parsed → bridge → deterministic Compiler → pred/import → Evidence backlink`，但六项 live 变量与本机 WeKnora/PostgreSQL 实例均缺失，运行结果明确为 **NOT RUN：1 skipped / 12 deselected**；当前 adapter 无 uploader，因此 existing-knowledge 分支也不代表 upload 创建覆盖。**重要边界：T7 仅保证同 revision 幂等，不保证不同 revision 并发/乱序；021 仍仅 proposed/pending。在 021 落地前只允许同一 Space/source 串行 lifecycle。018/019/020/021 均未随 017 自动完成，本轮未启动下一事项。**

0b. **Space 部署注意**：从 0001/0002 升级且已有业务行时，0003 会创建并回填 unbound `legacy-default`。在任何产品注册、路由、Source Bridge 或发布任务前，管理员必须按 `docs/insurance-kb/14-deployment-runbook.md` §3.1 执行 `python -m insurance_harness.db.scope_cli bind legacy-default --tenant-id ... --raw-kb-id ... --wiki-kb-id ... --db-url ...`；未绑定时运行时按设计 fail closed。新装空库不创建该 Space，当前也没有 create CLI，必须先走受控管理员 provisioning 创建 bound Space；幂等初始化脚本仍由 B10 承接。

0c. **PR #4 复审收口**：已修复空库 0003→0002 downgrade 被错误拒绝，以及 `SourceChunk` 默认 metadata 未深度冻结；migration/source focused `69 passed`，全库 non-live `916 passed / 5 deselected`，Ruff、mypy 139 files、diff check 全绿。其余评论中 revision 含 `processed_at`、numeric WeKnora identity 与新 revision recompile 均为 017 明文规格；rollback 外部写补偿仍按既有边界归 018。

0d. **OpenSpec 022 测试组合再平衡（P0～P3）完成并随 PR #5 合入 `main`**：修复 `test_live.py` 提前 close/dispose 导致 scope Engine attestation 在用例前失效；pytest 拆为 deterministic / `integration_postgres` / WeKnora `live` 三条互斥 lane，PR 新增 PostgreSQL 16 service job，受控 `harness-live` 手工 workflow 冻结七变量且用 JUnit 拒绝 tests=0 或 skipped≠0 的伪绿；含 secrets 的 workflow actions 与 uv 均固定不可变版本，publisher live 页面在任何失败路径均尝试删除且不覆盖主异常。bridge 已拆为 12 contract + 1 live；pipeline 88 与 revision 51 个规范化 identity/marker 全保留，最大测试文件 739 行。coverage-context audit 已用真实 scope suite 产物验证（208 passed；193 contexts / 1946 production lines / 999 advisory candidates at 0.8），候选不自动删测。本地最终 deterministic `933/938 collected`、exit 0，Ruff 全绿、mypy 151 files 全绿。`integration verified` 已由 commit `ed46df78fb975c5ef7963e49dd1e208dba31fdaa` 的 [PostgreSQL 16.14 job](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29312423361/job/87018894440) 证明：`1 passed / 937 deselected`、JUnit `tests=1 skipped=0`，run 于 2026-07-14T06:47:21Z～06:49:53Z 成功；WeKnora `live verified` 无受控 workflow 证据，继续 **NOT RUN**。

0e. **OpenSpec `022-review-hardening` 已随 [PR #5](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/5) 合入 `main`**：六项 Claude 复审意见已客观裁决并按 SDD/TDD 实现；RH1～RH6 task-level 双审均 Approved，整包 spec review `Approved`，整包 quality 的唯一 Important（持久化 `proposed=[]` 泄漏 `AttributeError`）已补 RED、在 RH2 边界统一为无泄漏 `ScopeViolation` 后复审 `Approved`，无剩余 Critical/Important/Minor。最终 fresh 本地证据：OpenSpec strict exit 0、Ruff exit 0、mypy 151 files exit 0、deterministic **961 passed / 5 deselected**；focused 为 RH1 `43 passed / 1 skipped`、RH2 `62 passed`、RH3 `136 passed`、RH4 `110 passed`、RH5/RH6 `15 passed`，bridge collection 仍为 contract 12 / live 1。PR 最终 head `7a924254` 的 [deterministic](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326433014/job/87063741905) 与 [PostgreSQL 16 integration](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326433014/job/87063741858) 均通过，merge commit 为 `2615b260`。WeKnora 继续 **`NOT RUN`**；PostgreSQL CI 不得替代真实 live。RH1 只保证函数内 savepoint，outer transaction/进程终止/多页补偿仍归 018；RH2 不含 ordering/`processed_at`/SourceHead/CAS，仍归 021；Directory replay 保持 eval-only；live 是 existing-knowledge 而非 upload。

0f. **当前排期与依赖（业务方 2026-07-14 最新裁决）**：先完成合并后收尾；随后 018 与 019 是无相互前置的两条工作轨，可独立或并行推进，019 作为解锁真实基线的工具轨，价值优先级不低于 018。技术硬依赖只有 **018 → 021、019 → 020、021 → 020**；不得把 018 → 019 写成技术依赖。各 change 仍分别遵守 SDD（先条款与裁决）、TDD（测试名引用条目号）、task-level spec/quality 双审及 CLAUDE 门禁。

   **阶段 1 — 合并后收尾（当前）**
   - [x] PR #5、#6 已合并，最新 `origin/main` 已确认指向 `27c36641`；新基线 Ruff、mypy strict、deterministic **961 passed / 5 deselected**。
   - [ ] 修正文档陈旧口径：`docs/insurance-kb/README.md` 的 017 T1～T6、`docs/insurance-kb/20-enterprise-runtime-foundation.md` 的 PostgreSQL integration / WeKnora live 边界、`harness/README.md` 的 deterministic marker。
   - [x] 对账排期与依赖：`docs/insurance-kb/16-roadmap.md`、`docs/insurance-kb/20-enterprise-runtime-foundation.md` 与本节统一为 018/019 可独立或并行、018 → 021、019+021 → 020；详细 checkbox 只保留在 HANDOFF，避免双份清单漂移。
   - [ ] 对账旧 ledger：001/003/004 的未勾项只做完成证据回填，不重做已验收功能；002 仅对账已完成项，真实未完成的 T8/T9 明确保留并转交 020；消除“18 条扩展字段待确认”与“已全部接受”的冲突。
   - [ ] 归档已完成的 016、017、022-test-portfolio-rebalance、022-review-hardening，并运行 OpenSpec strict / 文档链接与状态检查。

   **并行轨 A — 018 ReleaseSnapshot 统一读模型与可恢复发布（0/7）**
   - [ ] 按 `openspec/changes/018-release-snapshot-read-model/` 顺序完成 T1～T7；018 独占 Alembic `0005`。
   - [ ] 交付 immutable SnapshotFact、统一 SnapshotReader、Wiki snapshot render、PublishAttempt 状态机、补偿/reconciliation、curated-first/raw fallback。
   - [ ] 验收 publish V1 → V2 → rollback V1 后 Wiki/MCP/Agent 的事实与 Evidence 一致；多页失败不移动 current pointer，补偿可重放。无真实环境时 live 必须记 `NOT RUN`，不得伪绿。

   **并行轨 B — 019 Golden 工具、QualityProfile 与在线 Gate（0/6）**
   - [ ] 按 `openspec/changes/019-golden-quality-gate/` 顺序完成 T1～T6，先交付 portable assembler/validator，再交付 artifact approval、QualityProfile 与统一 QualityGate。
   - [ ] 本轨不依赖 018，可独立或与 018 并行；只做工具、fixture/replay 与门禁，不改写真实 11/13 现场、不调用大模型，为 020 提供稳定 artifact 工具与合同。`run-admission` 属于 020 T1，只能在 019、021 均完成后由 020 自己执行。

   **收敛轨 — 021 Source lifecycle ordering（0/10，硬依赖 018）**
   - [ ] 先完成 source ordering/delete/reactivation 状态机规格审查，再按 `openspec/changes/021-source-lifecycle-ordering/` T1～T10 TDD 实施。
   - [ ] 迁移编号排在 018 的 `0005` 之后；交付 SourceHead/SourceEvent、`processed_at/generation`、per-source lock/CAS、delete/import/notify 竞争处理与 PostgreSQL 双会话证据。
   - [ ] 在真实 PostgreSQL 逆序/并发/删除竞争用例通过前，不得宣称 ordering 安全。

   **价值出口 — 020 真实金标/baseline 运行（硬依赖 019+021）**：019 提供 artifact 工具/合同，021 关闭 source ordering 风险；两者完成后，020 才从 T1 `run-admission` 开始，未准入前零模型调用。B10 WeKnora 测试实例/真实 live 环境可由独立负责人并行准备，但不得与代码轨共享分支，也不得用 PostgreSQL integration 冒充 WeKnora live。

1. **T8 金标标注仍剩 2 个产品，但执行入口已统一**：现有 11 份保持不重做；019 先交付可移植 assembler/validator、QualityProfile 与在线 Gate，020 再按 run-admission 固定精确模型/预算/断点后完成 2 产品、13 产品 baseline、judge/dead-letter/keypoints。原 T8 现场仍见 `openspec/changes/002-goldenset-s0/T8-HANDOVER.md`，新的统一运行合同见 `openspec/changes/020-golden-v01-baseline-run/`。
2. ✅ **change 003 已完成并验收**（2026-07-12）：产品主数据/别名/版本/文档登记（幂等）+ 文档分类器 + 章节级产品路由 + unassigned 池 + CLI。验收：39 PDF 分类 100%、exact 路由 100%、零 LLM 调用（validation-report.md）；门禁 89 passed 全绿。别名剥后缀的歧义教训见 003/tasks.md 裁决记录。
3. ✅ **change 004（抽取管道 MVP）完成并验收**（2026-07-12）：compiler/ 全链路（切分→7组路由→分批抽取→回验→清洗→补漏→投票→置信分级），langgraph 可恢复编排+死信；门禁 135 tests 全绿。**首个真实弱模型基线**（deepseek-v4-flash vs gs-v0.1，3 代表产品，含 Claude 裁决回写）：micro F1 0.184 / 幻觉率 8.2% / **evidence 准确率 100%** / high 桶三态正确率 92%——反幻觉链已验证有效，失分主因是长文本字段的"值粒度/表述差异"被 eval 逐字等价误判 + present→unknown 漏抽 25 条（validation-report.md 有全量明细）。
3a. ✅ **change 007（Claim 落库/增量合并/审核门禁/WeKnora 发布，S2→S3 主链）完成**（2026-07-12）：
   `harness/src/insurance_harness/knowledge/` 新包 + Alembic 0002（claims/claim_evidence/claim_revisions/
   change_sets/change_items/conflicts/review_items/release_snapshots/snapshot_claims/current_release）。
   pred JSONL 导入器（记录级+批级幂等）、五种 ChangeItem 合并引擎（裁决序严格 03 §6.2，④=claude-session
   judge-queue 占位零模型调用）、ReviewItem 稳定 ID + approve/reject/defer、页面编译（分组渲染+证据角标）、
   发布器（03 §7 契约，respx 全 mock）+ 快照回滚。端到端两批材料故事（说明书→条款）验收通过；
   门禁 192 passed 全绿。live 发布契约用例（-m live）待测试实例。文档 03 已同步修订
   （pending_judge/schema_version 串/source_kind/rendered_pages 物化/④队列化）。
3b. ✅ **change 005（评测尺子升级与召回归因）完成**（2026-07-12，零真实模型调用）：
   ① eval v2 "关键要点匹配"（`--metric v1|v2` 可切换；金标旁挂 keypoints.jsonl，3 基线产品 59 条
   rule-split 小样已入库，全量强模型要点列 B6）——3 产品离线重评 micro F1 **0.184(v1) → 0.216(v2)**，
   long 字段逐字等价误判被修正、真实缺口（值粒度 54 条）凸显；② 报告五类错误归因
   （值粒度/漏抽/幻觉/三态混淆/证据错位）+ 工单化明细；③ eval-judge-queue 落盘（默认关，格式对齐
   compiler JudgeRequest/Judgement）；④ 漏抽归因工具 `compiler/recall_attribution.py`（纯确定性）：
   26 条漏抽 = routing_miss 3 / extract_empty 23 / cleaning_kill 0；⑤ 零成本路由修复
   `GROUP_KEYWORD_SUPPLEMENTS_005`（趸交/费率表→basic_info；入出院记录/出院小结/结算清单→claim_service），
   routing_miss 3→1、13 条款压缩比仍 ≤0.40；清洗白名单经证据判定不需要改（cleaning_kill=0）。
   报告：`openspec/changes/005-eval-refinement-recall/validation-report.md`（004 报告已附"尺子修正后"章节）。
3c. ✅ **change 006（模板抽取 fast path 与表格结构识别）完成并验收**（2026-07-12，零真实模型调用）：
   `harness/compiler/templates/` 新包——模板 schema（YAML 数据，注册表机制对齐 schemas，发布目录
   `dataset/templates/`）+ **确定性模板归纳器**（族内 ≥2 产品金标挖锚点：表格列名/引文上下文正则，
   全产品回放验证 hit_rate=1.0 才发布；LLM 润色留 claude-session 队列 stub）+ 运行时 fast path
   （族命中 → 锚点直取 → 既有校验链，未命中降级通用管道；命中字段退出通用抽取/补漏/投票）+
   `TableStructureProvider` Protocol（pdfplumber 首实现，费率表数字走列定位直取 12 #1；
   PP-StructureV3 留接口+配置位 `HARNESS_TABLE_PROVIDER`）+ 可喂性评分（12 #4，manifest 记录+
   隔离区目录，CLI 默认 dry-run）+ pred 增加 `data_quality`（12 #2，007 Claim 端衔接）。
   **修复 004 族指纹疑点**：无标题文档（说明书/费率表）曾全部退化为空串指纹 fam-e3b0c44298fc，
   现走 fallback（文档类型+页数桶+表头 token），有标题文档指纹零漂移。**留出验证**（盛世金越族，
   两分红产品归纳 → 尊享26终身寿留出）：fast path 命中字段正确率 1.00 vs 通用管道 0.00
   （交费期限 unknown→列直取全对），预估节省 1 次调用/产品（锚定字段尚少；随模板铺开增长）；
   发现分红说明书两版式不同构（归纳报告与 validation-report.md 有全量明细）。门禁 239 passed 全绿。
4. **非当前主线 backlog**：抽取召回主战场是 extract_empty 24 条（prompt 变体/补漏增强，见 005 归因清单），不得抢占 ⓪-0f 的执行顺序；模型配置：harness/.env（不入库）——弱模型 deepseek-v4-flash、裁决 claude-session 模式（judge-queue → apply-judgements CLI，本轮已实跑 3 条闭环）、兜底 deepseek-v4-pro。
5. **分工定位（2026-07-12 业务方定）**：本会话（Claude）负责**整体架构、代码设计、功能规划、技术方案**（产出设计文档与 OpenSpec change 提案）；**大批量 token 消耗的执行任务一律进下方遗留清单，交由其他模型/会话推进**。

**协作与排期**：三人分工与协作规范见 `docs/insurance-kb/17-team-collaboration.md`（模块所有权/PR 双查/认领制）；当前排期以 ⓪-0f 为准：先收尾，018/019 可独立或并行，021 等 018，020 等 019+021。认领 B 项请在下表加“认领人”并保持更新；B10 环境准备可独立并行。

## ⓪-B 遗留执行任务清单（按 17 号文档认领制推进，按优先级）

| # | 任务 | 怎么做 | 预估成本 |
|---|---|---|---|
| B1 | 金标 T8 收尾：剩 2 产品标注 + gs-v0.1 打包 | 并入 **020 D2**；先完成 run-admission，再按 T8-HANDOVER 原地接续 | ~2×10万 token（标注模型） |
| B2 | 全量 13 产品弱模型基线 | 并入 **020 D3**；必须消费 019 artifact/validator，断点运行 | 网关 ~6-12万 token/产品 |
| B3 | B2 产生的 judge-queue 批处理 | 并入 **020 D3**；回写后重新出分，unresolved 不得静默丢弃 | 视队列量，单条很小 |
| B4 | 死信复跑 | 并入 **020 D3**；保留最终失败原因 | 极小 |
| B5 | 向腾讯上游提 3 个 Issue | 文案已备好：`deploy/patches/upstream-issues.md`，提交后回填链接 | 人工 |
| B6 | gs-v0.1 全量 long 字段要点清单 | 并入 **020 D4**；使用 019 artifact 记录 complete/pending | ~1×10万 token（强模型） |
| B7 | 005/006 before/after 基线回归 | 并入 **020 D4**；结果进入 approved baseline/QualityProfile | 网关 ~6-12万 token/产品 ×3 |
| B8 | PP-StructureV3 表格结构识别部署（006 遗留） | 重依赖（paddlepaddle/paddleocr）按 08 选型进程隔离部署；实现 `compiler/templates/tables.py` `PPStructureV3Provider.extract_tables`（协议 F5.1），配置 `HARNESS_TABLE_PROVIDER=pp-structure-v3`，用金标回归 A/B 验证（11 §2）后替换默认 | 部署人工 + 金标回归 |
| B8 | **008 审核工作台实现** | 提案即交接物：`openspec/changes/008-review-workbench/proposal.md`（四页面+四动作，FastAPI+Jinja2+HTMX，复用 007 服务层与夹具；先补 specs/tasks 再 TDD） | 开发型任务，中等 |
| B9 | PP-StructureV3 表格结构识别服务部署接入 | 006 已留 TableStructureProvider 接口与配置位；部署独立服务进程（AGPL 隔离，08 §2）后接入并跑费率表对比 | 部署+联调 |
| B10 | WeKnora 测试实例搭建 + live 契约测试 | **完整 Runbook 已备好：`docs/insurance-kb/14-deployment-runbook.md`**（双库初始化/L1~L6 验收路径/完成定义清单） | 部署+联调 |
| B11 | 009 概念层编译实现（概念主页/义项/wikilink/purpose） | `openspec/changes/009-concept-layer/proposal.md`，先补 specs/tasks 再 TDD | 开发型，中等 |
| B12 | 010 结构化直入通道实现（JSON/FAQ→Claim/QA，幂等+dry-run） | `openspec/changes/010-structured-import/proposal.md`；属后续 backlog，不抢占 ⓪-0f 主线 | 开发型，中等 |
| B13 | 011 知识健康度巡检实现（过期/积压/漂移/退化/孤立） | `openspec/changes/011-knowledge-health/proposal.md` | 开发型，中小 |
| B14 | 012 QA 一等对象实现（权威/派生QA，Claim绑定硬门禁） | `openspec/changes/012-qa-objects/proposal.md`，依赖 B12 | 开发型，中等 |
| B15 | 013 insurance MCP server 实现（4 个只读工具：产品对齐/按日期取事实/证据链/跨产品对照） | `openspec/changes/013-insurance-mcp/proposal.md` | 开发型，中小 |
| B16 | 014 批量并发调度实现（三级任务模型/分片advisory lock/五级限流/批次控制台API） | `openspec/changes/014-batch-orchestration/proposal.md`；同分片锁顺带解决 007 多实例发布竞争 | 开发型，中等 |
| B17 | 015 数据飞轮实现（Langfuse 信号→缺口工单→回流报表） | `openspec/changes/015-feedback-flywheel/proposal.md`；依赖 007，008 展示 | 开发型，中小 |
| B18 | **016 KnowledgeSpace 与强制作用域** | ✅ T1～T8、validation report、规格/质量双审与主代理验收完成 | 开发型，大 |
| B19 | **017 WeKnora SourceDocument Bridge + Evidence lineage** | ✅ T1～T8 软件完成并通过双审/全量门禁；真实 live gate 已纳入冻结七变量的受控手工 workflow，但无运行证据仍为 `NOT RUN`；不同 revision 乱序由 021 承接 | 开发型，中大 + live |
| B20 | 018 SnapshotFact/统一读取/可恢复发布 | **并行轨 A**；`openspec/changes/018-release-snapshot-read-model/`，硬依赖 007+016+017，独占 migration `0005`，完成后解锁 021 | 开发型，中大 + live |
| B21 | 019 Golden 工具/QualityProfile/在线 Gate | ✅ **软件实施完成 + codex 五轮 review 返工 + 提交前对抗性自测**（feat/019-golden-quality-gate，T1～T6 严格 TDD，全库 non-live 1119 passed / ruff / mypy 161 files 全绿）：portable assembler+validator（强制证据回验、disputed≤5%）、**内容寻址** BaselineArtifact（六类产物各带 sha256+计数自洽）/不可变 approval（**提交 artifact + 画像内容哈希** `artifact_sha256`/`profile_content_sha256` + 强制回归 + prior 不可伪造 + 换 id 不能跳回归；`allow_lineage_reset` 须**真新 lineage + 非空 reason** 方逃生，且明确为结构约束+审计信号、非授权本身）、QualityProfile+六维 staleness（`content_hash` 排除 approval 回指、全链绑定、零观测不给满分）、`build_profile` **复用 `eval.evaluate`**（pred-only 多余字段计 FP、**每字段聚合并入 pred-only 幻觉**、口径一致）、`compare_baselines` 全局 micro/macro F1+幻觉+证据+unresolved+字段阈值结构化、统一 QualityGate **fail-closed**（校 profile↔approval↔artifact 内容哈希+指纹 + **profile 版本** + **pending_judge 收回 gate 裁定**；无 gate/不匹配一律进 ReviewItem）。**领域类型** `Rate[0,1]`/`NonNegativeInt` 令越界比率/负计数/NaN 构造期即不可入。真实 baseline/画像由 020 用同一 API 产出。详见 `openspec/changes/019-golden-quality-gate/validation-report.md` | 开发型，中 |
| B22 | 020 gs-v0.1 + 13 产品 baseline 真实运行 | **硬依赖 019+021**；统一承接 B1/B2/B3/B4/B6/B7，先完成 020 T1 run-admission，再允许模型调用 | 高 token 数据任务 |
| B23 | 021 Source lifecycle ordering | **硬依赖 018**；durable SourceHead、processed_at/generation、per-source lock/CAS；迁移在 018 `0005` 之后，完成后与 019 共同解锁 020 | 开发型，中大 |

> 016～021 已有条款级规格；验收以各 change spec、测试与 validation-report 为准。020 是环境/预算约束的数据运行，软件门禁绿不等于真实运行完成；021 规格存在不等于 ordering 能力已落地。

## 一、我们在做什么

为大型寿险企业建设企业级知识平台：以 **WeKnora（本仓库，官方 v0.6.3 零分岔 fork）为平台底座**，以**插件式 Python Harness** 承载全部寿险知识能力（抽取、校验、合并、冲突裁决、版本、审核、金标评估），把文档编译成原子化、有版本、可溯源的知识，供 Agent 与人共用。这是一个**示范性项目**（企业级 harness agent 标杆），文档与代码质量要求高于交付速度。

5 分钟了解项目：读 `docs/insurance-kb/00-project-overview.md`。

## 二、已完成

1. **三仓库深度调研**（2026-07-11）：
   - 本仓库 = 官方 WeKnora 0.6.3 原样 + 迭代规划文档，保险代码为零；Wiki 能力是官方自带（数据模型/管线/API 细节见调研结论，已固化进 02/03 文档）；
   - 确认三个平台缺口：Wiki REST 写入无乐观锁（last-write-wins）、无解析完成 webhook、`WikiEnabled=false` 时 REST 写 wiki 也 400；
   - LLM-wiki-black（旧寿险定制项目）资产盘点：可迁移的字段字典、抽取路由、清洗正则、Q001-Q027 踩坑档案 → 全部落入 `docs/insurance-kb/06-asset-migration.md`；
   - 上游 nashsu/llm_wiki（GPL-3.0）设计思想提炼 10 条，只借鉴不抄码。
2. **架构定稿（ADR-001，业务方确认）**：插件式路线 B。WeKnora 不动（补丁≤3 且提 PR 回上游），保险能力全在 `harness/`（尚未创建），自有 PostgreSQL。详见 `docs/insurance-kb/02-architecture.md`。
3. **设计文档集**：`docs/insurance-kb/` 00~10 全部完成（见该目录 README）：需求/架构/知识模型/抽取管道/金标评估/资产移植/schema 基线，外加 **08 技术选型**（逐组件开源框架与许可证核对）、**09 LLM Wiki 功能迁移对照表**（27 项功能的承接方与排期）、**10 开发规范**（SDD/TDD/边界纪律）。master plan 顶部已加架构修订说明。
4. **Schema 基线接入**：业务方 Excel（2026-07-10）已转成 `docs/insurance-kb/schema-baseline/` 13 个 YAML；07 §3 的 18 条扩展字段提案已由业务方全部接受并并入 schema v1.1。
5. **样本材料**：13 产品（说明书+条款+费率表+meta）已解压到仓库外 `../samples/`（**不入 git**，公司资料）。

## 三、已拍板决策（2026-07-11 业务方确认）与剩余卡点

已拍板：
1. **范围 = 全险种覆盖，不做单险种试点**。按样本到位程度分波：第一波用现有 13 产品（终身寿/年金/两全/医疗/意外/失能），第二波（重疾/护理/补充养老/意外医疗）待样本到位并入（07 §4）。
2. **18 条扩展字段提案全部接受**，已并入 schema v1.1（`docs/insurance-kb/schema-baseline/extensions-v1.1.yaml`）。
3. **金标模型 = Claude（Fable/Opus 级）**，S0 金标注 Agent 按此接入。

剩余卡点（不阻塞开工）：
- **待业务方补样本**：重疾/护理/补充养老产品各 2~3 个、多产品混合文档 3~5 份、扫描件 1~2 份、FAQ/结构化 JSON 一份。

## 四、下一步计划（按序）

1. **合并后收尾**：完成 ⓪-0f 的文档口径、旧 ledger、OpenSpec archive 与 strict/link/status 对账；只做收尾，不夹带 018 功能。
2. **收尾后并行/价值优先推进 018 与 019**：018 完成 SnapshotFact、统一 SnapshotReader、可恢复发布/回滚与 live/NOT RUN 证据；019 完成 Golden assembler/validator、artifact approval、QualityProfile 与在线 QualityGate。019 无 018 前置，价值优先级不低于 018；本轨不跑真实大模型，也不提前执行 020 T1 run-admission。
3. **018 完成后推进 021**：完成 source lifecycle ordering、并发/乱序/删除竞争及 PostgreSQL 双会话验证。
4. **019 与 021 均完成后启动 020**：先完成 020 T1 run-admission，再完成剩余 2 产品、13 产品 baseline、judge/dead-letter/keypoints；该项高 token，执行前登记模型、预算与断点。B10 WeKnora 环境准备可全程由独立负责人并行。

样本语料：业务方 2026-07-11 提供 `shouxian_product`（13 产品，39 PDF + 12 meta json）并确认拷入仓库 → `dataset/shouxian_product/`，作为测试验证集原料。仓库外 `../samples/` 的早期解压副本作废，以 dataset 内为准。

## 五、踩过的坑（绝对不要再踩）

1. **不要把保险逻辑写进 Go/Vue**——02 §3 三条硬边界是 code review 检查项；违反 = 每次跟版人肉解冲突。
2. **`WikiEnabled=false` 会连 REST 写 wiki 一起封掉**（`validateWikiKB`）；"关自动生成、留 API 写入"必须等 P-3 补丁；过渡方案：Wiki KB 不上传任何原始文档。
3. **Wiki REST 是 last-write-wins**，`version` 字段不做并发校验；P-1 合入前 Harness 必须自行对 slug 串行化写入。
4. **旧项目（LLM-wiki-black）的教训**：抽取无重试机制导致 section 失败即丢数据（新管道必须指数退避+死信）；向量维度硬编码 384 vs 实际 1152 曾丢 768 维语义（凡模型返回维度一律运行时探测）；`product_meta.json` 不算有效源资料（Q020）。
5. **"未抽取到"绝不能写成"不存在"**——三态字段是硬约束（03），豁免类字段尤其如此。
6. **GPL 边界**：nashsu/llm_wiki 及 LLM-wiki-black 代码不得复制进本仓库；字段字典等自研数据可迁移（06 §合规），最终需法务确认一次。
7. **本仓库 git 历史是压平的单提交**；`upstream` remote 指官方 Tencent/WeKnora，跟版走版本列车（02 §8），不要直接跟 main。
8. 样本语料经业务方确认已入库（`dataset/shouxian_product/`）；但金标产物含模型输出，release 前检查敏感信息。
9a. **"本地绿 ≠ CI 绿"三连坑（2026-07-13 付费确认）**：① ruff 的 first-party 自动探测本地/CI 漂移→已显式 known-first-party；② mypy/ruff 本地缓存可产生假绿→验收复跑加 --no-cache / 删缓存；③ **上游 .gitignore 的 `WeKnora`（二进制名）曾吞掉 adapters/weknora/ 整个目录**，5 个核心文件从未进 git、CI 因此一直红而本地全绿→已加例外；**新增目录后必须查 `git status --ignored`，验收标准含"CI 绿"而不只是本地门禁**。
9. **本机 shell 有 SOCKS 代理环境变量（ALL_PROXY 等），曾导致 httpx 全部请求挂掉**——适配层已用 `trust_env=False` 修复；新写任何 HTTP 客户端都要注意这一点。**git push 大提交会在 sideband 中途断连**——解法（已配置进本仓库）：`git config http.postBuffer 524288000` + `http.version HTTP/1.1`，并用 `env -u ALL_PROXY -u HTTPS_PROXY …` 绕开代理变量执行 push。
10. **“基础设施测试被收集 ≠ 真的执行”**：过去 PR 只跑 `-m "not live"`，PostgreSQL/WeKnora 可全部 skip 仍绿色。现在显式三 lane、preflight、JUnit `tests > 0 && skipped = 0`；以后新增基础设施用例必须同步维护 lane collection 契约，不能只看 pytest exit code。

## 六、工作方式约定（业务方明确要求）

- 动手前先讨论；文档驱动：先设计文档 → OpenSpec（`openspec/changes/`）→ 开发；SDD/TDD。
- Python 优先；能用成熟开源不自研。
- 金标 = 最强模型标注（本阶段无人工），金标子系统必须独立可持续维护。
- 每次重大变更更新本文。
