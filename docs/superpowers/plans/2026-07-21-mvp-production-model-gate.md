# MVP Production Model Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 027 so every production model call is bound to an immutable approved weak-model identity and the matching run admission, with strong/unknown/rolling fallbacks rejected before network I/O.

**Architecture:** Add one `model_policy` package that owns identity, permit, decision, receipt, and guarded-client behavior. Existing compiler clients remain transport primitives; production entrypoints must obtain a `ModelPermit` from the shared evaluator, while replay/offline-golden paths stay explicit and cannot be selected as production fallbacks.

**Tech Stack:** Python 3.12, Pydantic v2, existing run-admission models, httpx fakes/respx, pytest, Ruff, mypy.

---

## Authority, scope, and handoff

- Spec: `openspec/changes/027-production-weak-model-boundary/`
- North-star clauses: PWB1–PWB5; C2/C3.
- Risk: **A** (production boundary/admission). Use @superpowers:test-driven-development for each behavior and @superpowers:verification-before-completion before handoff.
- Allowed domain: `model_policy/`, `config.py`, minimal `compiler/cli.py`, `compiler/judge.py`, `compiler/llm.py` wiring, 027 tests/artifacts.
- S0/027 is the sole owner of global `harness/src/insurance_harness/config.py` in Wave 1 and merges before 028/013 integration. 028 and 013 use package-local immutable settings and must not edit this file; any later shared alias is a separate serialized integration patch.
- Forbidden: new extraction logic, templates, knowledge tables, releases, real provider calls, 020 canonical artifact mutation.
- This execution session does **not** commit or push. At each “human commit boundary,” stop, report the exact diff/tests, and let the human owner commit.

## File map

**Create**

- `harness/src/insurance_harness/model_policy/__init__.py` — stable public exports only.
- `harness/src/insurance_harness/model_policy/models.py` — immutable model identity, role, run binding, permit, decision, receipt.
- `harness/src/insurance_harness/model_policy/policy.py` — one fail-closed evaluator and approved-family/rolling-alias rules.
- `harness/src/insurance_harness/model_policy/gateway.py` — `GuardedModelClient` wrapper and receipt sink protocol.
- `harness/tests/test_production_model_boundary_027.py` — PWB1/PWB3/PWB4 behavioral tests.
- `harness/tests/test_production_entrypoints_027.py` — PWB2 inventory/guard tests.
- `openspec/changes/027-production-weak-model-boundary/artifacts/entrypoint-inventory.md` — public entrypoint classification.
- `openspec/changes/027-production-weak-model-boundary/validation-report.md` — evidence and NOT RUN statements.

**Modify**

- `harness/src/insurance_harness/config.py` — explicit production profile, immutable identity fields, policy version; deprecate old judge fallback in production.
- `harness/src/insurance_harness/compiler/llm.py` — expose transport behind the guarded wrapper; do not embed a second allowlist.
- `harness/src/insurance_harness/compiler/cli.py` — production `extract` obtains/validates permit before constructing a network client.
- `harness/src/insurance_harness/compiler/judge.py` — gateway judge accepts only guarded weak-model client in production; `claude-session` stays offline/manual only.

### Task 1: Freeze the entrypoint inventory and baseline

- [ ] **Step 1: Read the contract and enumerate current entrypoints**

Run:

```bash
rg -n "OpenAICompatClient\(|LiteLLMClient\(|JudgeDispatcher\(|def main|publish_product_version|import_pred" harness/src/insurance_harness
```

Expected: every transport construction and public command is visible; no files are changed.

- [ ] **Step 2: Write `entrypoint-inventory.md`**

For each CLI/API/export record: path, callable, production/offline/read-only classification, model role, current model source, required guard, and owner. Explicitly classify merge/release as zero-model; do not add a permit parameter merely to zero-model code.

- [ ] **Step 3: Run the focused pre-change baseline**

Run:

```bash
cd harness
uv run pytest -q tests/test_config.py tests/test_compiler_llm.py tests/test_source_pipeline_cli_017.py -m "not live and not integration_postgres"
```

Expected: PASS. Record count/time in the validation report draft; do not run the full suite.

- [ ] **Step 4: Human commit boundary**

Report inventory and baseline only. Do not commit/push.

### Task 2: Immutable identity and policy decision

- [ ] **Step 1: Write the PWB1 RED tests**

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

- [ ] **Step 2: Run RED**

Run:

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "identity or rolling or strong"
```

Expected: FAIL with `ModuleNotFoundError: insurance_harness.model_policy` or missing symbols.

- [ ] **Step 3: Implement minimal frozen models**

The public shape must remain equivalent to:

```python
class ModelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: str
    deployment_id: str
    family: Literal["minimax", "qwen", "qwen-vl"]
    role: Literal["classify", "extract", "gap", "verify", "consensus"]
    policy_version: str

class ModelPermit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: ModelIdentity
    run_id: str
    run_revision: str
    admission_hash: str
    template_hash: str
    model_plan_hash: str
    expires_at: AwareDatetime
```

Reject blank values, rolling aliases (`latest`, unversioned deployment names), non-approved families, role mismatch, and expired permits in one evaluator.

- [ ] **Step 4: Run GREEN**

Run the same test command. Expected: PASS in ≤90 seconds.

### Task 3: Admission/run binding and audit receipts

- [ ] **Step 1: Write PWB4 RED tests**

Cover: wrong run revision; borrowed 020 canonical approval for 030; wrong template/model-plan hash; expired permit; READY false; receipt contains no API key or raw prompt.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "admission or borrowed or receipt"
```

Expected: at least one assertion FAIL because run binding/receipts are not implemented.

- [ ] **Step 3: Implement evaluator and receipt sink**

Use a narrow adapter over existing admission artifacts; do not mutate 020 records. Every allow/deny returns a structured `PolicyReceipt` containing decision, reason code, identity key, run/template/model-plan hashes, timestamp, and request hash only.

- [ ] **Step 4: Run GREEN**

Run the same command. Expected: PASS; secret sentinel absent from serialized receipts.

### Task 4: Guard network calls and prohibit fallback escalation

- [ ] **Step 1: Write PWB3 zero-network RED tests**

Use a counting fake transport. Assert unknown identity, exhausted weak attempts, truncation, and no-consensus produce zero strong-model calls and no candidate-promotion callback.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_model_boundary_027.py -k "network or fallback or exhausted"
```

Expected: FAIL before wrapper implementation.

- [ ] **Step 3: Implement `GuardedModelClient`**

It must call the evaluator before delegating, persist a decision receipt for both allow/deny, and never choose another model. Retry selection belongs to 028 and may only reuse an approved permit/plan.

- [ ] **Step 4: Run GREEN**

Expected: PASS; fake transport counts exactly one call for allowed identity and zero for every denied case.

### Task 5: Wire every production entrypoint

- [ ] **Step 1: Write PWB2 inventory RED**

`test_production_entrypoints_027.py` must parse the checked-in inventory and assert each listed production model entrypoint imports/calls the common guard; zero-model entries must have a proof test and classification.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_production_entrypoints_027.py
```

Expected: FAIL for current unguarded `compiler/cli.py`/gateway judge construction.

- [ ] **Step 3: Add production settings without retaining an implicit fallback**

Add only global production-model-policy settings: profile, provider, immutable deployment ID, policy version, admission artifact, and model plan hash. Do not add runtime worker/attempt/time/token or MCP token/host/port/disclaimer keys; those belong to package-local 028/013 settings. In `production`, old `judge_mode=gateway`, `llm_model_judge_fallback`, `claude-session`, unknown IDs, and missing admission all fail before client construction. Replay/goldenset requires an explicit non-production profile.

- [ ] **Step 4: Wire CLI and judge to the common evaluator**

Do not spread allowlist checks into CLI branches. Production `extract` builds one `PolicyContext`, receives one permit, then builds guarded clients for the approved roles.

- [ ] **Step 5: Run GREEN and regression slice**

```bash
cd harness
uv run pytest -q tests/test_production_entrypoints_027.py tests/test_production_model_boundary_027.py tests/test_config.py tests/test_compiler_llm.py tests/test_source_pipeline_cli_017.py
```

Expected: PASS; no live/integration marker selected.

### Task 6: Validate and hand off PR 027

- [ ] **Step 1: Run static checks only on touched code**

```bash
cd harness
uv run ruff check src/insurance_harness/model_policy src/insurance_harness/config.py src/insurance_harness/compiler/cli.py src/insurance_harness/compiler/judge.py tests/test_production_*_027.py
uv run mypy src/insurance_harness/model_policy src/insurance_harness/config.py src/insurance_harness/compiler/cli.py src/insurance_harness/compiler/judge.py
```

Expected: both exit 0.

- [ ] **Step 2: Fill `validation-report.md`**

Record exact commands/counts, entrypoint coverage, permit/receipt examples with secrets redacted, confirm global config contains no runtime/MCP keys, and `real provider = NOT RUN`. Do not claim extraction quality improvement.

- [ ] **Step 3: Request independent spec/quality review**

Reviewer checks PWB1–PWB5 in one pass. Maximum two remediation rounds; third-round disagreement goes to the G planning window.

- [ ] **Step 4: PR-ready verification**

Run one complete deterministic suite only after review findings are closed, then let CI independently repeat it. Record time separately from focused tests.

- [ ] **Step 5: Human commit boundary**

Report diff, focused/full/static evidence, NOT RUN, and seven-stage time. Do not commit or push.
