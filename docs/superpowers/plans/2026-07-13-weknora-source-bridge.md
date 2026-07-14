# WeKnora SourceDocument Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task, and use `superpowers:test-driven-development` for every feature or fix. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 017 so production compilation materializes an immutable, scope-attested `SourceDocument` from WeKnora and freezes reproducible source/chunk lineage into Evidence.

**Architecture:** Keep every WeKnora URL and transport detail inside the adapter. Add a `sources` boundary that owns all-or-nothing materialization, PDF page parsing, source revision calculation and quote-to-chunk mapping. The Compiler consumes materialized documents and retains the post-004 semantic pipeline; the knowledge importer freezes lineage and handles source revision changes without moving the published snapshot pointer.

**Tech Stack:** Python 3.12, Pydantic v2, httpx/respx, tenacity, SQLAlchemy 2, Alembic, LangGraph, pdfplumber, pytest, Ruff, mypy.

**Spec:** `openspec/changes/017-weknora-source-bridge/specs/source-bridge.md`

**Repository rule:** AI workers do not commit or push. Task completion is recorded by the matching `tasks.md` checkbox and exact command evidence in `validation-report.md`; the human owner performs Git operations.

---

## Binding design decisions

1. WeKnora `file_hash` is the upstream MD5 contract (`internal/application/service/knowledge_util.go`). Streaming download validates that MD5 and independently calculates a SHA-256 `original_digest` for Harness evidence.
2. `source_revision` is SHA-256 over canonical JSON containing upstream `file_hash`, normalized UTC `processed_at`, and an explicit parser fingerprint. A production WeKnora source rejects a missing hash, processed time, parser fingerprint or non-`completed` state.
3. A successful download is an async context manager. One download retry attempt covers opening the response, consuming the entire stream, checking byte limits/length and validating MD5. Timeout/transport, 408/429/5xx, truncation and MD5 mismatch consume the same retry budget; a size-limit breach and other 4xx are permanent immediately. The response is closed on every path, every failed attempt deletes its own temporary file, and the successful file is deleted on context exit.
4. Chunk pagination owns one retry budget for the whole list operation. A failure on page N discards pages 1..N-1 and the next attempt starts at page 1.
5. `SourceDocument` is immutable and contains only serializable source identity, pages and chunks; no temporary path enters it, `DocPayload` or a checkpoint. A runtime-only `MaterializedBatch` pairs documents with local paths. `ExtractionPipeline.run()` owns `async with source.materialize(...)` for the entire graph invocation and keeps the path map only on that run. Resume always rematerializes, compares scope/revision/digest with the checkpoint, and fails closed before model calls on mismatch.
6. The production `extract` command accepts only explicit `--source weknora` and also requires a bound Space, parser fingerprint and knowledge IDs. Directory input is exposed through a separate `extract-replay` command (and explicit library construction), so invalid production configuration can never select it or fall back to it.
7. `ClaimEvidence.lineage_status` is `linked`, `page_only` or `ambiguous`. Source freshness is represented independently by nullable `stale_at`, so a stale row retains the mapping decision that originally produced it.
8. Source-change notification creates or reuses one pending `recompile` ChangeSet keyed by non-null `(space_id, source_kind="recompile", external_record_id=knowledge_id, source_revision)`. Import for that knowledge/revision must populate that existing ChangeSet, not open a second `document` ChangeSet. Multi-document compiler output is partitioned by source identity and imported as one ChangeSet per knowledge/revision.
9. Concurrent get-or-create relies on the existing database unique constraint `uq_changeset_source` plus a nested-savepoint `IntegrityError` recovery/re-read path; a prior select is not sufficient. Migration/tests must prove the key remains scoped and non-null for recompile operations.
10. Migration `0004` belongs to 017. OpenSpec 018 starts at `0005` and remains serial with this change.

---

## File map

**Create**

- `harness/src/insurance_harness/sources/__init__.py`
- `harness/src/insurance_harness/sources/models.py`
- `harness/src/insurance_harness/sources/protocol.py`
- `harness/src/insurance_harness/sources/directory.py`
- `harness/src/insurance_harness/sources/weknora.py`
- `harness/src/insurance_harness/sources/lineage.py`
- `harness/migrations/versions/0004_source_evidence_lineage.py`
- `harness/tests/test_weknora_source_contract_017.py`
- `harness/tests/test_source_models_017.py`
- `harness/tests/test_source_weknora_017.py`
- `harness/tests/test_source_pipeline_017.py`
- `harness/tests/test_evidence_lineage_017.py`
- `harness/tests/test_source_revision_017.py`
- `harness/tests/test_source_bridge_live_017.py`
- `openspec/changes/017-weknora-source-bridge/validation-report.md`

**Modify**

- `harness/src/insurance_harness/config.py`
- `harness/src/insurance_harness/adapters/weknora/errors.py`
- `harness/src/insurance_harness/adapters/weknora/models.py`
- `harness/src/insurance_harness/adapters/weknora/client.py`
- `harness/src/insurance_harness/adapters/weknora/__init__.py`
- `harness/src/insurance_harness/compiler/models.py`
- `harness/src/insurance_harness/compiler/pipeline.py`
- `harness/src/insurance_harness/compiler/cli.py`
- `harness/src/insurance_harness/knowledge/models.py`
- `harness/src/insurance_harness/knowledge/tables.py`
- `harness/src/insurance_harness/knowledge/importer.py`
- `harness/src/insurance_harness/knowledge/merge.py`
- existing compiler/importer/migration fixtures and tests where signatures become explicit
- `harness/src/insurance_harness/adapters/README.md`
- `harness/src/insurance_harness/knowledge/README.md`
- `harness/src/insurance_harness/db/README.md`
- `openspec/changes/017-weknora-source-bridge/tasks.md`
- `docs/insurance-kb/13-blueprint-status.md`
- `docs/insurance-kb/16-roadmap.md`
- `docs/insurance-kb/20-enterprise-runtime-foundation.md`
- `HANDOFF.md`

---

### Task 1: WeKnora metadata, whole-pagination retry and safe streaming download

**Files:** adapter/config files plus `harness/tests/test_weknora_source_contract_017.py` and focused existing adapter tests.

- [ ] Write RED tests for all fields in B1.1/B1.2, retry of timeout/408/429/5xx, permanent non-retry 4xx, page-2 failure restarting at page 1, zero partial chunks, content-length truncation, MD5 mismatch, size limit, scope mismatch, and temporary-file/response cleanup after success, error and cancellation.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_weknora_source_contract_017.py tests/test_client_chunks.py tests/test_client_knowledge.py tests/test_retry.py -q`

- [ ] Extend response models with strict identity fields and lenient optional metadata. Parse timestamps as timezone-aware datetimes. Add typed integrity/size exceptions whose final public failure is non-transient after the internal retry budget is exhausted.
- [ ] Treat timeout/transport, 408, 429 and 5xx as transport-transient. Preserve the existing response body/status for all other 4xx.
- [ ] Implement `download_knowledge(scope, knowledge)` as an async context manager yielding a frozen download descriptor (`path`, byte count, upstream MD5, SHA-256 digest). The outer retry attempt must encompass response open, bounded stream consumption, `Content-Length`, byte-limit and MD5 checks. Truncation and MD5 mismatch retry from a new response into a new file, then convert to a non-transient integrity exception only after budget exhaustion; a size-limit breach is permanent without retry. Unlink every allocated path in `finally`.
- [ ] Refactor `list_chunks` so an outer retry attempt initializes a fresh list and uses non-retrying single-page sends internally. Scope-validate every item before it is appended to the attempt-local result.
- [ ] Run GREEN with the RED command, then run:

  `cd harness && .venv/bin/ruff check src/insurance_harness/adapters tests/test_weknora_source_contract_017.py --no-cache`

  `cd harness && .venv/bin/mypy --no-incremental src/insurance_harness/adapters src/insurance_harness/config.py`

- [ ] Update OpenSpec T1 evidence. Request a fresh spec review, then a fresh quality review. Resolve findings with a new RED test before implementation changes.

**Checkpoint:** T1 may not touch `sources/`, Compiler, Evidence or migration files.

---

### Task 2: Immutable SourceDocument protocol and Directory replay source

**Files:** create `sources/models.py`, `sources/protocol.py`, `sources/directory.py`, `sources/__init__.py`, and `tests/test_source_models_017.py`.

- [ ] Write RED tests for frozen `SourceChunk`, `SourceRevision`, `SourceDocument`; canonical revision stability; mutation rejection; explicit replay identity; stable document ordering; scanned-PDF dead-letter behavior; and deterministic dead-letter key `space_id+knowledge_id+revision_or_unknown+stage`.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_source_models_017.py -q`

- [ ] Define an async `DocumentSource` protocol returning an all-or-nothing `MaterializedBatch` context. `SourceDocument` and source requests are serializable; runtime `local_paths` exist only on the batch and are explicitly excluded from dumps/checkpoints. Do not expose WeKnora URLs in this package.
- [ ] Implement canonical revision hashing using sorted compact JSON and normalized UTC timestamps. Freeze original SHA-256 digest separately from upstream MD5.
- [ ] Move directory PDF discovery and page extraction into `DirectoryDocumentSource`. Directory mode must be constructed explicitly, must use deterministic ordering and replay identity, and must never manufacture a WeKnora knowledge ID.
- [ ] Represent materialization failure with a typed stage plus deterministic dead-letter key; do not return a partial `SourceDocument`.
- [ ] Run GREEN and focused Ruff/mypy for `sources`.
- [ ] Update OpenSpec T2 evidence and perform spec then quality review.

**Checkpoint:** no pipeline behavior change yet; existing Compiler tests must remain green.

---

### Task 3: Scope-attested WeKnoraDocumentSource materialization

**Files:** create `sources/weknora.py`, modify source models/protocol as required, create `tests/test_source_weknora_017.py`.

- [ ] Write RED tests that assert the exact order/closure of metadata → completed-state gate → download/hash → page parse → complete chunk list → `SourceDocument`; every stage failure returns no document and cleans its temporary file.
- [ ] Cover tenant/KB/knowledge mismatch, missing hash/time/parser fingerprint, non-completed/failed parse, scanned PDF, corrupt PDF, hash mismatch, chunks failure, cancellation and multi-document all-or-nothing behavior.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_source_weknora_017.py tests/test_weknora_source_contract_017.py -q`

- [ ] Implement `WeKnoraDocumentSource` only by composing public adapter calls. Require an attested `KnowledgeScope`; use `scope.raw_kb_id`; never accept a free-form KB ID.
- [ ] Keep every successful download context alive through the yielded `MaterializedBatch`; construct `SourceDocument` only after every requested knowledge item is complete. On batch failure close all contexts and expose deterministic per-stage failure data. The caller, not the DTO, owns the batch context.
- [ ] Persist parser fingerprint into the source revision and DTO. Ensure identical input yields byte-identical serialized source identity.
- [ ] Run GREEN plus cancellation tests repeatedly (for example `--count=5` only if the plugin is installed; otherwise a normal focused run) and focused Ruff/mypy.
- [ ] Update T3 evidence and perform spec then quality review.

---

### Task 4: Compiler load boundary and explicit production CLI source

**Files:** compiler models/pipeline/CLI, existing compiler tests, and `tests/test_source_pipeline_017.py`.

- [ ] Write RED tests proving `_node_load` consumes source documents and never calls `Path.glob`; Directory replay output remains equivalent; production `extract` accepts only explicit `--source weknora`; the separate `extract-replay` command owns Directory input. Bound Space, parser fingerprint or knowledge ID omissions fail without local fallback.
- [ ] Add checkpoint/resume tests: `run()` rematerializes on every invocation, holds the batch context across the entire graph invocation, never serializes a temporary path, and compares checkpoint/manifest scope, revision and digest before model calls. Assert context cleanup on graph success/failure/cancellation and no real model call in non-live tests.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_source_pipeline_017.py tests/test_compiler_pipeline.py tests/test_template_fastpath.py -q`

- [ ] Keep `DocPayload` unchanged as required by `design.md`. Convert each `SourceDocument` to the existing payload and put source identity in manifest entries. Give fast path a runtime-only `doc identity → local path` map owned by the active `run()` context; never put it in LangGraph state.
- [ ] Extend `DocManifestEntry`/`RunManifest` with knowledge ID, source revision, upstream file hash, original digest and parser fingerprint. Validate all scope/source identity when resuming.
- [ ] Make the source explicit at construction/CLI. Directory source owns all glob/page loading and is reachable only from `extract-replay` or explicit library construction. Production `extract --source weknora` resolves only an already bound Space through 016 scope loading and creates `WeKnoraDocumentSource`; it never substitutes Directory source.
- [ ] Compare replay `pred.jsonl` semantically (stable record content and evidence), allowing only new audit fields in the manifest.
- [ ] Run GREEN and focused Ruff/mypy. Update T4 evidence and perform spec then quality review.

---

### Task 5: Pure quote-to-chunk lineage and source-aware pred evidence

**Files:** create `sources/lineage.py`, modify compiler/source models as needed, create `tests/test_evidence_lineage_017.py` (pure portion).

- [ ] Write table-driven RED tests for whitespace normalization, exact unique containment → `linked`, zero hits → `page_only`, multiple hits (including duplicate chunk content) → `ambiguous`, empty quote, Unicode/punctuation preservation, deterministic SHA-256 chunk hash, and proof that page is never derived from `chunk_index`/offset.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_evidence_lineage_017.py -q`

- [ ] Implement lineage as pure functions. Reuse the established whitespace normalization meaning, but do not case-fold or rewrite punctuation unless a spec amendment and tests explicitly require it.
- [ ] Enrich Compiler evidence by joining each verified PDF quote to that document's chunks. Preserve the original page/quote; add only verified `chunk_id`, `chunk_hash` and status.
- [ ] Ensure no hit and ambiguous hit remain publishable page evidence, while no placeholder filename is emitted as a knowledge ID or chunk ref.
- [ ] Run GREEN plus compiler focused tests, Ruff and mypy. Update T5 evidence and perform spec then quality review.

---

### Task 6: Evidence schema migration and source-aware import

**Files:** knowledge models/tables/importer/merge, `0004_source_evidence_lineage.py`, migration/importer tests, and the DB/knowledge README files.

- [ ] Write RED tests for new frozen columns: `raw_kb_id`, `source_revision`, `file_hash`, `original_digest`, `parser_version`, `chunk_hash`, `lineage_status`, `stale_at`; exact import propagation; production rejection of placeholder knowledge IDs; one-source-per-ChangeSet partitioning; reuse of a pending recompile ChangeSet; and legacy replay compatibility only through an explicit compatibility flag/path.
- [ ] Write migration RED tests for upgrade/backfill, constraints/indexes, PostgreSQL DDL compile, downgrade round-trip, and refusal/loss documentation where exact downgrade cannot preserve new audit fields.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_evidence_lineage_017.py tests/test_knowledge_importer.py tests/test_knowledge_db.py tests/test_scope_migration_016.py -q`

- [ ] Add nullable audit columns for legacy rows and require complete source lineage on the production/source-aware importer path. Add scoped indexes for `(knowledge_id, source_revision)` and stale lookup; avoid a cross-Space Evidence query by joining `Claim.space_id` at runtime.
- [ ] Extend `ProposedEvidence` and `_evidence_rows` as a lossless mapping. The source-aware importer partitions records by source identity. Each partition uses `external_record_id=knowledge_id` and `source_revision`; it reuses a matching pending `recompile` ChangeSet, otherwise opens one `document` ChangeSet. An already applied identical revision reports a duplicate without adding ChangeItems.
- [ ] Keep filename placeholders accepted only by the named legacy replay entry point. Publisher `source_refs/chunk_refs` must select only validated non-stale lineage rows.
- [ ] Run GREEN, upgrade a fresh SQLite DB, run `alembic check`, compile PostgreSQL DDL, and run Ruff/mypy. Update T6 evidence and perform spec then quality review.

---

### Task 7: Source revision change, stale evidence, recompile and scoped delete

**Files:** knowledge merge/importer (or a small focused source-revision service), `tests/test_source_revision_017.py`, related publisher tests.

- [ ] Write RED tests for same-revision no-op, new revision marking only the same `(space_id, knowledge_id)` Evidence stale, exactly one pending idempotent `recompile` ChangeSet, source-aware import filling that same ChangeSet, and no mutation to `CurrentRelease` or the existing published snapshot.
- [ ] Cover two concurrent sessions racing the same notification, two Spaces sharing the same knowledge string, mixed claims with multiple sources, repeated notification, stale import failure rollback, and scoped delete/retract retaining claims with other evidence while retracting zero-evidence claims.
- [ ] Run RED:

  `cd harness && .venv/bin/pytest tests/test_source_revision_017.py tests/test_knowledge_merge.py tests/test_scope_knowledge_016.py tests/test_scope_publisher_016.py -q`

- [ ] Implement one transactional service that validates current scope, detects the latest active revision, sets `stale_at` on older rows, and gets-or-creates `source_kind="recompile"` with non-null `external_record_id=knowledge_id` and new revision. Use the existing `uq_changeset_source` constraint with a nested savepoint and conflict re-read to close the concurrent race; leave the release pointer untouched.
- [ ] Extend `retract_source` to record an idempotent source-scoped ChangeSet and ignore stale rows when determining remaining active evidence. All reads join through scoped Claim ownership.
- [ ] Run GREEN including deterministic SQLite duplicate-key recovery and PostgreSQL unique-DDL compilation; run a real PostgreSQL concurrency test only when explicitly configured and otherwise mark it live/skip. Then run Ruff/mypy, update T7 evidence and perform spec then quality review.

---

### Task 8: Live E2E, runbook, validation report and handoff

**Files:** `tests/test_source_bridge_live_017.py`, adapter/knowledge runbooks, OpenSpec validation/status and roadmap/handoff files.

- [ ] Add a `pytest.mark.live` E2E that requires explicit WeKnora URL/API key, bound Space, PDF fixture, parser fingerprint and database URL. It performs upload (or uses an explicitly supplied knowledge ID), parse wait, bridge, Compiler with scripted/replay LLM unless live LLM is separately enabled, pred import, and Evidence backlink assertions.
- [ ] Make missing live prerequisites call `pytest.skip` with the exact missing variables. Never turn a mock response into live evidence.
- [ ] Run focused non-live 017 suite, then full gates:

  `cd harness && .venv/bin/pytest -m 'not live' -q`

  `cd harness && .venv/bin/ruff check . --no-cache`

  `cd harness && .venv/bin/mypy --no-incremental src tests`

  `git diff --check`

- [ ] If live prerequisites are actually available, run:

  `cd harness && .venv/bin/pytest tests/test_source_bridge_live_017.py -m live -q`

  Otherwise record `NOT RUN` and the missing prerequisites in `validation-report.md`.
- [ ] Record exact counts, commands, SQLite/PostgreSQL limitations, retry/cleanup evidence and any residual risk. Mark `tasks.md` and status docs only from fresh command output.
- [ ] Request a full-change spec review, then a full-change quality review. Resolve each finding through TDD and rerun the affected focused suite plus all full gates.

**Final checkpoint:** Do not start OpenSpec 018 until 017 has both independent approvals and the main agent has rerun all completion gates.
