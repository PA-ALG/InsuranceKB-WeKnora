# MVP Real Slice End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 030 by freezing and admitting the 23-source/5-product MVP slice, then prove the complete document/structured intake→weak-model runtime→Evidence→merge/conflict→human approval→Human/MCP same-snapshot→update/rollback story with honest deterministic, PostgreSQL, WeKnora, and provider evidence.

**Architecture:** I0 owns only data manifests, controlled fixtures, Golden Slice, and an admission plan independent of blocked 020. I1 starts from an integration branch after S/K/M changes land, writes cross-package contract/E2E tests and reports, never repairs feature-domain code, and runs the real slice only after 027 plus the exact 030 admission are READY.

**Tech Stack:** YAML/JSON manifests, existing run-admission APIs, pytest, PostgreSQL integration lane, local WeKnora live environment, approved MiniMax/Qwen/Qwen-VL provider plan.

---

## Authority, sessions, and non-negotiable boundaries

- Spec: `openspec/changes/030-enterprise-wiki-mvp-slice/` (MVP1–MVP7).
- Frozen range: 23 sources = 20 existing files across 5 products + mixed-product document + later revision/conflict document + known-schema FAQ JSON.
- I0 can start Day 1 and touches no production module. I1 starts only after 027/028/029/010-thin/013-core/032 are available on one integration baseline.
- Risk: **A** for admission/release/Space, **B** for extraction/routing/quality, **C** for report/runbook.
- Use @superpowers:test-driven-development for contracts, @superpowers:systematic-debugging for integration failures, and @superpowers:verification-before-completion for final claims.
- I1 does not fix S/K/M production code. It files a finding with owner, exact reproduction, expected clause, and evidence; G decides re-run order.
- Never edit or borrow `openspec/changes/020-golden-v01-baseline-run/run-admission.*`.
- AI sessions do not commit/push.

## File map

### I0 create

- `dataset/mvp_v0_1/manifest.yaml` — 23 exact sources/hashes/roles/product expectations/provenance.
- `dataset/mvp_v0_1/expected_routes.yaml` — document/section/fact ownership and unassigned expectations.
- `dataset/mvp_v0_1/golden_slice.yaml` — annotated fields/tri-state/Evidence/conflict expectations.
- `dataset/mvp_v0_1/fixtures/mixed-product-source.md`
- `dataset/mvp_v0_1/fixtures/product-update-conflict-v2.md`
- `dataset/mvp_v0_1/fixtures/known-faq-source.json`
- `harness/tests/test_mvp_manifest_030.py`
- `harness/tests/test_mvp_admission_030.py`
- `openspec/changes/030-enterprise-wiki-mvp-slice/run-admission.yaml`
- generated signed/approved admission artifacts in the same change directory, never under 020.

### I1 create

- `harness/tests/test_mvp_routing_quality_030.py`
- `harness/tests/test_mvp_structured_governance_030.py`
- `harness/tests/test_mvp_update_conflict_030.py`
- `harness/tests/test_mvp_serving_rollback_030.py`
- `harness/tests/test_mvp_recovery_030.py`
- `harness/tests/test_mvp_live_030.py` — explicitly marked `live`, no silent skip accepted in an authorized live run.
- `openspec/changes/030-enterprise-wiki-mvp-slice/run-request.yaml` — non-secret, content-addressed request for the one 028 `run-manifest` entrypoint; completed and frozen before I1 dispatch.
- `openspec/changes/030-enterprise-wiki-mvp-slice/runbook.md`
- `openspec/changes/030-enterprise-wiki-mvp-slice/validation-report.md`
- `openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/` — manifests, receipts, metric JSON, snapshot/hash evidence; large/private raw responses remain outside git and are referenced by digest.

During the authorized run, `artifacts/live-run/human-input/review-decisions.yaml` and `release-approval-request.yaml` are created only by the named human reviewers at the gates below. They are not generated or pre-filled by the compiler, an agent, or a test fixture. They contain no secret but are included by hash in the final audit bundle.

### Task 1: Freeze the exact 20 existing sources

- [ ] **Step 1: Write manifest RED tests**

Test exactly five allowed product directories, each with three PDFs and `product_meta.json`; exactly 20 existing sources; no symlink/outside-dataset path; SHA-256, byte size, source kind, document type, expected product/version, and rights/provenance non-empty.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_manifest_030.py
```

Expected: FAIL because `dataset/mvp_v0_1/manifest.yaml` is absent.

- [ ] **Step 3: Create manifest entries for these exact product roots**

```text
dataset/shouxian_product/平安e生保（尊享版）医疗保险/
dataset/shouxian_product/平安e生保（悦享版）医疗保险/
dataset/shouxian_product/平安盛世金越（尊享版26）终身寿险/
dataset/shouxian_product/平安盛世金越（尊享版26）终身寿险（分红型）/
dataset/shouxian_product/平安盛世金越养老年金保险（分红型）/
```

Generate hashes through a small test/helper invoked by the executor; do not hand-copy them. Product metadata is channel-one registration input and must be marked `claim_evidence_eligible=false`.

- [ ] **Step 4: Run GREEN**

Expected: exactly 20 real entries PASS; any byte drift fails.

### Task 2: Create three controlled sources and expected ownership

- [ ] **Step 1: Add RED assertions for controlled fixtures**

Require one mixed-product document, one later SourceRevision with both complement and conflict, and one registered known-schema FAQ. Every fixture has purpose, source identity/revision, generation method, expected product/field ownership, and SHA-256.

- [ ] **Step 2: Create minimal fixtures**

- `mixed-product-source.md`: sections for two named MVP products plus one deliberately ambiguous fact expected in `unassigned`.
- `product-update-conflict-v2.md`: same logical source identity as its declared v1 target, later revision/time, one new field and one conflicting existing field.
- `known-faq-source.json`: raw question/answer plus explicit approved `fact_assertions`; no implicit QA-to-field inference.

- [ ] **Step 3: Create `expected_routes.yaml`**

Record document, section, and fact-level expected `product_version_id`; ambiguous items are explicit, not omitted.

- [ ] **Step 4: Run GREEN**

```bash
cd harness
uv run pytest -q tests/test_mvp_manifest_030.py
```

Expected: exactly 23 sources, five products, three business shapes, one mixed, one update/conflict, one FAQ.

### Task 3: Freeze the MVP Golden Slice and metric formulas

- [ ] **Step 1: Write Golden Slice RED tests**

Require annotated canonical field ID, product/version, value state/value, evidence quote/locator, risk, source, and explicit unanswerable/unknown examples. Include medical, whole-life ordinary/dividend, and annuity facts.

- [ ] **Step 2: Implement the smallest representative slice**

Cover high-risk and frequently used fields, not every schema field. Include at least: positive value, explicit absence, unknown, cross-document complement, same-field conflict, structured fact assertion, and similar-name product separation.

- [ ] **Step 3: Pin metric definitions**

```text
precision = correct candidate facts / all candidate facts
recall = matched expected facts / all answerable expected facts
evidence_verify_rate = approved facts with verified frozen Evidence / all approved facts
cross_product_pollution = facts assigned to a wrong product / all assigned facts
controlled_conflict_detection = detected expected conflicts / expected conflicts
```

Unknown expectations are excluded from answerable recall but tested separately; `unknown` can never satisfy `absent_explicitly`.

- [ ] **Step 4: Run GREEN**

```bash
cd harness
uv run pytest -q tests/test_mvp_manifest_030.py -k "golden or metric"
```

Expected: PASS.

### Task 4: Create an independent zero-model admission

- [ ] **Step 1: Write MVP1 admission RED tests**

Test run ID/revision, all 23 hashes, Golden Slice hash, schema/template/model-plan identities, provider immutable revisions, budget/attempt/time caps, approval envelope, and explicit inequality with 020 run identity. Any input drift yields BLOCKED before model fake call.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_admission_030.py
```

- [ ] **Step 3: Build admission artifacts through existing APIs**

Do not manually fabricate signed/approved state. The designated human authorizes the exact manifest/model/template/budget envelope. Until then status remains `PENDING/BLOCKED` and I0 is still a valid data deliverable.

- [ ] **Step 4: Run zero-model GREEN**

Expected: admission verifier PASS only with the matching artifact; counting provider remains zero.

- [ ] **Step 5: Independent I0 review and human commit boundary**

Reviewer checks source count/hash/provenance, controlled expectations, metric denominator, and isolation from 020. Report; do not commit/push.

### Task 5: Build the integration baseline and contract matrix

- [ ] **Step 1: G records exact integration SHA set**

Record merged commits for 027, 028a/b, 029, 010-thin-a/b, 013-core, and 032. If any is missing, I1 does not begin.

- [ ] **Step 2: Run focused package baselines, not full suite**

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py tests/test_template_packages_028.py tests/test_runtime_orchestrator_028.py tests/test_runtime_cli_028.py tests/test_release_approval_029.py tests/test_release_cli_029.py tests/test_known_schema_import_010_mvp.py tests/test_mcp_service_013.py tests/test_human_agent_same_snapshot_032.py
```

Expected: PASS. A failure is returned to its owner before writing new E2E expectations.

- [ ] **Step 3: Create the cross-package story matrix in `runbook.md`**

Map each MVP1–MVP7 clause to setup, action, expected DB/artifact state, exact test, live requirement, and owner on failure.

### Task 6: Routing/template and quality contracts

- [ ] **Step 1: Write MVP1/MVP2/MVP3 RED tests**

Use deterministic replay/scripted weak-model outputs first. Assert all controlled product ownership, ambiguous unassigned+Alert, template hash pinning, ordinary/dividend separation, precision≥0.90, recall≥0.85, approved Evidence=1.00, pollution=0.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_routing_quality_030.py
```

Expected: fail on missing integration wiring or violated package contract.

- [ ] **Step 3: Route findings to owners**

I1 writes no production fix. Finding format: clause, exact test/seed, expected, actual, artifact/job/attempt IDs, owner S/K/M, severity, retest command.

- [ ] **Step 4: Re-run GREEN after owner fixes merge**

Expected: metric JSON generated with denominators and per-product breakdown, not just aggregate percentages.

### Task 7: Structured governance and update/conflict/Alert stories

- [ ] **Step 1: Write MVP4/MVP5 RED tests**

Assert product metadata causes zero Claim; FAQ raw text is staged; explicit FAQ fact assertions produce structured Evidence/ChangeSet/Review; later revision yields add/enrich plus conflict; CurrentRelease unchanged before review; template mismatch/no consensus/evidence failure/exhaustion each produces a persisted deduplicated Alert.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_structured_governance_030.py tests/test_mvp_update_conflict_030.py
```

- [ ] **Step 3: Return functional failures to K/S owner; rebase/retest**

Expected after fixes: PASS; controlled conflict detection=1.00 and no silent overwrite.

### Task 8: Human approval, same snapshot, and A→B→A rollback

- [ ] **Step 1: Write MVP6 RED test**

Story: build candidate A → unauthorized approval denied → named human approves exact manifest → promote A → Human/MCP exact same facts/hash → apply later revision/review → approve/promote B → rollback to still-approved A with stale-CAS and zero-model assertions.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_serving_rollback_030.py
```

- [ ] **Step 3: Verify immutable changelog evidence**

Assert manifest/approval/CurrentRelease and source/ChangeSet/revision audit form A→B→A; rollback does not erase B or regenerate facts.

- [ ] **Step 4: Re-run GREEN**

Expected: Human/MCP hashes/facts match at A, B, and rolled-back A; provider fake count does not change during rollback.

### Task 9: Restart/idempotency and bounded concurrency

- [ ] **Step 1: Write MVP7 RED tests**

Inject failure after verify/checkpoint, restart executor, assert earlier successful stage attempts do not increase; replay same run produces no duplicate facts/ChangeSets; more than configured worker count remains queued; blocked attempt has Alert.

- [ ] **Step 2: Run RED/GREEN loop**

```bash
cd harness
uv run pytest -q tests/test_mvp_recovery_030.py
```

Production failures go to S owner; I1 only updates integration fixtures/assertions when the spec was wrong.

### Task 10: Authorized real 23-source compile, human governance, and final seal

- [ ] **Step 1: Freeze the exact non-secret run request and preflight gates**

Before dispatching I1, write and hash `run-request.yaml`. It must contain the exact `dataset/mvp_v0_1/manifest.yaml` path/hash, 030 admission path/hash/status, bound `space_id`, integration commit SHA, approved template lock/hashes, immutable model-plan/deployment identities, worker/attempt/time/token caps, and `apply: true`. It contains no DB/provider credentials. Require `NS-RIGHTS=recorded`, 027 verified, exact 030 admission READY, single bound KnowledgeSpace, local WeKnora/PostgreSQL health, and a clean recorded integration SHA. Do not use 020 approval.

- [ ] **Step 2: Run zero-model manifest/admission tests immediately before live**

```bash
cd harness
uv run pytest -q tests/test_mvp_manifest_030.py tests/test_mvp_admission_030.py
```

Expected: PASS with current bytes/hashes.

- [ ] **Step 3: Execute the one frozen compilation command once**

```bash
cd harness
uv run python -m insurance_harness.runtime.cli run-manifest \
  --request ../openspec/changes/030-enterprise-wiki-mvp-slice/run-request.yaml \
  --output-dir ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run
```

The CLI contract is owned by 028: the output directory must not already exist; approved runtime environment supplies secrets without CLI arguments. Expected compilation success is exit `0`. Exit `2` means preflight/gate/config rejection and must prove zero model calls; exit `3` means execution began but ended blocked/failed and must retain partial receipts/Alerts. Never loop or invoke a second compilation runner to turn a nonzero result green.

On exit `0`, `artifacts/live-run/` must contain `run-summary.json`, `jobs.jsonl`, `stage-runs.jsonl`, `attempts.jsonl`, `receipts.jsonl`, `alerts.jsonl`, `metrics.json`, `governance-proposals.json`, and last-written `compilation-manifest.json`. The manifest hashes/counts every compiler-produced file and binds the real run's ChangeSet/ReviewItem identifiers. At this point `CurrentRelease` is unchanged, the run is `AWAITING_HUMAN_REVIEW`, and `release-proof.json`/final `artifact-manifest.json` must not exist.

- [ ] **Step 4: A named human reviews and applies every blocking decision**

The designated reviewer inspects the exact ChangeSets, ChangeItems, conflicts, Evidence, and ReviewItems referenced by `governance-proposals.json`. Only after that inspection, the human writes `artifacts/live-run/human-input/review-decisions.yaml` with the literal `compilation_manifest_hash` and, for every blocking ReviewItem, `review_id`, `expected_version`, explicit `approve` or `reject`, named principal, authorization receipt, and reason. An agent may validate the file but may not author decisions, invent a principal, or turn `defer` into approval.

Apply the human-authored file exactly once:

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli apply-review-decisions \
  --request ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/human-input/review-decisions.yaml \
  --compilation-manifest ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/compilation-manifest.json \
  --output ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/review-receipt.json
```

The command must use existing review services with optimistic version checks. Missing, stale, deferred, wrong-Space, unauthorized, incomplete, or compilation-hash-mismatched decisions fail closed; no candidate or release is produced.

- [ ] **Step 5: Build the reviewed candidate without promoting it**

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli build-candidate \
  --run-request ../openspec/changes/030-enterprise-wiki-mvp-slice/run-request.yaml \
  --review-receipt ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/review-receipt.json \
  --output-dir ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/candidate
```

This governance-only command rechecks `compilation-manifest.json`, complete review coverage, and the run/Space binding, then uses the 018 staging snapshot builder and 029 manifest builder. It must create `candidate/candidate-snapshot.json` and `candidate/release-manifest.json` with no model/runtime-stage call and no `CurrentRelease` movement.

- [ ] **Step 6: A separately authorized human approves the literal manifest hash, then CAS-promote**

The release authority opens `candidate/release-manifest.json`, verifies its four canonical artifact sections and overall hash, checks the current release, and only then writes `artifacts/live-run/human-input/release-approval-request.yaml`. That file must contain the literal 64-hex `manifest_hash`, exact `snapshot_id`, explicit `expected_current_snapshot_id` (including explicit null when there is no current release), named human principal, authorization receipt, and reason. It cannot be generated or filled from defaults by the CLI.

Run approval and promotion as separate commands:

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli approve-manifest \
  --request ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/human-input/release-approval-request.yaml \
  --manifest ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/candidate/release-manifest.json \
  --output ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/approval-receipt.json

uv run python -m insurance_harness.knowledge.release_cli promote-approved \
  --request ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/human-input/release-approval-request.yaml \
  --manifest ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/candidate/release-manifest.json \
  --approval-receipt ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/approval-receipt.json \
  --output ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/release-proof.json
```

`approve-manifest` only appends the exact-hash approval and leaves CurrentRelease unchanged. `promote-approved` revalidates the manifest/request/receipt and performs RA3 expected-current CAS. Stale current, altered manifest, wrong actor/Space, or substituted receipt fails closed; there is no automatic retry or approval refresh.

- [ ] **Step 7: Verify real metrics and both readers, then seal the final artifact manifest last**

```bash
cd harness
MVP_LIVE_ARTIFACT_DIR=../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run \
MVP_SERVING_PROOF_PATH=../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/serving-proof.json \
uv run pytest -q tests/test_mvp_live_030.py -m live

uv run python -m insurance_harness.knowledge.release_cli seal-run-artifacts \
  --directory ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run \
  --compilation-manifest ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/compilation-manifest.json \
  --release-proof ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/release-proof.json \
  --serving-proof ../openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/live-run/serving-proof.json
```

All selected live tests must execute with skipped=0. Only after metric thresholds pass and Human Reader/MCP return the exact promoted `snapshot_id`, manifest hash, canonical facts, Evidence, and ordering may the test exclusive-create `serving-proof.json`. `seal-run-artifacts` rechecks the unchanged compilation bundle, review/candidate/approval/release chain, and serving proof, then exclusive-creates `artifact-manifest.json` as the final file. It hashes/counts every preceding compiler, human-input, governance, candidate, release, metric, and serving artifact; raw secrets/provider bodies never enter the bundle. Only this state is overall Task 10 PASS.

- [ ] **Step 8: Handle external or human-governance blocking honestly**

If provider/WeKnora/credentials are unavailable, stop with compiler exit `2`/`BLOCKED` and the failed precondition. If a terminal runtime failure occurs after start, preserve the exit `3` partial artifact set and return the finding to its S/K/M owner. If the designated humans have not reviewed/authorized, report `AWAITING_HUMAN_REVIEW` or `AWAITING_RELEASE_APPROVAL`; compiler exit `0` is not MVP PASS. A rejected/deferred review, stale CAS, metric failure, or reader mismatch preserves its evidence and stops before final seal. Do not substitute replay data, synthesize human input, rerun the compiler, or expand scope while waiting. If live is not authorized, do not run and report `NOT RUN`.

### Task 11: Final validation, review, and Roadmap rebaseline

- [ ] **Step 1: Run all 030 deterministic/PG contracts**

```bash
cd harness
uv run pytest -q tests/test_mvp_manifest_030.py tests/test_mvp_admission_030.py tests/test_mvp_routing_quality_030.py tests/test_mvp_structured_governance_030.py tests/test_mvp_update_conflict_030.py tests/test_mvp_serving_rollback_030.py tests/test_mvp_recovery_030.py
uv run pytest -q -m integration_postgres tests/test_mvp_update_conflict_030.py tests/test_mvp_serving_rollback_030.py tests/test_mvp_recovery_030.py
```

Expected: PASS; selected PG tests execute with skipped=0.

- [ ] **Step 2: Complete `validation-report.md`**

Include exact input/commit/template/model identities; per-product metrics; Evidence/conflict/pollution results; A→B→A hashes; recovery proof; all alerts; deterministic/PG/live commands; every NOT RUN/BLOCKED; and seven-stage time per PR. Do not collapse review wait/provider wait into coding time.

- [ ] **Step 3: Independent spec review, then independent quality review**

Reviewers do not edit code. Findings go to original S/K/M owner. Maximum two remediation rounds; G arbitrates the third.

- [ ] **Step 4: One final full deterministic/CI run**

Only after all clause reviews close. Record count/time separately; CI independently repeats. This is the sole full-suite run for final integration readiness.

- [ ] **Step 5: G final release decision and human commit boundary**

G marks MVP PASS only if all ten control-board exit conditions have evidence. Otherwise mark PARTIAL/BLOCKED with owner/next action. Re-estimate M2 from measured seven-stage times. Do not commit/push from the AI session.
