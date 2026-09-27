# Draft PR: Upgrade WeKnora to v0.8.2 and preserve Harness boundaries

Destination: **PA-ALG/InsuranceKB-WeKnora**, base `main`, head `codex/830-upstream-plugin-boundary`. The user explicitly authorized this exact repository payload and Draft PR. The previous approval rejection is historical. The reviewed source and earlier evidence were pushed successfully at f3ff602b9; this PR also carries the subsequent mechanical recovery evidence.

Adopts fixed upstream `3e8b0bfc` on product baseline `8ccc2ac9`, preserving the Harness REST/lifecycle boundary, immutable sources, current ACL and sole Release authority. Model dispatch journaling moves to the native transport. Source mutation and worker writes use atomic generation fences and exact-batch resource cleanup.

GOAL_ID=830-UPSTREAM-PLUGIN-BOUNDARY. OpenSpec 130, UPG-01—09. Approved design SHA256 `8392a3a7420b09bc2beda82dcfcb82c385e61f4a857f98ec568eba6fbcd771bd`. Software source is `8a0863fa095bc27b901db90c5f744d1db84063b2`; later evidence-only commits do not change artifact inputs. Unique integration Owner=root; exact paths and validation matrix are in the OpenSpec.

Affected Go packages and source contract regressions, Harness checks/Ruff/mypy, frontend tests/type-check/build and OpenSpec validation pass. Frozen independent reviews report zero BLOCKER (core43 plus router fixture; frontend80; build18; migration13; DocReader base pin). RED and exact logs/identities are retained under `docs/insurance-kb/evidence/830-upgrade/`. Service full runtime and all models namespaces are not claimed; their recorded baseline/environmental limits remain explicit.

**Keep Draft.** One App build failed because Colima ran out of disk space; no new image was produced. The user then authorized deletion of the exact 32 unused historical business images and one conditional recovery build. Cleanup has completed, retaining all containers/volumes/build cache; available space is about 6.63 GiB. Independent capacity review supported the one recovery attempt. It failed after 13.50 seconds while resolving Dockerfile frontend metadata: the configured registry mirror returned EOF before compilation. The additional build budget is exhausted (1/1), with two total App attempts and no image. No automatic retry occurred. UI/DocReader builds and upgraded container health, database backup/restore/migration, provider probes, Candidate/Draft/review/publish/activation, source click and local/GitHub live acceptance are NOT RUN. Existing epoch27 is prior G3/G3.5 evidence, not upgrade acceptance.

Database target: official110/enterprise5, pg_search0.22.6. Historical Wiki log rows are retained. Rollback requires the matching old database backup and old App together. Ordinary-KB enrichment/finalizer and exact-index-cleanup retry limitations remain documented BACKLOG; current G3 disables affected enrichment and excludes managed RAW from ordinary tools.

Mechanical SQLite fixture additions preserve production prerequisites; the separate router fixture was independently verified. Six inherited whitespace findings are byte-identical fixed-upstream content. Upgraded-runtime screenshots are NOT RUN because nothing has been deployed.

## 前批证据提交的机械文档免 RED（历史）

本批只记录已经发生的 D2 构建失败、明确未执行状态、冻结构建输入和待授权恢复候选，不修改产品行为、制品输入或验证口径，因此按仓库 AGENTS.md 的机械文档条款免 RED。适用 Requirement 为 **UPG-08**，队列阶段为 **D1—D3**。独立 reviewer `migration_review` 已核对构建日志、时间、输入哈希、候选镜像与全部容器引用，明确确认这批机械记录的免 RED 理由；没有执行清理、重试或外部推送。精确路径为：

- `HANDOFF.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/delivery-impact.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/tasks.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/validation-report.md`
- `docs/insurance-kb/evidence/830-upgrade/delivery-attempt-01.json`
- `docs/insurance-kb/evidence/830-upgrade/capacity-recovery-candidates.json`
- `docs/insurance-kb/evidence/830-upgrade/ui-d2-inputs.json`
- `docs/insurance-kb/evidence/830-upgrade/docreader-d2-inputs.json`
- `docs/insurance-kb/evidence/830-upgrade/pr-draft.md`

## 授权恢复证据的机械文档免 RED

本批仅记录用户明确授权、32镜像删除的真实回执、一次恢复构建失败与推送状态，不修改产品行为、制品输入或验证口径。适用UPG-08，D0证据维护；不为文档重建应用。独立reviewer `migration_review` 复核本批冻结证据并明确确认机械文档免RED；只核实已发生事实，不扩大任何执行授权。精确路径：

- `HANDOFF.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/tasks.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/delivery-impact.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/validation-report.md`
- `docs/insurance-kb/evidence/830-upgrade/recovery-authorization.md`
- `docs/insurance-kb/evidence/830-upgrade/capacity-recovery-receipt.json`（清理完成时快照；其中build=0早于后续恢复尝试）
- `docs/insurance-kb/evidence/830-upgrade/delivery-attempt-02.json`
- `docs/insurance-kb/evidence/830-upgrade/pr-draft.md`
