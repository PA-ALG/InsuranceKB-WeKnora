# ReleaseSnapshot Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver OpenSpec 018’s immutable full-Space SnapshotFact read model, deterministic SnapshotReader, and recoverable pointer-last WeKnora publish/rollback saga.

**Architecture:** `SnapshotFact` is the only published fact projection consumed by Reader and Wiki rendering. A `ReleasePublisher` owns a SQLAlchemy `SessionFactory`, freezes a full-Space projection and `ReleaseOperation` plan before any HTTP, executes the plan through a narrow Wiki protocol, and atomically moves `CurrentRelease` last. Independent attempts, leases, and reconciliation jobs make partial HTTP work recoverable without pretending PostgreSQL and WeKnora form one transaction.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, Pydantic v2, asyncio, httpx/WeKnora REST adapter, pytest/pytest-asyncio/respx, Ruff, mypy strict, OpenSpec.

---

## Execution rules

- Canonical spec: `openspec/changes/018-release-snapshot-read-model/specs/release-read-model/spec.md`.
- Execute tasks serially in `/Users/houjing/Documents/LLM_wiki/.worktrees/insurancekb-018`; never dispatch two implementers against the shared worktree.
- Every behavior test name includes its clause, for example `test_r1_2_...`.
- For every behavior: write one RED test, run it and record the expected failure, then write the minimum GREEN implementation and rerun focused tests.
- Characterization tests for unchanged behavior are labeled as already-GREEN; do not break production code to manufacture RED.
- After each task: independent spec-compliance review, then independent code-quality review. Fix and re-review before the next task.
- `CLAUDE.md` overrides generic skill commit steps: subagents MUST NOT commit or push. Leave reviewed changes uncommitted for human acceptance.
- Do not modify WeKnora Go/Vue. Adapter-specific request/response handling remains under `harness/src/insurance_harness/adapters/weknora/`.

## File responsibility map

- `harness/src/insurance_harness/knowledge/tables.py`: ORM rows and cross-Space foreign-key/check/index declarations only.
- `harness/migrations/versions/0005_release_snapshot_read_model.py`: 0004→0005 schema, legacy backfill, SQLite/PostgreSQL triggers, guarded downgrade.
- `harness/src/insurance_harness/knowledge/snapshots.py`: immutable Pydantic fact/evidence views and full-Space projection builder.
- `harness/src/insurance_harness/knowledge/reader.py`: current pointer resolution, deterministic filtering/gaps, no mutable Claim reads.
- `harness/src/insurance_harness/knowledge/pages.py`: pure rendering of frozen fact views; existing Claim renderer remains only for pre-publish authoring tests.
- `harness/src/insurance_harness/knowledge/release_plan.py`: frozen plan/action models, Wiki protocol, ownership checks, per-Space process lock, action executor.
- `harness/src/insurance_harness/knowledge/publisher.py`: public `ReleasePublisher`, normal publish/retry state machine, service-owned sessions.
- `harness/src/insurance_harness/knowledge/reconcile.py`: rollback, expired-operation recovery, reconciliation job execution/requeue.
- `harness/src/insurance_harness/knowledge/fallback.py`: curated-first RAW provider protocol/policy only; no search implementation.
- `harness/tests/support/release_018.py`: source-aware fact fixtures and deterministic in-memory Wiki fake shared by 018 tests.

## Task 1: T1 schema, migration, freeze guards, and legacy policy

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/tables.py`
- Create: `harness/migrations/versions/0005_release_snapshot_read_model.py`
- Create: `harness/tests/test_release_snapshot_migration_018.py`
- Create: `harness/tests/test_snapshot_schema_018.py`
- Modify: `harness/tests/test_knowledge_db.py`
- Modify only incompatible fixture setup in: `harness/tests/test_scope_publisher_016.py`, `harness/tests/test_source_retract_017.py`, `harness/tests/test_source_revision_notify_017.py`

- [ ] **Step 1: RED — declare the ORM/migration contract (`R1.1`, `R1.2`, `R1.4`, `R2.1`).**

  Add tests asserting these shapes:

  ```python
  def test_r1_1_snapshot_fact_freezes_complete_projection_columns() -> None:
      assert required <= set(SnapshotFact.__table__.columns.keys())

  def test_r1_2_projection_frozen_marker_rejects_late_fact_insert(session: Session) -> None:
      snapshot.projection_frozen_at = utcnow()
      session.commit()
      session.add(SnapshotFact(...))
      with pytest.raises(IntegrityError):
          session.commit()

  def test_r1_2_snapshot_fact_rejects_update_or_delete_before_and_after_freeze(...) -> None: ...

  def test_r1_3_snapshot_fact_is_unique_by_space_snapshot_claim_revision(...) -> None: ...

  def test_r1_4_0004_to_0005_preserves_legacy_pointer_without_backfill(...) -> None:
      assert upgraded_snapshot.read_model_version == 0
      assert upgraded_snapshot.status == "published"
      assert snapshot_fact_count == 0
      assert pointer.snapshot_id == upgraded_snapshot.id

  def test_r2_1_current_release_trigger_rejects_new_legacy_or_failed_target(...) -> None: ...
  ```

  Required tables/columns:

  - `release_snapshots`: `status`, `read_model_version`, nullable `published_at`, `projection_frozen_at`;
  - `snapshot_facts`: frozen product identity, field display name/group, value/effective/confidence/schema, Evidence JSON;
  - `release_operations`: kind/status/base/target/parent/previous, plan JSON/digest/frozen marker, retry/lease/heartbeat/actor/reason;
  - `publish_attempts`: scoped operation FK, retry/action ordinal, operation/status/error/snapshot/slug/nullable created_new/timestamps;
  - `reconciliation_jobs`: unique scoped source operation, source digest, current reconcile operation, status/error.

- [ ] **Step 2: Run RED and confirm missing tables/columns/0005.**

  Run:

  ```bash
  cd harness
  uv run pytest tests/test_release_snapshot_migration_018.py tests/test_snapshot_schema_018.py -q
  ```

  Expected: collection/import or assertions fail because 0005 and new rows do not exist; no unrelated failure is accepted as RED.

- [ ] **Step 3: GREEN — add minimal ORM rows and 0005.**

  Use composite scoped FKs throughout. The lifecycle sets are:

  ```python
  SNAPSHOT_STATUSES = ("building", "publishing", "published", "failed")
  OPERATION_KINDS = ("publish", "rollback", "reconcile")
  OPERATION_STATUSES = ("building", "running", "succeeded", "failed")
  ATTEMPT_STATUSES = ("started", "succeeded", "failed", "collision")
  JOB_STATUSES = ("pending", "running", "succeeded", "failed")
  ```

  Add an explicit unique constraint on `(space_id, snapshot_id, claim_id, revision_no)`. In the building transaction, allow fact INSERTs only while `projection_frozen_at IS NULL`, but reject SnapshotFact UPDATE/DELETE immediately from insertion onward. After the marker is set, also reject late INSERT and rendered-page changes. Reject plan changes after `plan_frozen_at`. New pointer INSERT/UPDATE accepts only same-Space `published/read_model_version=1`; the migration-retained version-0 pointer is not rewritten.

  Migration rules:

  - `revision = "0005"`, `down_revision = "0004"`;
  - old snapshots become `published/read_model_version=0`, retain non-null `published_at` and pointer, and receive no facts;
  - downgrade succeeds only if no version-1 snapshot/fact/operation/attempt/job exists; otherwise raise before destructive DDL;
  - provide SQLite and PostgreSQL trigger DDL; add SQLAlchemy metadata DDL hooks so `Base.metadata.create_all()` tests enforce the same guards.

- [ ] **Step 4: GREEN — update only old fixtures that mutate published JSON.**

  Build malformed JSON before INSERT or explicitly model a legacy version-0 row; do not disable triggers in behavior tests. Keep the intent of 016/022 rollback preflight tests.

- [ ] **Step 5: Verify migration/schema GREEN.**

  Run focused tests, then:

  ```bash
  uv run pytest tests/test_knowledge_db.py tests/test_scope_publisher_016.py -q
  uv run ruff check src/insurance_harness/knowledge/tables.py migrations/versions/0005_release_snapshot_read_model.py tests/test_release_snapshot_migration_018.py tests/test_snapshot_schema_018.py
  uv run mypy src tests
  ```

  Expected: focused tests pass; mypy has zero issues.

## Task 2: T1 full-Space SnapshotFact projection builder

**Files:**
- Create: `harness/src/insurance_harness/knowledge/snapshots.py`
- Create: `harness/tests/support/release_018.py`
- Create: `harness/tests/test_snapshot_facts_018.py`
- Modify: `harness/src/insurance_harness/knowledge/__init__.py`

- [ ] **Step 1: RED — freeze a complete, deterministic candidate set (`R1.1`, `R1.3`, `R3.2`).**

  Tests must prove:

  - products A and B are projected when B is only the trigger argument;
  - candidate set is exactly scoped `published + product_version_id + value_state != unknown`;
  - missing current revision, legacy-null lineage, placeholder audit, or stale Evidence fails the whole build before returning any projection;
  - product rename and Evidence mutation after projection do not alter returned immutable records;
  - zero candidates returns a valid empty projection.

  Target immutable API:

  ```python
  class SnapshotFactView(BaseModel):
      model_config = ConfigDict(frozen=True)
      snapshot_id: str
      claim_id: str
      revision_no: int
      product_id: str
      product_version_id: str
      product_code: str
      product_name: str
      version_label: str
      predicate: str
      field_name: str
      field_group: str
      value_state: str
      value: JSONValue | None
      effective_from: date | None
      effective_to: date | None
      confidence: float
      schema_version: str
      evidence: tuple[FrozenEvidence, ...]

  def build_snapshot_facts(
      session: Session,
      scope: KnowledgeScope,
      *,
      snapshot_id: str,
      registry: SchemaRegistry | None = None,
      field_names: Mapping[str, str] | None = None,
      doc_titles: Mapping[str, str] | None = None,
  ) -> tuple[SnapshotFactView, ...]: ...
  ```

- [ ] **Step 2: Run RED.**

  `uv run pytest tests/test_snapshot_facts_018.py -q`

  Expected: import/API missing failure.

- [ ] **Step 3: GREEN — query once by Space, validate all candidates, then materialize.**

  Do not call `build_page_claims()` and do not silently skip a candidate after selection. Sort facts and Evidence deterministically before returning. Freeze all `ClaimEvidence` columns plus `doc_title`; do not retain ORM objects in Pydantic output.

- [ ] **Step 4: Verify GREEN and unchanged Claim page tests.**

  `uv run pytest tests/test_snapshot_facts_018.py tests/test_knowledge_pages.py -q`

## Task 3: T2 deterministic SnapshotReader and typed gaps

**Files:**
- Create: `harness/src/insurance_harness/knowledge/reader.py`
- Create: `harness/tests/test_snapshot_reader_018.py`
- Modify: `harness/src/insurance_harness/knowledge/__init__.py`

- [ ] **Step 1: RED — current, five gaps, exact precedence, bounds, overlap, and scope (`R2.1`, `R2.2`, `R2.4`).**

  Target result union:

  ```python
  CoverageGapCode = Literal[
      "no_release", "legacy_release", "product_not_found",
      "predicate_not_found", "effective_date_miss",
  ]

  class SnapshotFactsResult(BaseModel):
      snapshot_id: str
      facts: tuple[SnapshotFactView, ...]

  class CoverageGap(BaseModel):
      code: CoverageGapCode
      snapshot_id: str | None

  class SnapshotReader:
      def current(self, scope: KnowledgeScope, *, product_id: str | None = None,
                  product_version_id: str | None = None,
                  predicate: str | None = None,
                  effective_on: date | None = None) -> SnapshotFactsResult | CoverageGap: ...
  ```

  Assert NULL date endpoints are open-ended and sorting is exactly the R2.2 tuple. Assert first-empty filter precedence. Unattested/wrong-Engine inputs raise the same non-leaking `ScopeViolation("scope mismatch")`. For explicit product/product-version IDs, a scoped ownership lookup that selects IDs only SHALL treat nonexistent or foreign-Space IDs as ScopeViolation; a valid same-Space ID absent from current facts returns product_not_found. Never inspect another Space's facts or expose whether the rejected ID exists.

- [ ] **Step 2: Run RED.**

  `uv run pytest tests/test_snapshot_reader_018.py -q`

- [ ] **Step 3: GREEN — implement pointer-only reads.**

  `SnapshotReader` receives a `SessionFactory`, creates a read-only Session per call, validates scope against that Session, loads pointer/snapshot/facts, closes Session, and returns detached immutable views. It never queries Claim or ClaimEvidence. It may query only `InsuranceProduct.id/ProductVersion.id` with the requested `space_id` for ownership validation; it must not consume mutable product names or other content.

- [ ] **Step 4: Verify GREEN and run a SQL-spy assertion forbidding mutable tables.**

  `uv run pytest tests/test_snapshot_reader_018.py -q`

## Task 4: T3 frozen-fact Wiki renderer

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/pages.py`
- Create: `harness/tests/test_snapshot_pages_018.py`
- Modify: `harness/tests/test_knowledge_pages.py` only for compatible metadata expectations

- [ ] **Step 1: RED — render product A/B pages only from frozen facts (`R2.3`, `R4.4`, `R6.1`).**

  Target pure function:

  ```python
  def render_snapshot_pages(
      facts: Sequence[SnapshotFactView], *, space_id: str, snapshot_id: str,
      compiled_at: datetime, harness_version: str = "insurance-harness/0.1.0",
  ) -> tuple[RenderedPage, ...]: ...
  ```

  Assert one page per product version, deterministic slug/content/refs, and metadata contains `managed_by`, `space_id`, `snapshot_id`, entity IDs, claim IDs, compiled_at, harness/schema versions. Mutate/rename all source ORM rows after building views and assert byte-equivalent rerender with the same explicit `compiled_at`.

- [ ] **Step 2: Run RED.**

  `uv run pytest tests/test_snapshot_pages_018.py -q`

- [ ] **Step 3: GREEN — reuse formatting helpers, not mutable DB loaders.**

  Keep existing `build_page_claims()` for authoring/legacy characterization, but publisher code added later must call only `render_snapshot_pages()`.

- [ ] **Step 4: Verify GREEN.**

  `uv run pytest tests/test_snapshot_pages_018.py tests/test_knowledge_pages.py -q`

## Task 5: T4 frozen plan executor, ownership, attempts, and Space lock

**Files:**
- Create: `harness/src/insurance_harness/knowledge/release_plan.py`
- Create: `harness/tests/test_release_plan_018.py`
- Modify adapter only if required: `harness/src/insurance_harness/adapters/weknora/client.py`
- Modify adapter tests only if required: `harness/tests/test_client_wiki.py`

- [ ] **Step 1: RED — plan serialization/digest and ownership-safe actions (`R3.3`–`R3.5`, `R4.4`, `R4.5`).**

  Define frozen `PublishAction(kind: upsert|delete, slug, page?)` and `PublishPlan(base_snapshot_id, target_snapshot_id, actions, compensation_actions)` with canonical JSON SHA-256. Define a structural async `WikiPageClient` Protocol matching get/create/update/delete; do not depend on concrete `WeKnoraClient` in domain tests.

  Tests cover create/update/write-after-read, DELETE 404, response-loss `created_new=None`, third-party collision, managed wrong-Space collision, exact legacy dual-match adoption, same-Space serialization, and cross-Space concurrency.

- [ ] **Step 2: Run RED.**

  `uv run pytest tests/test_release_plan_018.py -q`

- [ ] **Step 3: GREEN — implement executor callbacks, not DB orchestration.**

  The executor accepts callbacks `attempt_started(action)`, `attempt_finished(...)`, so Task 6 owns transactions. It must persist nothing itself and must never accept a free-form kb_id; use `scope.wiki_kb_id` for every protocol call.

- [ ] **Step 4: Verify GREEN and adapter regressions.**

  `uv run pytest tests/test_release_plan_018.py tests/test_client_wiki.py tests/test_slug_lock.py -q`

## Task 6: T4 ReleasePublisher build/run/retry/lease recovery

**Files:**
- Rewrite: `harness/src/insurance_harness/knowledge/publisher.py`
- Create: `harness/tests/test_publish_state_machine_018.py`
- Modify: `harness/tests/test_knowledge_publisher.py`
- Modify: `harness/tests/test_scope_publisher_016.py`
- Modify: `harness/tests/test_knowledge_e2e.py`
- Modify exports: `harness/src/insurance_harness/knowledge/__init__.py`

- [ ] **Step 1: RED — prove service-owned Session boundary (`R3.6`).**

  Assert the public constructor/API:

  ```python
  publisher = ReleasePublisher(session_factory, wiki_client, lease_duration=timedelta(...))
  result = await publisher.publish_product_version(scope, product_version_id=..., label=...)
  ```

  No public saga method accepts `Session` or `kb_id`. PostgreSQL-marked coverage uses a caller Session with flushed/uncommitted data, runs a successful release through the factory, rolls back caller, and proves only release rows committed. Deterministic signature and independent-session tests run on SQLite without claiming unsupported concurrent writer behavior.

- [ ] **Step 2: RED — building→running→published, pointer-last, failed retry, and attempts (`R3.1`–`R3.5`).**

  Cover first release, A/B full-Space second release, zero-fact deletion release, multi-page second failure, collision, response loss, base-current change rejection, final DB commit failure, and same-plan retry. Replace the old 016 expectation “no snapshot after Wiki failure” with 018’s durable failed snapshot/operation/job contract; preserve RH1 zero-I/O on DB preflight failure.

- [ ] **Step 3: Run RED.**

  `uv run pytest tests/test_publish_state_machine_018.py tests/test_knowledge_publisher.py tests/test_scope_publisher_016.py -q`

- [ ] **Step 4: GREEN — implement phase-owned sessions and exact state transitions.**

  Phases:

  1. session A validates scope/label/trigger product, builds all facts/pages/actions, inserts snapshot + operation with null markers, flushes, sets projection/plan markers and initial lease, commits;
  2. session B atomically verifies base pointer, sets snapshot publishing + operation running + renewed lease, commits;
  3. executor action callbacks each use a fresh session to insert/update attempts and heartbeat;
  4. final session atomically rechecks base, marks published/succeeded, sets published_at and pointer, commits;
  5. exception path uses a fresh session to mark normal snapshot/operation failed and create the unique job when external I/O may have begun.

  `retry_operation()` reuses the operation/plan/snapshot and increments retry number only if base current still matches.

- [ ] **Step 5: GREEN — implement expired building/running recovery used by publisher failures.**

  Expired building with no started attempt → failed, no job; expired running/started → failed + unique job. Use injected `now` in tests; production defaults to `utcnow()`.

- [ ] **Step 6: Verify focused and publisher regression GREEN.**

  ```bash
  uv run pytest tests/test_publish_state_machine_018.py tests/test_knowledge_publisher.py tests/test_scope_publisher_016.py tests/test_knowledge_e2e.py -q
  uv run ruff check src/insurance_harness/knowledge tests/test_publish_state_machine_018.py
  uv run mypy src tests
  ```

## Task 7: T5 rollback and reconciliation

**Files:**
- Create: `harness/src/insurance_harness/knowledge/reconcile.py`
- Create: `harness/tests/test_reconcile_018.py`
- Modify: `harness/src/insurance_harness/knowledge/publisher.py`
- Modify: `harness/tests/test_scope_publisher_016.py`
- Modify: `harness/tests/test_knowledge_e2e.py`

- [ ] **Step 1: RED — pointer-last version-1 rollback (`R4.1`, `R4.2`).**

  Reject cross-Space, non-published, and legacy version-0 targets before I/O. V2→V1 creates a rollback operation without changing V1/V2 status, replays V1, and moves pointer only on success. Second-page failure persists failed operation/attempt/job and leaves rollback ChangeSet non-successful. Add `test_r3_3_failed_rollback_retry_reuses_operation_plan_and_increments_retry_no`: with base current unchanged, retry the failed rollback and assert identical rollback operation ID/plan digest, `retry_no + 1`, no new business snapshot, and target snapshot remains published.

- [ ] **Step 2: RED — exact, idempotent reconciliation and requeue (`R4.3`–`R4.5`).**

  Cover current replay, no-current cleanup, new slug, historical non-current managed slug, DELETE already 404, third-party takeover collision, legacy first-release adoption followed by failure, same-current child retry, and changed-current successor child retaining prior attempts.

- [ ] **Step 3: RED — add the three combined deterministic acceptance stories (`R6.1`–`R6.3`).**

  In `test_knowledge_e2e.py`, add explicit nodes:

  ```python
  async def test_r6_1_v1_v2_rollback_v1_keeps_reader_evidence_products_and_wiki_aligned(): ...
  async def test_r6_2_failed_publish_reconciles_then_retries_same_source_operation_and_plan(): ...
  async def test_r6_3_two_spaces_same_label_slug_rollback_only_one_is_fully_isolated(): ...
  ```

  R6.1 jointly asserts Reader values, frozen Evidence, products A/B, and every managed Wiki page `metadata.snapshot_id`. R6.2 executes second-page failure → reconciliation success → retry of the original failed source operation/plan and asserts pointer timing plus operation/attempt/job lineage. R6.3 gives A/B identical labels/slugs but different scoped Wiki KBs, rolls back only A, and asserts B snapshots, pointer, attempts, jobs, pages, and recorded Wiki calls are unchanged.

- [ ] **Step 4: Run RED.**

  `uv run pytest tests/test_reconcile_018.py tests/test_knowledge_e2e.py -q`

- [ ] **Step 5: GREEN — implement rollback/reconcile with the Task 5 executor.**

  Reconciliation locks Space, reloads current at execution, creates/reuses the child operation as specified, and derives cleanup only from source-plan touched slugs minus execution-current slugs. It never lists or scans an entire Wiki KB and never deletes a non-Harness page.

- [ ] **Step 6: Verify GREEN and RH1/R6 regression intent.**

  `uv run pytest tests/test_reconcile_018.py tests/test_scope_publisher_016.py tests/test_knowledge_e2e.py -q`

## Task 8: T6 curated-first RAW fallback protocol

**Files:**
- Create: `harness/src/insurance_harness/knowledge/fallback.py`
- Create: `harness/tests/test_snapshot_fallback_018.py`
- Modify exports: `harness/src/insurance_harness/knowledge/__init__.py`

- [ ] **Step 1: RED — provider called only for typed gaps (`R5.1`–`R5.3`).**

  Define:

  ```python
  class RawFallbackProvider(Protocol):
      async def search(self, scope: KnowledgeScope, gap: CoverageGap, query: str) -> Sequence[RawHit]: ...

  class RawHit(BaseModel):
      space_id: str
      raw_kb_id: str
      text: str
      source_ref: str | None = None

  class FallbackAnswer(BaseModel):
      review_status: Literal["unreviewed_raw"]
      hits: tuple[RawHit, ...]
  ```

  Tests prove curated facts cause zero provider calls; every fixed gap may explicitly invoke provider; any mismatched hit fails the whole response with `ScopeViolation`; no SnapshotFact write occurs.

- [ ] **Step 2: Run RED.**

  `uv run pytest tests/test_snapshot_fallback_018.py -q`

- [ ] **Step 3: GREEN — implement policy only.**

  Do not add REST calls, vector search, answer synthesis, merge logic, or writeback.

- [ ] **Step 4: Verify GREEN.**

  `uv run pytest tests/test_snapshot_fallback_018.py tests/test_snapshot_reader_018.py -q`

## Task 9: T7 PostgreSQL integration and real WeKnora live gate

**Files:**
- Create: `harness/tests/test_release_snapshot_postgres_018.py`
- Create: `harness/tests/test_release_snapshot_live_018.py`
- Modify: `harness/tests/support/live.py`
- Modify only if collection needs it: `.github/workflows/harness-ci.yml`, `.github/workflows/harness-live.yml`
- Modify: `harness/tests/test_ci_lanes_022.py`
- Modify: `docs/insurance-kb/14-deployment-runbook.md`

- [ ] **Step 1: RED/characterization — add mutually exclusive lane contracts (`R3.6`, `R6.4`).**

  PostgreSQL test proves trigger parity and service-owned session isolation. Live test uses existing bound Space/knowledge prerequisites and performs real V1→V2→rollback V1, verifying page metadata after each step and cleaning only pages it created. The live node is exactly one `@pytest.mark.live` E2E; it must not be selected by deterministic or integration lanes. Update `test_ci_lanes_022.py` from a singleton PostgreSQL constant to the exact set containing the existing 017 node plus the new 018 node, and add the new live node to `WEKNORA_NODES`; retain disjoint/exhaustive/exact assertions.

- [ ] **Step 2: Run deterministic collection/marker tests.**

  ```bash
  uv run pytest --collect-only -q -m "not live and not integration_postgres"
  uv run pytest --collect-only -q -m "integration_postgres"
  uv run pytest --collect-only -q -m "live"
  ```

  Expected: disjoint collections whose union is the full suite; live execution without all prerequisites is `NOT RUN`, never PASS.

- [ ] **Step 3: Run PostgreSQL integration when URL is available.**

  `uv run pytest tests/test_release_snapshot_postgres_018.py -m integration_postgres -q`

  Expected locally without `HARNESS_TEST_POSTGRES_URL`: non-zero fail-closed with `HARNESS_TEST_POSTGRES_URL is required`, matching RH6/P0.2. With the URL set: the selected nodes run with zero skip. Only a zero-skip PostgreSQL 16 CI run may be recorded as integration verified.

- [ ] **Step 4: Run live only when protected environment is complete.**

  `uv run pytest tests/test_release_snapshot_live_018.py -m live -q`

  Record exact command, commit/worktree state, UTC time, tests/skips, and cleanup outcome. Missing environment remains `NOT RUN`.

## Task 10: T7 documentation, task closure, and final verification

**Files:**
- Modify: `openspec/changes/018-release-snapshot-read-model/tasks.md`
- Create: `openspec/changes/018-release-snapshot-read-model/validation-report.md`
- Modify: `HANDOFF.md`
- Modify: `docs/insurance-kb/13-blueprint-status.md`
- Modify: `docs/insurance-kb/16-roadmap.md`
- Modify: `docs/insurance-kb/20-enterprise-runtime-foundation.md`
- Modify if needed: `docs/insurance-kb/README.md`, `harness/src/insurance_harness/knowledge/README.md`

- [ ] **Step 1: Run all focused 018 tests and record counts.**

  ```bash
  uv run pytest \
    tests/test_release_snapshot_migration_018.py \
    tests/test_snapshot_schema_018.py \
    tests/test_snapshot_facts_018.py \
    tests/test_snapshot_reader_018.py \
    tests/test_snapshot_pages_018.py \
    tests/test_release_plan_018.py \
    tests/test_publish_state_machine_018.py \
    tests/test_reconcile_018.py \
    tests/test_snapshot_fallback_018.py \
    tests/test_knowledge_e2e.py -q
  ```

- [ ] **Step 2: Run canonical completion gates from fresh output.**

  ```bash
  cd ..
  openspec validate 018-release-snapshot-read-model --strict
  cd harness
  uv run ruff check .
  uv run mypy src tests
  uv run pytest -m "not live and not integration_postgres" -q
  ```

  Expected: all exit 0. Telemetry DNS warnings do not change OpenSpec exit status.

- [ ] **Step 3: Update tasks/report/handoff truthfully.**

  Include every RED→GREEN command and result, independent task reviews, final counts, migration ownership (`0005`), the 018→021 dependency, and separate `software complete / integration verified / live verified` states. Never convert skip/NOT RUN into verified.

- [ ] **Step 4: Run independent whole-change spec review, then whole-change quality review.**

  Fix every Critical/Important/Minor issue, rerun the affected RED/GREEN test, and re-review. Only after both approve, rerun Step 2 without relying on stale output.

- [ ] **Step 5: Stop before git mutation.**

  Present `git status`, diff summary, validation evidence, review results, and remaining external gates to the user. Do not commit, push, or open/update a PR until explicitly instructed.
