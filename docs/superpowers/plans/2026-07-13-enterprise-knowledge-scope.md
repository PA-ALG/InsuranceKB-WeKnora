# Enterprise KnowledgeScope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 016 so every Harness product, Claim, review and release operation is isolated by an explicitly bound WeKnora KnowledgeSpace.

**Architecture:** Add `KnowledgeSpace` as the shared aggregate root and a frozen `KnowledgeScope` loaded only from bound rows. Migrate existing data into an unbound legacy Space, then thread scope through product and knowledge services while replacing global uniqueness and the global release pointer with per-Space constraints.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, SQLite migration tests, PostgreSQL-compatible schema, pytest, Ruff, mypy.

**Spec:** `openspec/changes/016-enterprise-knowledge-scope/specs/scope.md`

**Repository rule:** AI workers do not commit or push. Each task ends with a human commit checkpoint recorded in `tasks.md`; the human owner performs Git operations.

---

## File map

**Create**

- `harness/src/insurance_harness/db/scope.py` — frozen scope model, loader, bind service and ScopeViolation.
- `harness/migrations/versions/0003_enterprise_knowledge_scope.py` — scoped schema upgrade/downgrade.
- `harness/src/insurance_harness/db/scope_cli.py` — list/show/bind admin CLI.
- `harness/src/insurance_harness/adapters/weknora/scope.py` — adapter-bound response scope validation.
- `harness/tests/test_scope_016.py` — value object, bind and fail-closed behavior.
- `harness/tests/test_scope_migration_016.py` — upgrade/backfill/constraints/downgrade preconditions.
- `harness/tests/test_scope_product_016.py` — product/register/routing dual-Space behavior.
- `harness/tests/test_scope_knowledge_016.py` — importer/merge/review dual-Space behavior.
- `harness/tests/test_scope_publisher_016.py` — per-Space snapshot/publish/rollback behavior.
- `harness/tests/test_client_scope_016.py` — bound-space and WeKnora response mismatch tests.
- `openspec/changes/016-enterprise-knowledge-scope/validation-report.md` — final evidence.

**Modify**

- `harness/src/insurance_harness/db/models.py` — KnowledgeSpace and scoped product aggregate roots/constraints.
- `harness/src/insurance_harness/product/register.py` — scoped registration.
- `harness/src/insurance_harness/product/routing.py` — scoped index and unassigned persistence.
- `harness/src/insurance_harness/product/cli.py` — require a bound Space for product operations.
- `harness/src/insurance_harness/knowledge/tables.py` — space_id on knowledge aggregate roots and scoped constraints.
- `harness/src/insurance_harness/knowledge/models.py` — `ProposedClaim.space_id`.
- `harness/src/insurance_harness/knowledge/importer.py` — scoped import/idempotency.
- `harness/src/insurance_harness/knowledge/merge.py` — scoped queries, ChangeSets, reviews and source retraction.
- `harness/src/insurance_harness/knowledge/review.py` — scoped review keys/lookups.
- `harness/src/insurance_harness/knowledge/pages.py` — scope-filtered page input.
- `harness/src/insurance_harness/knowledge/publisher.py` — scope-owned wiki KB and per-Space pointer.
- `harness/src/insurance_harness/adapters/weknora/models.py` — tenant identity consumed for scope validation.
- `harness/src/insurance_harness/adapters/weknora/client.py` — actual metadata/wait entrypoints require and validate scope.
- `harness/src/insurance_harness/compiler/models.py` — scoped run-manifest audit fields used by 017.
- `harness/tests/conftest.py`, `harness/tests/kbhelpers.py` and existing product/knowledge tests — explicit test Space fixtures.
- `harness/src/insurance_harness/db/README.md`, `harness/src/insurance_harness/product/README.md`, `harness/src/insurance_harness/knowledge/README.md` — new contracts.
- `openspec/changes/016-enterprise-knowledge-scope/tasks.md`, `docs/insurance-kb/13-blueprint-status.md`, `docs/insurance-kb/16-roadmap.md`, `HANDOFF.md` — status and decisions.

---

### Task 1: Bound scope value object and fail-closed loader

**Files:**

- Create: `harness/tests/test_scope_016.py`
- Create: `harness/src/insurance_harness/db/scope.py`
- Modify: `harness/src/insurance_harness/db/models.py`
- Modify: `harness/tests/conftest.py`

- [ ] **Step 1: Write failing S1.1/S1.2/S1.3 tests**

```python
def test_s1_2_only_bound_space_builds_scope(session: Session) -> None:
    row = KnowledgeSpace(name="legacy", binding_status="unbound")
    session.add(row)
    session.flush()
    with pytest.raises(UnboundKnowledgeSpace):
        load_scope(session, row.id)


def test_s1_2_bound_space_builds_immutable_scope(session: Session) -> None:
    row = bound_space(session, tenant_id="100", raw_kb_id="raw-a", wiki_kb_id="wiki-a")
    scope = load_scope(session, row.id)
    assert scope.model_dump() == {
        "space_id": row.id,
        "tenant_id": "100",
        "raw_kb_id": "raw-a",
        "wiki_kb_id": "wiki-a",
    }
    with pytest.raises(ValidationError):
        scope.tenant_id = "200"  # type: ignore[misc]
```

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_016.py -q`

Expected: collection fails because `KnowledgeSpace`, `load_scope` and scope exceptions do not exist.

- [ ] **Step 3: Implement the minimal model and loader**

```python
class KnowledgeScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    space_id: str
    tenant_id: str
    raw_kb_id: str
    wiki_kb_id: str


def load_scope(session: Session, space_id: str) -> KnowledgeScope:
    row = session.get(KnowledgeSpace, space_id)
    if row is None or row.binding_status != "bound":
        raise UnboundKnowledgeSpace(space_id)
    assert row.tenant_id and row.raw_kb_id and row.wiki_kb_id
    return KnowledgeScope(
        space_id=row.id,
        tenant_id=row.tenant_id,
        raw_kb_id=row.raw_kb_id,
        wiki_kb_id=row.wiki_kb_id,
    )
```

Add a `bound_scope` fixture that explicitly creates a bound row. Do not add a production default scope.

- [ ] **Step 4: Run GREEN**

Run: `cd harness && uv run pytest tests/test_scope_016.py -q`

Expected: Task 1 tests pass.

- [ ] **Step 5: Refactor and type-check**

Run: `cd harness && uv run ruff check src/insurance_harness/db tests/test_scope_016.py --no-cache && uv run mypy --no-incremental src/insurance_harness/db tests/test_scope_016.py`

Expected: both pass.

- [ ] **Step 6: Record the human checkpoint**

Update `openspec/changes/016-enterprise-knowledge-scope/tasks.md` with the S1 decision and ask the human owner to commit Task 1. Do not commit from the AI session.

---

### Task 2: 0003 migration, legacy backfill and safe downgrade

**Files:**

- Create: `harness/tests/test_scope_migration_016.py`
- Create: `harness/migrations/versions/0003_enterprise_knowledge_scope.py`
- Modify: `harness/src/insurance_harness/db/models.py`
- Modify: `harness/src/insurance_harness/knowledge/tables.py`

- [ ] **Step 1: Write failing migration tests for S2.1/S2.4/S3**

Cover these separate behaviors:

```python
def test_s3_1_upgrade_from_0001_backfills_product_rows(...): ...
def test_s3_1_upgrade_from_0002_backfills_product_and_knowledge_rows(...): ...
def test_s3_3_empty_install_does_not_create_default_space(...): ...
def test_s1_1_bound_space_requires_all_three_bindings(...): ...
def test_s2_4_same_product_code_is_unique_only_within_space(...): ...
def test_s2_2_product_document_rejects_cross_space_product(...): ...
def test_s2_2_claim_rejects_cross_space_product_version(...): ...
def test_s2_2_snapshot_claim_rejects_cross_space_claim(...): ...
def test_s3_4_downgrade_rejects_multiple_spaces_before_ddl(...): ...
def test_s3_4_downgrade_rejects_single_non_legacy_space(...): ...
def test_s3_4_downgrade_single_legacy_space_restores_0002(...): ...
```

Seed one database at revision `0001` with product data and a second at `0002` with product/Claim/release data; upgrade each to `head` and assert every applicable aggregate root received the fixed `legacy-default` ID.

Update `test_product_db.py` and `test_knowledge_db.py` in this task: include `knowledge_spaces` and scoped columns/unique constraints, remove assertions for the old global unique keys, and keep them migration-only (they do not call product/knowledge services).

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_migration_016.py -q`

Expected: FAIL because revision 0003 and scoped columns/constraints are absent.

- [ ] **Step 3: Implement the 0003 upgrade**

Use Alembic batch operations so SQLite tests and PostgreSQL production both work. The upgrade must:

1. create `knowledge_spaces` with an all-null/all-present CHECK;
2. add nullable `space_id` to aggregate roots;
3. create `legacy-default` only when old aggregate rows exist and backfill them;
4. make `space_id` non-null;
5. replace global unique constraints with scoped constraints/indexes;
6. replace the singleton `current_release.id='current'` with one row per `space_id`.

For cross-aggregate relations, add inherited shadow `space_id` only where needed for composite integrity: ProductVersion/ProductDocument → Product, Claim → ProductVersion, SnapshotClaim → Snapshot+Claim, CurrentRelease → Snapshot. Add parent `(space_id, id)` unique keys and composite foreign keys. Relations not expressible without duplicating every child aggregate remain guarded in services and are listed in the validation report.

Before downgrade, require exactly one Space whose ID is `legacy-default`, then check global-key collisions. Raise a clear `CommandError` before DDL for any violation. Do not drop data to make downgrade pass.

- [ ] **Step 4: Run GREEN**

Run: `cd harness && uv run pytest tests/test_scope_migration_016.py tests/test_product_db.py tests/test_knowledge_db.py -q`

Expected: all migration/schema tests pass. Service-level tests are deliberately deferred until Tasks 3～5 thread explicit scope.

- [ ] **Step 5: Inspect the resulting schema**

Run: `cd harness && uv run python -m alembic upgrade head`

Expected: upgrade completes against the configured development database. If no safe development URL is configured, run only the temporary SQLite test and record that limitation.

- [ ] **Step 6: Record the migration decision, but do not hand off a commit yet**

Record the downgrade/composite-FK decisions in `tasks.md`. Tasks 2～5 are one cross-cutting migration batch: existing service tests will not all be green until their APIs receive explicit scope, so do not ask the human owner to commit or merge this intermediate state.

---

### Task 3: Scope product registration and routing

**Files:**

- Create: `harness/tests/test_scope_product_016.py`
- Modify: `harness/src/insurance_harness/product/register.py`
- Modify: `harness/src/insurance_harness/product/routing.py`
- Modify: `harness/src/insurance_harness/product/cli.py`
- Modify: existing `test_product_*.py`

- [ ] **Step 1: Write RED dual-Space product tests**

```python
def test_s2_5_same_product_code_can_exist_in_two_spaces(...):
    register_products(session, dataset, scope=scope_a)
    register_products(session, dataset, scope=scope_b)
    assert scoped_products(session, scope_a)[0].product_code == "1847H"
    assert scoped_products(session, scope_b)[0].product_code == "1847H"


def test_s2_3_match_index_cannot_see_other_space(...):
    index_a = MatchIndex.from_session(session, scope_a)
    result = route_document(index_a, "b.pdf", pages_naming_only_product_b)
    assert result.candidates == ()
```

Also test `persist_unassigned(session, scope_a, ...)` writes `space_id=scope_a.space_id`.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_product_016.py -q`

Expected: function signatures do not accept scope or cross-Space data leaks into the index.

- [ ] **Step 3: Implement scoped product APIs**

Target interfaces:

```python
def register_products(
    session: Session, root: Path, *, scope: KnowledgeScope
) -> RegisterReport: ...

@classmethod
def from_session(cls, session: Session, scope: KnowledgeScope) -> "MatchIndex": ...

def persist_unassigned(
    session: Session, scope: KnowledgeScope, drafts: tuple[UnassignedDraft, ...]
) -> int: ...
```

Every select/update includes `InsuranceProduct.space_id == scope.space_id`; every aggregate row receives `space_id`. CLI requires `--space-id` and resolves a bound scope before reading the dataset.

- [ ] **Step 4: Run GREEN and legacy regression**

Run: `cd harness && uv run pytest tests/test_scope_product_016.py tests/test_product_register.py tests/test_product_routing.py tests/test_product_cli.py -q`

Expected: all pass after updating existing tests to explicit fixtures.

- [ ] **Step 5: Run targeted static checks and record the internal decision**

Run: `cd harness && uv run ruff check src/insurance_harness/product tests/test_scope_product_016.py --no-cache && uv run mypy --no-incremental src/insurance_harness/product tests/test_scope_product_016.py`

Expected: pass; update the tasks decision log. Do not request a commit yet; Tasks 2～5 remain one migration batch.

---

### Task 4: Scope Claim import, merge, review and retraction

**Files:**

- Create: `harness/tests/test_scope_knowledge_016.py`
- Modify: `harness/src/insurance_harness/knowledge/models.py`
- Modify: `harness/src/insurance_harness/knowledge/importer.py`
- Modify: `harness/src/insurance_harness/knowledge/merge.py`
- Modify: `harness/src/insurance_harness/knowledge/review.py`
- Modify: `harness/tests/kbhelpers.py` and existing knowledge tests.

- [ ] **Step 1: Write RED tests for S2.2/S2.3/S2.5**

Test independently:

- same ChangeSet idempotency tuple in A/B creates two ChangeSets;
- `MergeEngine(scope_a)` cannot find active Claim in B;
- same review content creates one review per Space;
- `resolve_review(scope_a, review_id_b)` and `retract_source(scope_a, knowledge_b)` raise not-found/ScopeViolation without leaking B;
- ProposedClaim with a different `space_id` is rejected before writes.
- ChangeItem/Conflict operations that reference Claims in another Space are rejected by the service even where nullable links prevent a practical composite FK.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_knowledge_016.py -q`

Expected: FAIL on missing scope APIs and global queries.

- [ ] **Step 3: Implement scoped knowledge APIs**

Target constructor and entry points:

```python
class MergeEngine:
    def __init__(self, session: Session, *, scope: KnowledgeScope, ...):
        self.scope = scope

def import_pred_records(..., *, scope: KnowledgeScope, ...) -> ImportReport: ...
def resolve_review(session: Session, scope: KnowledgeScope, review_id: str, ...): ...
def retract_source(session: Session, scope: KnowledgeScope, knowledge_id: str, ...): ...
```

Add `space_id` to ProposedClaim and compare it with the engine scope. Add scoped filters to every aggregate lookup and scoped uniqueness to `open_change_set`/review derivation. Child row operations first load their scoped aggregate parent.

- [ ] **Step 4: Run GREEN**

Run: `cd harness && uv run pytest tests/test_scope_knowledge_016.py tests/test_knowledge_importer.py tests/test_knowledge_merge.py tests/test_knowledge_review.py -q`

Expected: pass.

- [ ] **Step 5: Search for unscoped aggregate queries**

Run: `rg -n "select\((InsuranceProduct|UnassignedItem|Claim|ChangeSet|ReviewItem|ReleaseSnapshot|CurrentRelease)\)" harness/src/insurance_harness`

Expected: every production occurrence is either scope-filtered in the same query or immediately guarded by `require_scoped_row`; document any justified admin-only exception in `tasks.md`.

- [ ] **Step 6: Static checks and internal decision record**

Run: `cd harness && uv run ruff check src/insurance_harness/knowledge tests/test_scope_knowledge_016.py --no-cache && uv run mypy --no-incremental src/insurance_harness/knowledge tests/test_scope_knowledge_016.py`

Expected: pass; record decisions, but do not request a commit until Task 6 completes the integrated suite.

---

### Task 5: Per-Space release pointer and publisher ownership

**Files:**

- Create: `harness/tests/test_scope_publisher_016.py`
- Modify: `harness/src/insurance_harness/knowledge/pages.py`
- Modify: `harness/src/insurance_harness/knowledge/publisher.py`
- Modify: existing publisher/e2e tests.

- [ ] **Step 1: Write RED publisher tests**

```python
async def test_s2_5_current_release_is_independent_per_space(...): ...
async def test_s4_1_unbound_space_cannot_publish(...): ...
async def test_s2_3_scope_a_cannot_publish_product_version_b(...): ...
async def test_s4_1_publisher_uses_scope_wiki_kb_not_caller_kb(...): ...
```

The last test should prove there is no free-form `kb_id` argument left to mismatch.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_publisher_016.py -q`

Expected: existing publisher has a global pointer and caller-supplied kb_id.

- [ ] **Step 3: Implement the scoped publisher contract**

```python
async def publish_product_version(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    *,
    product_version_id: str,
    label: str,
    ...,
) -> PublishResult: ...

def current_snapshot_id(session: Session, scope: KnowledgeScope) -> str | None: ...
def default_snapshot_label(session: Session, scope: KnowledgeScope) -> str: ...
```

Publisher loads product/version through the scope, writes `ReleaseSnapshot.space_id`, uses `scope.wiki_kb_id`, and moves only `CurrentRelease(space_id=scope.space_id)`.

- [ ] **Step 4: Run GREEN and E2E regression**

Run: `cd harness && uv run pytest tests/test_scope_publisher_016.py tests/test_knowledge_publisher.py tests/test_knowledge_e2e.py -q`

Expected: pass.

- [ ] **Step 5: Static checks and internal decision record**

Run: `cd harness && uv run ruff check src/insurance_harness/knowledge/publisher.py tests/test_scope_publisher_016.py --no-cache && uv run mypy --no-incremental src/insurance_harness/knowledge/publisher.py tests/test_scope_publisher_016.py`

Expected: pass; record decisions, but do not request a commit until Task 6 completes the integrated suite.

---

### Task 6: Atomic administration, WeKnora boundary guard and audit context

**Files:**

- Modify: `harness/tests/test_scope_016.py`
- Create: `harness/tests/test_client_scope_016.py`
- Modify: `harness/src/insurance_harness/db/scope.py`
- Create: `harness/src/insurance_harness/db/scope_cli.py`
- Create: `harness/src/insurance_harness/adapters/weknora/scope.py`
- Modify: `harness/src/insurance_harness/adapters/weknora/models.py`
- Modify: `harness/src/insurance_harness/adapters/weknora/client.py`
- Modify: `harness/src/insurance_harness/compiler/models.py`
- Modify: `harness/src/insurance_harness/db/README.md`

- [ ] **Step 1: Write RED S3.2/S4.3 tests**

Cover successful atomic bind, duplicate raw/wiki rejection, partial input rejection, failed bind leaving all three columns NULL, and list/show displaying binding status.

Add S4 tests:

```python
def test_s4_1_adapter_rejects_unbound_space_before_request(...): ...
def test_s4_2_knowledge_tenant_mismatch_is_scope_violation(...): ...
def test_s4_2_knowledge_kb_mismatch_is_scope_violation(...): ...
def test_s4_3_scope_audit_fields_have_ids_but_no_api_key(...): ...
def test_s4_3_scoped_run_manifest_contains_space_tenant_and_raw_kb(...): ...
```

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_scope_016.py tests/test_client_scope_016.py -q`

Expected: bind/CLI and adapter scope guard functions missing; RunManifest has no scope audit fields.

- [ ] **Step 3: Implement bind transaction and CLI**

```python
def bind_space(
    session: Session,
    space_id: str,
    *,
    tenant_id: str,
    raw_kb_id: str,
    wiki_kb_id: str,
) -> KnowledgeScope:
    with session.begin_nested():
        # load unbound, check both unique mappings, set all fields, flush
        ...
    return load_scope(session, space_id)
```

CLI examples:

```bash
uv run python -m insurance_harness.db.scope_cli list --db-url "$HARNESS_DB_URL"
uv run python -m insurance_harness.db.scope_cli bind <space-id> \
  --tenant-id <tenant> --raw-kb-id <raw> --wiki-kb-id <wiki> --db-url "$HARNESS_DB_URL"
```

Implement the adapter response guard and wire it into the real metadata entrypoints:

```python
def require_knowledge_scope(
    scope: KnowledgeScope, knowledge: WeKnoraKnowledge
) -> None:
    if str(knowledge.tenant_id) != scope.tenant_id:
        raise ScopeViolation("knowledge outside requested space")
    if knowledge.knowledge_base_id != scope.raw_kb_id:
        raise ScopeViolation("knowledge outside requested raw KB")
```

Change the actual client contract rather than leaving an unused helper:

```python
async def get_knowledge(
    self, scope: KnowledgeScope, knowledge_id: str
) -> WeKnoraKnowledge:
    data = await self._request("GET", f"/api/v1/knowledge/{knowledge_id}")
    knowledge = WeKnoraKnowledge.model_validate(data)
    require_knowledge_scope(scope, knowledge)
    return knowledge

async def wait_for_parsed(
    self, scope: KnowledgeScope, knowledge_id: str
) -> WeKnoraKnowledge: ...
```

Update existing client/live tests to pass a bound scope and assert the request is not considered successful until response tenant/KB validation passes. Add `space_id`, `tenant_id`, and `raw_kb_id` fields to scoped RunManifest construction and a `scope_log_context()` helper that returns IDs only—never API keys or tokens. 017 will reuse these actual client entrypoints when it wires download/chunks.

- [ ] **Step 4: Run GREEN**

Run: `cd harness && uv run pytest tests/test_scope_016.py tests/test_client_scope_016.py -q`

Expected: pass.

- [ ] **Step 5: Human checkpoint**

Update DB README with commands and production fail-closed warning; record the adapter/audit contract. Run the complete non-live test suite now that Tasks 2～6 are integrated; only after it is green ask the human owner for a checkpoint commit.

---

### Task 7: Full verification and SDD closeout

**Files:**

- Create: `openspec/changes/016-enterprise-knowledge-scope/validation-report.md`
- Modify: `openspec/changes/016-enterprise-knowledge-scope/tasks.md`
- Modify: `docs/insurance-kb/13-blueprint-status.md`
- Modify: `docs/insurance-kb/16-roadmap.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Run migration-specific verification**

Run: `cd harness && uv run pytest tests/test_scope_migration_016.py tests/test_scope_product_016.py tests/test_scope_knowledge_016.py tests/test_scope_publisher_016.py -q`

Expected: all 016 tests pass.

- [ ] **Step 2: Run complete clean gates**

Run: `cd harness && uv run ruff check . --no-cache`

Expected: `All checks passed!`

Run: `cd harness && uv run mypy --no-incremental src tests`

Expected: `Success: no issues found ...`

Run: `cd harness && uv run pytest -m 'not live' -q`

Expected: all non-live tests pass, live tests only are deselected.

- [ ] **Step 3: Verify no core WeKnora intrusion and no ignored files**

Run: `git diff -- internal frontend docreader`

Expected: empty.

Run: `git status --short --ignored`

Expected: no intended source file is ignored; `.venv` may be ignored.

- [ ] **Step 4: Write validation and handoff**

Map each S1～S5 clause to test names and outputs. Record any live/PostgreSQL-only limitation honestly. Check all completed task boxes, update roadmap/HANDOFF, and leave Git actions to the human owner.
