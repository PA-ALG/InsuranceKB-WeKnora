# P2d Space Security Boundary Implementation Plan

> **For the future implementation agent:** REQUIRED SUB-SKILL:
> `superpowers:executing-plans`. Execute this plan task-by-task with review
> checkpoints.
>
> **Future implementation only. Current status:
> `BLOCKED ON P3 CONTRACT + IMPLEMENTATION + P1 READ-ONLY FENCE /
> NO IMPLEMENTATION AUTHORIZATION`.**
>
> This plan applies the writing-plans skill to the frozen OpenSpec 043. It must
> not be executed until a separate P3 amendment owns an ACL-inspection
> authority, P3 implementation and a P1-owned read-only active-fence verifier
> are merged into main, and a new Mission Card explicitly opens P2d
> implementation.

**Goal:** Implement the smallest PostgreSQL-backed boundary that makes current
RAW/Wiki ACL equivalence and the current immutable compilation security profile
the exact authority for provider calls and future Candidate/promotion rechecks.

**Architecture:** Two append-only, Space-scoped registries
(`KnowledgeSpaceBinding`, `CompilationSecurityProfileVersion`) are selected by
current pointers and monotonic epochs on `knowledge_spaces`; an append-only
`SecurityBoundaryMutationReceipt` records every success/no-op/deactivate for
durable idempotency. Every mutation serializes on the same Space row and uses
expected-pointer/epoch CAS. P2d consumes P3 principals and a separately amended
P3-owned ACL-inspection authority, C0 hashing, current WeKnora ACL snapshots,
P1-owned active-fence verification against the current job row/DB clock, and
the safe deny-only kernel from change 027. It exposes current ACL/authority
guards, exact snapshot verifier, and pre-call gate contracts but does not
implement provider transports, Candidate/promotion, P11/P9 endpoints, or
identity.

**Tech stack:** Python 3.12, SQLAlchemy 2, PostgreSQL 16, Alembic, Pydantic,
C0 `insurance_harness.canonical`, pytest/pytest-postgresql-compatible project
fixtures, Ruff, strict mypy, OpenSpec.

## Preconditions and stop conditions

Before touching implementation:

1. Fetch latest `origin/main`; verify a clean isolated worktree and actual
   single Alembic head.
2. Verify a separate P3 amendment freezes a P3-owned, least-privilege
   RAW+Wiki ACL-inspection authority (or equivalent authenticated human
   delegation), and verify P3 implementation—not merely OpenSpec 039—is merged
   and its public contract is importable.
3. Verify current P1 exposes a public, read-only active-fence verifier over the
   current PostgreSQL job row and DB clock. It must validate same
   Space/job/`running` state/attempt/generation/unexpired lease without renewing
   the lease, advancing state, or writing Outbox. `JobStore.heartbeat` is not an
   acceptable authorization verifier because it renews the lease.
4. Obtain a new Mission Card authorizing P2d production code and migration
   `0016`.
5. Re-read OpenSpec 043 and the then-current HANDOFF/control board.

Stop immediately if the P3 amendment/implementation or P1 read-only verifier is
absent, main is
multi-head, migration id 0016 has been consumed, current ACL snapshots cannot
be authenticated without P2d inventing a third principal/capability, or the
implementation would exceed 15 logical files/~900 production lines or require
a second migration/non-goal.

## Frozen path budget

The exact 14-path ledger is:

1. Modify `harness/src/insurance_harness/db/models.py`.
2. Modify `harness/src/insurance_harness/db/scope.py`.
3. Create `harness/src/insurance_harness/security_boundary/__init__.py`.
4. Create `harness/src/insurance_harness/security_boundary/contracts.py`.
5. Create `harness/src/insurance_harness/security_boundary/registry.py`.
6. Create `harness/src/insurance_harness/security_boundary/gate.py`.
7. Create
   `harness/migrations/versions/0016_space_security_boundary.py`.
8. Create `harness/tests/test_space_security_contracts_043.py`.
9. Create `harness/tests/test_space_security_gate_043.py`.
10. Create `harness/tests/test_space_security_migration_043.py`.
11. Create `harness/tests/test_space_security_postgres_043.py`.
12. Modify `openspec/changes/043-p2d-space-security-boundary/tasks.md`.
13. Modify
    `openspec/changes/043-p2d-space-security-boundary/validation-report.md`.
14. Modify `HANDOFF.md` current block at closeout.

If this count cannot hold, return to OpenSpec before adding files.
In particular, do not modify `model_policy/**`: `security_boundary/gate.py`
may import the accepted deny-only kernel, but new-route authority and the 027
cutover proof must live entirely in the named new boundary/tests. If an existing
027 entrypoint truly requires modification, STOP and amend/reapprove OpenSpec
plus this exact ledger before editing it.

At every task checkpoint:

- immediately after creating a new ledger file, run `git add -N <exact-path>`
  (intent-to-add only) so it appears in diff/numstat before implementation;
- run both `git diff --name-only <implementation-base-sha>` and
  `git ls-files --others --exclude-standard`; reject the union if any non-ignored
  path is outside the ledger, and require the untracked list to be empty after
  intent-to-add;
- run `git diff --numstat <implementation-base-sha> -- harness/src
  harness/migrations`; because every new production path is intent-to-add, this
  count includes tracked and newly created production lines. Record cumulative
  additions and stop before ~900 production lines;
- commit only in the future authorized implementation lane, never in this
  spec-only lane.

### Task 1: Re-open implementation only after P3

**Read/verify:**

- `openspec/changes/039-p3-api-worker-shell/`
- P3 implementation package and tests
- `openspec/changes/043-p2d-space-security-boundary/`
- `harness/src/insurance_harness/db/models.py`
- `harness/src/insurance_harness/db/scope.py`
- `harness/src/insurance_harness/model_policy/`
- latest Alembic head

**Steps:**

- [ ] Record exact main SHA as `<implementation-base-sha>`, branch, worktree,
  single Alembic head, P3 amendment merge, P3 implementation merge, and Mission
  Card.
- [ ] Confirm P3 exports the five human roles, two service principals, derived
  Space scope, unique authority/ability checks, and the separately amended
  ACL-inspection authority required by P2D.1/P2D.3. Confirm P2d adds no third
  principal/capability.
- [ ] Confirm the P1-owned public read-only verifier enforces
  Space/job/generation/`running`/attempt/unexpired lease from the current row
  and DB clock with zero writes. Confirm P2d does not call heartbeat/start or
  read/write `wiki_jobs` directly.
- [ ] Confirm migration id 0016 is still reserved to 043 and record the actual
  main single head that its `down_revision` must use.
- [ ] Record change 027 provenance (source commit/path, accepted/rejected
  behaviors) before importing its deny-only kernel.
- [ ] Run the path/production-LOC checkpoint. Expected: zero implementation
  diff.

No code is permitted if any check fails.

### Task 2: RED migration and immutable registry schema

**Files:**

- Create
  `harness/migrations/versions/0016_space_security_boundary.py`.
- Modify `harness/src/insurance_harness/db/models.py`.
- Create `harness/tests/test_space_security_migration_043.py`.
- Start `harness/tests/test_space_security_postgres_043.py`.

**Steps:**

- [ ] Write deterministic RED nodes:
  `test_0016_upgrade_downgrade_and_single_head`,
  `test_0016_legacy_bound_not_promoted`, and
  `test_0016_cross_space_fk_state_reason_and_append_only_guards`.
- [ ] Write PG16 RED node
  `test_pg_0016_schema_guards_and_single_head` in the PG file. It must prove two
  registries + mutation-receipt table, current pointers/epochs, composite FKs,
  current KB uniqueness, state/reason checks, idempotency uniqueness, and
  direct UPDATE/DELETE rejection.
- [ ] Mark all three newly created Task 2 paths intent-to-add with `git add -N`
  before any path/LOC checkpoint.
- [ ] From `harness/`, run:

  ```text
  uv run pytest -q \
    tests/test_space_security_migration_043.py::test_0016_upgrade_downgrade_and_single_head \
    tests/test_space_security_migration_043.py::test_0016_legacy_bound_not_promoted \
    tests/test_space_security_migration_043.py::test_0016_cross_space_fk_state_reason_and_append_only_guards
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres \
    tests/test_space_security_postgres_043.py::test_pg_0016_schema_guards_and_single_head \
    --junitxml=reports/p2d-task2.xml
  ```

  Expected RED: migration/columns/tables/constraints are absent; selected tests
  fail, and the PG node is collected rather than skipped.
- [ ] Implement only the ORM/migration needed by those nodes. Existing
  `binding_status=bound` rows get NULL current pointers/epoch zero; no active
  backfill, historical migration edit, Candidate/Release/principal table, or
  second migration.
- [ ] Rerun both commands and
  `uv run python scripts/check_junit.py reports/p2d-task2.xml`.
  Expected GREEN: deterministic nodes pass; PG JUnit tests >0/skipped=0.
- [ ] Run the path/LOC checkpoint; require cumulative paths ⊆ ledger and
  production additions below the 500–800 target trajectory.
- [ ] Future authorized checkpoint commit:
  stage exactly the four Task 2 files and commit
  `feat: add p2d immutable security schema`.

### Task 3: RED binding admission, reconciliation, and current ACL

**Files:**

- Create
  `harness/src/insurance_harness/security_boundary/{__init__,contracts,registry}.py`.
- Modify `harness/src/insurance_harness/db/scope.py`.
- Create `harness/tests/test_space_security_contracts_043.py`.
- Extend `harness/tests/test_space_security_postgres_043.py`.

**Steps:**

- [ ] Write deterministic RED nodes:
  `test_binding_content_hash_and_closed_state_reason`,
  `test_acl_admission_stable_equivalent_active`,
  `test_acl_admission_mismatch_unavailable_and_scope_unsupported`,
  `test_legacy_bound_without_current_binding_fails_closed`,
  `test_current_raw_acl_guard_denies_wiki_only_principal`, and
  `test_binding_reconcile_noop_replays_receipt_and_aba_advances_epoch`, plus
  `test_api_principal_permission_matrix_fails_before_handler_and_zero_write`
  and `test_mutation_receipt_binds_exact_authority_snapshot`.
- [ ] Write PG16 RED nodes
  `test_pg_duplicate_binding_mutation_and_rebind_serialize` and
  `test_pg_cross_space_pointer_and_kb_reuse_fail`. Use barriers to force
  duplicate-key and admit-vs-rebind overlap; no sleeps as correctness proof.
- [ ] Mark the four newly created security-boundary package/contract-test paths
  intent-to-add with `git add -N` before any path/LOC checkpoint.
- [ ] From `harness/`, run:

  ```text
  uv run pytest -q \
    tests/test_space_security_contracts_043.py::test_binding_content_hash_and_closed_state_reason \
    tests/test_space_security_contracts_043.py::test_acl_admission_stable_equivalent_active \
    tests/test_space_security_contracts_043.py::test_acl_admission_mismatch_unavailable_and_scope_unsupported \
    tests/test_space_security_contracts_043.py::test_legacy_bound_without_current_binding_fails_closed \
    tests/test_space_security_contracts_043.py::test_current_raw_acl_guard_denies_wiki_only_principal \
    tests/test_space_security_contracts_043.py::test_binding_reconcile_noop_replays_receipt_and_aba_advances_epoch \
    tests/test_space_security_contracts_043.py::test_api_principal_permission_matrix_fails_before_handler_and_zero_write \
    tests/test_space_security_contracts_043.py::test_mutation_receipt_binds_exact_authority_snapshot
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres \
    tests/test_space_security_postgres_043.py::test_pg_duplicate_binding_mutation_and_rebind_serialize \
    tests/test_space_security_postgres_043.py::test_pg_cross_space_pointer_and_kb_reuse_fail \
    --junitxml=reports/p2d-task3.xml
  ```

  Expected RED: package/exports are absent or all new admission/guard/
  concurrency assertions fail; PG nodes are selected with zero skip.
- [ ] Implement C0 contracts, P3-owned ACL-inspection adapter protocol,
  append-only binding registry, mutation receipt replay, Space row CAS, and
  `CurrentRawAclGuard`. Change `load_scope` to require current active binding.
  Use fake ACL adapters only; do not patch WeKnora, add a principal, implement
  an endpoint, or add per-Claim ACL.
- [ ] Rerun both commands and
  `uv run python scripts/check_junit.py reports/p2d-task3.xml`.
  Expected GREEN: exact selected nodes pass, PG tests >0/skipped=0.
- [ ] Run path/LOC checkpoint; require no path outside the ledger.
- [ ] Future authorized checkpoint commit: stage exactly Task 3 package/scope/
  contract-test/PG-test changes and commit
  `feat: add p2d binding admission and current acl guard`.

### Task 4: RED immutable security-profile registry

**Files:**

- Modify
  `harness/src/insurance_harness/security_boundary/{contracts,registry,__init__}.py`.
- Extend `harness/tests/test_space_security_contracts_043.py`.
- Extend `harness/tests/test_space_security_postgres_043.py`.

**Steps:**

- [ ] Write deterministic RED nodes
  `test_profile_hash_requires_complete_security_contract` and
  `test_profile_rotation_deactivate_receipts_and_aba`.
- [ ] Write PG16 RED node
  `test_pg_binding_and_profile_mutations_share_space_lock`; deterministically
  overlap binding reconciliation and profile rotation, then assert no lost
  update and exact stale-CAS result.
- [ ] In the same PG file, write RED node
  `test_pg_noop_deactivate_receipts_replay_without_epoch_or_version_duplication`.
  It SHALL cover binding no-op and profile deactivate; same key/hash returns the
  original durable result, same key/different hash conflicts, and neither retry
  inserts a duplicate version or increments epoch.
- [ ] From `harness/`, run:

  ```text
  uv run pytest -q \
    tests/test_space_security_contracts_043.py::test_profile_hash_requires_complete_security_contract \
    tests/test_space_security_contracts_043.py::test_profile_rotation_deactivate_receipts_and_aba
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres \
    tests/test_space_security_postgres_043.py::test_pg_binding_and_profile_mutations_share_space_lock \
    tests/test_space_security_postgres_043.py::test_pg_noop_deactivate_receipts_replay_without_epoch_or_version_duplication \
    --junitxml=reports/p2d-task4.xml
  ```

  Expected RED: profile DTO/registry/rotation do not exist or assertions fail;
  the PG interleaving is selected, not skipped.
- [ ] Implement every P2D.6 field in C0 content identity plus register+activate/
  rotate/deactivate current-pointer transactions. Persist no-op/deactivate
  mutation receipts even without a new profile version. Define external DLP/
  KMS/sanitizer/renderer as contracts and trusted adapter identities only; do
  not build a platform.
- [ ] Rerun both commands and
  `uv run python scripts/check_junit.py reports/p2d-task4.xml`.
  Expected GREEN: selected deterministic and PG nodes pass/skipped=0.
- [ ] Run path/LOC checkpoint.
- [ ] Future authorized checkpoint commit: stage Task 4 contract/registry/test
  changes and commit `feat: add immutable compilation security profiles`.

### Task 5: RED provider pre-call gate and 027 cutover

**Files:**

- Create `harness/src/insurance_harness/security_boundary/gate.py`.
- Modify `harness/src/insurance_harness/security_boundary/{contracts,__init__}.py`.
- Create `harness/tests/test_space_security_gate_043.py`.
- Extend `harness/tests/test_space_security_postgres_043.py`.

**Steps:**

- [ ] Write deterministic RED nodes:
  `test_gate_denies_without_current_authority_or_verified_attestations`,
  `test_gate_denies_stale_expired_reclaimed_or_nonrunning_job`,
  `test_gate_denies_current_acl_or_profile_rotation_before_dispatch`,
  `test_gate_records_old_authority_only_after_linearization`, and
  `test_legacy_027_receipt_never_authorizes_p2d_gate`, plus
  `test_worker_authorization_is_read_only_and_all_denials_zero_write`.
- [ ] Write PG16 RED node
  `test_pg_gate_rejects_profile_acl_and_fence_interleavings`. Use barriers/fake
  ACL adapter to cover profile rotation, ACL revoke, DB-clock lease expiry,
  higher-generation reclaim, non-running state and attempt mismatch before
  dispatch; every stale branch asserts fake transport count 0.
- [ ] Mark the new gate implementation/test paths intent-to-add with
  `git add -N` before any path/LOC checkpoint.
- [ ] From `harness/`, run:

  ```text
  uv run pytest -q \
    tests/test_space_security_gate_043.py::test_gate_denies_without_current_authority_or_verified_attestations \
    tests/test_space_security_gate_043.py::test_gate_denies_stale_expired_reclaimed_or_nonrunning_job \
    tests/test_space_security_gate_043.py::test_gate_denies_current_acl_or_profile_rotation_before_dispatch \
    tests/test_space_security_gate_043.py::test_gate_records_old_authority_only_after_linearization \
    tests/test_space_security_gate_043.py::test_legacy_027_receipt_never_authorizes_p2d_gate \
    tests/test_space_security_gate_043.py::test_worker_authorization_is_read_only_and_all_denials_zero_write
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres \
    tests/test_space_security_postgres_043.py::test_pg_gate_rejects_profile_acl_and_fence_interleavings \
    --junitxml=reports/p2d-task5.xml
  ```

  Expected RED: gate/attestation issuer does not exist or new denial/interleaving
  assertions fail; PG node is selected with zero skip.
- [ ] Implement the minimal sealed gate in the named new file. It loads current
  binding/profile, revalidates WeKnora ACL/freshness, accepts only code-owned
  opaque `VerifiedSecurityAttestation`, invokes P1-owned active-fence authority,
  and emits single-use authorization plus secret-free receipt. The P1 verifier
  must be read-only; do not call heartbeat/start, mutate the job/lease, or write
  a receipt on DENY/runtime failure. Import 027
  deny-only identity helpers without editing `model_policy/**`; old 027
  receipt/permit/view must fail the new gate. Do not add a provider SDK or real
  network transport.
- [ ] Rerun both commands and
  `uv run python scripts/check_junit.py reports/p2d-task5.xml`.
  Expected GREEN: selected nodes pass/skipped=0, all denial paths transport=0.
- [ ] Run path/LOC checkpoint. Any perceived need to edit `model_policy/**`
  requires STOP + OpenSpec/ledger reapproval, not an ad hoc change.
- [ ] Future authorized checkpoint commit: stage Task 5 gate/contracts/tests
  and commit `feat: add p2d provider pre-call security gate`.

### Task 6: RED exact SecurityAuthoritySnapshot verifier

**Files:**

- Modify
  `harness/src/insurance_harness/security_boundary/{contracts,registry,__init__}.py`.
- Extend `harness/tests/test_space_security_contracts_043.py`.
- Extend `harness/tests/test_space_security_postgres_043.py`.

**Steps:**

- [ ] Write deterministic RED nodes
  `test_security_authority_snapshot_requires_current_acl_and_exact_epochs` and
  `test_p6b_p8_fake_consumers_fail_closed_without_domain_side_effects`.
- [ ] Write PG16 RED node
  `test_pg_snapshot_verifier_rejects_acl_profile_epoch_drift`; interleave
  snapshot read with ACL/profile/binding epoch changes including A→B→A.
- [ ] From `harness/`, run:

  ```text
  uv run pytest -q \
    tests/test_space_security_contracts_043.py::test_security_authority_snapshot_requires_current_acl_and_exact_epochs \
    tests/test_space_security_contracts_043.py::test_p6b_p8_fake_consumers_fail_closed_without_domain_side_effects
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres \
    tests/test_space_security_postgres_043.py::test_pg_snapshot_verifier_rejects_acl_profile_epoch_drift \
    --junitxml=reports/p2d-task6.xml
  ```

  Expected RED: snapshot/verifier API is absent or exact drift assertions fail;
  the PG node is selected with zero skip.
- [ ] Implement only read-only snapshot/verifier APIs. Issue a C0 snapshot only
  after current RAW/Wiki ACL/freshness exact revalidation. Fake P6b/P8 consumers
  prove stale/requeue and zero side effects; do not create Candidate, Decision,
  Release, input-batch, requeue or Outbox production code.
- [ ] Rerun both commands and
  `uv run python scripts/check_junit.py reports/p2d-task6.xml`.
  Expected GREEN: selected nodes pass/skipped=0.
- [ ] Run path/LOC checkpoint; production additions must still be <~900.
- [ ] Future authorized checkpoint commit: stage Task 6 contract/registry/test
  changes and commit `feat: add exact p2d security authority verifier`.

### Task 7: PostgreSQL 16 acceptance

**Files:**

- No new path. Final-rerun the RED-first PG nodes accumulated in Tasks 2–6.

**Steps:**

- [ ] From `harness/`, collect the exact lane:

  ```text
  uv run pytest --collect-only -q -m integration_postgres \
    tests/test_space_security_postgres_043.py
  ```

  Expected: all named PG nodes from Tasks 2–6 are collected; zero unrelated
  live/deterministic nodes.
- [ ] Run final deterministic focused:

  ```text
  uv run pytest -q -m "not live and not integration_postgres" \
    tests/test_space_security_contracts_043.py \
    tests/test_space_security_gate_043.py \
    tests/test_space_security_migration_043.py
  ```

  Expected: all selected tests pass.
- [ ] Run the complete PostgreSQL 16 file:

  ```text
  HARNESS_TEST_POSTGRES_URL=<redacted-postgres16-url> uv run pytest -q \
    -m integration_postgres tests/test_space_security_postgres_043.py \
    --junitxml=reports/p2d-043-postgres.xml
  uv run python scripts/check_junit.py reports/p2d-043-postgres.xml
  ```

  Expected: tests >0, failed=0, skipped=0. SQLite never satisfies this task.
- [ ] Verify the report covers schema guards, duplicate/no-op/deactivate
  idempotency, admit/rebind/profile serialization, cross-Space rejection,
  profile/ACL dispatch interleavings, P1 DB-clock lease expiry/reclaim/
  generation/state/attempt fencing, and snapshot drift.
- [ ] Run final path/LOC checkpoint. Any unlisted path or production additions
  at/above ~900 stop the plan and return to OpenSpec.

### Task 8: Closeout and review

- [ ] From `harness/`, run:

  ```text
  uv run ruff check src tests
  uv run mypy src tests
  ```

  Expected: exit 0.
- [ ] From repo root, run:

  ```text
  openspec validate 043-p2d-space-security-boundary --strict
  git diff --check
  git diff --name-only <implementation-base-sha>
  git ls-files --others --exclude-standard
  git diff --numstat <implementation-base-sha> -- harness/src harness/migrations
  ```

  Expected: strict PASS; tracked-diff + untracked union contains only the exact
  14-path ledger and the untracked list is empty after intent-to-add; exactly
  one `0016_*` migration; numstat includes all new production paths and remains
  <~900 additions; UTF-8/LF/diff clean.
- [ ] Run repository-standard private/secret scan over the exact diff and
  confirm zero credential/DSN/token/private-key values. Do not print matched
  secret values.
- [ ] Confirm no provider SDK/real provider call, Go/Vue, Candidate/Decision/
  Release, principal/auth, DLP/KMS platform, historical cleanup or upstream
  Tencent work.
- [ ] Dispatch the P2d-required independent Spec plus Quality/Security reviews.
  Resolve every Critical/Important finding with a named RED node, then rerun the
  exact focused/PG commands above.
- [ ] Modify only OpenSpec 043 tasks/validation and `HANDOFF.md` current block
  with exact, non-inflated evidence. Keep provider/model/live/full as NOT RUN
  unless a later Mission Card separately authorized and actually ran them.
- [ ] Future authorized closeout commit: stage only the exact ledger, review the
  staged diff, and commit `feat: implement p2d space security boundary`.

No full/provider/live/model claim may be made unless a later Mission Card
explicitly authorizes and the corresponding lane actually ran.
