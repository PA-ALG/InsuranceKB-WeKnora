# 018 Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every merge-relevant Claude review finding on PR #9 without changing the approved 018 snapshot/saga architecture.

**Architecture:** Keep 007 characterization helpers in test support, enforce deterministic database constraints at the fixture boundary, and harden the existing `ReleasePublisher` state machine with operation-history-aware reconciliation decisions. Migration and live-test changes are contract corrections only; no new production subsystem is introduced.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, pytest/pytest-asyncio, Ruff, mypy strict, OpenSpec, PostgreSQL 16, WeKnora live workflow.

**Repository rule:** `CLAUDE.md` forbids AI commit/push. Workers modify and verify files only; the human owner authorizes Git operations after review.

---

## File map

- `harness/tests/support/legacy_publisher_007.py` — self-contained copies of the three retired 007-only helpers.
- `harness/src/insurance_harness/knowledge/publisher.py` — remove retired helpers; make reconciliation and rollback lease recovery follow R3.4/R4.2.
- `harness/tests/conftest.py` — enable SQLite foreign-key enforcement only for `kb_session`.
- `harness/tests/test_publish_state_machine_018.py` — R3.1/R3.4/R3.7 regression tests.
- `harness/tests/test_snapshot_guards_018.py` — R2.1 real cross-Space pointer and R6.4 database FK tests.
- `harness/tests/test_reconcile_018.py` — R4.2 rollback lease recovery audit test.
- `harness/tests/test_release_snapshot_migration_018.py` — pin 0005 contract tests to revision `0005`.
- `harness/tests/test_release_snapshot_live_018.py` — schema-only PostgreSQL `search_path` and deterministic helper contract.
- `openspec/changes/018-release-snapshot-read-model/{design.md,tasks.md,specs/release-read-model/spec.md,validation-report.md` — approved requirements, checklist, and fresh evidence.
- `HANDOFF.md` — final PR #9 merge blockers and evidence status.

### Task 1: R3.7 production/test boundary

**Files:**
- Modify: `harness/tests/test_publish_state_machine_018.py`
- Modify: `harness/tests/support/legacy_publisher_007.py`
- Modify: `harness/src/insurance_harness/knowledge/publisher.py`

- [x] **Step 1: Write the failing production-boundary test**

Add `test_r3_7_retired_007_helpers_are_not_exported_by_production_publisher` asserting the production module has none of:

```python
(
    "_snapshot_claims_for_publish",
    "_validate_rollback_pages",
    "_move_pointer",
)
```

- [x] **Step 2: Verify RED**

Run:

```bash
cd harness
uv run pytest tests/test_publish_state_machine_018.py::test_r3_7_retired_007_helpers_are_not_exported_by_production_publisher -q
```

Expected: FAIL because all three attributes currently exist on `publisher_module`.

- [x] **Step 3: Make the 007 support self-contained**

Copy only those three helper implementations and their required imports into
`tests/support/legacy_publisher_007.py`. Continue importing genuinely shared production primitives such as `_upsert_page` and scope validators. Preserve the old 007 characterization semantics exactly; do not move its non-empty page/claim validation into 018 production behavior.

- [x] **Step 4: Remove the three helpers from production**

Delete the three definitions from `publisher.py` and remove imports that become unused. Do not alter `ReleasePublisher`, zero-fact release, or frozen-plan rollback behavior.

- [x] **Step 5: Verify GREEN and legacy characterization**

Run:

```bash
cd harness
uv run pytest \
  tests/test_publish_state_machine_018.py::test_r3_7_retired_007_helpers_are_not_exported_by_production_publisher \
  tests/test_knowledge_publisher.py \
  tests/test_knowledge_e2e.py \
  tests/test_scope_publisher_016.py -q
```

Expected: PASS; production boundary is clean and 007 characterization remains unchanged.

### Task 2: R6.4 SQLite FK enforcement and R2.1 cross-Space guard

**Files:**
- Modify: `harness/tests/conftest.py`
- Modify: `harness/tests/test_snapshot_guards_018.py`

- [x] **Step 1: Write two failing tests**

Add:

```python
def test_r6_4_kb_session_enforces_sqlite_foreign_keys(kb_session: Session) -> None:
    assert kb_session.scalar(text("PRAGMA foreign_keys")) == 1
```

Then extend the same test with a cross-Space composite-FK insert against a table not protected by the CurrentRelease trigger (for example a `ReleaseOperation` whose `space_id` differs from its `target_snapshot_id` owner) and assert `IntegrityError`.

Extend `test_r2_1_current_pointer_rejects_legacy_failed_and_cross_space_targets` to create Space B plus a published/frozen Space B snapshot, then attempt to make Space A current point to it and assert database rejection.

- [x] **Step 2: Verify RED**

Run:

```bash
cd harness
uv run pytest \
  tests/test_snapshot_guards_018.py::test_r6_4_kb_session_enforces_sqlite_foreign_keys \
  tests/test_snapshot_guards_018.py::test_r2_1_current_pointer_rejects_legacy_failed_and_cross_space_targets -q
```

Expected: the PRAGMA assertion fails (`0`), and the new FK-only negative path is not protected until the fixture enables enforcement.

- [x] **Step 3: Enable FK only in `kb_session`**

Before `Base.metadata.create_all(engine)`, execute `PRAGMA foreign_keys=ON` on the engine connection used by the fixture. Keep `make_engine` and migration fixtures unchanged because migration tests intentionally inspect historical FK states.

- [x] **Step 4: Verify GREEN**

Re-run the two nodes above, then:

```bash
cd harness
uv run pytest tests/test_snapshot_guards_018.py tests/test_release_snapshot_migration_018.py -q
```

Expected: PASS, including migration behavior that must not inherit the fixture-only setting.

### Task 3: R3.1 stale-base retry is side-effect free

**Files:**
- Modify: `harness/tests/test_publish_state_machine_018.py`
- Modify only if RED exposes a defect: `harness/src/insurance_harness/knowledge/publisher.py`

- [x] **Step 1: Write the failing/characterization test**

Add `test_r3_1_retry_rejects_failed_plan_after_current_changes_without_side_effects`:

1. Publish snapshot X successfully.
2. Create failed operation A with base X by failing a later release.
3. Publish unrelated snapshot Y successfully so current is no longer X.
4. Capture operation A `retry_no`, attempt count, Wiki call/mutation count, and current.
5. Retry A and assert `ScopeViolation`.
6. Assert every captured value remains unchanged.

- [x] **Step 2: Verify the test is load-bearing**

Run the new node. If it passes against current code, temporarily mutate the base-current comparison in `_retry_operation_locked`, run again and observe the expected failure, then immediately restore the production file. This proves the characterization test guards the intended branch without retaining the mutation.

- [x] **Step 3: Implement only if current behavior fails**

Keep the base-current validation before `retry_no += 1`, status change, commit, and `_execute_active`. Do not create an extra operation or reconciliation job on rejection.

- [x] **Step 4: Verify GREEN**

Run:

```bash
cd harness
uv run pytest tests/test_publish_state_machine_018.py -q
```

Expected: PASS with the new stale-base zero-side-effect assertion.

### Task 4: R3.4 collision compensation and R4.2 rollback recovery audit

**Files:**
- Modify: `harness/tests/test_publish_state_machine_018.py`
- Modify: `harness/tests/test_reconcile_018.py`
- Modify: `harness/src/insurance_harness/knowledge/publisher.py`

- [x] **Step 1: Write the first-action collision RED test**

Seed a third-party page at the first planned slug and publish. Assert collision attempt + failed operation/snapshot + unchanged current, but zero `ReconciliationJob` because the operation has no succeeded/started/unknown mutation history.

- [x] **Step 2: Write the operation-history collision test**

Exercise or seed the same failed operation with an earlier succeeded or unknown mutation attempt, then encounter collision on a later retry/action. Assert exactly one reconciliation job for that operation. The decision must inspect all retries, not only the current call's action index.

- [x] **Step 3: Verify collision tests RED**

Run both nodes. Expected: first-action test fails because current code passes `bool(plan.actions)` to `_mark_failed`; history-aware behavior is absent.

- [x] **Step 4: Implement history-aware reconciliation requirement**

Before `_mark_failed`, derive whether any persisted `PublishAttempt` for the operation represents a possible mutation (`succeeded`, or a `started`/failed result with `created_new is None` after mutation could be unknown). A collision proven to be pre-mutation for the entire operation passes `False`; all possible-mutation histories pass `True`. Keep the existing unique `(space_id, source_operation_id)` job guard.

- [x] **Step 5: Write rollback lease recovery RED test**

Create/obtain a rollback operation and ChangeSet, leave the operation `running` with an expired lease (and a started attempt where appropriate), call `recover_expired`, then assert operation `failed`, job present, and ChangeSet `partially_applied` rather than `pending`.

- [x] **Step 6: Verify RED and implement minimal recovery update**

In `_recover_expired_locked`, when an expired operation is `kind == "rollback"`, load the matching ChangeSet by `external_record_id == operation.id` and set non-applied state to `partially_applied`, mirroring `_mark_failed`.

- [x] **Step 7: Verify GREEN**

Run:

```bash
cd harness
uv run pytest tests/test_publish_state_machine_018.py tests/test_reconcile_018.py -q
```

Expected: PASS with correct job cardinality and audit state.

### Task 5: R6.4 migration revision and live schema isolation

**Files:**
- Modify: `harness/tests/test_release_snapshot_migration_018.py`
- Modify: `harness/tests/test_release_snapshot_live_018.py`

- [x] **Step 1: Add the live helper RED test**

Add `test_r6_4_live_postgresql_schema_does_not_fallback_to_public`, mirroring the existing integration helper test: `_connect_args("release_live_018_test")` contains that schema and does not contain `,public`.

- [x] **Step 2: Verify RED**

Run the node and observe failure because `_connect_args` currently emits `search_path=<schema>,public`.

- [x] **Step 3: Remove the public fallback**

Change the live helper to `-csearch_path={schema}` only. Do not modify credentials, live API calls, cleanup ownership, or skip policy.

- [x] **Step 4: Pin 0005 contract tests**

Use `command.upgrade(..., "0005")` for tests whose names and assertions are specifically the 0005 schema/guard/default contract. Keep `test_r1_4_0005_metadata_matches_head_and_alembic_check` on `head`, since it intentionally verifies current metadata against repository head.

- [x] **Step 5: Verify GREEN**

Run:

```bash
cd harness
uv run pytest tests/test_release_snapshot_migration_018.py tests/test_release_snapshot_live_018.py -m "not live" -q
```

Expected: PASS; deterministic helper test is collected, the real live node remains excluded.

### Task 6: Fresh gates, evidence, and PR readiness

**Files:**
- Modify: `openspec/changes/018-release-snapshot-read-model/tasks.md`
- Modify: `openspec/changes/018-release-snapshot-read-model/validation-report.md`
- Modify: `HANDOFF.md`

- [x] **Step 1: Run specification and focused gates**

```bash
DO_NOT_TRACK=1 openspec validate 018-release-snapshot-read-model --strict
cd harness
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live and not integration_postgres" -q
```

Record exact fresh counts, elapsed time, warnings, command, date, branch, and SHA/working-tree state. Do not retain the stale 73/171/1035 counts as current evidence.

- [x] **Step 2: Run PostgreSQL integration on the final tree**

With an available isolated PostgreSQL 16 URL:

```bash
cd harness
HARNESS_TEST_POSTGRES_URL='<redacted>' uv run pytest -m integration_postgres -q
```

Expected: zero skips. Never write the URL or credentials to tracked files or logs.

- [x] **Step 3: Update checklist and handoff honestly**

Mark RH1～RH5 complete only from matching evidence; mark RH6 PostgreSQL complete only after its run. Keep T7/live incomplete until the protected live workflow runs the exact five expected nodes with `tests=5 skipped=0`. State that PR #10 trusted workflow must merge before that run.

- [x] **Step 4: Review the final diff**

```bash
git diff --check
git status --short
git diff --stat
```

Ensure the unrelated untracked local-live plan/spec files are untouched and unstaged. Request Claude review on the final pushed SHA only after human-authorized commit/push.
