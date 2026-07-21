# MVP Template Compilation Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 028 as an approved TemplatePackage registry plus a recoverable, auditable single-process compilation runtime that connects existing WeKnora sources, product routing, weak-model calls, Evidence verification, and the existing governance sink.

**Architecture:** Build new Python `template_packages` and `runtime` packages beside the legacy compiler. LLM-wiki-black TypeScript is a provenance/characterization source only: no Node/TS domain service, queue, fact store, or Python↔TS runtime bridge ships. Stable database identities cover Job/StageRun/Attempt/Receipt/Alert; a fixed stage plan invokes small Python plugins through explicit ports, and all semantic writes go through Source lifecycle and `MergeEngine`. MVP uses 2–4 in-process workers; distributed lease/fencing remains an adapter-level enterprise extension.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/Alembic, asyncio, existing Source/Product/Knowledge services, pytest, PostgreSQL integration lane.

---

## Authority, dependencies, and PR split

- Spec: `openspec/changes/028-template-compilation-runtime-mvp/` (TR0–TR8).
- Hard dependency: 027 merged and verified. Real provider execution additionally needs 030 admission READY.
- Risk: 028a **B**, 028b persistence/migration **A**, orchestration **B**.
- Required skills while implementing: @superpowers:test-driven-development and @superpowers:verification-before-completion.
- PR 028a: pure-domain TemplatePackage models/ports/resolver only—no ORM or migration. PR 028b: deployable TemplatePackage/runtime persistence, production Python stage adapters, orchestration, knowledge sink, composition root, and CLI.
- Acquire the single migration lane from G immediately before creating `0014`; set `down_revision` to the actual main head, not the numerically previous migration.
- Do not import `compiler.pipeline`, `knowledge.importer`, or create parallel Claim/Review/Snapshot tables.
- Do not add a Node/TS domain process or invoke the old TS runtime from Python; frontend TypeScript is presentation/API-client only.
- AI execution sessions do not commit/push; stop at each human commit boundary.

## Stable file map

**028a create**

- `harness/src/insurance_harness/template_packages/__init__.py`
- `harness/src/insurance_harness/template_packages/models.py` — immutable package/version/content/provenance/approval DTOs.
- `harness/src/insurance_harness/template_packages/ports.py` — read-only `TemplateCatalog` protocol; no SQLAlchemy.
- `harness/src/insurance_harness/template_packages/resolver.py` — pure global→product-line→document-type→product-family resolution over an injected catalog.
- `harness/tests/test_template_packages_028.py`

**028b create**

- `harness/src/insurance_harness/template_packages/tables.py` — approved versions and immutable canonical payload.
- `harness/src/insurance_harness/template_packages/repository.py` — SQLAlchemy `TemplateCatalog` implementation with Space isolation.
- `harness/src/insurance_harness/runtime/__init__.py`
- `harness/src/insurance_harness/runtime/models.py` — domain identities/state/result DTOs.
- `harness/src/insurance_harness/runtime/ports.py` — typed stage ports plus `ModelGateway`, `AdmissionPort`, `KnowledgeSink`, `AlertPort`.
- `harness/src/insurance_harness/runtime/settings.py` — package-local immutable worker/attempt/time/token settings; no edit to global config.
- `harness/src/insurance_harness/runtime/plugins/materialize.py` — production adapter over existing `DocumentSource.materialize`.
- `harness/src/insurance_harness/runtime/plugins/classify_route.py` — production adapter over `classify_document` + `route_sections`/`persist_unassigned`.
- `harness/src/insurance_harness/runtime/plugins/resolve_template.py` — production adapter over the durable approved TemplateCatalog/resolver.
- `harness/src/insurance_harness/runtime/plugins/extract.py` — short-task extraction through 027 `ModelGateway` and resolved TemplatePackage.
- `harness/src/insurance_harness/runtime/plugins/verify.py` — deterministic quote/locator/schema verification using existing lineage/schema helpers.
- `harness/src/insurance_harness/runtime/plugins/gap.py` — required/high-risk unknown detection and bounded targeted attempts.
- `harness/src/insurance_harness/runtime/plugins/consensus.py` — deterministic normalization/agreement and conflict handoff; zero strong judge.
- `harness/src/insurance_harness/runtime/tables.py` — Job/StageRun/Attempt/AgentReceipt/Alert ORM.
- `harness/src/insurance_harness/runtime/repository.py` — idempotency/checkpoint/append-only receipt/alert operations.
- `harness/src/insurance_harness/runtime/orchestrator.py` — deterministic stage plan and bounded worker executor.
- `harness/src/insurance_harness/runtime/knowledge_sink.py` — CandidateFact→ProposedClaim/Evidence→lifecycle/MergeEngine adapter.
- `harness/src/insurance_harness/runtime/wiring.py` — production composition root.
- `harness/src/insurance_harness/runtime/cli.py` — `submit/resume/status/run-manifest` with frozen exit/artifact contract.
- `harness/migrations/versions/0014_template_compilation_runtime_mvp.py`
- `harness/tests/fixtures/runtime_028/medical_terms_materialized.json` — frozen chunks/lineage derived from one admitted real medical-terms source; hash and provenance recorded.
- `harness/tests/test_runtime_contracts_028.py`
- `harness/tests/test_runtime_repository_028.py`
- `harness/tests/test_runtime_orchestrator_028.py`
- `harness/tests/test_runtime_knowledge_sink_028.py`
- `harness/tests/test_runtime_composed_028.py`
- `harness/tests/test_runtime_cli_028.py`
- `harness/tests/test_runtime_migration_028.py`
- `openspec/changes/028-template-compilation-runtime-mvp/validation-report.md`

**Modify**

- `harness/migrations/env.py` — import new table metadata.
- `harness/tests/conftest.py` — register new ORM tables for isolated test databases.

Global `harness/src/insurance_harness/config.py` is owned by S0/027 and is not modified by 028. `RuntimeSettings` is injected by the composition root; a future global alias, if required, is a separate serialized integration patch after 027.

### Task 1: 028a contract, Python convergence, and provenance

- [ ] **Step 1: Write TR0/TR1/TR2 RED tests and architecture assertion**

Cover canonical hash stability, one-byte content change, approval/hash mismatch, cross-Space lookup, unresolved scope, and ordinary-vs-participating product-family isolation. Add an architecture assertion/review fixture proving migrated behaviors resolve to Python target paths and the Harness deployment does not start or call a Node/TS domain runtime; do not flag the upstream WeKnora frontend build.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_template_packages_028.py
```

Expected: FAIL because `template_packages` does not exist.

- [ ] **Step 3: Implement frozen package models**

The canonical payload must include at least:

```python
class TemplatePackageContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str
    field_groups: tuple[FieldGroup, ...]
    role_prompts: Mapping[str, str]
    validators: tuple[ValidatorRef, ...]
    evidence_policy: EvidencePolicy
    attempt_limits: Mapping[str, int]
    golden_slice_ref: str
    provenance: tuple[ProvenanceReceipt, ...]
```

Hash canonical JSON (`sort_keys=True`, UTF-8, compact separators); approval binds full hash and scope.

- [ ] **Step 4: Implement pure catalog port and resolver**

`TemplateCatalog` exposes approved frozen versions by explicit Space/applicability identity. Resolver returns merged content and an ordered source chain with every version/hash. The 028a test uses an in-memory catalog fixture; 028a creates no tables/repository and is independently mergeable without a migration. It never matches product names in orchestration code.

- [ ] **Step 5: Record first-party migration receipts**

For each reused LLM-wiki-black behavior, record source repo/branch/commit/path, `source_language=typescript`, accepted behavior, rejected behavior, Python target file, translation method, and characterization/Golden Slice tests. Do not bulk-copy the UI or monolithic pipeline and do not create a runtime bridge to it.

- [ ] **Step 6: Run GREEN and resolver Golden Slice**

```bash
cd harness
uv run pytest -q tests/test_template_packages_028.py tests/test_product_classify.py tests/test_product_routing.py
uv run ruff check src/insurance_harness/template_packages tests/test_template_packages_028.py
uv run mypy src/insurance_harness/template_packages
```

Expected: PASS; zero model calls.

- [ ] **Step 7: Independent review and human commit boundary for 028a**

Review TR0–TR2, pure-domain/no-ORM boundary, provenance, no hard-coded product names, and scope isolation. Report; do not commit/push.

### Task 2: Runtime identities, ports, and state transitions

- [ ] **Step 1: Write contract RED tests**

Assert deterministic Job identity includes `space_id + source_revision + product_version_id + schema_version + template_hash + model_plan_hash`; invalid state transitions and duplicate plugin names fail closed. Freeze these exact Python port shapes: `MaterializeStage.run(JobContext)->MaterializedBatch`, `ClassifyRouteStage.run(MaterializedBatch)->RoutedSections`, `ResolveTemplateStage.run(RoutedSections)->ResolvedTemplate`, `ExtractStage.run(RoutedSections, ResolvedTemplate)->CandidateFactBatch`, `VerifyStage.run(CandidateFactBatch)->VerifiedFactBatch`, `GapStage.run(VerifiedFactBatch)->GapResult`, `ConsensusStage.run(VerifiedFactBatch, GapResult)->ConsensusResult`, and `KnowledgeSink.apply(ConsensusResult)->GovernanceResult`.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_runtime_contracts_028.py
```

Expected: FAIL because runtime models/ports are missing.

- [ ] **Step 3: Implement minimal models and ports**

Freeze the MVP stage sequence; every name is a separately persisted checkpoint:

```text
materialize → classify_route → resolve_template → extract → verify → gap → consensus → knowledge_sink
```

Statuses: Job `queued/running/blocked/succeeded/failed`; Stage `pending/running/succeeded/blocked/failed`. A succeeded stage is terminal and cannot be overwritten.

- [ ] **Step 4: Run GREEN**

Expected: focused contract test PASS in ≤90 seconds.

### Task 3: Persistence and migration

- [ ] **Step 1: Re-check the actual Alembic head and acquire lane**

```bash
cd harness
uv run alembic heads
```

Expected: exactly one head. If more than one, stop and report to G; do not invent a merge migration.

- [ ] **Step 2: Write repository/migration RED tests**

Cover approved TemplateVersion persistence/immutability and catalog Space isolation together with Job idempotency, unique `(job_id, stage_name)`, append-only monotonically numbered Attempt, immutable AgentReceipt, Alert dedupe/claim/resolve, Space isolation, and upgrade/downgrade on empty tables.

- [ ] **Step 3: Run RED**

```bash
cd harness
uv run pytest -q tests/test_runtime_repository_028.py tests/test_runtime_migration_028.py
```

Expected: FAIL before tables/migration exist.

- [ ] **Step 4: Implement TemplatePackage plus runtime tables/repositories in one migration**

028b provides the first deployable SQLAlchemy `TemplateCatalog`; no 028a schema exists to rewrite. MVP deliberately omits lease/fencing columns that have no behavior; retain stable Job/Stage/Attempt IDs and timestamps so M2 can add distributed claims without identity migration. Receipts store hashes, usage, latency, provider request ID, outcome, evidence refs, and redacted metadata—never secret or raw unredacted response.

- [ ] **Step 5: Run SQLite GREEN**

Run the RED command again. Expected: PASS.

- [ ] **Step 6: Run focused PostgreSQL migration/invariant lane**

```bash
cd harness
uv run pytest -q -m integration_postgres tests/test_runtime_migration_028.py tests/test_runtime_repository_028.py
```

Expected: all selected tests execute; zero selected/skipped is not acceptable.

### Task 4: Recoverable orchestrator and bounded workers

- [ ] **Step 1: Write TR3/TR4/TR7 RED tests**

Use deterministic plugins and a fake repository. Test restart after verify failure, no rerun of succeeded stages, 2–4 worker cap, bounded attempts/tokens/time, empty response blocked, and one deduplicated Alert.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_runtime_orchestrator_028.py
```

Expected: FAIL before orchestrator exists.

- [ ] **Step 3: Implement the minimal executor**

`resume(job_id)` loads the persisted checkpoint, starts at the first non-succeeded stage, creates an Attempt before each external call, appends its receipt, and never treats empty/invalid output as success. A bounded asyncio semaphore enforces 2–4 workers; extra jobs stay queued.

- [ ] **Step 4: Run GREEN**

Expected: PASS; stage call counters prove already-succeeded stages are not repeated.

### Task 5: Multi-weak-model roles and Evidence-first blocking

- [ ] **Step 1: Write TR5 RED tests**

Cover approved weak-role plans, mutually exclusive values with valid Evidence, quote mismatch, ambiguous tri-state, and attempt exhaustion. Assert no direct publish/current movement.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_runtime_orchestrator_028.py -k "consensus or evidence or permit or exhausted"
```

- [ ] **Step 3: Implement the seven concrete production Python adapters**

Implement the exact files listed in the map:

- `MaterializeStage` calls the injected existing `DocumentSource.materialize` and preserves SourceRevision/chunk lineage;
- `ClassifyRouteStage` calls existing `classify_document` and `route_sections`, persisting ambiguous ownership through `persist_unassigned`;
- `ResolveTemplateStage` calls only the durable 028b repository/resolver and returns content hash plus ordered source chain;
- `ExtractStage` makes bounded short calls through the 027 `ModelGateway`, always passing frozen template hash/role prompt/permit;
- `VerifyStage` performs deterministic quote/locator match and schema validators before any candidate may advance;
- `GapStage` schedules only approved required/high-risk missing-field attempts within the frozen cap;
- `ConsensusStage` normalizes comparable values, preserves all Evidence, and returns an explicit conflict/Review+Alert handoff when no agreement exists.

These are production adapters used by `wiring.py`, not deterministic test plugins. They may inject fake external ports in tests, but no adapter imports or executes the LLM-wiki-black TS subsystem and none invokes a strong judge.

- [ ] **Step 4: Run GREEN**

Expected: PASS with exact weak-model fake call counts and zero fallback calls.

### Task 6: Existing governance knowledge sink

- [ ] **Step 1: Write TR6 RED tests**

Assert missing lineage, scope mismatch, stale SourceRevision, and invalid Evidence stop before merge; same revision replay is idempotent; conflict/low-confidence enters existing ReviewItem. Add a static import assertion forbidding `compiler.*`, `knowledge.importer`, and direct ORM writes in `runtime/knowledge_sink.py`.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_runtime_knowledge_sink_028.py
```

- [ ] **Step 3: Implement adapter**

Map `CandidateFact` to existing `ProposedClaim/ProposedEvidence`, call `coordinate_source_lifecycle`, then `MergeEngine`. Do not create a second transaction owner or call publisher/WeKnora writer.

- [ ] **Step 4: Run GREEN with regressions**

```bash
cd harness
uv run pytest -q tests/test_runtime_knowledge_sink_028.py tests/test_knowledge_merge.py tests/test_knowledge_review.py tests/test_source_lifecycle_021.py
```

Expected: PASS.

### Task 7: Composed zero-network path, composition root, CLI, and 028b handoff

- [ ] **Step 1: Write a composed real-fixture RED test**

`test_runtime_composed_028.py` loads `medical_terms_materialized.json`, verifies its recorded source SHA/provenance, and runs the actual seven production adapters plus actual `knowledge_sink` against an isolated database. Only the external `DocumentSource` and 027 `ModelGateway` are deterministic fakes; no stage plugin is replaced. Assert exact product route, verified Evidence, governed ChangeSet/Review result, attempt/receipt chain, and zero Wiki/CurrentRelease/Node/TS writes or calls.

- [ ] **Step 2: Run composed RED/GREEN**

```bash
cd harness
uv run pytest -q tests/test_runtime_composed_028.py
```

Expected RED before production adapters/composition exist; GREEN after wiring, with zero network/model provider calls.

- [ ] **Step 3: Write wiring/CLI contract tests**

Test `submit`, `resume`, `status`, and the exact batch entrypoint:

```text
python -m insurance_harness.runtime.cli run-manifest --request <yaml> --output-dir <new-directory>
```

`run-manifest` validates a strict request containing manifest path/hash, admission path/hash, bound Space, template lock/hash, model-plan hash, worker/attempt/time/token caps, and `apply=true`. Credentials/provider secrets come only from approved runtime environment and are never accepted as CLI arguments or serialized. Exit `0` means compilation through `knowledge_sink` completed and a `compilation-manifest.json` was written last over `run-summary.json`, jobs, stage runs, attempts, receipts, alerts, metrics, and governance proposal identifiers. It does **not** mean a release exists: `CurrentRelease` is unchanged and no `release-proof.json` or final `artifact-manifest.json` exists yet. Exit `2` means preflight/gate/config rejection with zero model calls; `3` means execution started but ended blocked/failed, with partial receipts/alerts written. It refuses an existing output directory. No subcommand writes Wiki or moves CurrentRelease.

The compilation manifest freezes every compiler-produced file and explicitly permits only later additions under the human-governance phase. The 029 governance-only CLI may consume this bundle to apply human-authored review decisions, build a candidate, approve an exact manifest hash, CAS-promote, and finally seal the full artifact bundle. That CLI must not import runtime stage plugins or call a model and is not a second compilation runner.

- [ ] **Step 4: Implement `wiring.py`, package-local settings, and `cli.py`**

All dependencies are injected: scope, source, product router, template resolver, seven production stages, model gateway, admission, repositories, knowledge sink, and `RuntimeSettings`. No module reads global mutable scope/model/template and 028 does not edit global `config.py`.

- [ ] **Step 5: Run the 028 focused domain suite**

```bash
cd harness
uv run pytest -q tests/test_template_packages_028.py tests/test_runtime_contracts_028.py tests/test_runtime_repository_028.py tests/test_runtime_orchestrator_028.py tests/test_runtime_knowledge_sink_028.py tests/test_runtime_composed_028.py tests/test_runtime_cli_028.py tests/test_weknora_source_contract_017.py tests/test_product_routing.py
```

Expected: PASS; real provider remains uncalled.

- [ ] **Step 6: Run touched-code static checks**

```bash
cd harness
uv run ruff check src/insurance_harness/runtime src/insurance_harness/template_packages tests/test_runtime_*_028.py tests/test_template_packages_028.py
uv run mypy src/insurance_harness/runtime src/insurance_harness/template_packages
```

- [ ] **Step 7: Complete validation report and independent review**

Record deterministic/PG evidence, migration head, TypeScript→Python provenance receipts, production-adapter composition proof, CLI/exit/artifact contract, restart proof, resource caps, and `real provider=NOT RUN`. Reviewer checks TR0–TR8 and rejects any TS runtime, fake-only wiring, second runner, or distributed-runtime scope creep.

- [ ] **Step 8: PR-ready one-time full deterministic and human commit boundary**

After findings close, run full deterministic once, report seven-stage time, and stop for the human owner. Do not commit/push. Real weak-model execution belongs only to 030 after admission READY.
