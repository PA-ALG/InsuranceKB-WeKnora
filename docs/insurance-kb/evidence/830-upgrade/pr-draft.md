# Draft PR: Upgrade WeKnora to v0.8.2 and preserve Harness boundaries

Destination: **PA-ALG/InsuranceKB-WeKnora**, base `main`, head `codex/830-upstream-plugin-boundary`. The user explicitly authorized this exact repository payload and Draft PR. The previous approval rejection is historical. The reviewed source and earlier evidence were pushed successfully at f3ff602b9; this PR also carries the subsequent mechanical recovery evidence.

Adopts fixed upstream `3e8b0bfc` on product baseline `8ccc2ac9`, preserving the Harness REST/lifecycle boundary, immutable sources, current ACL and sole Release authority. Model dispatch journaling moves to the native transport. Source mutation and worker writes use atomic generation fences and exact-batch resource cleanup.

GOAL_ID=830-UPSTREAM-PLUGIN-BOUNDARY. OpenSpec 130, UPG-01—09. Approved design SHA256 `8392a3a7420b09bc2beda82dcfcb82c385e61f4a857f98ec568eba6fbcd771bd`. The initial upgraded software source was `8a0863fa095bc27b901db90c5f744d1db84063b2`; the current PR additionally fixes the BrowserSkill child-process PATH defect. That script correction changes App artifact inputs; intervening evidence-only commits did not. Unique integration Owner=root; exact paths and validation matrix are in the OpenSpec.

Affected Go packages and source contract regressions, Harness checks/Ruff/mypy, frontend tests/type-check/build and OpenSpec validation pass. Frozen independent reviews report zero BLOCKER (core43 plus router fixture; frontend80; build18; migration13; DocReader base pin). RED and exact logs/identities are retained under `docs/insurance-kb/evidence/830-upgrade/`. Service full runtime and all models namespaces are not claimed; their recorded baseline/environmental limits remain explicit.

**Keep Draft.** The first three App attempts produced no image: disk exhaustion, registry frontend EOF, then a BrowserSkill lifecycle child unable to find pnpm. The third attempt followed the user's renewed authorization, reused 22 cached steps and stopped after 588.13 seconds. A temporary registry-mirror hot reload bypassed the network failure; the original daemon configuration was restored byte-for-byte and all eight running container identities/start times/PIDs remained unchanged. The new source fix exposes the checksum-verified pnpm executable on child PATH. Its regression failed on the old script and passes after the fix; the related suite is 130 PASS, full Ruff PASS and mypy 736 files PASS. This changes App artifact inputs; a fixed-source image is NOT RUN, and the latest one-attempt authorization is exhausted.

GitHub checks at 4dec9ef66 are **BLOCKED** by six independently diagnosed groups: license fixture, frontend style guard, Nginx route fixture, stale historical Go DTO, CLI lint and client lint. They remain open and are not fixed by the pnpm correction. Exact findings are in `ci-failures-4dec9ef.json`. UI/DocReader local images, upgraded container health, database backup/restore/migration, provider probes, Candidate/Draft/review/publish/activation and local live acceptance are NOT RUN. Existing epoch27 is prior evidence, not upgrade acceptance.

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

## 本次源码修复与机械证据范围

UPG-08：`scripts/build_browserskill.sh`与`harness/tests/test_browserskill_build_830.py`有真实child-shell RED→GREEN，不适用免RED。独立reviewer `migration_review` 在冻结身份上复核。

本次机械文档仅记录授权、实际失败、网络配置恢复、局部验证和独立CI诊断，不修改产品验收标准，适用UPG-08、D0免RED（由独立reviewer明确确认）。精确路径：`HANDOFF.md`；OpenSpec130的`tasks.md`、`delivery-impact.md`、`validation-report.md`；evidence/830-upgrade中的`recovery-authorization.md`、`delivery-attempt-03.json`、`ci-failures-4dec9ef.json`、`pr-draft.md`。

## Fourth App attempt: network failure before compilation

The user explicitly granted one more attempt on repaired source `e71c72f7dd885e228c4f447c68902450fed7ae26`, artifact `sha256:12d583e5de9f3ad36cad01490250962a18c4d5197b9da0494fa874747c5a1da4`. It failed after 10.095880297 seconds at the official Docker Registry frontend manifest HEAD with a TLS handshake timeout. Compilation did not start; no image was created. This attempt does not validate or invalidate the pnpm source correction. Total App attempts are four; the current additional budget is exhausted (1/1), with no fifth build. The temporary daemon configuration was restored byte-for-byte; daemon PID and all eight running container IDs/start times/PIDs are unchanged. See `delivery-attempt-04.json`.

Post-failure probes of the same manifest endpoint reached HTTP401 on three direct and three daemon-proxy requests; one proxy request took 10.591052 seconds. These samples show later reachability and latency variation, not stable authenticated image access. The next step is to stabilize the actual daemon registry/proxy route before another build window. The six CI blockers remain open; keep Draft.

本批仅记录第四次新授权、实际网络失败和配置/容器恢复，按UPG-08/D0机械文档免RED，由独立reviewer明确确认。精确7路径：`HANDOFF.md`；OpenSpec130的`tasks.md`、`validation-report.md`、`delivery-impact.md`；evidence/830-upgrade中的`recovery-authorization.md`、`delivery-attempt-04.json`、`pr-draft.md`。不改变源码、构建输入或验收口径，不因本批文档再构建。
