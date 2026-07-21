# Source Lifecycle Ordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every behavior step uses superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make source-aware notify, import, delete, and reactivation deterministic under retries, out-of-order delivery, and concurrent PostgreSQL sessions, while preserving Space isolation, caller-owned transactions, immutable release snapshots, and auditable recovery for 017 history that has no ordering.

**Architecture:** Add a strict `SourceOrdering` discriminated value carried from WeKnora `SourceRevision` through compiler manifests and `SourceImportIdentity`. Migration `0006` (whose current base is actual Alembic head `0012`) adds durable `SourceHead`, append-only `SourceEvent`, and `SourceLifecycleBackfillIssue`. A shared lifecycle coordinator validates the bound Space, blocks unresolved historical sources, acquires one stable per-source PostgreSQL transaction lock, evaluates the complete L3 matrix, and records accepted/idempotent/stale decisions inside each caller's nested savepoint. Existing notify/import/retract functions call that coordinator and keep ChangeSet, Evidence, tombstone, head, and event writes in one caller-owned unit of work. ReleaseSnapshot, SnapshotFact, and CurrentRelease remain outside this state machine.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL advisory/row locks, SQLite contract tests, pytest, Ruff, mypy strict, OpenSpec.

**Repository rule:** `CLAUDE.md` forbids AI workers from committing or pushing. Each task ends in a verified diff checkpoint; commit/push/PR steps are reserved for the human owner after final evidence.

**Command working directory:** All Harness commands in Tasks 2-8 run from `harness/`. Each command is written as `cd harness && uv run ...` so it is safe to copy from the repository root and matches `CLAUDE.md`.

**Execution stop-loss:** Each implementation slice must produce its first clause-named RED within 15 minutes and a verifiable diff or GREEN within 30 minutes. Poll tools/agents at 60 seconds; stop ordinary commands at 10 minutes; interrupt an unresponsive delegated slice at 2 minutes and continue in the main thread. Do not bundle the next slice before the current slice has spec then quality review.

---

### Task 1: Freeze the formal L1-L6 contract

**Files:**
- Modify: `openspec/changes/021-source-lifecycle-ordering/proposal.md`
- Modify: `openspec/changes/021-source-lifecycle-ordering/design.md`
- Delete: `openspec/changes/021-source-lifecycle-ordering/specs/source-lifecycle-ordering.md`
- Create: `openspec/changes/021-source-lifecycle-ordering/specs/source-lifecycle-ordering/spec.md`
- Modify: `openspec/changes/021-source-lifecycle-ordering/tasks.md`

- [x] **Step 1: Convert the flat draft into a formal OpenSpec delta**

  Add `## ADDED Requirements`, clauses L1-L6, executable scenarios, and clause-prefixed test naming.

- [x] **Step 2: Close the historical-data hole**

  Require a durable `SourceLifecycleBackfillIssue`, fail-closed normal lifecycle behavior while open, and an explicit audited atomic resolution entry point. Do not infer ordering from revision hashes, Evidence timestamps, ChangeSet timestamps, or filesystem metadata.

- [x] **Step 3: Close the delete transition matrix**

  Define every `absent|active|deleted × older|equal|newer × active|deleted` outcome, including first-event delete and newer delete on active/deleted heads.

- [x] **Step 4: Validate and independently review**

  Run: `DO_NOT_TRACK=1 openspec validate 021-source-lifecycle-ordering --strict`

  Expected: `Change '021-source-lifecycle-ordering' is valid`.

  Run: `git diff --check`

  Expected: no output. Independent review must return Approved with no Critical/Important.

### Task 2: Carry strict ordering from source metadata to import identity

**Files:**
- Create: `harness/tests/test_source_ordering_021.py`
- Modify: `harness/src/insurance_harness/sources/models.py`
- Modify: `harness/src/insurance_harness/sources/weknora.py`
- Modify: `harness/src/insurance_harness/sources/directory.py`
- Modify: `harness/src/insurance_harness/compiler/models.py`
- Modify: `harness/src/insurance_harness/compiler/pipeline.py`
- Modify: `harness/src/insurance_harness/knowledge/models.py`
- Modify: `harness/tests/support/source_bridge.py`
- Modify: `harness/tests/support/source_pipeline.py`
- Modify: `harness/tests/support/source_revision.py`
- Modify: affected 017 source fixtures that construct `SourceRevision` or `SourceImportIdentity`

- [x] **Step 1: Write L1 RED for the discriminated ordering value**

  Add `test_l1_*` cases for UTC-equivalent offsets, naive datetime rejection, non-negative strict integer generation, bool/float/string rejection, kind mixing, same revision/different ordering, and same ordering/different revision.

- [x] **Step 2: Prove RED is for the missing 021 behavior**

  Run: `cd harness && uv run pytest tests/test_source_ordering_021.py -q`

  Expected: collection/import or assertion failure because `SourceOrdering` and ordering fields do not exist. Preserve this exact output in the validation report.

- [x] **Step 3: Implement the minimal immutable ordering DTO**

  Add a Pydantic discriminated union for `processed_at` and `generation`. Canonicalize processed timestamps to UTC; use `StrictInt` and explicitly reject bool. Preserve the 017 processed-at revision hash canonical JSON so existing source revisions do not change merely because 021 is installed; generation gets an explicit distinct canonical input.

- [x] **Step 4: Propagate ordering without lossy reconstruction**

  Add ordering to `DocManifestEntry`, checkpoint identity comparisons, source bridge context construction, and `SourceImportIdentity`. The WeKnora adapter uses its required `processed_at`; directory replay uses its fixed deterministic processed timestamp. Deep revalidation must compare manifest, materialized document, import context, and evidence identity before writes.

- [x] **Step 5: Verify focused GREEN and 017 compatibility**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_ordering_021.py tests/test_source_models_017.py tests/test_source_pipeline_runtime_017.py tests/test_source_bridge_contract_017.py tests/test_source_weknora_017.py -q
  ```

  Expected: all pass; no model/network/live calls.

### Task 3A: Add the 0006 schema and ORM contracts

**Files:**
- Create: `harness/tests/test_source_lifecycle_migration_021.py`
- Modify: `harness/src/insurance_harness/db/models.py`
- Modify: `harness/src/insurance_harness/knowledge/tables.py`
- Create: `harness/migrations/versions/0006_source_lifecycle_ordering.py`
- Modify: `openspec/changes/README.md`
- Modify: `docs/insurance-kb/03-knowledge-model.md`

- [x] **Step 1: Write L2/L5 schema RED**

  Cover revision id `0006`, `down_revision == "0012"`, one Alembic head, SourceHead unique `(space_id, knowledge_id)`, Space/tenant/raw-KB composite closure, strict ordering/state/version checks, SourceEvent FK shape and decision enum, append-only update/delete rejection, BackfillIssue unique/open/resolved shape, and all required indexes.

- [x] **Step 2: Verify schema RED**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_migration_021.py -k 'schema or orm or append_only' -q`

  Expected: FAIL because migration 0006 and ORM rows do not exist.

- [x] **Step 3: Implement minimal ORM and Alembic schema**

  Add:

  - `SourceHead`: scoped source identity, ordering kind/value, `active|deleted`, CAS version, last event, actor/time.
  - `SourceEvent`: append-only incoming identity/desired state/decision, before/after head snapshots, causation/actor, optional ChangeSet/tombstone link.
  - `SourceLifecycleBackfillIssue`: scoped source, observed revisions, reason, `open|resolved`, resolver identity/actor/reason/time.

  Use dialect-appropriate durable append-only guards. PostgreSQL integration fixtures for 021 must run actual Alembic migrations instead of `Base.metadata.create_all`, so migration-only triggers cannot be bypassed.

- [x] **Step 4: Verify schema GREEN**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_migration_021.py -k 'schema or orm or append_only' -q`

  Expected: selected tests pass. Complete an independent spec review for Task 3A before 3B.

### Task 3B: Backfill historical 017 sources without guessing

**Files:**
- Modify: `harness/tests/test_source_lifecycle_migration_021.py`
- Modify: `harness/migrations/versions/0006_source_lifecycle_ordering.py`

- [x] **Step 1: Write historical backfill RED**

  Seed source-aware Evidence/ChangeSet rows with only revision hashes. Assert upgrade creates one open issue per Space/source, creates no guessed head, ignores unrelated legacy rows, and is idempotent. Assert it never uses `extracted_at`, `created_at`, or revision lexical order.

- [x] **Step 2: Verify backfill RED**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_migration_021.py -k backfill -q`

  Expected: FAIL because 0006 does not yet populate BackfillIssue.

- [x] **Step 3: Implement the minimal safe backfill**

  Enumerate distinct existing source-aware `(space_id, knowledge_id, raw_kb_id)` identities and their observed revision set. Insert one open issue per source. Never create a head during migration.

- [x] **Step 4: Verify backfill GREEN**

  Run the focused command again. Complete independent spec review for Task 3B before 3C.

### Task 3C: Add first-DDL preflight and conditional downgrade

**Files:**
- Modify: `harness/tests/test_source_lifecycle_migration_021.py`
- Modify: `harness/migrations/versions/0006_source_lifecycle_ordering.py`
- Modify: `openspec/changes/README.md`
- Modify: `docs/insurance-kb/03-knowledge-model.md`

- [x] **Step 1: Write chain-level downgrade RED**

  Cover: non-empty head/event/issue refuses downgrade before any DDL and leaves schema/data/alembic_version unchanged; empty lifecycle tables downgrade cleanly and roll forward to an equivalent schema; unexpected base/multiple heads fail before DDL.

- [x] **Step 2: Verify downgrade RED**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_migration_021.py -k 'downgrade or roll_forward or topology' -q`

  Expected: FAIL because 0006 has no chain-level preflight/downgrade policy.

- [x] **Step 3: Implement first-DDL preflight and conditional downgrade**

  Mirror the repository's chain-level preflight pattern. Downgrade refuses any lifecycle/provenance data before DDL; an empty lifecycle schema can downgrade and roll forward.

- [x] **Step 4: Verify migration GREEN and topology**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_lifecycle_migration_021.py -q
  cd harness && uv run alembic heads
  ```

  Expected: all tests pass and only `0006 (head)` is printed. Complete independent spec then quality review for the migration slice.

### Task 4A: Implement the pure lifecycle decision matrix

**Files:**
- Create: `harness/src/insurance_harness/knowledge/source_lifecycle.py`
- Create: `harness/tests/test_source_lifecycle_021.py`
- Modify: `harness/src/insurance_harness/knowledge/__init__.py`

- [x] **Step 1: Write a table-driven L2/L3 RED for every matrix cell**

  Cover absent/active/deleted heads, older/equal/newer input, desired active/deleted, revision collisions, and stable decisions: `accepted_create`, `accepted_advance`, `accepted_delete`, `accepted_reactivate`, `idempotent`, `stale`, `blocked_deleted`.

- [x] **Step 2: Add existing-head ordering-kind RED**

  Assert an existing processed_at head rejects generation input and vice versa before any event/business write. Same ordering/different revision and same revision/different ordering also fail closed.

- [x] **Step 3: Verify correct RED**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_021.py -q`

  Expected: FAIL because the pure decision engine does not exist.

- [x] **Step 4: Implement the minimal pure comparison engine**

  Implement exhaustive typed comparison without SQL or side effects. Return the stable decision plus proposed next head/business intent. Do not compare revision hashes or arrival time.

- [x] **Step 5: Verify pure GREEN**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_021.py -k decision -q`

  Expected: selected tests pass. Complete independent spec review for Task 4A before 4B.

### Task 4B: Persist scoped lock, CAS, head, and append-only events

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/source_lifecycle.py`
- Modify: `harness/tests/test_source_lifecycle_021.py`
- Modify: `harness/src/insurance_harness/knowledge/__init__.py`

- [x] **Step 1: Write persistence invariant RED**

  Assert stale only adds one audit event; idempotent reuses business rows; accepted delete intent uses one tombstone identity; head version changes only on accepted state/order transitions; events replay reconstructs head; malformed/cross-Space aggregates fail closed; caller outer transaction is never committed or rolled back.

  Add both existing processed_at head→incoming generation and existing generation head→incoming processed_at coordinator cases. Each must fail closed before any SourceHead, SourceEvent, Evidence, ChangeSet, or ChangeItem count/content changes; after the exception the same Session must still query and flush caller-owned work.

- [x] **Step 2: Verify persistence RED**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_021.py -k 'persistence or event or cas or scope' -q`

  Expected: FAIL because the SQL coordinator does not exist.

- [x] **Step 3: Implement validation, lock, compare, CAS, and event recording**

  Use one stable 64-bit digest of the full `(space_id, knowledge_id)` for PostgreSQL transaction advisory locking, then row lock/CAS on an existing head. Handle first creation with the same key. For SQLite deterministic tests use the same pure decision function but do not present SQLite locking as concurrency evidence. Never commit/rollback the caller outer transaction.

- [x] **Step 4: Verify persistence GREEN**

  Run the focused command again. Complete independent spec review for Task 4B before 4C.

### Task 4C: Resolve BackfillIssue through an audited atomic admin path

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/source_lifecycle.py`
- Modify: `harness/tests/test_source_lifecycle_021.py`
- Modify: `harness/src/insurance_harness/knowledge/__init__.py`

- [x] **Step 1: Write BackfillIssue resolution RED**

  Assert open issues block normal lifecycle; resolution requires database-attested scope, full valid ordering identity, desired state, actor, and reason; resolution creates initial head/event and stales/retracts incompatible historical Evidence atomically.

- [x] **Step 2: Add failure-injection RED**

  Flush prior caller work, inject failure after issue/head/event staging, and assert the issue remains open, no lifecycle writes leak, prior work remains, and the Session is usable.

- [x] **Step 3: Verify resolution RED, then implement the minimal admin service**

  Run: `cd harness && uv run pytest tests/test_source_lifecycle_021.py -k backfill_issue -q`

  Expected before implementation: FAIL for the missing resolver. Implement inside one nested savepoint without caller commit/rollback.

- [x] **Step 4: Verify complete lifecycle core GREEN and static checks**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_lifecycle_021.py -q
  cd harness && uv run ruff check src/insurance_harness/knowledge/source_lifecycle.py tests/test_source_lifecycle_021.py
  cd harness && uv run mypy src/insurance_harness/knowledge/source_lifecycle.py tests/test_source_lifecycle_021.py
  ```

### Task 5: Put notify on the shared state machine

**Files:**
- Create: `harness/tests/test_source_lifecycle_notify_021.py`
- Modify: `harness/src/insurance_harness/knowledge/source_revision.py`
- Modify: `harness/src/insurance_harness/knowledge/models.py`
- Modify: `harness/tests/test_source_revision_notify_017.py`
- Modify: `harness/tests/test_source_revision_import_017.py`

- [x] **Step 1: Write notify RED for L2/L3/L4**

  Cover first notify, same revision replay, B→C advance, C then late B, deleted equal/older block, newer reactivate, open backfill issue block, cross-Space same knowledge ID, and Snapshot/CurrentRelease zero change.

- [x] **Step 2: Write caller-owned transaction failure RED**

  Flush unrelated valid caller work, inject failure between head/event/recompile/Evidence writes, catch it, and assert lifecycle writes roll back while prior work and Session usability remain.

- [x] **Step 3: Verify RED, then implement minimal integration**

  Acquire/decide through `source_lifecycle.py` before reading or mutating Evidence/ChangeSet. Accepted active creates/reuses only its recompile aggregate and stales only older scoped active Evidence. Stale/blocked paths never create or awaken a recompile. Link the final event to the actual ChangeSet.

- [x] **Step 4: Verify notify GREEN plus the 017 suite**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_lifecycle_notify_021.py tests/test_source_revision_notify_017.py tests/test_source_revision_import_017.py -q
  ```

### Task 6: Put source-aware import on the same lock and decision

**Files:**
- Create: `harness/tests/test_source_lifecycle_import_021.py`
- Modify: `harness/src/insurance_harness/knowledge/importer.py`
- Modify: `harness/src/insurance_harness/knowledge/models.py`
- Modify: `harness/tests/test_knowledge_importer.py`
- Modify: `harness/tests/test_source_revision_import_017.py`

- [x] **Step 1: Write import RED**

  Cover first active import, pending notify aggregate consumption, duplicate import, late B after C, equal/older import against deleted, strictly newer reactivation, ordering collision, open backfill issue, and invalid source-aware identity never falling back to legacy.

- [x] **Step 2: Add multi-document deadlock-order RED**

  Assert partitions acquire full source keys in deterministic sorted order and all partitions remain one caller-owned savepoint; any partition failure rolls back every partition in that call while preserving caller work from before the call.

  Also add `test_l4_*` assertions that first import, recompile consumption, stale import, and reactivate do not create/modify/delete ReleaseSnapshot or SnapshotFact and do not move CurrentRelease.

- [x] **Step 3: Verify RED, then implement minimal integration**

  Move tombstone/existing ChangeSet reads behind the shared source lock. For each sorted partition, decide before creating a MergeEngine/ChangeSet. Stale/blocked partitions report a typed lifecycle result without importing records; accepted/reactivated partitions link their actual aggregate to SourceEvent.

- [x] **Step 4: Verify import GREEN and regression coverage**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_lifecycle_import_021.py tests/test_knowledge_importer.py tests/test_source_revision_import_017.py -q
  ```

### Task 7: Put delete/retract and reactivation on the complete matrix

**Files:**
- Create: `harness/tests/test_source_lifecycle_delete_021.py`
- Modify: `harness/src/insurance_harness/knowledge/merge.py`
- Modify: `harness/src/insurance_harness/knowledge/source_revision.py`
- Modify: `harness/tests/test_source_retract_017.py`

- [x] **Step 1: Write delete RED for every accepted/stale/idempotent branch**

  Cover first-event delete with empty tombstone, equal delete winning over active, older delete leaving new Evidence untouched, newer delete on active, newer delete on deleted, repeated delete reusing one tombstone, and only strictly newer active identity reactivating.

- [x] **Step 2: Add evidence and release-boundary RED**

  Assert accepted delete removes only same-Space/source Evidence and emits ChangeItems once per affected claim; no lifecycle transition changes ReleaseSnapshot, SnapshotFact, or CurrentRelease.

  Flush unrelated valid caller work, then inject failures after tombstone/event staging and midway through Evidence/ChangeItem mutation. After catching the error, assert every delete-unit write rolled back, prior caller work remains, the Session can query/flush, and outer commit/rollback is still caller-controlled.

- [x] **Step 3: Verify RED, then implement minimal integration**

  Route source-aware retract through the coordinator. Keep explicit legacy replay outside SourceHead but fail closed if source-aware head/event/issue/evidence exists. Create the tombstone inside the same savepoint and finalize the event only after Evidence/ChangeItems succeed.

- [x] **Step 4: Verify delete GREEN and 017 compatibility**

  Run:

  ```bash
  cd harness && uv run pytest tests/test_source_lifecycle_delete_021.py tests/test_source_retract_017.py -q
  ```

### Task 8: Prove real PostgreSQL ordering and wire the zero-skip lane

**Files:**
- Create: `harness/tests/test_source_lifecycle_postgres_021.py`
- Create: `harness/tests/test_source_lifecycle_migration_postgres_021.py`
- Modify: `harness/tests/test_ci_lanes_022.py`
- Modify: `.github/workflows/harness-ci.yml` only if collection/JUnit settings need adjustment
- Modify: `harness/scripts/check_junit.py` only if existing zero-skip aggregation cannot validate the new nodes

- [x] **Step 1: Write bounded two-session PostgreSQL tests**

  Use separate connections/Sessions and cover at least: first same identity create/reuse; first B/C race and inverse commit order; C then late B; first-event delete; active/deleted newer delete; delete-vs-import; delete-vs-notify; newer reactivate; CAS loser reread; injected failure with caller transaction still usable.

- [x] **Step 2: Write real PostgreSQL migration-contract tests**

  Run actual Alembic `0012 → 0006`, not `Base.metadata.create_all`. Assert PostgreSQL schema/constraints/triggers exist, SourceEvent update/delete is rejected, Alembic has the single head `0006`, and historical source-aware rows without explicitly resolved ordering produce zero SourceHead rows plus exactly one unique open BackfillIssue per Space/source. Assert non-empty SourceHead/SourceEvent/BackfillIssue blocks downgrade before DDL with schema/data/alembic_version unchanged, and empty lifecycle data permits `downgrade 0012 → upgrade head`. Include `alembic check` on the migrated schema.

- [x] **Step 3: Set hard timeouts and isolated cleanup**

  Set connection, PostgreSQL statement, lock, barrier, future/join timeouts. Use a per-run schema or equivalent isolated Space and sanitize run identity. Never put a password-bearing DSN into traceback/log output.

- [x] **Step 4: Pin exact test nodes in the PostgreSQL allowlist**

  Add every new `integration_postgres` node to `POSTGRES_NODES`; prove no node leaks into deterministic or live lanes. Keep JUnit guard `tests>0`, `skipped=0`.

- [x] **Step 5: Verify locally when the controlled PostgreSQL fixture exists**

  Run:

  ```bash
  cd harness && HARNESS_TEST_POSTGRES_URL=<sanitized-postgres-url> uv run pytest tests/test_source_lifecycle_postgres_021.py tests/test_source_lifecycle_migration_postgres_021.py -m integration_postgres -q --junitxml=reports/source-lifecycle-021.xml
  cd harness && uv run python scripts/check_junit.py reports/source-lifecycle-021.xml
  ```

  Expected: all selected tests pass; JUnit reports `tests>0`, `skipped=0`. If the fixture is absent, record `NOT RUN`; do not claim PostgreSQL verification.

### Task 9: Reconcile runbook, evidence, and the human handoff

**Files:**
- Create: `openspec/changes/021-source-lifecycle-ordering/validation-report.md`
- Modify: `openspec/changes/021-source-lifecycle-ordering/tasks.md`
- Modify: `openspec/changes/README.md`
- Modify: `docs/insurance-kb/03-knowledge-model.md`
- Modify: `docs/insurance-kb/22-parallel-execution-blueprint.md`
- Modify: `HANDOFF.md`

- [x] **Step 1: Map L1-L6 to exact tests and RED→GREEN evidence**

  Record the main baseline and fresh final totals, every focused RED reason, focused GREEN totals, migration head/base, and exact PostgreSQL node/JUnit evidence. Do not copy old SHA evidence onto new code.

- [x] **Step 2: Document operations and unresolved-source recovery**

  Explain SourceHead/Event decisions, BackfillIssue monitoring, explicit resolution prerequisites, retry behavior, safe rollback conditions, and why normal lifecycle fails closed while an issue is open.

- [x] **Step 3: Run final deterministic gates**

  From repository root:

  ```bash
  DO_NOT_TRACK=1 openspec validate 021-source-lifecycle-ordering --strict
  git diff --check
  ```

  From `harness/`:

  ```bash
  uv run ruff check .
  uv run mypy src tests
  uv run pytest -m "not live and not integration_postgres" -q
  uv run pytest tests/test_source_lifecycle_migration_021.py -q
  uv run alembic heads
  uv run alembic -x db_url=sqlite+pysqlite:////absolute/fresh-temp/021-final.db upgrade head
  uv run alembic -x db_url=sqlite+pysqlite:////absolute/fresh-temp/021-final.db downgrade 0012
  uv run alembic -x db_url=sqlite+pysqlite:////absolute/fresh-temp/021-final.db upgrade head
  uv run alembic -x db_url=sqlite+pysqlite:////absolute/fresh-temp/021-final.db check
  ```

  Replace `/absolute/fresh-temp/021-final.db` with a newly allocated empty absolute temp path and delete it only after evidence capture. Expected: all exit 0 and `alembic heads` remains the single `0006` head. Then rerun both controlled PostgreSQL lifecycle and migration-contract files plus the JUnit zero-skip guard on the exact final diff.

- [x] **Step 4: Complete independent spec and quality reviews**

  First reviewer checks only L1-L6 behavior coverage; after fixes, a fresh reviewer checks code quality, transaction safety, migration topology, and test validity. No Critical/Important may remain.

- [x] **Step 5: Stop at the repository's human Git boundary**

  Present `git status`, `git diff --stat`, gate evidence, remaining live status, and exact files for human review. The human owner performs commit/push/PR; AI workers do not.
