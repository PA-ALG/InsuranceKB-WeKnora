# HANDOFF — 交接文档

> 写给完全没有上下文的新会话/新成员。任何变更请持续更新本文。
> 最后更新：2026-07-21（021/024/Wave 2 fast-follow 已分别随 PR #23/#13/#22 合入 `main`；020 T1 的 PR #24 合并前硬化已关闭四项 P1，canonical admission 仍按设计 BLOCKED。最新本机证据为 focused 700、全仓 deterministic 2607、Ruff/mypy/OpenSpec；T2～T7/D4b 未运行，只有刷新为 READY 后才允许真实模型调用；见 0j/0k/B22/B23/B24。）

## ⓪ 当前最优先事项（接手先看这里）

0. **基础建设已合入 main（PR #1，2026-07-13）**：此后一律按 17 号规范从 main 切 `feat/NNN-*` 分支，PR 双查 + **CI 绿才算绿**（坑 9a）。上游 workflow "Build and Push Docker Image" 已在 GitHub 界面手动禁用（fork 无腾讯 registry 凭据必失败，属继承性噪音）；其余上游 workflow 有路径/标签过滤暂无干扰，误触发照此禁用，不影响版本列车跟版。

0a. **016 企业 KnowledgeSpace 与 017 SourceDocument Bridge 软件实施已收尾**：总设计见 `docs/insurance-kb/20-enterprise-runtime-foundation.md`，分支 `codex/016-enterprise-foundation`。017 T1～T8 已按 TDD 完成，最终规格复审 `Spec compliant: yes`、质量复审 `Quality approved: yes`，无剩余 finding；主代理 T8 non-live **12 passed / 1 deselected**、source standalone **49 passed**、最终全量 non-live **915 passed / 5 deselected**，Ruff、mypy 139 files 与 diff check 全绿。T8 live gate 已实现真实 `wait_for_parsed → bridge → deterministic Compiler → pred/import → Evidence backlink`，但六项 live 变量与本机 WeKnora/PostgreSQL 实例均缺失，运行结果明确为 **NOT RUN：1 skipped / 12 deselected**；当前 adapter 无 uploader，因此 existing-knowledge 分支也不代表 upload 创建覆盖。017 当时只保证同 revision 幂等，不保证不同 revision 并发/乱序；该边界现已由 021 的 SourceHead/Event、ordering 与 per-source lock/CAS 关闭，不能再把 021 记为 pending。

0b. **Space 部署注意**：从 0001/0002 升级且已有业务行时，0003 会创建并回填 unbound `legacy-default`。在任何产品注册、路由、Source Bridge 或发布任务前，管理员必须按 `docs/insurance-kb/14-deployment-runbook.md` §3.1 执行 `python -m insurance_harness.db.scope_cli bind legacy-default --tenant-id ... --raw-kb-id ... --wiki-kb-id ... --db-url ...`；未绑定时运行时按设计 fail closed。新装空库不创建该 Space，当前也没有 create CLI，必须先走受控管理员 provisioning 创建 bound Space；幂等初始化脚本仍由 B10 承接。

0c. **PR #4 复审收口**：已修复空库 0003→0002 downgrade 被错误拒绝，以及 `SourceChunk` 默认 metadata 未深度冻结；migration/source focused `69 passed`，全库 non-live `916 passed / 5 deselected`，Ruff、mypy 139 files、diff check 全绿。其余评论中 revision 含 `processed_at`、numeric WeKnora identity 与新 revision recompile 均为 017 明文规格；rollback 外部写补偿仍按既有边界归 018。

0d. **OpenSpec 022 测试组合再平衡（P0～P3）完成并随 PR #5 合入 `main`**：修复 `test_live.py` 提前 close/dispose 导致 scope Engine attestation 在用例前失效；pytest 拆为 deterministic / `integration_postgres` / WeKnora `live` 三条互斥 lane，PR 新增 PostgreSQL 16 service job，受控 `harness-live` 手工 workflow 冻结七变量且用 JUnit 拒绝 tests=0 或 skipped≠0 的伪绿；含 secrets 的 workflow actions 与 uv 均固定不可变版本，publisher live 页面在任何失败路径均尝试删除且不覆盖主异常。bridge 已拆为 12 contract + 1 live；pipeline 88 与 revision 51 个规范化 identity/marker 全保留，最大测试文件 739 行。coverage-context audit 已用真实 scope suite 产物验证（208 passed；193 contexts / 1946 production lines / 999 advisory candidates at 0.8），候选不自动删测。本地最终 deterministic `933/938 collected`、exit 0，Ruff 全绿、mypy 151 files 全绿。`integration verified` 已由 commit `ed46df78fb975c5ef7963e49dd1e208dba31fdaa` 的 [PostgreSQL 16.14 job](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29312423361/job/87018894440) 证明：`1 passed / 937 deselected`、JUnit `tests=1 skipped=0`，run 于 2026-07-14T06:47:21Z～06:49:53Z 成功；WeKnora `live verified` 无受控 workflow 证据，继续 **NOT RUN**。

0e. **OpenSpec `022-review-hardening` 已随 [PR #5](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/5) 合入 `main`**：六项 Claude 复审意见已客观裁决并按 SDD/TDD 实现；RH1～RH6 task-level 双审均 Approved，整包 spec review `Approved`，整包 quality 的唯一 Important（持久化 `proposed=[]` 泄漏 `AttributeError`）已补 RED、在 RH2 边界统一为无泄漏 `ScopeViolation` 后复审 `Approved`，无剩余 Critical/Important/Minor。最终 fresh 本地证据：OpenSpec strict exit 0、Ruff exit 0、mypy 151 files exit 0、deterministic **961 passed / 5 deselected**；focused 为 RH1 `43 passed / 1 skipped`、RH2 `62 passed`、RH3 `136 passed`、RH4 `110 passed`、RH5/RH6 `15 passed`，bridge collection 仍为 contract 12 / live 1。PR 最终 head `7a924254` 的 [deterministic](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326433014/job/87063741905) 与 [PostgreSQL 16 integration](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326433014/job/87063741858) 均通过，merge commit 为 `2615b260`。WeKnora 继续 **`NOT RUN`**；PostgreSQL CI 不得替代真实 live。RH1 只保证函数内 savepoint，outer transaction/进程终止/多页补偿仍归 018；RH2 不含 ordering/`processed_at`/SourceHead/CAS，仍归 021；Directory replay 保持 eval-only；live 是 existing-knowledge 而非 upload。

0f. **排期与依赖裁决（业务方 2026-07-14；2026-07-21 状态更新）**：既定技术依赖为 **018 → 021、019 → 020、021 → 020**，不得把 018 → 019 写成技术依赖；目前 018/019/021 均已合入，020 T1 已消费这些前置能力。当前关键路径不再是写 ordering 代码，而是完成 020 PR 后解除数据、provenance、审批、模型 identity/probe 与预算准入，再进入 T2～T7。各 change 继续遵守 SDD、TDD、独立复核与 CLAUDE 门禁。

0g. **OpenSpec 023 本机 WeKnora live 环境（2026-07-17 当前状态）**：PR #10、#16、#19、#20 均已合入 `main`。受信 main workflow 已从锁定的 Tencent upstream `5eefa70e...` 构建 `linux/arm64` app，OCI/GitHub attestation、SLSA provenance 与 SPDX SBOM 均已核验；`deploy/local-live/images.lock` 和 Compose 固定 subject digest `sha256:e2dd00b37dbcfebf87fab9d1e2338ad43e6ea9939a5ba9fcab9d412d866521f5`。本机六服务 healthy，宿主只监听 `127.0.0.1:8080/8081/5442`；百炼五角色 direct probe、幂等 provision、普通 PDF 与 clean-SHA VLM smoke 均通过，VLM 结果为 `status=completed / image_ocr_chunks=1 / image_caption_chunks=1 / dirty=false / evidence=exact`。PR #20 另以真实 API TDD 修复重复注册、Wiki indexing strategy、pages envelope 与服务端扩展 VLM overrides 四项合同差异；最终 live 又发现 Wiki 空关系返回 `null`，PR #9 以 `test_s2_4_*` RED→GREEN 仅规范化为 `[]`。018 的本机 5-node 已 `5 passed / skipped=0`；正式 GitHub exact-SHA gate 作为收尾 PR 的合并前门禁执行。

   以下“官方 v0.6.3 缺 scoped key / T6d.1 待制品”的段落仅保留为历史故障与供应链决策记录；其阻塞已由 PR #16、#19、#20 关闭，不得再用作当前状态。

   **当前唯一核心阻塞是 app artifact，不是模型或 Docker**：固定的官方 `wechatopenai/weknora-app:v0.6.3@sha256:7480...` 构建于 2026-06-26，早于 7 月新增的 scoped tenant API key routes。真实 provision 已创建 `user=1 / tenant=2 / models=4 / KB=2`，随后在 `GET /tenants/10001/api-keys` 得到 404；按最小权限合同正确 fail closed，禁止降级 legacy full-access key。实机同时发现官方镜像把 `/models/:id/debug` 的 prompt/raw response/reasoning/error 写 access log；当前源码已按 `test_r3_3_*` RED→GREEN，整个 debug response 在 access log 中省略。曾尝试的 dirty checkout + mutable local tag build 经安全复核已撤回。

   T6d 已拆成 bootstrap 两段：**T6d.1 软件阶段已完成，T6d.2 制品阶段待执行**。`deploy/local-live/weknora-app-source.lock.json` 固定 Tencent upstream `5eefa70e...`、tree `a44f7eae...`、真实 `docker/Dockerfile.app` SHA-256、六个 scoped-key/security ancestor、`linux/arm64` 与 security patch digest；patch 同时把 model-debug response 整包从 access log 省略、在实际 upstream build context 排除 `.env.*`、固定 `golang-migrate@v4.19.1`，并校验 uv 0.9.26 安装脚本 SHA-256。`.github/workflows/weknora-app-local-live-image.yml` 仅允许 trusted `main` dispatch，不接受 caller repository/commit/platform，全部 action 固定完整 SHA，只用 `github.token` 发布 GHCR，并启用 max provenance、SBOM、registry attestation。Claude 对 PR #16 的 review 已按第一性原理裁决：CI hermetic checkout、官方 uv hash、`supports_vision=false` 省略、scoped 404、代理隔离、VLM CLI/retry/marker 与 output 控制字符均已 RED→GREEN；R2.1 pre-start 动态 HTTP 与删除 BuildKit cache 不改善既定安全不变量，未采纳；ReRank/canary 重构不属于本 PR 阻断项。2026-07-17 fresh 本机门禁：供应链 **7 passed**、023 focused **248 passed**、Ruff、mypy 181 files、deterministic **1412 passed / 5 deselected**、PostgreSQL **1 passed / 1416 deselected** 且 JUnit `tests=1 skipped=0`、OpenSpec strict。一次性 known-secret 扫描器未入库，故不再把旧精确计数当验收证据。由于高权限 workflow 必须先由人工复核并合入 main，GHCR build/manifest digest/provenance/SBOM/attestation、digest 写回、完整 provision、VLM 与 T7/T8 仍为 **NOT RUN**；本机结果在 GitHub CI 覆盖同一提交 SHA 前只作 provisional 证据。

   **阶段 1 — 合并后收尾（当前）**
   - [x] PR #5、#6 已合并，最新 `origin/main` 已确认指向 `27c36641`；新基线 Ruff、mypy strict、deterministic **961 passed / 5 deselected**。
   - [ ] 修正文档陈旧口径：`docs/insurance-kb/README.md` 的 017 T1～T6、`docs/insurance-kb/20-enterprise-runtime-foundation.md` 的 PostgreSQL integration / WeKnora live 边界、`harness/README.md` 的 deterministic marker。
   - [x] 对账排期与依赖：`docs/insurance-kb/16-roadmap.md`、`docs/insurance-kb/20-enterprise-runtime-foundation.md` 与本节统一为 018/019 可独立或并行、018 → 021、019+021 → 020；详细 checkbox 只保留在 HANDOFF，避免双份清单漂移。
   - [ ] 对账旧 ledger：001/003/004 的未勾项只做完成证据回填，不重做已验收功能；002 仅对账已完成项，真实未完成的 T8/T9 明确保留并转交 020；消除“18 条扩展字段待确认”与“已全部接受”的冲突。
   - [ ] 归档已完成的 016、017、022-test-portfolio-rebalance、022-review-hardening，并运行 OpenSpec strict / 文档链接与状态检查。

   **并行轨 A — 018 ReleaseSnapshot 统一读模型与可恢复发布（✅ PR #9 已合入）**
   - [x] T1～T6 软件完成并通过两轮独立复审（`d38dfb2` 全部发现关闭；deterministic 1224 passed / mypy 181 files 全绿，见 PR #9 复审记录）；018 独占 Alembic `0005`。
   - [x] T7：最终 head `44d5d7df` 的本机受控 5-node 为 `5 passed / tests=5 / skipped=0`，clean-SHA VLM 为 OCR=1/Caption=1；正式 GitHub exact-SHA 证据由收尾 PR check/comment 固化。
   - [x] PR #9 已以 merge commit `b093a447` 合入，已解锁 021（迁移 0006）、013 实现、008 W4 回滚动作。

   **并行轨 B — 019 Golden 工具、QualityProfile 与在线 Gate（✅ 已完成并合入 main）**
   - [x] T1～T6 严格 TDD 完成，codex 七轮 APPROVED，随 PR #8 合入（merge commit `4d9c84e`，2026-07-15）；证据见 B21 与 `openspec/changes/019-golden-quality-gate/validation-report.md`。
   - `run-admission` 属于 020 T1，只能在 019、021 均完成后由 020 自己执行（边界不变）。

   **收敛轨 — 021 Source lifecycle ordering（T1～T10 全部完成；硬依赖 018✅）**
   - [x] source ordering/delete/reactivation 状态机按 SDD/TDD 实施；`notify/import/delete/reactivate` 共用 per-source lock/CAS 与 append-only event。
   - [x] 迁移 `0006` 实际接 main head `0012`；交付 SourceHead/SourceEvent/BackfillIssue resolver、`processed_at/generation` 与 caller-owned nested transaction。
   - [x] 本机 PostgreSQL 16 逆序/并发/删除竞争与真实 Alembic lane：021 核心 21 passed，全部 PG 25 passed，JUnit skipped=0。
   - [x] 最终 spec PASS、quality APPROVED；OpenSpec strict、Ruff、mypy 248 files、deterministic 1901 与 diff check 全绿。
   - [x] commit `f557fc94`、push、PR #23 六项 CI 全绿并合入 main（merge `cfefcc9b`）。

   **价值出口 — 020 真实金标/baseline 运行（019+021 已满足）**：T1 零模型 `run-admission` 由 PR #24 承载；其结果仍为 BLOCKED，真实标注/baseline 尚未运行。只有 canonical admission 变为 READY 才能进入 D2～D4；不得用软件门禁或 PostgreSQL integration 冒充真实运行证据。

0g.1. **018 执行事故与 PR #9 硬化（必须保留）**：2026-07-14～15 曾因三轮规格审查、三轮计划审查和一个过大的 T1 子任务，出现约 `23143s` 无 RED、无 diff、无可验证产出的执行故障。此后 018 强制拆成单闭环 TDD：15 分钟内首个 RED、30 分钟内可核验产物、工具 60 秒无输出主动轮询、普通命令 10 分钟硬中止、子任务 2 分钟无响应转主线程。PR #9 的 RH1～RH5 已补齐 test-support 隔离、SQLite FK、stale-base mutation、collision/lease recovery 与 0005/search_path 合同；两轮独立复审无剩余 finding，最终 CI 与 5-node 已完成。该事故规则继续适用于 021 等后续 change，不得因 018 已合入而删除。

0h. **并行执行蓝图（2026-07-21 对账）**：021 已随 PR #23、024 已随 PR #13、Wave 2 fast-follow 已随 PR #22 合入；当前关键路径是 PR #24 的 020 T1 run-admission → READY → D2～D4/D4b。旁路中，010 T5～T12、011、013 与 008 W4/T6 可分别从最新 `main` 认领；009 必须等待 010 knowledge 域段，012 必须等待 010 的 qa_staging/冻结合同。规格完成不得表述为整波实现可立即并发。

0i. **OpenSpec 015 durable foundation 已随 PR #18 合入**：迁移 `0012` 的 Space-scoped checkpoint/processed ledger/gap 三表、caller-owned transaction 与 exactly-once 基础已落地；F1.1b Langfuse 直连、F2.4 ReviewItem 动作投影、009 concept 和 011 合流仍 gated，禁止因 durable foundation 完成而虚报完整飞轮闭环。

0j. **OpenSpec 021 主流程已合入（2026-07-21）**：确定性链路已贯通 `SourceRevision → per-source advisory lock → SourceHead/append-only SourceEvent → notify/import/delete → stale-or-blocked audit no-op → strictly-newer reactivate`；历史 ordering 不可证明时只建唯一 open BackfillIssue，显式 resolver 与正常 lifecycle 共锁且 exact retry 返回原 resolution event。Task8 覆盖 13 个真实业务并发节点与 8 个真实 Alembic 节点；合并前 fresh 本地 deterministic **1901 passed/30 deselected**、PostgreSQL **25 passed/skipped=0**、OpenSpec/Ruff/mypy 全绿，PR #23 的两组 deterministic/integration-postgres/wheel-smoke 共六项全绿，merge=`cfefcc9b`。021 已解除 020 的 source-ordering 依赖，但不会自动放行模型调用。

0k. **OpenSpec 020 T1 run-admission 软件闭环（2026-07-21，PR #24 合并前硬化）**：已按 SDD/TDD 实现类型化 admission/evaluator/CLI、签名 canonical identity、完整输入与 execution-surface 指纹、安全 provider probe、durable budget reservation/request-attempt ledger、每产品 runtime 重验、annotation/baseline 可恢复执行入口、提交前 exact-bytes/语义回验及 validation→settlement 同锁。最终高风险复核关闭四项 P1：删除可伪造的 provider `no_usage` 退款路径（历史态只按 uncertain/full-reserve 恢复）；同 run revision 只允许提高 account ceiling，禁止新增/删除/修改产品、请求或池；production Bailian 必须使用与真实请求 `model` 相同的 provider-guaranteed immutable deployment ID；019/021 固定实际 main merge `4d9c84e`/`cfefcc9b`，拒绝 feature head/cherry-equivalent 替代。代码/source plan 已先提交为 `2169c582`，canonical JSON/Markdown 再从该 clean SHA 生成，结果不含 dirty/dependency/identity drift blocker。最新本地 focused **700 passed**、deterministic **2607 passed/30 deselected**、Ruff/mypy 285 files/OpenSpec 全绿。权威工件仍为零模型 **`BLOCKED`**，runtime capability=`budget-ledger-v3-canary-v1`，provider probe 全为 `not_attempted`，模型调用/token/费用均为 0；剩余阻塞只有预算、11 个产品历史 provenance、一个产品缺失/未消费输入、签名审批及三模型不可变 identity。**这只表示 T1 软件闭环完成，不表示 020 数据运行完成**：T2～T7 尚未运行，D5/T8 最终对账也未完成；得到 READY 后方可按 T2→T7 执行。

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
   隔离区目录，CLI 默认 dry-run）+ pred 增加 `data_quality`（12 #2；**2026-07-16 对账：该字段至今只在 pred 侧，Claim 主链/快照/MCP 未持久化——端到端落地已占号 change 026**，010/013 不预支承诺）。
   **修复 004 族指纹疑点**：无标题文档（说明书/费率表）曾全部退化为空串指纹 fam-e3b0c44298fc，
   现走 fallback（文档类型+页数桶+表头 token），有标题文档指纹零漂移。**留出验证**（盛世金越族，
   两分红产品归纳 → 尊享26终身寿留出）：fast path 命中字段正确率 1.00 vs 通用管道 0.00
   （交费期限 unknown→列直取全对），预估节省 1 次调用/产品（锚定字段尚少；随模板铺开增长）；
   发现分红说明书两版式不同构（归纳报告与 validation-report.md 有全量明细）。门禁 239 passed 全绿。
4. **非当前主线 backlog**：抽取召回主战场是 extract_empty 24 条（prompt 变体/补漏增强，见 005 归因清单），不得抢占 ⓪-0f 的执行顺序；模型配置：harness/.env（不入库）——弱模型 deepseek-v4-flash、裁决 claude-session 模式（judge-queue → apply-judgements CLI，本轮已实跑 3 条闭环）、兜底 deepseek-v4-pro。
5. **分工定位（2026-07-12 业务方定）**：本会话（Claude）负责**整体架构、代码设计、功能规划、技术方案**（产出设计文档与 OpenSpec change 提案）；**大批量 token 消耗的执行任务一律进下方遗留清单，交由其他模型/会话推进**。

**协作与排期**：三人分工与协作规范见 `docs/insurance-kb/17-team-collaboration.md`（模块所有权/PR 双查/认领制）；当前排期以 ⓪-0f/0h 为准：先收尾，018/019 可独立或并行，021 等 018，020 等 019+021；**并行轨道结构与开工基线见 `docs/insurance-kb/22-parallel-execution-blueprint.md`（L0–L6），编号占用见 `openspec/changes/README.md` 注册表**。认领 B 项请在下表加“认领人”并保持更新；B10 环境准备可独立并行。

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
| B8 | **008 审核工作台实现** | ✅ T1～T5/T7 核心工作台已随 PR #15 合入；并发令牌、SQL 分页、Scope 校验等阻断项已闭合。T6/W4 仍按既有裁决作为独立 follow-up，从最新 main 认领 | 开发型任务，中等 |
| B9 | PP-StructureV3 表格结构识别服务部署接入（006 遗留；原重复的两行 B8/B9 已合并于此） | 重依赖（paddlepaddle/paddleocr）按 08 选型进程隔离部署（AGPL 隔离，08 §2）；实现 `compiler/templates/tables.py` `PPStructureV3Provider.extract_tables`（协议 F5.1），配置 `HARNESS_TABLE_PROVIDER=pp-structure-v3`；接入后跑费率表对比，用金标回归 A/B 验证（11 §2）替换默认；接入时证据元数据补记表格行列坐标（同事实证反馈 2026-07-16，见 19 号实证补强） | 部署人工 + 金标回归 + 联调 |
| B10 | WeKnora 测试实例搭建 + live 契约测试 | ✅ OpenSpec 023 已由 PR #10/#16/#19/#20/#21 收口：受信镜像、provenance/SBOM、loopback-only 六服务、真实 provision/PDF/VLM 与 018 五节点均已有证据；未来 WeKnora/镜像升级仍须重新验收 | 部署+联调 |
| B11 | 009 概念层编译实现（概念主页/义项/wikilink/purpose） | 📋 规格已收口；**等待 010 T5～T12 knowledge 域段合入后认领**。021 已合入只解除 010 前置，不能替代 010 产物；迁移 0008 | 开发型，中等 |
| B12 | 010 结构化直入通道实现（**双通道**：meta bootstrap→003 零 Claim / 可信业务源→Claim/QA） | 🚧 T1～T4 已随 PR #14 合入；021 已随 PR #23 合入，**T5～T12 knowledge 域段现可从最新 main 认领**。迁移 0007；Owner-A 复审 | 开发型，中等偏大 |
| B13 | 011 知识健康度巡检实现（过期/积压/漂移/退化/孤立/同类缺口/**任务可靠性**） | 📋 PR #12 主规格与 PR #22 fast-follow 已写入：远端/输入/工具链独立证据轴，多信号并报，无法归因时 degraded；**011 本体可认领**。020 registry 未就绪与 009 未落地分别按 unavailable/not-applicable 处理，不伪报健康 | 开发型，中小 |
| B14 | 012 QA 一等对象实现（权威/派生QA，Claim绑定硬门禁） | 📋 规格已收口；**等待 010 T5～T12 交付 qa_staging 与冻结合同后认领**；迁移 0009 | 开发型，中等 |
| B15 | 013 insurance MCP server 实现（4 个只读工具：产品对齐/按日期取事实/证据链/跨产品对照） | **规格就绪且已解锁（轨道 L3）**：`openspec/changes/013-insurance-mcp/`（M1–M5 + T1–T8；HTTP Streamable 主传输，读路径走已合入的 018 SnapshotReader） | 开发型，中小 |
| B16 | 014 批量并发调度实现（三级任务模型/分片advisory lock/五级限流/批次控制台API） | `openspec/changes/014-batch-orchestration/proposal.md`；同分片锁顺带解决 007 多实例发布竞争 | 开发型，中等 |
| B17 | 015 数据飞轮实现（Langfuse 信号→缺口工单→回流报表） | ✅ durable foundation 已随 PR #18 合入：Space-scoped checkpoint/processed ledger/gap 与 exactly-once 基础可用；F1.1b Langfuse 直连、F2.4 ReviewItem 动作投影、009 concept、011 合流仍 gated | 开发型，中小 |
| B18 | **016 KnowledgeSpace 与强制作用域** | ✅ T1～T8、validation report、规格/质量双审与主代理验收完成 | 开发型，大 |
| B19 | **017 WeKnora SourceDocument Bridge + Evidence lineage** | ✅ T1～T8 软件完成并通过双审/全量门禁；真实 live gate 已纳入冻结七变量的受控手工 workflow，但无运行证据仍为 `NOT RUN`；不同 revision 乱序由 021 承接 | 开发型，中大 + live |
| B20 | 018 SnapshotFact/统一读取/可恢复发布 | ✅ PR #9 已合入（merge `b093a447`）；`0005`、统一读模型、可恢复 publish/rollback 与 5-node live 已验收，021 已解锁 | 开发型，中大 + live |
| B21 | 019 Golden 工具/QualityProfile/在线 Gate | ✅ **软件实施完成 + codex 六轮返工→七轮 APPROVED(可合并) + 提交前独立红队自测(R6/R7) + 七轮非阻断清理(红队归档 27→5、注释去返工叙事、canonicalize≠provenance 措辞，`6e3e5f9`)**（feat/019-golden-quality-gate，T1～T6 严格 TDD，全库 non-live 1142 passed / ruff / mypy 161 files 全绿）：portable assembler+validator（强制证据回验、disputed≤5%）、**内容寻址** BaselineArtifact（六类产物各带 sha256+计数自洽）/不可变 approval（**提交 artifact + 画像内容哈希** `artifact_sha256`/`profile_content_sha256` + 强制回归 + prior 不可伪造 + 换 id 不能跳回归；`allow_lineage_reset` 须 prior 非空 + baseline_id 不在 prior + **golden 集(评测基准)真变更** + 非空 reason 方逃生；**非 reset 回归对称要求候选与基线同 golden 集**，明确为结构约束+审计信号、非授权本身）、QualityProfile+六维 staleness（`content_hash` 排除 approval 回指、全链绑定、零观测不给满分）、`build_profile` **复用 `eval.evaluate`**（pred-only 多余字段计 FP、每字段聚合并入 pred-only 幻觉、**disputed 键预测经 `excluded_disputed_keys` 单一权威排除、不计幻觉**、口径一致）、`compare_baselines` 全局 micro/macro F1+幻觉+证据+unresolved+字段阈值结构化、统一 QualityGate **fail-closed**（校 profile↔approval↔artifact 内容哈希+指纹 + **profile 版本** + **pending_judge**；merge `_gate_ok` 保留独立 pending 短路做纵深防御、gate 异常 fail-closed 不崩批**且 logging 记可审计原因**；无 gate/不匹配一律进 ReviewItem）。**领域类型** `Rate[0,1]`/`NonNegativeInt`/`Identifier`(禁空白 id)/`Sha256Hex`(golden hash 64hex+规范小写，`_canon_hash` 比较点再规范化防 model_copy 绕过) 令越界比率/负计数/NaN/空白标识/大小写变体身份构造期即不可入。真实 baseline/画像由 020 用同一 API 产出（020 从磁盘加载须 `model_validate` 使领域约束 load-bearing）。详见 `openspec/changes/019-golden-quality-gate/validation-report.md` | 开发型，中 |
| B22 | 020 gs-v0.1 + 13 产品 baseline 真实运行 | 🚧 019/021 前置已满足；T1 零模型 run-admission 在 PR #24，canonical 结果仍 BLOCKED。T2～T7/D4b 未运行；READY 前禁止真实模型调用 | 高 token 数据任务 |
| B23 | 021 Source lifecycle ordering | ✅ 已随 PR #23 合入；SourceHead/Event/BackfillIssue、per-source lock/CAS 与迁移 0006 已落地 | 开发型，中大 |
| B24 | 024 抽取召回提升 | ✅ 软件已随 PR #13 合入：durable `llm-attempts.sqlite`、真实 producer 归因、实验/配置 fail-closed 已落地；**真实召回与非退化证据仍归 020 D4/D4b** | 开发型任务，中 |
| B25 | 025 合并前置弱值门槛 | 📋 规格已随 PR #17 合入；021 前置已满足，现可从最新 main 认领实现；迁移 0011 | 开发型，小 |
| B26 | 026 data_quality 端到端持久化（已占号未开目录） | 12 号 #2 采纳项对账发现只落了 pred 侧：需 Claim/Revision/Snapshot/MCP 全链字段+迁移+回填设计；业务确需时立项，落地前 010/013 等不得预支该字段承诺 | 开发型，中小 |

> 验收以各 change spec、测试与 validation-report 为准。021 已落地；020 是环境/预算约束的数据运行，软件门禁绿不等于 canonical admission READY，更不等于真实 baseline 完成。

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
2. **先合入 020 T1 PR**：保持当前零模型 `BLOCKED` 工件，不把软件门禁通过误报为真实基线完成。
3. **解除 020 准入阻塞**：补齐 11 个产品历史 provenance 与一个产品缺失/未消费输入，冻结三模型不可变 identity，完成签名审批、预算账户和 provider probe。
4. **只有 canonical admission 为 READY 后执行 T2～T7**：完成剩余 2 产品、13 产品 baseline、judge/dead-letter/keypoints；该项高 token，运行时持续登记成本、断点与审批 identity。B10 WeKnora 环境可独立并行维护。

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
10a. **020 T1 的 exact-bytes/长门禁教训（2026-07-20）**：安全工件不能在校验后重新按路径读取；PDF、schema、annotation bundle 与 SQLite checkpoint 必须绑定同一快照/exact bytes，SQLite context manager 不负责关闭连接，须显式 `closing`。validate→settle 必须持同一 run lock，候选授权必须在 settle/resume 后 fresh 重算。全库长测不可因暂时无输出判断卡死，须每 60 秒轮询并报告进度；遇到 flake 先定位根因（本轮为测试替身未接收 `dir_fd` 与进程启动窗口），不得单纯扩大超时掩盖产品 bug。
10b. **可选 authority 必须在信任链完整前关闭（2026-07-21）**：caller 自报的 provider `no_usage` proof 即使字段齐全，也不能证明未计费；缺 trust root、签名 schema、受控 loader 或 provider evidence lineage 任一项时，正确实现是删除该退款能力并按最坏费用恢复，而不是留下“以后再认证”的生产 API。canonical admission 也必须两阶段生成：代码/source plan 先形成 clean commit，再运行 CLI 生成派生 JSON/Markdown；未提交工作树上的 `dirty_consumed_file` 工件只能作 provisional 调试证据，不能入 PR 验收结论。
11. **长时间无反馈是执行故障，不是“任务复杂”**：023 期间先后出现 reviewer spawn 约 30/67 分钟，以及 2026-07-16 一次并行子任务调度调用异常挂起约两小时。硬规则升级：任何 agent/tool **60 秒无新输出即轮询**；普通测试/网络命令 **10 分钟硬中止**；spawn/follow-up 调度 **2 分钟无返回即中断并转主线程**。主路径已有可测试产物后，不得让可选 reviewer/spawn 阻塞收口；每 60 秒给业务方可验证进度。子代理方案必须由主线程安全复核，mutable tag、dirty build 或放宽 digest 合同不得因局部测试全绿直接进入 PR。
12. **子代理 GREEN 只是局部证据**：023 CLI 子线曾把 runtime env 错写成七个 `HARNESS_LIVE_*`，单模块 22 passed 仍无法真实运行；主线程组合复核后才改为复用四角色 `load_local_live_config`、八项 `ensure_runtime_environment` 与默认 `probe_all_models`。并行开发必须文件独占，但合并前主线程必须检查真实数据流并跑跨模块 focused + 全量 deterministic，不能把各轨测试数相加当集成完成。
13. **真实 adapter 要尽早做最小闭环**：023 在实机才发现 worktree 派生 Compose project 会撞固定 container name，以及 PostgreSQL `CREATE ROLE ... PASSWORD %s` 不支持该位置的 bind 参数。以后 concrete adapter 完成第一版即跑最小、可逆、无敏感输出的 create→verify→cleanup；不要等大量 mock 测试结束才碰真实 handler/DDL。Compose project、REST 响应字段、DDL 语法和清理后不存在都必须单独验明。
14. **已知无效凭据不做循环重试**：provider 401 是外部认证阻塞，不是代码“继续跑就会好”。只记录角色、HTTP 状态和 `BLOCKED`，不打印 URL/key/body；等本地 0600 文件更新后再从 probe 开始。软件 PASS、容器 healthy、provider probe、provision、local live、GitHub live 六层状态必须分开报告。
15. **安全测试要断言结构，不能做宿主字符串猜测**：023 runner 测试曾用“Docker argv 不含 `Path.home()`”证明无宿主 mount；CI 宿主 home 与容器 destination 都是 `/home/runner`，导致本地绿、CI 稳定红。正确检查是解析 `--mount`，精确允许 anonymous `type=volume`，拒绝 `type=bind/-v/--volume/docker.sock`。以后跨平台隔离测试不得用路径子串、用户名或本机目录布局代替配置结构。
16. **数据库失败栈不得携带 password DSN**：023 在沙箱拒绝 loopback 时，psycopg traceback 展开了本机 Harness 测试库密码；已立即轮换数据库 role 与 mode-0600 runtime，并用临时 `PGPASSFILE` + 无密码 URL重跑通过。以后 PostgreSQL smoke/integration 一律用 passfile、service 或其他不把 password 放进 DSN repr 的方式；一旦异常输出展开凭据，先轮换再继续，不能只删日志。
17. **新约束不能以丢旧防御测试为代价**：018 DB trigger 拒绝坏 pointer/published JSON 后，仍须用历史损坏态 fixture 保留 `current_snapshot_id` 读侧 fail-closed；migration backfill default 与新写 default 必须分开，metadata DDL 必须验证重复 `create_all()`。
18. **saga 的锁、回读与恢复身份必须组合验收**：用两个 service 实例证明 `(Engine, space_id)` 共享锁；WeKnora 写成功后必须 GET 回读 `managed_by/space_id/snapshot_id`；recovery 与在线发布共锁，reconcile child 不得形成 job-of-job。
19. **Alembic 多版本降级要做链级预检**：任何 `head → old` 路径在首个 DDL 前完成下游兼容性检查，并验证拒绝后 schema、数据和 `alembic_version` 全部不变；测试动态解析 head，禁止写死 revision。
20. **新安全主链上线必须封死旧公开旁路**：package import、`__all__`、CLI/API 与生产调用点均须枚举；只为历史回归保留的实现移入 `tests/support`，生产代码不得继续暴露 caller-session 式 publish/rollback。
21. **非 root runner 的“匿名卷”也必须实测可写**：R5.1 静态测试曾只证明没有 bind mount，却漏掉 `volume-nocopy` 会把 `_work` 挂成 `0:0 755`；runner 能注册、能接单，但在任何 step 前失败。修复必须同时保留非 root、匿名卷和零宿主挂载：镜像预建/chown `_work`，挂载允许 Docker copy-up ownership，并用真实 job 验收。外部 runner 包下载保留 checksum 终验，同时用有限 retry 抗 HTTP/2 瞬断。

## 六、工作方式约定（业务方明确要求）

- 动手前先讨论；文档驱动：先设计文档 → OpenSpec（`openspec/changes/`）→ 开发；SDD/TDD。
- Python 优先；能用成熟开源不自研。
- 金标 = 最强模型标注（本阶段无人工），金标子系统必须独立可持续维护。
- 每次重大变更更新本文。
