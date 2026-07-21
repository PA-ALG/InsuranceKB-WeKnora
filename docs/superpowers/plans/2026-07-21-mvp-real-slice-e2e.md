# MVP Real Slice End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 030 by freezing and admitting the 23-entry/5-product MVP slice, then prove the complete product-registration plus document/structured-fact intake→weak-model runtime→Evidence→merge/conflict→human approval→Human/MCP same-snapshot→update/rollback story with honest deterministic, PostgreSQL, WeKnora, and provider evidence.

**Architecture:** I0a owns data manifests, controlled fixtures, Golden Slice, and unsigned admission/request templates independent of blocked 020. After 027 lands, I0b implements a minimal run-admission core parameterized by a code-owned `purpose + run_schema_version` profile registry; MVP registers only `enterprise-wiki-mvp`. Its profile implements the 027 `AdmissionVerifier`: it verifies a domain-separated, root-policy-authorized human approval, compares every independently requested field with actual signed content, and returns an opaque `VerifiedAdmission` whose `AdmissionBinding` is a read-only view. Arbitrary CLI/YAML profiles/roles fail closed, and it does not reuse the 020 evaluator whose dataset/roles are hard-coded. The one 028 manifest dispatcher routes five exact metadata entries to registration-only, the registered FAQ to 010 structured governance, and only knowledge-eligible documents to parent/child compilation jobs; all three branches contribute receipts/counts/hashes to one sealed compilation manifest. I1 starts from a clean integration commit after S/K/M changes land, writes cross-package contract/E2E tests and sanitized reports, never repairs other feature-domain code, and runs the real slice only after 027 plus the exact external 030 admission are READY.

**Tech Stack:** YAML/JSON manifests, Pydantic v2, audited canonicalization/Ed25519 primitives, 027 `AdmissionVerifier`/opaque `VerifiedAdmission`, pytest, PostgreSQL integration lane, local WeKnora live environment, approved MiniMax/Qwen/Qwen-VL provider plan.

---

## Authority, sessions, and non-negotiable boundaries

- Spec: `openspec/changes/030-enterprise-wiki-mvp-slice/` (MVP1–MVP7).
- Frozen range: 23 manifest entries = 15 PDFs + 5 registration-only `product_meta.json` files across 5 products + mixed-product document + later revision/conflict document + known-schema FAQ JSON.
- I0a can start Day 1 and touches no production module. I0b starts after 027 and owns only the minimal `run_admission/` core, root-protected `trust_policy.py`, code-owned `profiles/mvp.py`, its tests, unsigned templates, and sanitized artifact indexes; it neither imports 020 policy/evaluator constants nor changes 020 artifacts. Final signed envelopes, strict requests, human inputs, and live outputs stay in a repository-external content-addressed store. General profile authoring/DSL/UI and 020 migration are out of scope. I1 starts only after 027/028/029/010-thin/013-core/032 are available on one clean integration baseline.
- Risk: **A** for admission/release/Space, **B** for extraction/routing/quality, **C** for report/runbook.
- Use @superpowers:test-driven-development for contracts, @superpowers:systematic-debugging for integration failures, and @superpowers:verification-before-completion for final claims.
- I1 does not fix S/K/M production code. It files a finding with owner, exact reproduction, expected clause, and evidence; G decides re-run order.
- Never edit or borrow `openspec/changes/020-golden-v01-baseline-run/run-admission.*`.
- This campaign has explicit business-owner authorization for execution sessions to commit, push, and open ready PRs after verification; they SHALL NOT self-merge.

## File map

### I0 create

- `dataset/mvp_v0_1/manifest.yaml` — 23 exact entries/hashes/roles/product expectations/provenance and registration/source eligibility.
- `dataset/mvp_v0_1/expected_routes.yaml` — document/section/fact ownership and unassigned expectations.
- `dataset/mvp_v0_1/golden_slice.yaml` — annotated fields/tri-state/Evidence/conflict expectations.
- `dataset/mvp_v0_1/fixtures/mixed-product-source.md`
- `dataset/mvp_v0_1/fixtures/product-update-conflict-v2.md`
- `dataset/mvp_v0_1/fixtures/known-faq-source.json`
- `harness/tests/test_mvp_manifest_030.py`
- `harness/tests/test_mvp_admission_030.py`
- `harness/src/insurance_harness/run_admission/__init__.py` — stable exports; no 020 constants.
- `harness/src/insurance_harness/run_admission/models.py` — generic frozen purpose/schema/profile/approval inputs and typed outcomes.
- `harness/src/insurance_harness/run_admission/evaluator.py` — code-owned profile registry and 027 `AdmissionVerifier` implementation: canonical hash/signature/current-content verification, strict-request full-field comparison, and controlled opaque `VerifiedAdmission` issuance.
- `harness/src/insurance_harness/run_admission/trust_policy.py` — root-protected deployment policy mapping `key_id + public-key fingerprint` to named human identity, approver role, signature domain, allowed purpose/schema and Spaces; no artifact/request/CLI override.
- `harness/src/insurance_harness/run_admission/profiles/mvp.py` — the only MVP-registered purpose/schema and exact role/content validator.
- `harness/src/insurance_harness/run_admission/cli.py` — render unsigned payload and verify/seal commands only; no arbitrary profile/schema/role loading, signing key generation, trust-root override, provider mutation, or model call.
- `openspec/changes/030-enterprise-wiki-mvp-slice/admission-plan.template.yaml` — unsigned schema/example only; no signature, READY state, real key, run identity or live digest.
- `openspec/changes/030-enterprise-wiki-mvp-slice/run-request.template.yaml` — unsigned strict-request shape only; final request is created externally after the clean integration SHA and signed envelope digest exist.
- `openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/index.template.json` — schema for a later sanitized digest/status index; no signed envelope, human decision or raw provider body.

### I1 create

- `harness/tests/test_mvp_routing_quality_030.py`
- `harness/tests/test_mvp_structured_governance_030.py`
- `harness/tests/test_mvp_update_conflict_030.py`
- `harness/tests/test_mvp_serving_rollback_030.py`
- `harness/tests/test_mvp_recovery_030.py`
- `harness/tests/test_mvp_live_030.py` — explicitly marked `live`, no silent skip accepted in an authorized live run.
- `openspec/changes/030-enterprise-wiki-mvp-slice/runbook.md`
- `openspec/changes/030-enterprise-wiki-mvp-slice/validation-report.md`
- `openspec/changes/030-enterprise-wiki-mvp-slice/artifacts/index.json` — post-run sanitized digest/status/metric index only; it references external immutable artifacts by digest and contains no signature, human decision, secret, prompt, raw response, or trusted capability.

The final signed approval envelope, final strict request, compiler output, review decisions, release-approval request, and release/serving proofs live only under a root-protected, repository-external content-addressed run store. During the authorized run, `human-input/review-decisions.yaml` and `release-approval-request.yaml` are created there only by the named human reviewers at the gates below. They are not generated or pre-filled by the compiler, an agent, or a test fixture. Git records only unsigned templates plus a later sanitized index/report. This avoids the impossible cycle of signing integration SHA `X` and then changing `X` by committing the signed request: the human signs clean `X`, the external request binds `X + envelope digest`, the run executes from clean `X`, and reporting is committed afterwards.

### Task 1: Freeze the exact 20 existing inputs

- [ ] **Step 1: Write manifest RED tests**

Test exactly five allowed product directories, each with three PDFs and `product_meta.json`; exactly 20 existing entries; no symlink/outside-dataset path; SHA-256, byte size, input kind, document type, expected product/version, and rights/provenance non-empty. Every `product_meta` entry is registration-only with `claim_evidence_eligible=false`; every PDF is knowledge-source eligible.

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

Expected: exactly 20 real entries PASS with 15 knowledge-source eligible and 5 registration-only; any byte drift fails.

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

Expected: exactly 23 entries, five products, three business shapes, one mixed, one update/conflict, one FAQ.

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

### Task 4: Create an independent zero-model MVP admission profile (I0b, after 027)

- [ ] **Step 1: Write MVP1 admission RED tests**

Test code-owned registration and rejection of unknown `purpose/run_schema_version/role`; run ID/revision, all 23 entry hashes/eligibility, Golden Slice hash, Space, schema/template/structured-dispatch/model-plan identities, provider immutable revisions/roles, budget/attempt/time caps and resource-caps hash, rights/provenance, clean integration SHA, expiry, approval envelope, and explicit inequality with 020 run identity. Freeze the 027 contract `AdmissionVerifier.verify(StrictAdmissionRequestBinding) -> VerifiedAdmission`: only the opaque return value is authority, while its read-only binding view must retain each signed actual value and the full `verified_binding_digest`. Table-driven mutation of every request field must block before any job/model fake call. The request carries independent expected purpose/schema/Space/run identity/revision plus external admission ref+digest; neither evaluator nor 027 may derive both sides from the artifact. Add architecture probes proving the adapter does not import/call the 020 hard-coded evaluator or its dataset/role constants. Any input drift, cross-Space/profile/domain replay, arbitrary CLI/YAML profile, YAML self-declared READY, caller-constructed binding/capability, missing/untrusted/expired signature, trust override, or 020 artifact yields typed BLOCKED before model fake call.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mvp_admission_030.py
```

- [ ] **Step 3: Implement the dedicated MVP profile adapter and build artifacts through it**

Implement frozen generic plan/approval DTOs and a code-owned registry keyed by purpose/schema version. Only the MVP profile is registered in this slice; it freezes exact allowed roles and payload fields. Use domain-separated signed bytes (`insurancekb.run-admission.enterprise-wiki-mvp.v1\0` or an equivalently versioned unique domain), root-protected trust-policy verification, current-content hashing, derived READY/BLOCKED state, exact strict-request comparison, and the 027 controlled issuer path to return opaque `VerifiedAdmission` with a rich read-only binding. `trust_policy.py` maps `key_id + public-key fingerprint` to a named human, `mvp-run-admission-approver` role, signature domain, allowed purpose/schema and Spaces; none of these authorities can come from the envelope, request, environment variable or CLI. The CLI may render an unsigned payload and verify a separately supplied external human envelope; it must not generate/sign with the approval key, self-enroll a key, accept runtime profile/schema/role definitions, accept a trust-root override, or write signed output into Git. Do not import 020 evaluator/policy constants or manually fabricate signed/approved state. The designated human authorizes the exact run/Space/manifest/eligibility/Golden/routing/schema/template/structured-dispatch/model/deployment/cap/rights/provenance/clean-integration-SHA envelope only after integration SHA `X` is known; the final external strict request then binds `X` and the envelope digest. Until then status remains `PENDING/BLOCKED`; I0a remains a valid data PR while I0b can prove all rejection paths with non-authority fixtures.

- [ ] **Step 4: Run zero-model GREEN**

Expected: admission verifier PASS only with a matching trusted human envelope, root-policy-authorized signer and exact current inputs; it yields an opaque 027 `VerifiedAdmission` whose binding view matches all actual fields. A 020 artifact and every mismatched/unsigned/forged-capability case are BLOCKED; counting provider remains zero.

- [ ] **Step 5: Independent I0 review and human commit boundary**

Review I0a for entry count/hash/provenance, controlled expectations, metric denominator, and dual-channel eligibility; commit/push it as a data-only ready PR after checks. Review I0b separately at risk A for signature domain/trust policy, expected-vs-actual identity, expiry/content drift, 020 isolation, and zero provider calls; commit/push a second ready PR after checks. Neither PR self-merges.

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

Use deterministic replay/scripted weak-model outputs first. Assert one parent intake job per knowledge-eligible document SourceRevision; registration-only metadata and 010 structured fact records create no fake runtime job. The mixed document deterministically reuses two exact product/template children; its ambiguous section produces only unassigned+Alert/ReviewItem and is absent from child model inputs. Also assert template hash pinning, ordinary/dividend separation, precision≥0.90, recall≥0.85, approved Evidence=1.00, pollution=0.

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

Inject failure after a product child's verify checkpoint, restart executor, assert its successful parent stages/fan-out and child extract attempt do not increase; replay same run reuses parent/child identities and produces no duplicate unassigned records, facts, or ChangeSets; more than configured worker count remains queued; blocked attempt has Alert.

- [ ] **Step 2: Run RED/GREEN loop**

```bash
cd harness
uv run pytest -q tests/test_mvp_recovery_030.py
```

Production failures go to S owner; I1 only updates integration fixtures/assertions when the spec was wrong.

### Task 10: Authorized real 23-entry compile, human governance, and final seal

- [ ] **Step 1: Freeze the exact non-secret run request and preflight gates**

From a clean integration commit `X`, render the unsigned payload, obtain the named human's domain-separated signature, and store the final envelope in the root-protected external content-addressed run store. Then create the final strict request in that store and bind its digest to: independent expected purpose/schema/Space/run identity/revision; exact 23-entry manifest path/hash/eligibility hash; external 030 admission ref/hash; Golden Slice, routing-policy, schema/template-lock and structured-dispatch-lock hashes; immutable model-plan/deployment-role identities; rights/provenance; clean integration commit `X`; worker/attempt/time/token caps plus canonical resource-caps hash; and `apply: true`. The structured-dispatch lock includes the exact five meta entry path+hash pairs, registered structured-source identity/authority/record-schema refs, adapter/canonicalizer versions, source-profile fingerprints, mapping manifests and effective mapping versions. The request contains no DB/provider credentials and no trusted READY boolean. Require `NS-RIGHTS=recorded`, 027 verified, canonical `AdmissionVerifier.verify(...)` returning opaque `VerifiedAdmission` with an exact full-field 030 binding view, one bound KnowledgeSpace, local WeKnora/PostgreSQL health, and a clean checkout of `X`. Do not use 020 approval. Neither final request nor signed envelope is committed to Git.

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
  --request "$MVP_RUN_DIR/run-request.yaml" \
  --output-dir "$MVP_RUN_DIR/live-run"
```

`MVP_RUN_DIR` is a deployment-supplied pointer to the root-protected external content-addressed store, not authority or a substitute for content verification. The CLI recomputes the canonical request digest and verifies its content-addressed reference internally; it does not trust a caller-supplied digest. The output directory must not already exist; approved runtime environment supplies secrets without CLI arguments. It first verifies the entire sealed manifest and dispatches every entry through exactly one branch: exact-entry product registration, registered structured FAQ import, or document compilation. Registration and structured branches create no fake `CompilationJob` and make zero model calls; all three branches emit canonical receipts/counts/hashes into the same final compilation manifest. Expected compilation success is exit `0`. Exit `2` means preflight/gate/config rejection and must prove zero job/write/model calls; exit `3` means execution began but ended blocked/failed and must retain partial receipts/Alerts. Never loop or invoke a second compilation runner to turn a nonzero result green.

On exit `0`, external `$MVP_RUN_DIR/live-run/` must contain `run-summary.json`, `jobs.jsonl`, `stage-runs.jsonl`, `attempts.jsonl`, `receipts.jsonl`, `alerts.jsonl`, `metrics.json`, `governance-proposals.json`, branch receipts/counts/hashes, and last-written `compilation-manifest.json`. The manifest hashes/counts every compiler-produced file and binds the real run's ChangeSet/ReviewItem identifiers. At this point `CurrentRelease` is unchanged, the run is `AWAITING_HUMAN_REVIEW`, and `release-proof.json`/final `artifact-manifest.json` must not exist.

- [ ] **Step 4: A named human reviews and applies every blocking decision**

The designated reviewer inspects the exact ChangeSets, ChangeItems, conflicts, Evidence, and ReviewItems referenced by `governance-proposals.json`. Only after that inspection, the human writes external `$MVP_RUN_DIR/live-run/human-input/review-decisions.yaml` with the literal `compilation_manifest_hash` and, for every blocking ReviewItem, `review_id`, `expected_version`, explicit `approve` or `reject`, named principal, authorization receipt, and reason. An agent may validate the file but may not author decisions, invent a principal, or turn `defer` into approval.

Apply the human-authored file exactly once:

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli apply-review-decisions \
  --request "$MVP_RUN_DIR/live-run/human-input/review-decisions.yaml" \
  --compilation-manifest "$MVP_RUN_DIR/live-run/compilation-manifest.json" \
  --output "$MVP_RUN_DIR/live-run/review-receipt.json"
```

The command must use existing review services with optimistic version checks. Missing, stale, deferred, wrong-Space, unauthorized, incomplete, or compilation-hash-mismatched decisions fail closed; no candidate or release is produced.

- [ ] **Step 5: Build the reviewed candidate without promoting it**

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli build-candidate \
  --run-request "$MVP_RUN_DIR/run-request.yaml" \
  --review-receipt "$MVP_RUN_DIR/live-run/review-receipt.json" \
  --output-dir "$MVP_RUN_DIR/live-run/candidate"
```

This governance-only command rechecks `compilation-manifest.json`, complete review coverage, and the run/Space binding, then uses the 018 staging snapshot builder and 029 manifest builder. It must create `candidate/candidate-snapshot.json` and `candidate/release-manifest.json` with no model/runtime-stage call and no `CurrentRelease` movement.

- [ ] **Step 6: A separately authorized human approves the literal manifest hash, then CAS-promote**

The release authority opens external `candidate/release-manifest.json`, verifies its four canonical artifact sections and overall hash, checks the current release, and only then writes `$MVP_RUN_DIR/live-run/human-input/release-approval-request.yaml`. That file must contain the literal 64-hex `manifest_hash`, exact `snapshot_id`, explicit `expected_current_snapshot_id` (including explicit null when there is no current release), named human principal, authorization receipt, and reason. It cannot be generated or filled from defaults by the CLI and is never committed to Git.

Run approval and promotion as separate commands:

```bash
cd harness
uv run python -m insurance_harness.knowledge.release_cli approve-manifest \
  --request "$MVP_RUN_DIR/live-run/human-input/release-approval-request.yaml" \
  --manifest "$MVP_RUN_DIR/live-run/candidate/release-manifest.json" \
  --output "$MVP_RUN_DIR/live-run/approval-receipt.json"

uv run python -m insurance_harness.knowledge.release_cli promote-approved \
  --request "$MVP_RUN_DIR/live-run/human-input/release-approval-request.yaml" \
  --manifest "$MVP_RUN_DIR/live-run/candidate/release-manifest.json" \
  --approval-receipt "$MVP_RUN_DIR/live-run/approval-receipt.json" \
  --output "$MVP_RUN_DIR/live-run/release-proof.json"
```

`approve-manifest` only appends the exact-hash approval and leaves CurrentRelease unchanged. `promote-approved` revalidates the manifest/request/receipt and performs RA3 expected-current CAS. Stale current, altered manifest, wrong actor/Space, or substituted receipt fails closed; there is no automatic retry or approval refresh.

- [ ] **Step 7: Verify real metrics and both readers, then seal the final artifact manifest last**

```bash
cd harness
MVP_LIVE_ARTIFACT_DIR="$MVP_RUN_DIR/live-run" \
MVP_SERVING_PROOF_PATH="$MVP_RUN_DIR/live-run/serving-proof.json" \
uv run pytest -q tests/test_mvp_live_030.py -m live

uv run python -m insurance_harness.knowledge.release_cli seal-run-artifacts \
  --directory "$MVP_RUN_DIR/live-run" \
  --compilation-manifest "$MVP_RUN_DIR/live-run/compilation-manifest.json" \
  --release-proof "$MVP_RUN_DIR/live-run/release-proof.json" \
  --serving-proof "$MVP_RUN_DIR/live-run/serving-proof.json"
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

G marks MVP PASS only if all ten control-board exit conditions have evidence. Otherwise mark PARTIAL/BLOCKED with owner/next action. Re-estimate M2 from measured seven-stage times. The I1 execution session may commit/push sanitized tests/runbook/index/report and open a ready PR under this campaign's explicit authorization; signed envelopes, strict requests, human decisions and live bundles remain external. I1 does not self-merge; G independently reviews and decides merge.
