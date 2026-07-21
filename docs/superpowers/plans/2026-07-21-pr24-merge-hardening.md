# PR #24 Merge Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four P1 admission/budget bypasses found in the final review so PR #24 can merge without weakening the fail-closed contract.

**Architecture:** Keep the existing OpenSpec 020 boundary. Because 020 has no durable authentication schema or deployment-owned reconciliation trust loader, remove the unsafe provider no-usage transition and conservatively convert any legacy/tampered `no_usage` row to `uncertain` at full reserve; a complete reconciliation authority is deferred to a separate OpenSpec. Same-run budget revisions may only raise the ceiling. Bailian production admission accepts only an invocable immutable deployment identity, and dependency identity pins the designated merged revisions rather than feature heads. All behavior changes are test-first and remain blocked when the provider or repository cannot supply stronger evidence.

**Tech Stack:** Python 3.12, Pydantic v2, Ed25519/cryptography, SQLite, pytest, Ruff, mypy strict, OpenSpec.

---

### Task 1: Disable unauthenticated reconciliation and freeze expansion

**Files:**
- Modify: `harness/src/insurance_harness/goldenset/admission_budget.py`
- Modify: `harness/tests/test_run_admission_budget_020.py`
- Modify: `harness/tests/test_run_admission_request_pool_020.py` only if an existing expansion fixture must be made immutable
- Modify: `openspec/changes/020-golden-v01-baseline-run/specs/run/spec.md`
- Modify: `openspec/changes/020-golden-v01-baseline-run/design.md`

- [x] **Step 1: Write RED tests for D1.3b fail-closed no-usage handling**

Add tests proving no production or test API can move `prepared|sent|uncertain` to `no_usage`; a legacy/tampered `no_usage` row cannot release or settle at zero and is recovered as `uncertain` with full-reserve charge and cleared proof fields.

- [x] **Step 2: Run the focused tests and verify RED**

Run: `cd harness && .venv/bin/pytest -q tests/test_run_admission_budget_020.py -k 'no_usage or expansion'`

Expected: FAIL because arbitrary `ProviderNoUsageProof` is currently accepted, legacy `no_usage` can release/settle at zero, and expansion currently admits additions.

- [x] **Step 3: Remove the unsafe reconciliation capability**

Remove `ProviderNoUsageProof` and `record_provider_no_usage`. Release only reservations with zero attempts. Reject `no_usage` during settlement; recovery converts any such row to `uncertain`, restores full maximum charge, and clears legacy proof fields. Record the separately scoped trust-root/key-role/provenance/loader work as a future OpenSpec rather than adding a test-only authority.

- [x] **Step 4: Write RED tests for D1.3c immutable expansion**

Test that later budget revisions reject any added/removed/changed product, exact request, or request pool while still accepting a pure monotonically larger account ceiling with identical limits/rates.

- [x] **Step 5: Implement exact set/value equality for expansion**

Validate the new contract's product/request/pool structure against revision 1 before any inserts or account update. Expansion may change only the account ceiling and signed approval lineage.

- [x] **Step 6: Verify Task 1 GREEN**

Run the focused budget and request-pool suites, then Ruff and mypy for changed modules.

### Task 2: Make execution identity and dependency merge pins load-bearing

**Files:**
- Modify: `harness/src/insurance_harness/goldenset/admission_probe.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_runtime.py`
- Modify: `harness/src/insurance_harness/goldenset/admission_identity.py`
- Modify: `harness/tests/test_run_admission_probe_020.py`
- Modify: `harness/tests/test_run_admission_runtime_020.py`
- Modify: `harness/tests/test_run_admission_identity_020.py`
- Modify: `openspec/changes/020-golden-v01-baseline-run/run-admission.yaml`
- Regenerate: `openspec/changes/020-golden-v01-baseline-run/run-admission.json`
- Regenerate: `openspec/changes/020-golden-v01-baseline-run/run-admission.md`
- Modify: `openspec/changes/020-golden-v01-baseline-run/specs/run/spec.md`
- Modify: `openspec/changes/020-golden-v01-baseline-run/design.md`
- Modify: `openspec/changes/020-golden-v01-baseline-run/validation-report.md`

- [x] **Step 1: Write RED tests for revision-only Bailian plans**

Prove that production probe/runtime reject a role carrying only `expected_model_revision`: the mutable deployment alias cannot become executable because the POST carries only `model_id`. Prove an exact immutable deployment identity must equal the value actually sent as `model`; otherwise remain `BLOCKED` with zero inference calls.

- [x] **Step 2: Implement the production identity restriction**

For the Bailian production policy require a provider-guaranteed invocable immutable deployment ID and require it to equal `model_id`. Keep revision metadata as audit/freshness evidence only where it cannot authorize a mutable alias. Do not weaken test-only policies or add a force path.

- [x] **Step 3: Write RED tests for designated merge revisions**

Prove feature-head/cherry-picked ancestry is insufficient and only the code-owned designated 019/021 merged revisions satisfy the dependency identity contract.

- [x] **Step 4: Pin the actual merges and prepare clean regeneration**

Pin 019 merge `4d9c84e25bd53f3564631b8f8dc0b1f85e21e55f` and 021 merge `cfefcc9b3a7d6af0503f3b76cf8ac5a1b6d44b35`, update the identity contract/hash, then use a two-phase commit: first commit reviewed code/YAML, regenerate canonical BLOCKED JSON/Markdown from the CLI on that clean code commit, and commit derived artifacts separately. Do not hand-edit derived hashes or publish provisional `dirty_consumed_file` output.

- [x] **Step 5: Verify Task 2 GREEN**

Run probe/runtime/identity/CLI focused suites, OpenSpec strict, Ruff, and mypy.

### Task 3: Final integration and PR completion

**Files:**
- Modify: `openspec/changes/020-golden-v01-baseline-run/tasks.md`
- Modify: `openspec/changes/020-golden-v01-baseline-run/validation-report.md`
- Modify: `HANDOFF.md` only if the merge/readiness evidence changed

- [x] **Step 1: Run the complete local gates**

Run focused 020 tests, the full non-live deterministic suite, Ruff, mypy strict, OpenSpec strict, `git diff --check`, and the relevant PostgreSQL lane where configured. Record exact counts and honest BLOCKED operational state.

- [x] **Step 2: Independent spec review, then code-quality review**

Require no open P0/P1/P2. Any finding returns to its implementer and is re-reviewed.

Independent high-risk review produced the four P1s addressed by this plan; the budget/spec follow-up was approved. The main thread re-reviewed the final Bailian identity and HTTP mutation boundary after the optional final reviewer exceeded the two-minute no-result cutoff. No P0/P1/P2 remains open.

- [ ] **Step 3: Commit and push**

Commit the complete hardening batch to `codex/020-golden-v01-run-admission`, push it, and update PR #24 with the four findings and their fixes.

- [ ] **Step 4: Wait for new-SHA CI and merge**

Require deterministic, integration-postgres, and wheel-smoke success on the new head SHA. Merge only if GitHub reports mergeable/clean and the current operational artifact remains honestly `BLOCKED` until external admissions are supplied.
