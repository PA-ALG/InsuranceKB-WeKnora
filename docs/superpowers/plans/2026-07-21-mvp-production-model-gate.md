# MVP Production Model Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 027 so every production model call is bound to an immutable approved weak-model identity and the matching run admission, with strong/unknown/rolling fallbacks rejected before network I/O.

**Architecture:** Add one `model_policy` package that owns the cross-package strict admission request/rich binding/opaque verified capability/verifier Protocol plus model identity, internally issued scoped capability, decision, receipt, and guarded-client behavior. A production composition root selects the canonical verifier from independent expected purpose/schema and accepts no caller-supplied READY/binding/verifier. Existing compiler clients remain transport primitives; every model-capable production entrypoint invokes the canonical `GuardedModelClient` with `VerifiedAdmission + ModelCallContext`, while only its non-public policy issuer may mint an opaque `IssuedModelPermit`. Replay/offline-golden paths stay explicit and cannot be selected as production fallbacks.

**Tech Stack:** Python 3.12, Pydantic v2, Protocol/opaque capability boundary, existing 020 adapter plus future 030 verifier implementation, httpx fakes/respx, pytest, Ruff, mypy.

---

## Authority, scope, and handoff

- Spec: `openspec/changes/027-production-weak-model-boundary/`
- North-star clauses: PWB1–PWB5; C2/C3.
- Risk: **A** (production boundary/admission). Use @superpowers:test-driven-development for each behavior and @superpowers:verification-before-completion before handoff.
- Allowed domain: `model_policy/`, `config.py`, minimal `compiler/cli.py`, `compiler/judge.py`, `compiler/llm.py` wiring, 027 tests/artifacts.
- S0/027 is the sole owner of global `harness/src/insurance_harness/config.py` in Wave 1 and merges before 028/013 integration. 028 and 013 use package-local immutable settings and must not edit this file; any later shared alias is a separate serialized integration patch.
- Forbidden: new extraction logic, templates, knowledge tables, releases, real provider calls, 020 canonical artifact mutation.
- This campaign has explicit business-owner authorization to commit, push, and open a ready PR after verification; the execution session SHALL NOT self-merge and still stops for G review.

## File map

**Create**

- `harness/src/insurance_harness/model_policy/__init__.py` — stable public exports only.
- `harness/src/insurance_harness/model_policy/admission.py` — `StrictAdmissionRequestBinding`, rich binding view, opaque `VerifiedAdmission`, controlled issuer, and `AdmissionVerifier` Protocol; no profile evaluator.
- `harness/src/insurance_harness/model_policy/models.py` — immutable model identity, role, full-scope permit, decision, receipt.
- `harness/src/insurance_harness/model_policy/policy.py` — one fail-closed evaluator and approved-family/rolling-alias rules.
- `harness/src/insurance_harness/model_policy/gateway.py` — `GuardedModelClient` wrapper and receipt sink protocol.
- `harness/tests/test_production_model_boundary_027.py` — PWB1/PWB3/PWB4 behavioral tests.
- `harness/tests/test_production_entrypoints_027.py` — PWB2 inventory/guard tests.
- `openspec/changes/027-production-weak-model-boundary/artifacts/entrypoint-inventory.md` — public entrypoint classification.
- `openspec/changes/027-production-weak-model-boundary/validation-report.md` — evidence and NOT RUN statements.

**Modify**

- `harness/src/insurance_harness/config.py` — explicit production profile, immutable identity fields, policy version; deprecate old judge fallback in production.
- `harness/src/insurance_harness/compiler/llm.py` — expose transport behind the guarded wrapper; do not embed a second allowlist.
- `harness/src/insurance_harness/compiler/cli.py` — production `extract` builds the strict request, obtains `VerifiedAdmission` through canonical composition, and invokes the guarded client; it never accepts or constructs a permit.
- `harness/src/insurance_harness/compiler/judge.py` — gateway judge accepts only guarded weak-model client in production; `claude-session` stays offline/manual only.

### Task 1: Freeze the entrypoint inventory and baseline

- [x] **Step 1: Read the contract and enumerate current entrypoints**

Run:

```bash
rg -n "OpenAICompatClient\(|LiteLLMClient\(|JudgeDispatcher\(|def main|publish_product_version|import_pred" harness/src/insurance_harness
```

Expected: every transport construction and public command is visible; no files are changed.

- [x] **Step 2: Write `entrypoint-inventory.md`**

For each CLI/API/export record: path, callable, production/offline/read-only classification, model role, current model source, required guard, and owner. Explicitly classify merge/release as zero-model; do not add a permit parameter merely to zero-model code.

- [x] **Step 3: Run the focused pre-change baseline**

Run:

```bash
cd harness
uv run pytest -q tests/test_config.py tests/test_compiler_llm.py tests/test_source_pipeline_cli_017.py -m "not live and not integration_postgres"
```

Expected: PASS. Record count/time in the validation report draft; do not run the full suite.

- [x] **Step 4: Human commit boundary**

Report inventory and baseline only. Do not commit/push.

### Task 2: Immutable identity and policy decision

- [x] **Step 1: Write the PWB1 RED tests**

Add tests equivalent to:

```python
@pytest.mark.parametrize("model_id", ["", "qwen-latest", "claude-opus", "deepseek-v4"])
def test_production_identity_rejects_unknown_strong_or_rolling(model_id: str) -> None:
    with pytest.raises(ModelPolicyDenied):
        evaluator.evaluate(context(identity=model_identity(model_id)))

def test_identity_binds_provider_deployment_role_and_policy() -> None:
    assert approved.identity_key == (
        "dashscope", "qwen3.6-prod-20260715", "extract", "pwb-v1"
    )
```

- [x] **Step 2: Run RED**

Run:

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "identity or rolling or strong"
```

Expected: FAIL with `ModuleNotFoundError: insurance_harness.model_policy` or missing symbols.

- [x] **Step 3: Implement minimal frozen models**

The public shape must remain equivalent to:

```python
class ModelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: str
    deployment_id: str
    family: Literal["minimax", "qwen", "qwen-vl"]
    role: Literal["classify", "extract", "gap", "verify", "consensus"]
    policy_version: str

class ModelPermitView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: ModelIdentity
    purpose: str
    run_schema_version: str
    space_id: str
    run_id: str
    run_revision: str
    admission_hash: str
    verified_binding_digest: str
    template_hash: str
    model_plan_hash: str
    call_scope_hash: str
    expires_at: AwareDatetime
```

`StrictAdmissionRequestBinding` carries independent expected purpose/schema/run identity and every request hash: admission artifact, Space, manifest/eligibility, Golden Slice, routing policy, schema/template lock, structured-dispatch lock, model plan/deployment roles, resource caps, rights/provenance, and integration SHA. `AdmissionBinding` preserves the actual values plus a canonical full-binding digest, but raw DTO construction is not authority. `VerifiedAdmission` has a non-public controlled issuer/seal and verification receipt; only a canonical `AdmissionVerifier` selected by production composition may issue it. `PolicyContext` accepts this opaque capability, never caller-supplied binding/READY/verifier.

Likewise `ModelPermitView` is only serializable receipt data. The canonical policy uses a non-public issuer to create opaque `IssuedModelPermit` with a process seal; Pydantic construction/model-copy/deserialization cannot create authority. Prefer `GuardedModelClient.call(verified_admission, model_call_context)` so the client internally evaluates/issues/compares before transport, rather than accepting a caller-provided permit. It compares purpose/schema/Space/full-binding/call-scope on every call. Reject blank expected identity, expected/actual mismatch, hand-crafted READY/permit, custom policy/guard injection, cross-Space/binding replay, rolling aliases, non-approved families, role/template mismatch, and expired capabilities.

- [x] **Step 4: Run GREEN**

Run the same test command. Expected: PASS in ≤90 seconds.

### Task 3: Admission/run binding and audit receipts

- [x] **Step 1: Write PWB4 RED tests**

Cover: missing independent expected purpose/schema/run identity/revision; unknown/wrong profile pair; wrong run revision; borrowed 020 canonical approval for 030; deriving expected from actual; hand-constructed READY binding; caller-injected verifier; wrong Space/manifest/eligibility/Golden/routing/schema/template/structured-dispatch/model-plan/caps/rights/provenance/integration hash; exact template not in lock; hand-crafted/copied/deserialized permit view; custom policy/guard injection; cross-Space/different-binding permit replay; expired permit; receipt contains no API key or raw prompt and does contain Space/full-binding/call-scope digests.

- [x] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "admission or borrowed or receipt"
```

Expected: at least one assertion FAIL because run binding/receipts are not implemented.

- [x] **Step 3: Implement evaluator and receipt sink**

Freeze the 027-owned Protocol and both controlled capability issuers. Production composition selects the verifier by independent expected purpose/schema and the canonical model policy by code/config identity; it accepts no CLI/config verifier/policy/issuer override. Applicable 020/030 adapters implement the Protocol and do their own signature/full-request checks; 027 does not mutate their records or duplicate evaluation. The common model policy accepts only `VerifiedAdmission`, compares purpose/schema/run/Space plus call role/model plan/exact template membership, and issues an opaque permit bound to the full binding and call scope. Every allow/deny returns a structured `PolicyReceipt` containing decision, reason code, identity key, run/template/model-plan hashes, Space, verified-binding/call-scope digests, timestamp, and request hash only.

- [x] **Step 4: Run GREEN**

Run the same command. Expected: PASS; secret sentinel absent from serialized receipts.

### Task 4: Guard network calls and prohibit fallback escalation

- [x] **Step 1: Write PWB3 zero-network RED tests**

Use a counting fake transport. Assert unknown identity, exhausted weak attempts, truncation, and no-consensus produce zero strong-model calls and no candidate-promotion callback.

- [x] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "network or fallback or exhausted"
```

Expected: FAIL before wrapper implementation.

- [x] **Step 3: Implement `GuardedModelClient`**

It accepts `VerifiedAdmission + ModelCallContext`, calls the canonical policy internally, receives an opaque issued permit through the non-public issuer, compares all scopes, persists a decision receipt for both allow/deny, and only then delegates. It never accepts a caller-supplied permit/policy/guard and never chooses another model. Retry selection belongs to 028 and must re-enter this method with the approved plan/context.

- [x] **Step 4: Run GREEN**

Expected: PASS; fake transport counts exactly one call for allowed identity and zero for every denied case.

### Task 5: Wire every production entrypoint

- [x] **Step 1: Write PWB2 inventory RED**

`test_production_entrypoints_027.py` must parse the checked-in inventory and assert each listed production model entrypoint imports/calls the common guard; zero-model entries must have a proof test and classification.

- [x] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_entrypoints_027.py
```

Expected: FAIL for current unguarded `compiler/cli.py`/gateway judge construction.

- [x] **Step 3: Add production settings without retaining an implicit fallback**

Add only global production-model-policy settings: production profile, provider, immutable deployment ID, policy version, admission artifact reference, independently required expected purpose/schema/run identity/revision, and model plan hash. Expected values are frozen request/config data, not late CLI overrides and never default from the artifact. No setting accepts READY/binding/verifier/policy/permit issuer. Do not add runtime worker/attempt/time/token or MCP token/host/port/disclaimer keys; those belong to package-local 028/013 settings. In `production`, old `judge_mode=gateway`, `llm_model_judge_fallback`, `claude-session`, unknown IDs, missing expected identity, and missing admission all fail before client construction. Replay/goldenset requires an explicit non-production profile.

- [x] **Step 4: Wire CLI and judge to the common evaluator**

Do not spread allowlist checks into CLI branches. Production composition builds the strict request and selects the canonical verifier from expected purpose/schema. On this 027 branch the 030 verifier module is absent; a deterministic verifier fake additionally proves that successful verification still fails as `canonical_adapter_unavailable` while the reviewed 028 provider adapter is absent. Thus Task 5 wires the boundary fail-closed but does not claim a usable production transport. No caller can inject or deserialize permit/policy/guard objects.

- [x] **Step 5: Run GREEN and regression slice**

```bash
cd harness
uv run pytest -q tests/test_production_entrypoints_027.py tests/test_production_model_boundary_027.py tests/test_config.py tests/test_compiler_llm.py tests/test_source_pipeline_cli_017.py
```

Expected: PASS; no live/integration marker selected.

### Task 6: Validate and hand off PR 027

- [x] **Step 1: Run static checks only on touched code**

```bash
cd harness
uv run ruff check src/insurance_harness/model_policy src/insurance_harness/config.py src/insurance_harness/compiler/cli.py src/insurance_harness/compiler/judge.py tests/test_production_*_027.py
uv run mypy src/insurance_harness/model_policy src/insurance_harness/config.py src/insurance_harness/compiler/cli.py src/insurance_harness/compiler/judge.py
```

Expected: both exit 0.

- [x] **Step 2: Fill `validation-report.md`**

Record exact commands/counts, entrypoint coverage, permit/receipt examples with secrets redacted, confirm global config contains no runtime/MCP keys, and `real provider = NOT RUN`. Do not claim extraction quality improvement.

- [ ] **Step 3: Request independent spec/quality review**

Reviewer checks PWB1–PWB5 in one pass. Maximum two remediation rounds; third-round disagreement goes to the G planning window.

- [ ] **Step 4: PR-ready verification**

Run one complete deterministic suite only after review findings are closed, then let CI independently repeat it. Record time separately from focused tests.

- [ ] **Step 5: Human commit boundary**

Report diff, focused/full/static evidence, NOT RUN, and seven-stage time. Under this campaign's explicit authorization, commit/push and open a ready PR after both reviews close; do not self-merge.
