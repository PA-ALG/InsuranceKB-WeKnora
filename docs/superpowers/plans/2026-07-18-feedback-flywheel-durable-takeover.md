# Feedback Flywheel Durable Takeover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close PR #18's remaining durability, exactly-once, tenant-isolation, and empty-knowledge gaps without inventing a Langfuse or ReviewItem contract that the current platform does not support.

**Architecture:** Keep `run_pull` as the deterministic pure evaluator. Add a Space-scoped SQLAlchemy repository that locks one KnowledgeSpace, loads the source checkpoint and gap state, evaluates traces, persists redacted observations and gap aggregates, and advances the checkpoint in one caller-owned transaction. The CLI uses the repository for both read-only dry-run and `--apply`; filesystem state is removed as the source of truth. Langfuse direct mode and ReviewItem projection remain gated until their external citation and action contracts are specified.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, SQLite contract tests, PostgreSQL integration tests, pytest, Ruff, mypy strict, OpenSpec.

---

### Task 1: Harden the OpenSpec contract before implementation

**Files:**
- Modify: `openspec/changes/015-feedback-flywheel/specs/flywheel/spec.md`
- Modify: `openspec/changes/015-feedback-flywheel/tasks.md`
- Modify: `openspec/changes/README.md`
- Modify: `docs/insurance-kb/03-knowledge-model.md`

- [x] **Step 1: Replace file-state wording with database invariants**

  Specify Space + source scoped checkpoints, an observation ledger, durable gaps, transactionally atomic observation/gap/checkpoint writes, and retry exactness. State that dry-run is read-only and that file exports are derivatives, never state.

- [x] **Step 2: Clarify the gated boundaries**

  Keep F1.1b gated on the real WeKnora/Langfuse citation contract. Keep F2.4 gated because the current ReviewItem approve/reject resolver requires a ChangeItem; require an explicit knowledge-gap action contract before projection.

- [x] **Step 3: Reserve migration 0012 and document tables first**

  Register `flywheel_checkpoints`, `flywheel_observations`, and `knowledge_gaps` under migration 0012. Document Space composite foreign keys and unique identities.

- [x] **Step 4: Validate the delta**

  Run: `DO_NOT_TRACK=1 openspec validate 015-feedback-flywheel --strict`
  Expected: `Change '015-feedback-flywheel' is valid`.

### Task 2: Add the durable schema and migration through TDD

**Files:**
- Create: `harness/tests/test_flywheel_migration_015.py`
- Create: `harness/src/insurance_harness/flywheel/tables.py`
- Create: `harness/migrations/versions/0012_feedback_flywheel.py`

- [x] **Step 1: Write failing migration tests**

  Cover upgrade from 0005, table/column/unique/check/FK contracts, cross-Space observation-to-gap rejection, and downgrade to 0005.

- [x] **Step 2: Verify RED**

  Run: `PYTHONPATH=src uv run pytest tests/test_flywheel_migration_015.py -q`
  Expected: FAIL because revision 0012 and the three tables do not exist.

- [x] **Step 3: Implement minimal ORM and Alembic schema**

  Add:
  - `FlywheelCheckpoint`: `(space_id, source_id)` unique, cursor token, timestamps.
  - `FlywheelObservation`: Space/source/trace identity, UTC timestamp, redacted question, signals, alignment outcome, optional composite Space + gap FK.
  - `KnowledgeGapRow`: Space + gap key unique, aligned dimensions, signals, hit count, recent samples, lifecycle timestamps/status.

- [x] **Step 4: Verify GREEN**

  Run the focused migration test and confirm all tests pass.

### Task 3: Expose complete trace evaluations from the pure core

**Files:**
- Modify: `harness/tests/test_flywheel_pull_015.py`
- Modify: `harness/src/insurance_harness/flywheel/pull.py`

- [x] **Step 1: Write failing F2.1/F3.3 tests**

  Assert `PullResult` carries one redacted evaluation per fresh trace, including empty signals, alignment reason/entity, and the resulting gap key. This is the payload persisted by the observation ledger.

- [x] **Step 2: Verify RED**

  Run the new focused test and confirm it fails because evaluations are absent.

- [x] **Step 3: Implement the minimal immutable evaluation model**

  Populate evaluations inside `run_pull` without adding I/O or changing signal semantics.

- [x] **Step 4: Verify GREEN and the existing flywheel tests**

### Task 4: Add Space-scoped repository reads and the real empty-knowledge lookup

**Files:**
- Create: `harness/tests/test_flywheel_repository_015.py`
- Create: `harness/src/insurance_harness/flywheel/repository.py`
- Modify: `harness/src/insurance_harness/flywheel/__init__.py`

- [x] **Step 1: Write failing repository tests**

  Cover Space/source checkpoint isolation, gap round-trip, unaligned queue queries, and `has_published_claim` for product-level and field-level alignments. Include a cross-Space negative test.

- [x] **Step 2: Verify RED**

  Run: `PYTHONPATH=src uv run pytest tests/test_flywheel_repository_015.py -q`
  Expected: FAIL because repository APIs do not exist.

- [x] **Step 3: Implement typed row/domain conversion and scoped queries**

  Every public repository function must call `require_current_scope`; all SQL predicates include `space_id`. The claim lookup joins product versions to published claims and never treats another Space's claims as coverage.

- [x] **Step 4: Verify GREEN**

### Task 5: Make apply atomic and retry-exact through TDD

**Files:**
- Modify: `harness/tests/test_flywheel_repository_015.py`
- Modify: `harness/src/insurance_harness/flywheel/repository.py`

- [x] **Step 1: Write failing F1.1a/F3.3 atomicity tests**

  Cover:
  - observation + gap + checkpoint committed together;
  - injected failure after observation staging rolls back all three;
  - retry after rollback increments a gap exactly once;
  - duplicate input and repeated apply do not duplicate observations or counts;
  - two sources in one Space keep independent checkpoints.

- [x] **Step 2: Verify RED**

- [x] **Step 3: Implement one caller-owned unit of work**

  Lock the KnowledgeSpace row before loading checkpoint state, evaluate while the lock is held, upsert observation/gap rows, then advance the checkpoint. Do not commit inside the repository. Persistence errors propagate so the caller rolls back the whole transaction; never continue after a failed flush.

- [x] **Step 4: Verify GREEN**

### Task 6: Replace filesystem state in the CLI

**Files:**
- Modify: `harness/tests/test_flywheel_cli_015.py`
- Modify: `harness/src/insurance_harness/flywheel/cli.py`

- [x] **Step 1: Write failing CLI tests**

  Assert:
  - `--source-id` is required;
  - dry-run reads durable state but writes no checkpoint/observation/gap rows;
  - `--apply` commits all durable state;
  - a failed apply leaves all three tables unchanged;
  - state cannot leak when the same source ID is used in two Spaces;
  - CLI injects the real published-Claim lookup so `empty_knowledge_active=True` only when evaluated.

- [x] **Step 2: Verify RED**

- [x] **Step 3: Implement minimal CLI integration**

  Remove cursor/gap files as state inputs. Keep report rendering deterministic. Keep `--open-tickets` as an I/O-free gate and reject it before connecting to the database.

- [x] **Step 4: Verify GREEN**

### Task 7: Add the PostgreSQL concurrency contract

**Files:**
- Create: `harness/tests/test_flywheel_postgres_015.py`
- Modify: `harness/tests/test_ci_lanes_022.py`
- Modify: `.github/workflows/harness-ci.yml` only if the existing `integration_postgres` collection does not discover the marker.

- [x] **Step 1: Write an integration_postgres test**

  Two sessions apply the same Space/source batch concurrently. Assert serial equivalence, one observation, one gap hit, and one checkpoint. Record `tests=1, skipped=0` in JUnit when the environment exists; otherwise local runs report an explicit skip.

- [x] **Step 2: Add the node to the CI lane allowlist**

  Update `POSTGRES_NODES` in `test_ci_lanes_022.py` and its collection assertions so the new test cannot silently fall out of the PostgreSQL job or leak into deterministic tests.

- [x] **Step 3: Verify RED/GREEN against the controlled PostgreSQL fixture**

### Task 8: Reconcile evidence and handoff

**Files:**
- Modify: `openspec/changes/015-feedback-flywheel/tasks.md`
- Modify: `openspec/changes/015-feedback-flywheel/validation-report.md`
- Modify: `HANDOFF.md`

- [x] **Step 1: Map every new invariant to a test name**

- [x] **Step 2: Remove obsolete file-state claims and record the takeover lesson**

  Record that local atomic file replacement cannot satisfy a multi-instance enterprise exactly-once contract and that ReviewItem projection stayed gated because its action resolver is ChangeItem-specific.

- [x] **Step 3: Run final gates**

  From repository root:
  - `DO_NOT_TRACK=1 openspec validate 015-feedback-flywheel --strict`
  - `git diff --check`

  From `harness/`:
  - `uv run ruff check .`
  - `uv run mypy src tests`
  - `uv run pytest -m "not live and not integration_postgres" -q`
  - controlled `integration_postgres` collection with non-zero tests and zero skips.

- [x] **Step 4: Commit, push to `feat/015-feedback-flywheel`, update PR #18, and wait for the new SHA checks**
