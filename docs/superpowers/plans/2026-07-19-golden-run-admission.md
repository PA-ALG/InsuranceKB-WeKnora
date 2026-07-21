# Golden v0.1 Run Admission Implementation Plan

> **Execution:** Use `superpowers:subagent-driven-development`. Every task starts
> with `superpowers:test-driven-development`, then receives a specification review
> followed by a code-quality review. Repository policy overrides the generic skill:
> **no AI agent may commit or push**.

**Goal:** Implement change 020 T1 as a fail-closed, zero-inference run-admission and
durable budget boundary, produce an honest `BLOCKED` artifact on the current branch,
and make the future T2/T4 per-product model entrypoints incapable of bypassing it.

**Architecture:** A typed immutable plan is evaluated by deterministic identity,
approval, probe, and runtime-capability checks. Detached Ed25519 envelopes authorize
one run and its historical provenance/budget. A code-owned HTTPS metadata probe never
touches inference routes. A SQLite `BEGIN IMMEDIATE` ledger provides one stable
run-level budget lineage, product reservations, request owner-CAS, crash-safe
`uncertain` accounting, and chained cap increases. Stored `READY` output is audit
only: per-product runtime re-runs the evaluator, reserves budget, and uses an admitted
model wrapper before network I/O.

**Tech stack:** Python 3.12, Pydantic v2, PyYAML, httpx, cryptography Ed25519,
stdlib sqlite3, pytest/respx, Ruff, mypy strict, OpenSpec strict.

**Authoritative contracts:**

- `openspec/changes/020-golden-v01-baseline-run/specs/run/spec.md` D1.1a–D1.5
- `docs/superpowers/specs/2026-07-19-golden-run-admission-design.md`
- `CLAUDE.md` (`trust_env=False`, SDD/TDD, no AI commit/push)

**Non-negotiable execution rules:**

- No real model inference while implementing or testing T1.
- Tests are named with the exact D1 clause.
- Never read or print secret values from `.env.local-live` or another project.
- Do not edit/stage the separate 021 worktree.
- No `--force` or mutable stored `state=READY` trust path.
- Use `/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/*`
  with `PYTHONPATH=src` when `uv` cannot use its sandboxed cache.

---

## Task 1: Typed plan, canonical bytes, and trusted Ed25519 envelopes

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission_models.py`
- Create: `harness/tests/test_run_admission_models_020.py`
- Modify: `harness/pyproject.toml`
- Modify: `harness/uv.lock` (via `uv lock --offline` or the smallest valid lock update)

### Step 1: Write the failing D1 contract tests

Cover at minimum:

```python
def test_d1_1a_requires_exact_three_roles_and_signed_expected_revision() -> None: ...
def test_d1_1d_payload_hash_excludes_approvals_observations_and_state() -> None: ...
def test_d1_1d_canonical_bytes_reject_float_extra_and_type_confusion() -> None: ...
def test_d1_1d_ed25519_rejects_cross_domain_scope_run_and_payload_replay() -> None: ...
def test_d1_1d_rejects_unknown_key_role_expired_and_invalid_signature() -> None: ...
```

Generate Ed25519 keys in tests. Never store a real private key fixture. Require
Pydantic `extra="forbid"`, frozen models, timezone-aware issued/expiry timestamps,
one stable `run_identity`, exact purpose, and three named model roles. The signed
expected revision/deployment is part of the plan payload.

### Step 2: Prove RED

Run:

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/pytest \
  -q tests/test_run_admission_models_020.py
```

Expected: import/test failures because the contract module does not exist.

### Step 3: Implement the smallest contract layer

Implement:

- `AdmissionPlanPayload`, `ModelRolePlan`, `ProductInputPlan`,
  `HistoricalProvenance`, `BudgetPlan`, and approval-envelope models;
- recursive canonical JSON validation: no floats, string keys only, no unknown model
  fields, key sorting, array order preservation, compact UTF-8 without ASCII escaping;
- `plan_payload_hash(payload)`;
- domain labels:
  `insurancekb.run-admission.provenance.v1\0` and
  `insurancekb.run-admission.budget.v1\0`;
- trusted public-key/role policy supplied outside the plan;
- Ed25519 verification with `cryptography`, including scope/run/purpose/hash/expiry.
- budget entry `budget_contract_hash` plus signed monotonic `revision` and
  `previous_approval_digest`, so later ceiling approvals cannot be reordered or made
  to authorize unsigned rates/reserves/attestations.

Add `cryptography>=49` as a direct runtime dependency; it already exists in the lock
transitively, so do not churn unrelated resolutions.

### Step 4: Prove GREEN and quality

Run the focused test, then:

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/ruff check \
  src/insurance_harness/goldenset/admission_models.py tests/test_run_admission_models_020.py
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/mypy \
  src/insurance_harness/goldenset/admission_models.py tests/test_run_admission_models_020.py
```

Expected: all pass. Do not commit.

---

## Task 2: Dependency ancestry, exact 13-product inputs, and execution-surface identity

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission_identity.py`
- Create: `harness/tests/test_run_admission_identity_020.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_models.py` only if tests
  expose a missing typed field; no unrelated refactor

### Step 1: Write failing D1.1b/D1.1c tests

Cover:

```python
def test_d1_1b_manifest_requires_exactly_thirteen_unique_products() -> None: ...
def test_d1_1b_hashes_every_pdf_meta_fields_and_other_consumed_input() -> None: ...
def test_d1_1b_rejects_missing_extra_duplicate_absolute_or_symlink_escape() -> None: ...
def test_d1_1b_detects_dirty_and_untracked_consumed_files() -> None: ...
def test_d1_1b_dependency_revision_must_be_ancestor() -> None: ...
def test_d1_1b_execution_surface_digest_changes_for_any_consumed_code() -> None: ...
def test_d1_1c_reports_each_unattested_historical_product() -> None: ...
```

Use temporary repositories/fixtures or injected Git/file-system adapters. Do not let
unit tests depend on the developer's current dirty worktree.

### Step 2: Prove RED

Run only `test_run_admission_identity_020.py`; expected import/failing assertions.

### Step 3: Implement identity inspection

Implement a deterministic inspector that:

- compares required 019/021 revisions with the evaluated revision by ancestry;
- records evaluated commit in result, not in the self-referential tracked payload;
- validates repository-relative, root-contained paths after symlink resolution;
- enumerates exactly thirteen product directories from a code-owned expected set;
- SHA-256 hashes every PDF, `product_meta.json`, `fields.json`, WIP Golden/fields,
  schema, prompt, template, and declared execution-surface file;
- fails on missing/extra/duplicate products and dirty/untracked files inside consumed
  roots (explicit cache/output exclusions only);
- produces a stable execution-surface digest and per-product digest;
- emits one blocker per missing/invalid historical provenance record, never applying
  a global annotator default.

The inspector returns typed observations/checks; it does not mutate the plan or data.

### Step 4: Prove GREEN

Run focused pytest, Ruff, and mypy on the new module/test. Expected all pass.

---

## Task 3: Code-owned, zero-inference provider probe

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission_probe.py`
- Create: `harness/tests/test_run_admission_probe_020.py`

### Step 1: Write failing D1.2a/D1.2b tests

Cover:

```python
def test_d1_2a_static_mode_performs_zero_network_and_cannot_ready() -> None: ...
def test_d1_2a_remote_probe_forces_https_tls_trust_env_false_no_redirect() -> None: ...
def test_d1_2a_rejects_post_query_userinfo_fragment_encoded_path_and_suffix() -> None: ...
def test_d1_2a_does_not_follow_3xx_or_cross_origin() -> None: ...
def test_d1_2b_compares_signed_expected_revision_or_deployment() -> None: ...
def test_d1_2b_redacts_key_url_secret_response_body_and_exception() -> None: ...
def test_d1_2b_rejects_expired_probe_and_price_observations() -> None: ...
def test_d1_2b_unsafe_retained_provider_fields_never_enter_audit() -> None: ...
def test_d1_2b_overall_probe_deadline_blocks_slow_drip_response() -> None: ...
def test_d1_2b_public_alias_without_deployment_detail_is_blocked() -> None: ...
def test_d1_2b_blocked_results_never_retain_legal_response_canaries() -> None: ...
def test_d1_2b_deeply_nested_metadata_is_typed_invalid() -> None: ...
```

Use injected `httpx.MockTransport`/factory. Assert construction includes
`trust_env=False`, `follow_redirects=False`, TLS verification, GET/HEAD, and empty
body. Ambient proxy variables must not influence the request. Loopback HTTP is
accepted only under an explicit test-only policy, with no credential and the exact
code-owned `/metadata/{deployed_model}` path.

### Step 2: Prove RED

Run focused pytest; expected import/failing assertions.

### Step 3: Implement provider policies and probe

Implement a code-owned allowlist initially containing the documented Bailian
dedicated-deployment detail policy
`GET https://dashscope.aliyuncs.com/api/v1/deployments/{deployed_model}` plus a
sealed internal test policy. The OpenAI-compatible base URL is an inference identity,
not a metadata endpoint. Public aliases without provider-verifiable immutable
deployment evidence remain `BLOCKED`. The plan selects a policy ID and role; it
cannot define arbitrary method/origin/path, clock, TTL, or credential environment
name. Normalize and percent-decode before equality checks. Reject every 3xx without
a second request. Enforce a code-owned whole-probe monotonic deadline in addition to
per-I/O timeouts. Force identity encoding, reject compressed responses before body
iteration, and stream through a hard response-size limit. Parse only the documented
`output.deployed_model/base_model/gmt_modified/status` fields and reject recursive
parser exhaustion. Validate each with code-owned provider grammar before comparison.
Blocked results retain no response-derived identity; after an exact match, successful
audit fields come from the signed plan. Never persist provider response bodies.

### Step 4: Prove GREEN

Run focused pytest, Ruff, mypy. Expected all pass and zero live calls.

---

## Task 4: Durable run-level budget lineage and owner-CAS request ledger

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission_budget.py`
- Create: `harness/tests/test_run_admission_budget_020.py`

### Step 1: Write failing D1.3a–D1.3c tests

Cover:

```python
def test_d1_3a_invalid_caps_rates_attestation_or_approval_block() -> None: ...
def test_d1_3b_two_processes_debit_once_and_only_owner_sends() -> None: ...
def test_d1_3b_release_and_attempt_claim_share_one_lock() -> None: ...
def test_d1_3b_crash_at_prepare_send_response_boundaries_becomes_uncertain() -> None: ...
def test_d1_3b_uncertain_is_full_charge_and_never_auto_replayed_or_released() -> None: ...
def test_d1_3b_terminal_or_provider_no_usage_proof_controls_resume() -> None: ...
def test_d1_3c_cross_run_envelope_replay_cannot_open_or_debit_account() -> None: ...
def test_d1_3c_cap_revision_preserves_settled_reserved_uncertain_debits() -> None: ...
def test_d1_3c_new_ceiling_cannot_drop_below_existing_debits() -> None: ...
def test_d1_3c_ceiling_revision_cannot_replace_pool_model_or_rate() -> None: ...
def test_d1_3b_legacy_exact_attempt_schema_migrates_atomically_without_loss() -> None: ...
```

Use two independent SQLite connections and barriers/threads for contention. Assert
the logical outbound callback count is exactly one, not merely that reserve count is
one. Exact prompt reserves are used for enumerable requests; dynamic retry/gap-fill/
judge prompts use signed per-product/per-role pools that bind model identity, RoleRate,
attempt count, and per-attempt bounds. The pool-aware schema migration must preserve
legacy exact attempt rows in one verified transaction and fail closed without
replacing the old table on any mismatch.

### Step 2: Prove RED

Run focused pytest; expected import/failing assertions.

### Step 3: Implement the ledger

Use stdlib `sqlite3` with WAL, foreign keys, busy timeout, and `BEGIN IMMEDIATE` for
all mutations. Tables must represent:

- stable run-level budget account keyed by domain-separated run identity + purpose;
- chained approval revisions with previous digest and monotonically increasing total
  ceiling;
- product reservation unique by account/stage/product;
- request attempt unique by account/stage/product/request-unit/attempt-no, with owner
  token and durable state;
- actual/reserved input/output/cost integer counters and provider proof metadata.

Only an insert/CAS claim winner may receive a send permit. Lease expiry never grants
a second sender. Any non-terminal attempt recovered after a crash becomes
`uncertain` and full-reserve charged. Release is allowed only before any attempt or
with durable provider no-usage proof. Cap revisions modify the same account in one
transaction and retain every debit/attempt.

### Step 4: Prove GREEN

Run focused tests repeatedly (at least 5 times for concurrency), Ruff, and mypy.
Expected deterministic all-pass, no sleeps used as synchronization.

---

## Task 5: Admission evaluator, CLI, redacted artifacts, and honest BLOCKED plan

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission.py`
- Create: `harness/src/insurance_harness/goldenset/admission_cli.py`
- Create: `harness/tests/test_run_admission_cli_020.py`
- Create: `harness/tests/test_run_admission_evaluator_020.py`
- Create: `openspec/changes/020-golden-v01-baseline-run/run-admission.yaml`
- Create: `openspec/changes/020-golden-v01-baseline-run/run-admission.json`
- Create: `openspec/changes/020-golden-v01-baseline-run/run-admission.md`
- Modify: `harness/src/insurance_harness/goldenset/__init__.py` only for deliberate
  public exports

### Step 1: Write failing D1.4/D1.5 tests

Cover:

```python
def test_d1_4_well_formed_blocked_plan_writes_json_markdown_and_exit_2() -> None: ...
def test_d1_4_invalid_plan_or_checker_error_exits_1_without_ready_artifact() -> None: ...
def test_d1_4_ready_requires_every_check_and_exit_0() -> None: ...
def test_d1_4_outputs_never_contain_secret_body_or_absolute_path() -> None: ...
def test_d1_5_tampered_stored_ready_or_blockers_are_ignored() -> None: ...
def test_d1_5_expired_or_drifted_observation_rederives_blocked() -> None: ...
```

### Step 2: Prove RED

Run focused pytest; expected import/failing assertions.

### Step 3: Implement evaluator and CLI

Implement:

```text
python -m insurance_harness.goldenset.admission_cli check
  --plan <relative yaml>
  --repo-root <root>
  --trusted-keys <deployment-owned file>
  --result-json <path>
  --report-md <path>
  [--probe]
```

The evaluator aggregates typed checks from Tasks 1–4. It derives state every time;
it never accepts state/blocker input from a stored result. Static mode records probe
unverified and cannot be ready. Result JSON includes checker/runtime capability
versions, evaluated revision, plan hash, execution/input fingerprints, verified
approval identities/expiry, budget summary, checks, and blockers. Markdown renders
the same object. Exit codes: ready=0, well-formed blocked=2, invalid/internal=1.

Create a well-formed current plan with null/unattested fields represented as blockers,
not placeholders that look real. Deterministically populate the exact thirteen
product input manifest and hashes. Required 021 merge revision remains absent, exact
annotator/judge revisions, trusted approvals/provenance, and probe remain absent.
Run the static CLI to generate committed audit artifacts. Expected final state:
`BLOCKED`, exit 2, zero network/model calls, no absolute paths/secrets.

Use explicit typed `pending_immutable_identity` / `pending_required_input` variants
and a null budget-contract reference for those gaps. Reject duplicate YAML keys and
path aliases between plan/result/report. JSON is compact canonical UTF-8; the JSON
result is the atomic commit marker installed after the Markdown rendering.

### Step 4: Prove GREEN

Run focused tests, then run the real static check against the new plan and inspect the
JSON/Markdown. Run `git diff --check`, Ruff, mypy. Do not probe real providers.

---

## Task 6: Admitted model client and per-product runtime revalidation

**Files:**

- Create: `harness/src/insurance_harness/goldenset/admission_runtime.py`
- Create: `harness/tests/test_run_admission_runtime_020.py`

### Step 1: Write failing D1.3b/D1.5 tests

Cover:

```python
async def test_d1_5_each_product_reruns_evaluator_and_ignores_stored_ready() -> None: ...
async def test_d1_5_blocked_drift_calls_inner_model_zero_times() -> None: ...
async def test_d1_3b_two_workers_make_exactly_one_inner_model_call() -> None: ...
async def test_d1_3b_terminal_response_is_durable_before_attempt_settlement() -> None: ...
async def test_d1_3b_exception_or_ambiguous_crash_recovers_uncertain() -> None: ...
async def test_d1_5_no_force_bypass_exists() -> None: ...
```

### Step 2: Prove RED

Run focused pytest; expected import/failing assertions.

### Step 3: Implement admitted runtime wrapper

Implement `AdmissionRuntimeGuard` plus an `AdmittedModelClient` satisfying the existing
`ModelClient.complete(system, user) -> str` protocol. At product start, re-run the
evaluator and reserve the product. For every request, derive a stable request-unit
fingerprint, acquire owner-CAS, and only the winner may call the inner model. Persist
the response atomically under the checkpoint/run root before marking terminal;
observers reuse a verified terminal artifact. A non-terminal/ambiguous attempt raises
a typed pause error and remains full-reserve charged. Conservative full-reserve
settlement is acceptable for T1; it must never undercharge or exceed the approved
provider-side cap.

The public API has no `force`, `skip_admission`, or caller-supplied `ready` argument.

### Step 4: Prove GREEN

Run focused tests repeatedly, Ruff, mypy. Assert fake inner-client call counts and
durable file/ledger ordering.

---

## Task 7: Record typed provider usage and protect startup recovery

**Files:**

- Modify: `harness/src/insurance_harness/goldenset/admission_runtime.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_budget.py` only for a
  canonical signed-rate cost helper or settlement evidence API
- Modify: `harness/tests/test_run_admission_runtime_020.py`
- Create: `harness/tests/test_run_admission_usage_020.py`

### Step 1: Write failing D1.3b/D1.5 tests

Cover typed `{content,input_tokens,output_tokens}` responses, integer/overflow-safe
cost recomputation from the signed RoleRate, provider usage missing/malformed/negative
or above the request maximum, and conservative full-reserve settlement that remains
ineligible for canary continuation. Also prove an exclusive, code-owned run-session
lock is acquired before startup recovery and held through settlement, so a competing
process cannot mark a live sender uncertain. No caller-supplied ledger/run path is
allowed by the production CLI.

### Step 2: Prove RED, implement the minimum, then prove GREEN

Run only usage/recovery tests first and observe the expected failures. Implement the
typed invoker result and session lock without exposing raw provider clients or secrets.
Run focused pytest, Ruff, and mypy. Do not make a live provider call.

---

## Task 8: Signed canary review and fresh product authorization

**Files:**

- Modify: `harness/src/insurance_harness/goldenset/admission_models.py`
- Modify: `harness/src/insurance_harness/goldenset/admission.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_cli.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_runtime.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_budget.py`
- Create: `harness/tests/test_run_admission_canary_020.py`

### Step 1: Write failing D1.1d/D1.5 tests

Add a separate `canary-review` Ed25519 domain. The payload binds run/purpose,
execution plan hash and evaluated revision, runtime capability version, fixed canary
stage/product, budget account/revision/approval digest, canonical settlement/attempt
digest, checkpoint/manifest, Golden/quote/disputed artifacts and threshold version,
provider-reported actual usage and signed-rate cost, `review_decision`, exact ordered
unique `granted_targets`, approver role, issued/expiry. The fixed deployment trust
file gains `canary_review_roles`; the run CLI cannot select it. The post-run envelope
is not added to the tracked plan: it is loaded from a code-fixed, repo-external,
root-owned, non-symlink, non-group/world-writable, size-bounded approval inbox. Tests
prove attachment/loading leaves the evaluated Git revision and plan hash unchanged,
and that a review object placed in tracked plan/candidate/result never authorizes.

Prove fresh authorization is initially exactly the first missing-product annotation
canary and no baseline. The first valid review may grant only the exact second-product
annotation target it signs; baseline stays empty until an immutable Golden release is
a newly approved admission input. The evaluator may return only a subset of signed
targets. Duplicate/rejected/invalid/expired/drifted/old-budget review empties all
authorization. `begin_product` must recheck expiry and atomically claim the envelope
digest + target, verify the complete canary settlement snapshot, and reserve the
continuation product. Same-target recovery is idempotent; another target is denied.

Canary outputs and the unsigned `CanaryReviewCandidate` live only in a code-fixed,
content-addressed run-output root excluded from the pre-run input identity. Candidate
generation must not change the plan hash or authorization, and the evaluator never
reads candidate/result/observation files as authority. Tests cover output-byte drift,
derive-to-begin ledger/artifact/time TOCTOU, unsigned `approved:true`, ungranted target,
and historical prepared/sent/uncertain attempts.

### Step 2: Prove RED, implement the minimum, then prove GREEN

Run focused canary tests, then Ruff and mypy. Tests use generated keys and temporary
artifacts only; no model/network calls.

---

## Task 9: Wire guarded single-product T2/T4 entrypoints and finish T1 evidence

**Files:**

- Create: `harness/src/insurance_harness/goldenset/run_020.py`
- Create: `harness/tests/test_run_admission_entrypoints_020.py`
- Modify: `openspec/changes/020-golden-v01-baseline-run/tasks.md`
- Create: `openspec/changes/020-golden-v01-baseline-run/validation-report.md`
- Modify: `HANDOFF.md`
- Modify: `docs/insurance-kb/05-golden-set-eval.md` only if needed to document the
  new commands; avoid broad roadmap edits

### Step 1: Write failing guarded-entrypoint tests

Cover:

```python
def test_d1_5_annotation_entrypoint_accepts_exactly_one_product_and_has_no_force() -> None: ...
def test_d1_5_baseline_entrypoint_accepts_exactly_one_product_and_has_no_force() -> None: ...
async def test_d1_5_blocked_entrypoints_construct_no_model_client_and_call_zero_models() -> None: ...
async def test_d1_5_ready_entrypoint_uses_admitted_client_for_every_role() -> None: ...
def test_d1_5_first_annotation_is_one_missing_product_canary_only() -> None: ...
def test_d1_5_production_bootstrap_forces_remote_probe_and_fixed_paths() -> None: ...
def test_d1_5_startup_recovery_precedes_begin_and_client_construction() -> None: ...
def test_d1_5_production_entrypoint_imports_no_raw_model_client() -> None: ...
```

### Step 2: Prove RED

Run focused pytest; expected import/failing assertions.

### Step 3: Implement guarded per-product commands

Provide explicit commands such as:

```text
python -m insurance_harness.goldenset.run_020 annotate-canary --product <one product> ...
python -m insurance_harness.goldenset.run_020 baseline-product --product <one product> ...
```

Both commands load the code-fixed plan/trusted keys/ledger/run roots, force remote
probe, acquire the run-session lock, recover, re-run the evaluator, and construct
model clients only after admission. Annotator, weak extractor, and judge clients use
the exact plan role and `AdmittedModelClient`; no direct raw client is reachable from
these entrypoints. Baseline wiring must use the current `DirectoryDocumentSource`,
`DirectorySourceRequest`, and current `ExtractionPipeline.run` signature, not the
obsolete `baseline_004.py` call shape. Each invocation accepts exactly one product.
The annotation command initially permits only the code-owned first missing product
and stops after it; continuing requires a valid signed canary-review envelope. The
parser exposes only `--product`: no force/ready/probe/trust/model/key/path/line/resume
override is available.

Tests use fake clients/evaluator only; no live provider calls.

### Step 4: Focused and full verification

Run:

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/pytest \
  -q tests/test_run_admission_*_020.py
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/ruff check .
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/mypy src tests
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/pytest \
  -m "not live and not integration_postgres" -q
```

Also run:

```bash
DO_NOT_TRACK=1 openspec validate 020-golden-v01-baseline-run --strict
git diff --check
```

Expected: all deterministic gates pass. Do not claim live/model coverage. Generate
`validation-report.md` with exact counts and record the current `BLOCKED` reasons.
Mark only T1.1–T1.6 complete if every implementation/review gate passed; T2–T8 stay
unchecked. Update HANDOFF with the durable lesson: high-cost tasks must be decomposed,
bounded, and stopped at explicit evidence gates; no indefinite command babysitting.

### Step 5: Final reviews, staging, and handoff

Run one independent whole-change spec review and one independent code-quality/security
review. Fix and re-review all P0–P2 findings. Run `superpowers:verification-before-
completion`, then `superpowers:finishing-a-development-branch`.

Because `CLAUDE.md` forbids AI commit/push, the final state is a reviewed, verified
worktree ready for a human to inspect, stage, commit, push, and open/update the PR.
