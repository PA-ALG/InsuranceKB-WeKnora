# MVP Known-Schema Structured Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the `010 known-schema thin` profile so an approved structured product-fact/FAQ JSON source bypasses PDF parsing but still becomes immutable structured Evidence, governed Claims/ChangeSets/Review, and a frozen readable snapshot without fake page/chunk lineage.

**Architecture:** Extend the existing 010 registry/mapping foundation with one strict known-schema adapter and the complete forward-compatible `0007` schema fixed by I4/I7/I9. The behavior remains thin, but each record is first bound to a reconstructable common `SourceRevision`, then a discriminated structured Evidence branch flows through model→merge→snapshot v2→reader. Raw FAQ question/answer stays in `qa_staging`; only explicit mapped `fact_assertions` may enter the Claim governance path.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/Alembic, existing 007/018/021/029 knowledge services, pytest, PostgreSQL migration lane.

---

## Authority, order, and honest status

- Specs: `openspec/changes/010-structured-import/specs/structured-import/spec.md` plus `openspec/changes/010-structured-import/mvp-profile.md`.
- This plan completes the full T5 `0007` schema contract and “010 known-schema thin” runtime only. Generalized T6–T12/full I1–I9 behavior remains PARTIAL for M2; dormant schema is not a completion claim.
- Dependency/order: merge after 029 because both touch `knowledge/` and migrations. Rebase on actual main and acquire the sole migration lane before authoring preallocated `0007`.
- Risk: **A** for schema/migration/frozen provenance; **B** for mapping/merge behavior.
- Use @superpowers:test-driven-development and @superpowers:verification-before-completion.
- Do not implement unknown mapping, CSV/API, generalized mapping-change/M:N reprocessing services, FAQ search/pages, QA objects, or modify 013/032. The M:N table, I9 constraints, and qa_staging schema still ship now because an applied `0007` may not be rewritten later.
- AI session does not commit/push.

## PR and file split

### 010-thin-a: structured Evidence and snapshot v2

**Create**

- `harness/src/insurance_harness/knowledge/structured_evidence.py` — canonical record hash and structured Evidence validation helpers.
- `harness/migrations/versions/0007_structured_import.py`
- `harness/tests/test_structured_import_migration_010.py`
- `harness/tests/test_structured_import_migration_postgres_010.py`
- `harness/tests/test_structured_evidence_snapshot_010_mvp.py`
- `harness/tests/test_structured_source_lifecycle_010_mvp.py`

**Modify**

- `harness/src/insurance_harness/knowledge/tables.py` — full `StructuredSourceRecord` revision binding, append-only batch association, qa_staging, Evidence/ChangeSet I4/I7/I9 columns/checks/indexes, snapshot version support.
- `harness/src/insurance_harness/knowledge/models.py` — strict Evidence discriminant.
- `harness/src/insurance_harness/knowledge/merge.py` — persist/dedupe structured Evidence and enforce Space match.
- `harness/src/insurance_harness/knowledge/pages.py` — verify structured record/hash and render non-document source reference.
- `harness/src/insurance_harness/knowledge/snapshots.py` — strict v1/v2 frozen Evidence union.
- `harness/src/insurance_harness/knowledge/reader.py` — strict mixed v1/v2 read; no source-table lookup.
- `harness/src/insurance_harness/knowledge/release_guard_ddl_010.py` — new v2-aware guards; do not rewrite the historical 018 guard module/migration.
- `harness/migrations/env.py`, `harness/tests/conftest.py` as required.

### 010-thin-b: known-schema intake service

**Create**

- `harness/src/insurance_harness/structured_import/known_schema.py` — strict record/FAQ/assertion DTOs and mapping adapter.
- `harness/src/insurance_harness/structured_import/source_identity.py` — common `SourceRevision` construction/reconstruction plus a neutral structured lifecycle identity; no fake raw_kb/document identity.
- `harness/tests/test_known_schema_import_010_mvp.py`
- `harness/tests/test_known_faq_import_010_mvp.py`
- `openspec/changes/010-structured-import/validation-report-mvp.md`

**Modify**

- `harness/src/insurance_harness/structured_import/service.py` — replace the hard stop only for explicit known-schema API.
- `harness/src/insurance_harness/structured_import/__init__.py` — export the named thin API.
- `harness/tests/test_structured_import_010.py` — retain unknown/unregistered fail-closed regression.

### Task 1: Freeze the known-schema and FAQ assertion boundary

- [ ] **Step 1: Write DTO RED tests**

Require a strict provenance envelope with `source_system`, `external_record_id`, `source_revision`, `ordering: SourceOrdering`, `record_locator`, product/version identity, and a separate raw business `payload` containing explicit `fact_assertions`. Reject extra keys, missing product identity, unknown field IDs, raw question/answer without assertions, caller-supplied authority that disagrees with registry, `imported_at` used as ordering, or mapping version used as source-profile identity.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_known_schema_import_010_mvp.py tests/test_known_faq_import_010_mvp.py -k "schema or assertion or reject"
```

Expected: FAIL because `known_schema.py` is missing.

- [ ] **Step 3: Implement strict input models only**

Use a shape equivalent to:

```python
class FactAssertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    field_id: str
    value_state: Literal["present", "absent_explicitly", "unknown"]
    value: JsonValue | None
    evidence_text: str

class KnownFaqRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_system: str
    external_record_id: str
    source_revision: str
    ordering: SourceOrdering
    record_locator: str
    product_version_id: str
    payload: KnownFaqPayload
```

`KnownFaqPayload` owns `question/answer/fact_assertions`; only this payload is canonicalized into `record_hash`. The adapter computes `source_profile_fingerprint` from the registered record schema, known-schema-adapter version, and canonicalizer version, then reconstructs the shared `SourceRevision(file_hash=record_hash, ordering=ordering, parser_fingerprint=source_profile_fingerprint, value=source_revision)`. A mismatch is rejected before persistence. Question/answer text alone never becomes a Claim; it is retained in raw structured payload and qa_staging.

- [ ] **Step 4: Run DTO GREEN**

Expected: selected tests PASS; no database writes yet.

### Task 2: Structured-source schema and migration

- [ ] **Step 1: Acquire lane and inspect actual head**

```bash
cd harness
uv run alembic heads
```

Expected: one head including 029. If not, stop and ask G for ordering.

- [ ] **Step 2: Write migration RED tests**

Inspect and test the complete fixed `0007` DDL: `StructuredSourceRecord` identity plus source-profile/ordering exact-one CHECK; immutable `structured_import_batch_records`; qa_staging; Evidence source kind (`legacy/weknora/structured`) with nullable-add→exact backfill→NOT NULL/CHECK; structured-vs-WeKnora exclusivity; ChangeSet `batch_fingerprint/mapping_version/mapping_manifest` all-or-none CHECK; exact structured/non-structured partial unique indexes; read-model `(0,1,2)`; new 010 guard registration; SQLite and PostgreSQL UPDATE/DELETE triggers.

Downgrade tests first snapshot schema/data/`alembic_version`. Empty downgrade and roll-forward must restore equivalent schema. Before its first DDL, downgrade must refuse atomically if any structured record, batch link, structured Evidence/lineage column, structured-import ChangeSet/mapping column, qa_staging row, or v2 snapshot exists; the three snapshots remain byte/semantically unchanged after refusal.

- [ ] **Step 3: Run RED**

```bash
cd harness
uv run pytest -q tests/test_structured_import_migration_010.py
```

- [ ] **Step 4: Implement the complete forward-compatible `0007` schema**

`StructuredSourceRecord` stores canonical raw payload/hash, stable locator, source-profile fingerprint and ordering so the common SourceRevision can be reconstructed without mutable config; it has no batch foreign key. Create the append-only M:N association now, plus qa_staging and every I9 ChangeSet constraint/index. `ClaimEvidence` structured branch requires record ID + mapping version and forbids raw_kb/chunk/page lineage. Set `down_revision` to the actual sole head after 029 (numeric order is not topology). Never modify an applied partial `0007` later.

- [ ] **Step 5: Run SQLite and PG GREEN**

```bash
cd harness
uv run pytest -q tests/test_structured_import_migration_010.py
uv run pytest -q -m integration_postgres tests/test_structured_import_migration_postgres_010.py
```

Expected: selected PG tests execute; skipped=0.

### Task 3: Bind every structured record to the common SourceRevision lifecycle

- [ ] **Step 1: Write source identity/lifecycle RED tests**

Cover exact reconstruction from persisted record; tampered payload/hash/ordering/profile/revision rejection; mapping-version changes leaving SourceRevision unchanged; distinct lifecycle partitions for two external records in one source system and for the same external ID across systems; same revision replay; same external revision/different hash collision before any event/write; older ordering produces no business mutation; cross-Space isolation. Add a real PostgreSQL two-session replay proving one source record and one business outcome.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_structured_source_lifecycle_010_mvp.py
uv run pytest -q -m integration_postgres tests/test_structured_source_lifecycle_010_mvp.py
```

- [ ] **Step 3: Implement neutral structured identity and materialization service**

`StructuredSourceLifecycleIdentity` partitions by `(space_id, source_system, external_record_id)` and carries the existing common `SourceRevision`; it does not fake `raw_kb_id` or reuse Evidence's display-only `knowledge_id=source_system` as a head key. `materialize_structured_revision(...)` validates registry/profile/order, canonicalizes payload, reconstructs the common revision, preflights collisions, and inserts/reuses one append-only `StructuredSourceRecord`, returning its `structured_record_id` binding. Align accepted/idempotent/stale decisions and per-source serialization with 021 semantics without creating a second Claim/Review lifecycle.

- [ ] **Step 4: Run GREEN**

Expected: deterministic and selected PostgreSQL tests PASS; selected PG tests skipped=0.

### Task 4: Domain model and merge persistence

- [ ] **Step 1: Write model/merge RED tests**

Test structured Evidence construction, mixed document/structured fields rejected, Space mismatch before any write, source hash revalidation, duplicate record/revision idempotency, Evidence dedupe includes record+mapping identity, and existing WeKnora/legacy acceptance/rejection behavior remains unchanged.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_known_schema_import_010_mvp.py tests/test_knowledge_merge.py -k "structured or evidence_kind"
```

- [ ] **Step 3: Implement discriminated `ProposedEvidence` and merge branch**

Keep existing call sites valid. Structured Evidence fields are explicit and document lineage fields are `None`; `knowledge_id=source_system` is display grouping only, not evidence identity.

- [ ] **Step 4: Run GREEN plus existing merge suite**

```bash
cd harness
uv run pytest -q tests/test_known_schema_import_010_mvp.py tests/test_knowledge_merge.py tests/test_source_lifecycle_021.py
```

Expected: PASS.

### Task 5: Strict snapshot v2 and frozen provenance

- [ ] **Step 1: Write snapshot RED tests**

Cover v1 historical read unchanged; v2 document Evidence; v2 structured Evidence; no fake page/chunk; missing/tampered structured record blocks freeze; once frozen, make `structured_source_records` inaccessible and prove Reader still returns identical provenance; v2→v1 pointer rollback works.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_structured_evidence_snapshot_010_mvp.py
```

- [ ] **Step 3: Implement strict frozen union**

Use separate `FrozenWeknoraEvidence` and `FrozenStructuredEvidence` with a `source_kind` discriminator. Do not use `extra="ignore"`. Before the v2 rollout gate, any structured publication fails closed. Once the gate is enabled, every newly built snapshot—including document-only snapshots—writes version 2; existing v1 remains byte/behavior compatible and is never rewritten.

- [ ] **Step 4: Implement rollout guard and page evidence view**

Writer enables v2 only when reader capability is configured/verified. Freeze recomputes canonical raw hash before snapshot mutation; reader thereafter reads only `SnapshotFact.evidence`.

- [ ] **Step 5: Run GREEN and 018 regressions**

```bash
cd harness
uv run pytest -q tests/test_structured_evidence_snapshot_010_mvp.py tests/test_snapshot_facts_018.py tests/test_snapshot_reader_018.py tests/test_snapshot_pages_018.py tests/test_snapshot_guards_018.py
```

Expected: PASS.

- [ ] **Step 6: Independent review and human commit boundary for 010-thin-a**

Reviewer focuses on migration, provenance, strict union, cross-Space, and old v1 behavior. Stop; do not commit/push.

### Task 6: Known-schema write service through governance

- [ ] **Step 1: Write service RED tests**

Test unregistered source, unconfirmed mapping, dry-run zero write, same record replay, same identity/different hash collision before lifecycle/business write, valid fact assertions producing one governed ChangeSet and batch-record link, low-confidence/high-risk ReviewItem, and no direct published Claim. Assert every Evidence `structured_record_id` is the frozen SourceRevision binding returned by Task 3.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_known_schema_import_010_mvp.py
```

- [ ] **Step 3: Implement one explicit API**

Add `import_known_schema_records(session, scope, *, source_entry, mapping, records, apply=False)`. Flow: attest scope → resolve registered source/mapping → construct/validate common SourceRevision for every record → preflight the whole batch and collisions → materialize/reuse revision records → open/reuse the I9-fingerprinted ChangeSet and append batch links → map assertions with that revision binding to `ProposedClaim` → call existing `MergeEngine`/Review. Lifecycle decisions, revision rows, ChangeSet, links and Evidence use one caller-owned transaction/nested savepoint; the service never commits/rolls back the caller Session. The generic `import_records()` remains fail-closed for unknown/unprofiled input.

- [ ] **Step 4: Run GREEN**

Expected: PASS with deterministic ChangeSet/actions and zero model calls.

### Task 7: FAQ raw staging plus governed fact assertions

- [ ] **Step 1: Write FAQ RED tests**

Assert raw question/answer are retained in the structured record and qa_staging; zero assertions produce zero Claim; explicit assertions follow the same SourceRevision/mapping/merge path; final snapshot Evidence points to the FAQ revision record; raw FAQ is absent from current facts/search; rerun is idempotent.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_known_faq_import_010_mvp.py
```

- [ ] **Step 3: Implement FAQ adapter without QA publication**

Do not create a fake predicate such as `faq_answer`. Only canonical product predicates in approved mapping may become Claims. Leave `qa_items` and FAQ page/search work to 012.

- [ ] **Step 4: Run GREEN with full thin domain slice**

```bash
cd harness
uv run pytest -q tests/test_structured_import_010.py tests/test_known_schema_import_010_mvp.py tests/test_known_faq_import_010_mvp.py tests/test_structured_evidence_snapshot_010_mvp.py
```

Expected: PASS.

### Task 8: Validate and hand off 010 known-schema thin

- [ ] **Step 1: Touched-code static checks**

```bash
cd harness
uv run ruff check src/insurance_harness/structured_import src/insurance_harness/knowledge tests/test_*010_mvp.py
uv run mypy src/insurance_harness/structured_import src/insurance_harness/knowledge
```

- [ ] **Step 2: Complete `validation-report-mvp.md`**

Report three statuses separately: `0007 schema contract=PASS`, `010 known-schema thin behavior=PASS`, and `010 full I1–I9/T6–T12=PARTIAL`. Record common SourceRevision reconstruction, source/mapping independent axes, collision/idempotency, full schema/index/trigger/downgrade evidence, Evidence freeze, v1/v2 rollout regression, FAQ staging/assertion boundary, PG evidence, and exact deferred behaviors.

- [ ] **Step 3: Independent review**

Owner-A reviews every `knowledge/` and migration change; structured-import owner reviews schema/mapping. Maximum two remediation rounds.

- [ ] **Step 4: One PR-ready full deterministic run and human commit boundary**

Run full deterministic once after both reviews close, report seven-stage time and exact evidence, then stop. Do not commit/push.
