# Operational Run Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fail-closed operational admission layer that can prove 13-product input/provenance identity, govern real deployment fixed costs, and either produce an auditable READY or an honest typed BLOCKED without model inference.

**Architecture:** Keep 020's admission/budget runtime intact and add three focused boundaries: repository-derived provenance, offline authority/trust, and crash-safe deployment operations. All externally mutable actions consume a signed, domain-separated authorization and a durable infrastructure reserve before network I/O; current deployments use a separate adoption path. A coordinator projects these proofs into the existing final plan and metadata probe, but never weakens the provider-cap or human-signature requirements.

**Tech Stack:** Python 3.12, Pydantic v2, cryptography Ed25519, SQLite WAL/transactions, httpx, pytest, Ruff, mypy strict, OpenSpec.

---

## File map and boundaries

- `admission_models.py`: only cross-cutting immutable plan/provenance/approval types and canonical signature verification.
- `admission_identity.py`: repository identity and provenance proof validation; no provider calls.
- `admission_authority.py` (new): trust policy plus safe offline keygen/render/sign/verify primitives; no run execution.
- `admission_infrastructure.py` (new): immutable authorization, signed price/cap and receipt models plus pure validation/cost derivation.
- `admission_budget.py`: schema v5 and the single transactional owner of infrastructure and request/token reserves; no second budget database.
- `admission_deployment.py` (new): Bailian request allowlist, durable journal, reconcile/create/delete state machine; injectable transport for deterministic tests.
- `operational_admission_031.py` (new): O8 orchestration and typed status report; it composes existing 020 admission/probe APIs and contains no provider-specific parsing.
- `operational_admission_cli_031.py` (new): explicit operator commands; render/verify are read-only, provision/adopt/cleanup require their corresponding proof.
- `.gitignore`: explicit local key/staging-material exclusions; production key paths remain outside the repository.
- Existing 020 modules remain compatible except for the intentionally discriminated provenance union and trust-policy loader extension.

### Task 1: O1 canonical product-meta input

**Files:**
- Rename: `dataset/shouxian_product/平安福满分（2026）养老年金保险/product_meta.txt` → `dataset/shouxian_product/平安福满分（2026）养老年金保险/product_meta.json`
- Test: `harness/tests/test_operational_input_031.py`
- Modify: `openspec/changes/031-operational-run-admission/tasks.md`

- [ ] **Step 1: Write failing byte/semantic and clean-revision tests**

Test O1 against a temporary Git fixture: the old bytes parse as JSON, the target bytes are identical, and after committing the rename the inspector recomputes product, shared-input and execution-surface digests at that exact clean SHA. Assert the old path is absent rather than ignored, and prove dirty/uncommitted input cannot be emitted as authoritative identity.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd harness && uv run pytest tests/test_operational_input_031.py -q`
Expected: FAIL because production still contains `product_meta.txt`.

- [ ] **Step 3: Implement the fixture recomputation and perform only a production Git rename**

Use `mv`/Git rename without serialization or formatting. Capture SHA-256 `f074916cec067cfd1c173afba2a0460a22c6e24a2d7085518ae49ffc531aa9ae` and assert the target digest is identical. The test's clean commit proves recomputation; the real worktree remains non-authoritative until a human commit creates a clean SHA.

- [ ] **Step 4: Run O1 and identity regression tests; record the production clean-SHA dependency**

Run: `cd harness && uv run pytest tests/test_operational_input_031.py tests/test_run_admission_identity_020.py -q`
Expected: PASS. The validation report must state that production identity regeneration is pending the later human commit; it must never reuse the pre-rename SHA.

- [ ] **Step 5: Update T1 checkboxes (human commit checkpoint)**

AI workers update `tasks.md`; per repository policy they do not commit or push.

### Task 2: O2 discriminated repository-derived provenance

**Files:**
- Modify: `harness/src/insurance_harness/goldenset/admission_models.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_identity.py`
- Create: `harness/tests/test_operational_provenance_031.py`
- Modify: affected `harness/tests/test_run_admission_*_020.py` fixtures to use explicit observed discriminator

- [ ] **Step 1: Write failing model tests for the union**

Require `provenance_kind` to discriminate:

```python
class ObservedAnnotationProvenance(ProvenanceApprovalEntry):
    provenance_kind: Literal["observed_annotation"]

class LegacyFrozenProvenance(_ImmutableModel):
    provenance_kind: Literal["legacy_frozen"]
    product_id: NonBlankStr
    product_digest: Sha256Digest
    wip_digest: Sha256Digest
    frozen_commit: GitObjectId
    evidence_path: NonBlankStr
    evidence_blob_id: GitObjectId
    evidence_digest: Sha256Digest
    recorded_agent_id: NonBlankStr
    evidence_frozen_at: datetime
    limitation: Literal["original_annotation_time_unavailable"]
```

`GitObjectId` accepts lowercase hexadecimal 40- or 64-character syntax, while the evidence inspector
queries `git rev-parse --show-object-format` and requires the exact OID length/algorithm used by that
repository. `Sha256Digest` remains mandatory for independently calculated content digests. Use
`Annotated[ObservedAnnotationProvenance | LegacyFrozenProvenance, Field(discriminator="provenance_kind")]`;
reject missing/unknown discriminator and forbid synthetic annotation windows on legacy entries.

- [ ] **Step 2: Run the model test and verify RED**

Run: `cd harness && uv run pytest tests/test_operational_provenance_031.py -q`
Expected: FAIL because the classes/union do not exist.

- [ ] **Step 3: Implement the minimal immutable union**

Export the new types, replace `HistoricalProvenance` in `IdentityInspectionRequest`, and update 020 fixtures to declare `observed_annotation`; do not add a permissive legacy alias/default.

- [ ] **Step 4: Write failing Git evidence-inspector tests**

Create temporary SHA-1 Git histories that cover valid 40-character commit/blob OIDs, invalid length/
case/non-hex OIDs, valid ancestor/blob, non-ancestor commit, missing blob, content drift,
caller-supplied agent mismatch, duplicate/missing products, naive freeze time and fixed-limitation
violation. Where Git supports a SHA-256 fixture, cover valid 64-character OIDs too; otherwise unit-test
the detected-format length rule. Expected results are typed blockers, not uncaught Git errors.

- [ ] **Step 5: Implement repository-derived validation**

Add a `LegacyProvenanceEvidenceInspector` that resolves commit ancestry and blob bytes using literal Git pathspecs, calculates digests itself, derives agent ID only from a code allowlist matched to repository evidence, and validates exactly the 11 historical IDs. Never execute hooks or accept shell fragments.

- [ ] **Step 6: Bind full entries into existing hashes/signatures**

Confirm `identity_contract_hash()` and `ProvenanceApprovalPayload` canonical JSON include every union field; a valid candidate without a provenance envelope remains `approval_missing`.

- [ ] **Step 7: Run focused and 020 provenance regressions**

Run: `cd harness && uv run pytest tests/test_operational_provenance_031.py tests/test_run_admission_identity_020.py tests/test_run_admission_models_020.py -q`
Expected: PASS.

### Task 3: O3 key policy and offline signing ceremony

**Files:**
- Create: `harness/src/insurance_harness/goldenset/admission_authority.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_cli.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_models.py`
- Modify: `.gitignore`
- Create: `harness/tests/test_operational_authority_031.py`

- [ ] **Step 1: Write failing policy and path-security tests**

Define `TrustedKeyPolicy(key_id, approver_identity, domains, scopes, roles, public_key)` and test exact identity/domain/scope/role matching. Cover self-enrollment, symlink parent/file, wrong owner where testable, mode other than 0600, hard-link/replace race, oversized key, stdout/stderr leakage, existing-file overwrite, and any private/staging material located below the repository root.

- [ ] **Step 2: Verify RED**

Run: `cd harness && uv run pytest tests/test_operational_authority_031.py -q`
Expected: FAIL because authority primitives are absent.

- [ ] **Step 3: Implement safe key storage**

Open a trusted parent directory, create private keys with `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`, mode 0600, compare `lstat`/`fstat`, limit encoded bytes, fsync file+directory, and emit only key ID/public key/fingerprint. Signing reopens with nofollow, validates ownership/mode/size and never logs private bytes.

- [ ] **Step 4: Extend signature verification with key policy**

Preserve the existing low-level Ed25519 verifier for deterministic tests, then make the production loader return policies and verify that payload `approver_identity`, domain, scope and role all match the selected key. CLI flags cannot replace the fixed production trust path.

- [ ] **Step 5: Separate CLI commands**

Expose keygen, render, sign and verify as separate commands. `render` produces canonical public payload, `sign` consumes an already-rendered file and private key, and neither mutates trust. Use atomic output for public envelopes.

- [ ] **Step 6: Enforce the repository boundary**

Add explicit `.gitignore` patterns for local key/staging conventions, but do not rely on ignore alone: keygen/sign rejects any private key or temporary signing-material path whose resolved trusted parent is within the repository. Public final envelopes remain eligible for version control.

- [ ] **Step 7: Run authority and 020 CLI regressions**

Run: `cd harness && uv run pytest tests/test_operational_authority_031.py tests/test_run_admission_cli_020.py tests/test_run_admission_models_020.py -q`
Expected: PASS.

### Task 4: O4/O6 authorization and infrastructure ledger

**Files:**
- Create: `harness/src/insurance_harness/goldenset/admission_infrastructure.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_budget.py`
- Create: `harness/tests/test_operational_authorization_031.py`
- Create: `harness/tests/test_operational_infrastructure_ledger_031.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_models.py` only for shared domain typing/export

- [ ] **Step 1: Write failing canonical authorization tests**

Model exact provisioning and adoption payloads. Prefix signed bytes with respectively `insurancekb.run-admission.provisioning.v1\0` and `insurancekb.run-admission.deployment-adoption.v1\0`. Mutation-test every common field: run identity, purpose, scope, operation/reserve, workspace/project/credential, region, base, request/receipt plan mapping, quotas, price/cap evidence, maximum cost and deadline. Adoption additionally binds exact deployed model, receipt digest, `gmt_create`, explicit `preexisting` and `not_preauthorized_by_031` limitations, incurred cost and future maximum cost. Require failure before ledger/network access and prove an adoption envelope can never select the create transition.

- [ ] **Step 2: Implement domain-separated authorization verification**

Provisioning requires role `deployment-provisioner`; adoption requires `budget-approver`. Enforce aware issuance/expiry and code-owned expected values rather than merely verifying internal payload consistency.

- [ ] **Step 3: Write failing SQLite migration/reserve tests**

Specify schema-v5 tables for `infrastructure_reserves`, `deployment_role_bindings`, and authorization digests inside the existing budget database. Test fresh schema, in-place migration from current v4 with exact row preservation/foreign-key checks, repeat reservation, conflicting deployment/reserve, crash rollback, ceiling overflow and annotator/judge sharing one strong reserve.

- [ ] **Step 4: Extend the single BudgetLedger with two ordered transactions**

Increment `BudgetLedger` to schema v5. The pre-POST `BEGIN IMMEDIATE` verifies provisioning authorization plus trusted price/cap, occupies the signed fixed-cost maximum, and inserts stable reserve ID/authorization digest while deployed model and role bindings are still absent. After receipt, a second `BEGIN IMMEDIATE` verifies the final budget approval and binds receipt/deployed model/roles to that existing reserve without adding or enlarging cost. Byte-identical replay returns the same snapshot; semantic conflict, increased cost or overflow rolls back. Recovery reads this same ledger before provider reconciliation. `admission_infrastructure.py` owns models/validation, not storage.

- [ ] **Step 5: Write dedicated failing O6 receipt mutation tests**

Mutation-test operation ID, reserve linkage, request `ptu_v2`→receipt `ptu`, base/deployed model, input/output quotas, every required GMT field, workspace evidence, cleanup state and content digest. Role bindings must reject any violation of `model_id == immutable_deployment_id == deployed_model`; one deployment cannot bind multiple reserves.

- [ ] **Step 6: Implement request/receipt normalization**

Accept only the fixed plan mapping and 10_000/1_000 quotas. Normalize all required receipt fields into canonical bytes, hash them, and validate the hash before role/reserve binding. Multiple roles may bind the same verified reserve.

- [ ] **Step 7: Run focused authorization/ledger tests**

Run: `cd harness && uv run pytest tests/test_operational_authorization_031.py tests/test_operational_infrastructure_ledger_031.py -q`
Expected: PASS.

### Task 5: O5 crash-safe deployment controller

**Files:**
- Create: `harness/src/insurance_harness/goldenset/admission_deployment.py`
- Create: `harness/tests/test_operational_deployment_031.py`
- Reuse: `harness/src/insurance_harness/goldenset/admission_artifacts.py` safe artifact primitives where interfaces fit

- [ ] **Step 1: Write failing fixed-plan and zero-network tests**

Inject a counting fake transport. Any base/alias/region/endpoint/plan/quota/payment/suffix drift or missing authorization/reserve must yield a typed blocker with `post_calls == 0`.

Also construct the production transport factory under hostile `HTTP_PROXY`, `HTTPS_PROXY` and
`ALL_PROXY` environment values and assert its `httpx.Client` is created with `trust_env=False`.

- [ ] **Step 2: Implement immutable request policy**

Code owns two exact base models, Beijing endpoint, `ptu_v2`, 10_000/1_000 quotas and deterministic suffix derived from run+operation. Secrets remain environment references, never model fields or artifacts.

- [ ] **Step 3: Write failing journal/recovery tests**

Cover crash before reserve, after reserve, after pre-send fsync, provider accept then timeout, response lost before receipt, 409, two operators, marker collision, multiple matches, malformed/oversized response and receipt/remote mismatch. Assert at-most-one POST after reconciliation and exact-once reserve.

- [ ] **Step 4: Implement journal and reconciliation**

Acquire a secure run lock; atomically persist `authorized → reserved → prepared → reconciled|created → receipted`. Before every POST, list/reconcile by deterministic marker. After any ambiguous result, never POST until reconciliation establishes zero/one/multiple matches. Multiple or foreign matches block.

The only production HTTP construction seam must instantiate `httpx.Client(..., trust_env=False)`;
callers cannot override this invariant.

- [ ] **Step 5: Persist a redacted content-addressed receipt**

Allowlist deployment/base/plan/quota/status/gmt/workspace/operation fields, cap bytes, reject secrets and absolute paths, hash canonical bytes and atomically install. Re-query remote detail before ownership-dependent transitions.

- [ ] **Step 6: Run deployment controller tests**

Run: `cd harness && uv run pytest tests/test_operational_deployment_031.py -q`
Expected: PASS with all transport call-count assertions.

### Task 6: O7 authoritative pricing, hard cap and cleanup

**Files:**
- Modify: `harness/src/insurance_harness/goldenset/admission_infrastructure.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_deployment.py`
- Create: `harness/tests/test_operational_cost_cleanup_031.py`

- [ ] **Step 1: Write failing price/cap authority tests**

Require evidence bytes plus digest and a trusted signed envelope. Use the independent domains `insurancekb.run-admission.pricing.v1\0` and `insurancekb.run-admission.provider-cap.v1\0`, with exact trust-policy roles `pricing-evidence-approver` and `provider-cap-attestor`. Mutation-test signer identity/role/domain, issuer, currency, cap amount, observed/expiry, region/base/request→receipt plan/quota/effective window/billing quantum/round-up rule and exact workspace/project/credential. Reject self-authored, unsigned, expired and cross-resource evidence before reserve or READY. Compute worst-case fixed reserve and RoleRate; reject caller-provided cost that differs. Cap coverage must explicitly include both infrastructure and inference.

- [ ] **Step 2: Implement mechanical cost derivation**

Parse only the versioned evidence schema, verify trusted signature and freshness before digest/values, round duration upward by the evidence quantum, choose the declared worst-case rate, and expose computed amounts plus evidence/envelope digests. Unknown tier/thinking/cache/overflow is BLOCKED rather than zero.

- [ ] **Step 3: Write failing cleanup authority and ownership tests**

Define `DeploymentCleanupAuthorization` with domain `insurancekb.run-admission.deployment-cleanup.v1\0` and trust-policy role `deployment-cleanup-operator`. It binds exact run/purpose/scope, operation/reserve, receipt/deployed model, workspace/project/credential, expected remote manifest, cleanup reason, issued/expires and deadline. Mutation-test each field plus missing/expired/wrong-domain/wrong-role/cross-resource proofs and assert `delete_calls == 0`; provisioning/adoption authorization and ownership alone are insufficient. With valid cleanup authority, only a verified-owned RUNNING PTU for the same operation may call DELETE. Also test changed manifest, status drift, 404-before-send, timeout/ambiguous delete and any attempted MU stop. Ambiguous results preserve `billing_stop_unverified`.

- [ ] **Step 4: Implement authorized direct-delete reconciliation**

Verify cleanup signature/policy/freshness and exact resource bindings before any remote call, then re-probe detail, compare the receipt manifest, journal pre-delete, call only DELETE, and poll/reconcile to terminal 404/deleted. Install a redacted cleanup receipt; do not mark cost stopped until terminal evidence exists.

- [ ] **Step 5: Run cost/cleanup tests**

Run: `cd harness && uv run pytest tests/test_operational_cost_cleanup_031.py -q`
Expected: PASS.

### Task 7: O8 coordinator, production projection and current-resource report

**Files:**
- Create: `harness/src/insurance_harness/goldenset/operational_admission_031.py`
- Create: `harness/src/insurance_harness/goldenset/operational_admission_cli_031.py`
- Create: `harness/tests/test_operational_state_machine_031.py`
- Modify: `harness/src/insurance_harness/goldenset/run_020.py` only at the composition seam if required
- Modify: `harness/pyproject.toml` for the operator entry point

- [ ] **Step 1: Write failing transition-table tests**

For new resources require `preauth→reserve→create/reconcile→final plan→sign→admit→probe→READY`; for existing resources require `receipt→adoption approval→reserve→final plan→sign→admit→probe→READY`. Every missing/expired/out-of-order proof returns a stable blocker code and performs no later side effect.

- [ ] **Step 2: Implement a pure coordinator state projection**

Represent evidence as immutable snapshots and calculate the next permitted transition. Keep provider mutations behind explicit CLI subcommands. The status/report command is read-only and may render unsigned candidates but cannot sign, reserve, adopt, provision or clean up.

- [ ] **Step 3: Project verified receipts into the 020 plan**

Build role plans only from receipt+reserve bindings: annotator/judge share the strong deployment; weak_extractor uses weak. Preserve exact immutable deployment IDs and the existing `bailian-deployment-detail-v1` probe policy. Call the existing admission evaluator and probe rather than duplicating them.

- [ ] **Step 4: Enforce honest zero-inference reporting**

Count coordinator-controlled inference routes, not account-global activity. READY needs `probes=3`, `verified=3`, controller inference requests=0 plus all identity/approval/budget/cap proofs. Missing provider hard cap or real signatures remains typed BLOCKED even if both deployments are RUNNING.

- [ ] **Step 5: Render, but do not execute, existing-resource adoption candidates**

Bind exact IDs `qwen3.7-plus-2026-05-26-031strng` and `deepseek-v4-flash-031weak1` only after fresh read-only receipt verification. Record preexisting-cost limitation and current exposure. Do not create/delete/adopt without signed approvals and durable reserve.

- [ ] **Step 6: Run state-machine and 020 production regressions**

Run: `cd harness && uv run pytest tests/test_operational_state_machine_031.py tests/test_run_admission_production_wiring_020.py tests/test_run_admission_probe_020.py -q`
Expected: PASS.

### Task 8: Gates, evidence and handoff

**Files:**
- Create: `openspec/changes/031-operational-run-admission/validation-report.md`
- Modify: `openspec/changes/031-operational-run-admission/proposal.md`
- Modify: `openspec/changes/031-operational-run-admission/tasks.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Run all 031 focused tests**

Run: `cd harness && uv run pytest tests/test_operational_*_031.py -q`
Expected: PASS, no skips.

- [ ] **Step 2: Run 020 admission regression**

Run: `cd harness && uv run pytest tests/test_run_admission_*_020.py -q`
Expected: PASS, no unexpected skips.

- [ ] **Step 3: Run repository deterministic gates**

Run the exact commands from `CLAUDE.md`: Ruff, mypy strict, and pytest excluding live/integration_postgres. Record counts and SHA; do not summarize a stale run as current evidence.

- [ ] **Step 4: Validate OpenSpec**

Run: `openspec validate 031-operational-run-admission --strict && openspec validate 020-golden-v01-baseline-run --strict`
Expected: both PASS.

- [ ] **Step 5: Secret and mutation audit**

Review Git diff and generated artifacts for API keys, private key bytes, temporary signing materials, complete provider responses and absolute credential paths. Confirm `.gitignore` boundaries are present, key tooling rejects repository-local private/staging paths, deterministic tests use injected transports and no model-inference endpoint was called.

- [ ] **Step 6: Write validation report and HANDOFF**

Separate (a) implemented software, (b) locally verified gates, and (c) external conditions still required: real approver signatures and a provider hard cap covering fixed+inference spend. Explicitly list the two RUNNING PTUs as a continuing operational cost risk until verified cleanup or adoption.

- [ ] **Step 7: Human commit/PR checkpoint**

Leave the complete, reviewed worktree uncommitted for a human to inspect and commit, following `CLAUDE.md`.
