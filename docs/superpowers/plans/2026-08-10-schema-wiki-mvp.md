# Schema Wiki Medical Insurance 596-1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile one real, sealed Schema67 Candidate for Ping An eShengBao product version `596-1` into a deterministic, reviewable and atomically activatable Schema Wiki with one product root, seven sections, all 67 field pages and exact revision/page/bbox citations, while preserving the generic Wiki only as a non-authoritative material browser.

**Architecture:** One OpenSpec governs three non-overlapping lanes. Lane A freezes the shared canonical contracts and adapts validated releases to the existing WeKnora Release/CAS/Active Head. Lane B registers `medical-schema67.v1` and compiles only a concrete, replay-valid `Schema67CandidateV2` into the complete immutable release. Lane C consumes only pinned release DTOs and renders the Schema Wiki plus exact revision PDF citations. No lane creates a second Head, converts generic Wiki output into Schema facts, activates a partial release, or substitutes `current/latest/page=1` for missing authority.

**Tech Stack:** Python 3.12, Pydantic v2, existing Harness C0/057/119 Candidate contracts, Go 1.25 WeKnora services and transactional Release/CAS repository, Vue 3/TypeScript with existing `tsx --test` for pure TS and Vitest + the existing Vite Vue plugin + `@vue/test-utils`/`happy-dom` for real `.vue` component assertions, `pdfjs-dist` for page+bbox rendering, pytest, Ruff, strict mypy, Go test/vet, OpenSpec.

---

## Mission Card

- **Business goal:** Turn the approved Schema67 medical-insurance contract into the first formal product Wiki, independently of the existing generic material Wiki.
- **Exact first slice:** `medical-insurance` → Ping An eShengBao stable entity → product version `596-1` → `medical-schema67.v1` → 7 sections → 67 field pages.
- **Authoritative base:** `db6fd60bbf9cf4529db43ded24934c7bbdd422f9`.
- **Branches/worktrees:**
  - Lane A: `.worktrees/schema-wiki-core`, `codex/schema-wiki-core`.
  - Lane B: `.worktrees/schema-wiki-compiler`, `codex/schema-wiki-compiler`.
  - Lane C: `.worktrees/schema-wiki-ui`, `codex/schema-wiki-ui`.
- **Governance owner:** Lane B owns this plan and the single OpenSpec `120-schema-wiki-medical-596-1-mvp`; the other lanes must not edit registry/OpenSpec paths.
- **Serving authority:** the existing WeKnora Wiki Release Head remains the only Active Head. Existing `Prepare`, `ActivateReviewed`, `Revert`, pinned reads, dual ACL and transaction/CAS behavior are reused.
- **Current facts:** generic Wiki pages exist, but no real sealed Candidate or Active Schema Release currently exists. Fixtures can prove contracts; they cannot claim MVP completion.
- **Fresh external preflight (2026-08-10):** tenant `10003`, RAW KB `b1f1764c-443d-46b8-98e3-d5aa5e55eb42`; terms `f987fc16-222a-4246-8ca0-22c1a81dd6d9` completed attempt 2, brochure `1265a343-c408-4620-8eed-c4f6a2adadc2` completed attempt 1, rate `32402c40-6131-4049-8080-cc5b68188cd3` completed attempt 1. Their exact file/revision/manifest hashes remain external custody inputs and must be supplied to the trusted citation join.
- **Live migration fact:** the live database has no `wiki_release_*` tables. This plan adds
  no new Release/Head migration. The integrated immutable citation-source delta does add
  the narrow `000004_knowledge_revision_sources` migration for attempt-bound resource
  custody and delete guards; it is not a second serving authority. Real preparation/Head
  acceptance remains blocked until the standard release migrations and this source
  migration are applied in a separately authorized deployment window and their ledgers
  are verified clean.
- **Generic-Wiki fact:** 46 generic material pages are already live/published; rate `pages_affected=14` is not a source-document total-page count. Terms generic `source_refs` provenance is zero. None of these pages/counts may be migrated, promoted or guessed into Schema fields/citations.
- **Operational residue:** brochure retains two historical `running` subspans. The release runbook must freeze an accept/cleanup policy before activation; this plan does not alter the live residue.
- **Non-goals:** no provider/model run, no Golden mutation, no generic Wiki migration, no new release tables/migration, no second CAS/head, no benefits-domain content, no general CMS/registry platform, no partial activation, no default page 1.

## Frozen invariants

1. `Schema67CandidateV2` is accepted only through the public concrete validator/loader and its complete hash/replay custody. A duck object, self-rehash, old `CandidateAssemblyV1`, report-only payload or caller-selected subset fails closed.
2. Candidate absence returns `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE` and emits no draft/member/activation request. It never falls back to generic Wiki.
3. The medical pack has exactly seven ordered sections and a bijection over the approved ordered 67 field IDs:
   - Product overview: 16.
   - Application and contract: 15.
   - Renewal and rates: 6.
   - Coverage and exclusions: 11.
   - Claims and reimbursement: 9.
   - Services and benefits: 5.
   - Sales support: 5.
4. `present` has a value and at least one replay-valid, revision-bound citation. `absent_explicitly` has an explicit negative/not-applicable value and at least one replay-valid citation. `unknown` has neither value nor citation and renders as `待补充` with a ReviewItem.
5. `CitationTargetV1` binds source/replay identity plus a logical member reference, but never hashes its own final member digest. A separate `CitationMemberBindingV1` maps `citation_sha256 → final member_digest` outside the member digest preimage; the release manifest hash covers members and bindings together. Missing/zero/out-of-range page or missing/invalid bbox is typed failure, never page 1/full-page fallback.
6. The medical release has exactly 75 content members: 1 immutable root + 7 section members + 67 field members. The root member payload contains the exact `TaxonomySnapshotV1`, redirects and schema navigation/search-index metadata so existing pinned member reads can reconstruct the Active taxonomy; these are not extra members. Lane A's shared validator derives topology from the supplied validated SchemaPack rather than hardcoding medical counts. Any missing, extra, duplicated, generic or invalid member prevents preparation and activation.
7. Taxonomy, pages and citations activate in one release CAS. A failed new version/taxonomy/receipt/CAS leaves the previous Active release and Active Taxonomy intact; an existing opaque pin remains stable after Head advances.

## Physical ownership (no shared write paths)

### Lane A — public contracts and WeKnora serving foundation

Create:

- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py`
- `harness/tests/test_schema_wiki_contracts.py`
- `internal/types/schema_wiki.go`
- `internal/types/schema_wiki_test.go`
- `internal/application/service/schema_wiki.go`
- `internal/application/service/schema_wiki_citation_revision.go`
- `internal/application/service/schema_wiki_citation_revision_test.go`
- `internal/application/service/schema_wiki_test.go`
- `internal/application/service/testdata/schema_wiki_contract_vector.json`
- `internal/config/schema_wiki_signing_test.go`
- `internal/container/schema_wiki_production_readiness_test.go`
- `internal/handler/schema_wiki.go`
- `internal/handler/schema_wiki_test.go`
- `internal/router/routes_schema_wiki.go`
- `internal/router/routes_schema_wiki_test.go`
- `internal/application/repository/wiki_release_scope_test.go`

Modify:

- `internal/types/wiki_release.go` only to add the persisted Draft state to the existing
  Wiki Release preparation model; no new table, Head or migration.
- `internal/application/repository/wiki_release.go` for the read-only exact
  `GetHeadForWikiKB` scope lookup and the bounded existing-row Draft creation / exact
  Draft-to-Ready compare-and-swap. The CAS binds the previously read preparation digest
  and custody authorities, while reusing the existing Activate/Revert repository seams;
  it adds no table, migration, second Head or parallel release model.
- `internal/application/service/wiki_release.go` only for the bounded existing
  preparation lifecycle used by Schema `CreateDraft` / `ReviewDraft`; named-human review
  still happens before the state change and activation still uses the existing separate
  publish authorization and `ActivateReviewed` Head CAS.
- `internal/config/config.go` only to load strict public Ed25519 human-decision and publish-
  authorization key rings. It contains no private-key field, rejects cross-ring key ID or
  key-material reuse, and excludes the complete signing configuration from JSON output.
- `internal/container/container.go` only to provide the Schema Wiki service/handler, wire
  the existing human-decision/publish-authorization verifiers from those distinct public-
  key rings, and inject the fail-closed native citation replay adapter.
- `internal/router/router.go` is the approved mechanical DI and direct mount: `NewRouter`
  constructs the handler/middleware and registers all 13 Schema Wiki routes under the real
  `/api/v1` group. `internal/router/routes_knowledge.go` remains unchanged because its
  existing Wiki group carries ingest policy; moving the Schema routes there would either
  duplicate registration or alter the retrieve-only policy of Active Schema reads.

Immutable citation-source and token integration paths:

- `internal/types/knowledge_revision.go`,
  `internal/types/knowledge_revision_test.go` and
  `internal/types/schema_wiki_citation_content_test.go`.
- `internal/application/repository/{knowledge.go,knowledge_revision_test.go,resource.go}`,
  `internal/application/service/file/{resource_catalog.go,resource_catalog_test.go}` and
  `internal/application/service/resource_test.go` for the exact attempt/resource custody
  and delete-guard join.
- `internal/application/service/schema_wiki_citation_content.go` and its focused test,
  plus `internal/config/schema_wiki_citation_token_signing_test.go`, for the third,
  citation-token-only Ed25519 ring and token-bound immutable bytes.
- `internal/database/enterprise_migration.go`,
  `migrations/enterprise/versioned/000004_knowledge_revision_sources.{up,down}.sql`,
  `migrations/enterprise/versioned/000005_knowledge_revision_source_binding.{up,down}.sql` and
  `migrations/versioned/knowledge_revision_manifest_test.go` for the narrow source-custody
  migration only; these paths add no Release table, Head or CAS.

### Lane B — governance, medical pack and sealed-Candidate compiler

Create:

- `openspec/changes/120-schema-wiki-medical-596-1-mvp/proposal.md`
- `openspec/changes/120-schema-wiki-medical-596-1-mvp/tasks.md`
- `openspec/changes/120-schema-wiki-medical-596-1-mvp/validation-report.md`
- `openspec/changes/120-schema-wiki-medical-596-1-mvp/specs/schema-wiki-medical-596-1-mvp/spec.md`
- `harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py`
- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py`
- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_candidate_evidence_join_596_1.py`
- `harness/tests/test_medical_schema_pack_596_1.py`
- `harness/tests/test_schema_wiki_candidate_evidence_authority_121.py`
- `harness/tests/test_schema_wiki_release_596_1.py`
- `internal/application/service/testdata/schema_wiki_release_596_1_vector.json`

Modify:

- `openspec/changes/README.md` only for the exact `120` registry row.

The current plan file is planning custody, not a production implementation path.

### Lane C — release-pinned UI and exact citation viewer

Modify:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/router/index.ts`
- `frontend/src/views/knowledge/KnowledgeBase.vue`
- `frontend/src/i18n/locales/zh-CN.ts`
- `frontend/src/i18n/locales/en-US.ts`

Create:

- `frontend/src/api/schema-wiki/index.ts`
- `frontend/src/views/knowledge/schema-wiki/schemaWikiContract.ts`
- `frontend/src/views/knowledge/schema-wiki/schemaWikiContract.test.ts`
- `frontend/src/views/knowledge/schema-wiki/schemaWikiNavigation.ts`
- `frontend/src/views/knowledge/schema-wiki/schemaWikiNavigation.test.ts`
- `frontend/src/views/knowledge/schema-wiki/SchemaWikiBrowser.vue`
- `frontend/src/views/knowledge/schema-wiki/SchemaWikiFieldPage.vue`
- `frontend/src/components/schema-wiki/schemaCitationTarget.ts`
- `frontend/src/components/schema-wiki/schemaCitationTarget.test.ts`
- `frontend/src/components/schema-wiki/SchemaCitationViewer.vue`
- `frontend/src/components/schema-wiki/SchemaCitationViewer.test.ts`

Integration support paths (not Schema Wiki owner-path substitutes):

- `frontend/src/components/schema-wiki/pdfJsPort.ts`
- `frontend/src/components/sessionSidebarBuckets.ts`
- `frontend/src/i18n/locales/en-US.ts`
- `frontend/src/i18n/locales/ko-KR.ts`
- `frontend/src/i18n/locales/ru-RU.ts`
- `frontend/src/views/agent/AgentEditorModal.vue`
- `frontend/src/views/system/SystemSettings.vue`

`pdfJsPort.ts` is the bounded adapter used by the approved viewer. The other six paths are
the exact integration typecheck/build hygiene delta. These seven paths only close viewer
runtime, localization and whole-frontend type safety; they do not add routes, DTOs,
release semantics, citation authority or a substitute for any approved Lane C path.

### Machine-readable integrated owner/support closure

The following block is the exact, closed 74-path set for the provider-free immutable-
citation integration checkpoint. It is the union of governance documents, Lane A/B/C owner
paths, the seven bounded frontend support paths and the narrow immutable-source/token paths
above; automated verification compares this block byte-for-byte as a sorted set with
`git diff --name-only` from the authoritative base.

<!-- BEGIN SCHEMA_WIKI_EXACT_OWNER_SUPPORT_SET -->
```text
docs/superpowers/plans/2026-08-10-schema-wiki-mvp.md
frontend/package-lock.json
frontend/package.json
frontend/src/api/schema-wiki/index.ts
frontend/src/components/schema-wiki/SchemaCitationViewer.test.ts
frontend/src/components/schema-wiki/SchemaCitationViewer.vue
frontend/src/components/schema-wiki/pdfJsPort.ts
frontend/src/components/schema-wiki/schemaCitationTarget.test.ts
frontend/src/components/schema-wiki/schemaCitationTarget.ts
frontend/src/components/sessionSidebarBuckets.ts
frontend/src/i18n/locales/en-US.ts
frontend/src/i18n/locales/ko-KR.ts
frontend/src/i18n/locales/ru-RU.ts
frontend/src/i18n/locales/zh-CN.ts
frontend/src/router/index.ts
frontend/src/views/agent/AgentEditorModal.vue
frontend/src/views/knowledge/KnowledgeBase.vue
frontend/src/views/knowledge/schema-wiki/SchemaWikiBrowser.vue
frontend/src/views/knowledge/schema-wiki/SchemaWikiFieldPage.vue
frontend/src/views/knowledge/schema-wiki/schemaWikiContract.test.ts
frontend/src/views/knowledge/schema-wiki/schemaWikiContract.ts
frontend/src/views/knowledge/schema-wiki/schemaWikiNavigation.test.ts
frontend/src/views/knowledge/schema-wiki/schemaWikiNavigation.ts
frontend/src/views/system/SystemSettings.vue
harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py
harness/src/insurance_harness/knowledge_compiler/schema_wiki_candidate_evidence_join_596_1.py
harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py
harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py
harness/tests/test_medical_schema_pack_596_1.py
harness/tests/test_schema_wiki_candidate_evidence_authority_121.py
harness/tests/test_schema_wiki_contracts.py
harness/tests/test_schema_wiki_release_596_1.py
internal/application/repository/knowledge.go
internal/application/repository/knowledge_revision_test.go
internal/application/repository/resource.go
internal/application/repository/wiki_release.go
internal/application/repository/wiki_release_scope_test.go
internal/application/service/file/resource_catalog.go
internal/application/service/file/resource_catalog_test.go
internal/application/service/resource_test.go
internal/application/service/schema_wiki.go
internal/application/service/schema_wiki_citation_content.go
internal/application/service/schema_wiki_citation_content_test.go
internal/application/service/schema_wiki_citation_revision.go
internal/application/service/schema_wiki_citation_revision_test.go
internal/application/service/schema_wiki_test.go
internal/application/service/testdata/schema_wiki_contract_vector.json
internal/application/service/testdata/schema_wiki_release_596_1_vector.json
internal/application/service/wiki_release.go
internal/config/config.go
internal/config/schema_wiki_citation_token_signing_test.go
internal/config/schema_wiki_signing_test.go
internal/container/container.go
internal/container/schema_wiki_production_readiness_test.go
internal/database/enterprise_migration.go
internal/handler/schema_wiki.go
internal/handler/schema_wiki_test.go
internal/router/router.go
internal/router/routes_schema_wiki.go
internal/router/routes_schema_wiki_test.go
internal/types/knowledge_revision.go
internal/types/knowledge_revision_test.go
internal/types/schema_wiki.go
internal/types/schema_wiki_citation_content_test.go
internal/types/schema_wiki_test.go
internal/types/wiki_release.go
migrations/enterprise/versioned/000004_knowledge_revision_sources.down.sql
migrations/enterprise/versioned/000004_knowledge_revision_sources.up.sql
migrations/versioned/knowledge_revision_manifest_test.go
openspec/changes/120-schema-wiki-medical-596-1-mvp/proposal.md
openspec/changes/120-schema-wiki-medical-596-1-mvp/specs/schema-wiki-medical-596-1-mvp/spec.md
openspec/changes/120-schema-wiki-medical-596-1-mvp/tasks.md
openspec/changes/120-schema-wiki-medical-596-1-mvp/validation-report.md
openspec/changes/README.md
```
<!-- END SCHEMA_WIKI_EXACT_OWNER_SUPPORT_SET -->

## Shared contracts to freeze before dependent GREEN

Lane A publishes matching Python/Go canonical JSON contracts for:

- `KnowledgeDomainV1`, `SchemaPackV1`, `SchemaPackRegistryV1`, `SchemaSectionV1`, `SchemaFieldDefinitionV1`.
- `KnowledgeEntityV1`, `KnowledgeEntityVersionV1`, `TaxonomySnapshotV1` and release-bound `ActiveTaxonomyV1`.
- `BBoxV1`, non-circular `CitationTargetV1`, `CitationMemberBindingV1`, `SchemaFieldMemberV1`, `KnowledgeWikiReleaseV1` and citation-to-final-member bindings.
- `ParseKnowledgeWikiReleaseV1`, `ValidateKnowledgeWikiReleaseV1` and `MapKnowledgeWikiReleaseToPreparation`.

The contract is closed-world and canonical. `KnowledgeWikiReleaseV1` is draft/preparation authority only and cannot self-declare Active. Lane A's Go service may map a reviewed immutable preparation to the existing release transaction, but activation and revert continue through the existing named-human receipt, publish authorization and CAS APIs.

The HTTP surface remains under existing Space/RAW-KB scope and dual ACL. The UI first calls `GET /api/v1/knowledgebase/:wiki_kb_id/wiki/schema-scope`. Its middleware chain is exact: existing `Viewer` + `KBAccessRead("kb_id")` → record Wiki evidence → `SchemaWikiHandler.ResolveScopeParams` reads unique `GetHeadForWikiKB(tenant_id, wiki_kb_id)` and appends non-overridable derived `space_id/raw_kb_id` Gin params → existing `KBAccessRead("raw_kb_id")` → record RAW evidence → existing `WikiReleaseHandler.SealAccess` → return closed `SchemaWikiScopeV1`. Thus both human/JWT and API-key principals traverse the existing organization/share/agent/API-key KB authorization logic twice; no client composes IDs and no Wiki-only/API-key-only shortcut is accepted. Every subsequent URL uses the exact prefix `/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema`:

- `GET .../schema/domains`
- `GET .../schema/taxonomy/current`
- `GET .../schema/entities/:entity_id/versions/:version_id/current`
- `GET .../schema/releases/:release_id/{root|sections/:section_id|fields/:field_id}`
- `GET .../schema/preparations/:preparation_id/{root|sections/:section_id|fields/:field_id}` for a reviewed immutable preparation only; there is no pre-activation `release_id`.
- `POST .../schema/preparations`
- existing activation endpoint with opaque named-human decision and publish authorization
- future pinned citation endpoint `GET .../schema/releases/:release_id/fields/:field_id/citations/:citation_id/preview`; the server must re-read the immutable release member and its `CitationTargetV1`, then verify revision, parse attempt, document/manifest/member and ACL before returning bytes. It never accepts client-supplied revision/hash authority.

Pre-review Candidate/manifest review remains Lane B dossier custody. The shared HTTP facade exposes only reviewed immutable preparations and Active/history releases.

`NO_SCHEMA_WIKI_ACTIVE_RELEASE`, `PAGE_UNAVAILABLE`, `BBOX_UNAVAILABLE`, `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE` and authority/hash drift are typed fail-closed states. Generic members never pass the schema read facade.

## Task 0: Approve one bounded OpenSpec before production changes

**Files:** Lane B OpenSpec/registry paths only.

- [x] Register OpenSpec 120 at the initial `plan-approved / implementation-not-started`
  phase; the current registry row is reconciled separately to `CODE-INTEGRATED /
  LIVE-NOT-RUN`.
- [x] Specify the three-lane ownership matrix above and make path overlap a stopping condition.
- [x] Specify Candidate-only compilation, the exact medical pack, tri-state rules, exact citation custody, all-or-nothing preparation/activation, pinned reads and no generic fallback.
- [x] Specify current blockers separately from fixture-based implementation acceptance.
- [x] Run `openspec validate 120-schema-wiki-medical-596-1-mvp --strict` and record the initial missing-spec RED, then complete the four OpenSpec documents until GREEN.
- [x] Run `git diff --check -- openspec/changes/README.md openspec/changes/120-schema-wiki-medical-596-1-mvp`.
- [x] Commit only these five paths with `docs(120): specify Schema Wiki medical MVP` after plan approval.

Expected RED: the change ID is absent. Expected GREEN: strict validation passes and no production path is changed.

## Task 1: Lane A1 freezes canonical domain, taxonomy, release and citation contracts

**Files:** Lane A DTO/validator/vector files only.

- [ ] Write Python REDs for extra/noncanonical fields, self-rehash, taxonomy cycle/orphan/duplicate path, foreign domain, reparented entity identity and pack section/field mismatch.
- [ ] Write tri-state REDs: present without value/Evidence, absent without explicit Evidence, unknown with value/citation, and multi-source known fields missing a required source role.
- [ ] Write citation REDs for page `0`/missing, absent/degenerate/full-page bbox, unknown coordinate system, foreign revision/document/manifest, quote/content drift and member-binding drift.
- [ ] Write release REDs proving shared validation derives the exact root/section/field topology from the supplied validated SchemaPack. Missing/duplicate/extra/generic members, a topology that disagrees with that pack, Candidate/review-policy mismatch and a draft claiming Active must fail; Lane A must not hardcode medical 7/67 counts.
- [ ] Confirm RED with `uv run pytest harness/tests/test_schema_wiki_contracts.py -q` before production DTOs exist.
- [ ] Implement the smallest frozen Pydantic DTOs, canonical hashes and validators in `schema_wiki_contracts.py`.
- [ ] Add equivalent Go DTO validation and exact cross-language bytes/digest vector.
- [ ] Run:
  - `uv run pytest harness/tests/test_schema_wiki_contracts.py -q`
  - `go test ./internal/types -run TestSchemaWiki -count=1`
  - `uv run ruff check harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py harness/tests/test_schema_wiki_contracts.py`
  - `uv run mypy --strict harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py harness/tests/test_schema_wiki_contracts.py`
- [ ] Freeze the A1 commit and publish only its exact commit/tree identity to lanes B/C; do not merge other A2 paths into the interface checkpoint.
- [ ] Commit with `feat(schema-wiki): freeze canonical domain and release contracts`.

Expected GREEN: Python and Go parse the same canonical vector and reject every identity/citation/topology mutation before output, while a second synthetic non-medical pack proves the shared contract is configurable without registering benefits content.

## Task 2: Lane B registers the only medical SchemaPack

**Files:** `medical_schema_pack_596_1.py` and its focused test.

- [ ] Build a test from the approved ordered 67 `FieldContractV1` IDs, not from Golden answers or a new field list.
- [ ] RED: missing, extra, duplicate or reordered field; wrong section count/order; field assigned to zero or multiple sections; foreign field-contract-set hash; caller-created alternate medical pack.
- [ ] RED: assert the exact counts `16/15/6/11/9/5/5` and stable section identifiers.
- [ ] Implement one code-owned factory/validator for `medical-schema67.v1` using Lane A's public `SchemaPackV1` contract.
- [ ] In the same module, code-own the initial medical domain/category, stable Ping An eShengBao `entity_id`, product version `596-1` and initial taxonomy factory. These identities are not caller parameters. A later reparent starts from the prior Active taxonomy, preserves entity/version IDs and emits redirects.
- [ ] RED: substitute or self-rehash domain/category/entity/version/taxonomy/path identities and require rejection before Candidate compilation.
- [ ] Keep benefits as a configuration boundary only; do not register benefits content.
- [ ] Run `uv run pytest harness/tests/test_medical_schema_pack_596_1.py -q` and confirm RED→GREEN.
- [ ] Run Ruff and strict mypy on the module and test.
- [ ] Commit with `feat(schema-wiki): register medical Schema67 pack`.

Expected GREEN: exactly one approved pack covers each ordered Schema67 field exactly once and contains no answer/value/Evidence oracle.

## Task 3: Lane B compiles a real sealed Candidate into one complete release draft

**Files:** `schema_wiki_release_596_1.py`, its focused test and the immutable Go interop vector.

- [ ] RED: `candidate=None` returns `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE`, produces no member bytes/vector and never invokes a generic-Wiki adapter.
- [ ] RED: reject old `CandidateAssemblyV1`, report-only payload, duck object, self-rehashed Candidate, wrong product/tree/model/pack/ordered67 identity and partial task/batch custody.
- [ ] RED: known fields without replay-valid 057 receipts or without a trusted exact SourceRevision/knowledge/chunk/page/locator/bbox join produce zero draft; a caller-created citation mapping is not authority.
- [ ] RED: unknown retains no value/citation and emits a stable pending ReviewItem; `absent_explicitly` cannot be inferred from missing material.
- [ ] RED: mutate any root/section/field/member/citation/taxonomy/redirect/digest, either side of `citation_sha256 → member_digest`, or a code-owned 596-1 entity/taxonomy identity and assert no partial release is returned.
- [ ] Define `SchemaWikiReviewBundleV1` in this existing module. Its hash binds the exact Candidate hash, release draft hash, manifest digest, ordered member digests, citation bindings and domain/taxonomy/schema/entity/version identities.
- [ ] RED: reuse a named-human decision for a different manifest/member order/taxonomy or alter the review bundle after signing. Require `HumanBatchDecisionReceiptV1.HumanBatchHash` and `WikiReleasePreparation.ReadyReceiptDigest` to equal the exact review-bundle hash before mapping to preparation.
- [ ] RED: shuffle input mappings and prove canonical output bytes remain stable; mutate a semantic value or citation and prove the release digest changes.
- [ ] Implement a pure compiler that first calls the public concrete Candidate validator, the code-owned medical pack validator and Lane A's release validator.
- [ ] Build exactly one entity-version root, seven section members and 67 field members. Put the exact taxonomy snapshot, redirects and navigation/search-index metadata in the root payload so pinned reads do not require hidden manifest bytes. First hash each `CitationTargetV1` over source/replay identity plus logical member ref; then hash the member payload containing citation hashes; finally emit release-level `CitationMemberBindingV1` rows outside member digest preimages. The manifest/release hash covers both sets.
- [ ] Emit canonical `KnowledgeWikiReleaseV1` bytes and `schema_wiki_release_596_1_vector.json`; perform no filesystem/network/provider/Golden/DB/WeKnora action in production code.
- [ ] Run:
  - `uv run pytest harness/tests/test_schema_wiki_release_596_1.py harness/tests/test_medical_schema_pack_596_1.py harness/tests/test_schema67_candidate_report_596_1.py -q`
  - `uv run ruff check harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py harness/tests/test_medical_schema_pack_596_1.py harness/tests/test_schema_wiki_release_596_1.py`
  - `uv run mypy --strict harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py harness/tests/test_medical_schema_pack_596_1.py harness/tests/test_schema_wiki_release_596_1.py`
- [ ] Commit with `feat(schema-wiki): compile sealed Schema67 release draft`.

Expected GREEN: a synthetic Candidate created only through the real public Candidate factory compiles deterministically; no test may use a hand-authored sealed object. The named-human receipt is mechanically bound to this exact release manifest. Real MVP remains blocked until a real Candidate and trusted citation-authority join exist.

## Task 4: Lane A2 maps the reviewed draft to the existing Release/CAS and read facade

**Files:** Lane A type/service/handler/router files plus the exact release-scope and
existing-preparation-row repository seams/tests listed in ownership. Only the bounded
Draft creation and Draft-to-Ready CAS may write; do not add a release table, Head,
migration or parallel approval path.

- [ ] RED: a schema preparation with malformed vector, incomplete topology, generic member, invalid citation or Candidate/review-bundle drift fails before the existing `Prepare` transaction.
- [ ] RED: mutate taxonomy/redirect/navigation metadata inside the entity-version root payload and prove preparation rejects it; after activation, pinned/current reads must reconstruct taxonomy only from that immutable root member.
- [ ] RED: R1 Active followed by any R2 taxonomy/member/prepare/receipt/CAS failure keeps complete R1 current; no R2 member or taxonomy becomes visible.
- [ ] RED: after successful R2 activation, an opaque R1 pin still reads R1; each read performs fresh dual ACL.
- [ ] RED: revert R2→R1 changes Head epoch once and creates no new release/member; concurrent expected-head activation/revert has one winner.
- [ ] RED: no Active returns `NO_SCHEMA_WIKI_ACTIVE_RELEASE`; the service does not read generic Wiki pages as fallback.
- [ ] Freeze a narrow `CitationRevisionReadPort` contract and REDs for current/latest substitution, client-supplied authority, revision/attempt/document/manifest/member mismatch, bad page/bbox and ACL failure. The production adapter may replay only the native knowledge/revision/chunk/manifest custody currently available; after that replay it must still return typed unavailable and zero bytes because no immutable attempt-bound blob or canonical page/bbox coordinate authority exists.
- [ ] Implement `PrepareSchemaReviewed` as validation+mapping into existing `WikiReleaseService.Prepare`; keep `ActivateReviewed` and `Revert` as the only activation paths.
- [ ] Implement current/pinned/prepared schema reads over release members and the scoped handler/router facade, including the server-derived `SchemaWikiScopeV1` bootstrap. Wire the native custody replay adapter without current/latest/presigned/page-1 fallback; actual revision-byte preview remains blocked until an immutable attempt-bound blob plus canonical page/bbox/coordinate-space authority is frozen.
- [ ] Wire the existing named-human and publish-authorization verifiers from distinct strict Ed25519 public-key rings. Empty/unknown/malformed/private-length input fails closed, cross-ring duplicate IDs or key bytes are rejected, and signing configuration/key bytes are excluded from JSON output.
- [ ] Implement `GetHeadForWikiKB` as a read-only exact lookup over the existing release Head. Bootstrap must apply Wiki ACL first, then derived RAW-KB ACL and release access seal before returning scope; zero/multiple/cross-tenant results fail closed.
- [ ] RED the exact bootstrap middleware sequence: Wiki authorized + derived RAW unauthorized, API-key allowlist containing only Wiki KB, caller-supplied conflicting params, cross-tenant Head and zero/multiple Head all return no `SchemaWikiScopeV1` and never create a release seal.
- [ ] Run:
  - `go test ./internal/application/service -run 'TestSchemaWiki|TestWikiReleasePR2|TestWikiReleaseFalsification' -count=1`
  - `go test ./internal/handler -run TestSchemaWiki -count=1`
  - `go test ./internal/application/repository -run TestGetHeadForWikiKBScope -count=1`
  - `go test ./internal/router -run TestSchemaWikiScopeBootstrap -count=1`
  - `go test ./internal/config -run 'TestDecodeSchemaWikiSigningPublicKeys|TestSchemaWikiSigningPublicKeys' -count=1`
  - `go test ./internal/container -run 'TestSchemaWikiProduction|TestSchemaWikiContainer' -count=1`
  - `go vet ./internal/types ./internal/application/repository ./internal/application/service ./internal/handler ./internal/router ./internal/container`
  - `git diff --check`
- [ ] Commit with `feat(schema-wiki): add release-pinned schema read foundation`.

Expected GREEN: the existing release transaction remains the sole serving authority; schema taxonomy and members change atomically or not at all. A2 production-readiness GREEN proves the native revision/chunk/manifest replay, non-nil DI and separated public-key verifier wiring fail closed. It does not prove immutable revision bytes, coordinate space, page/bbox authority or real citation preview are serviceable.

## Task 5: Lane C freezes fail-closed frontend contracts and navigation

**Files:** Lane C API/contract/navigation files and tests first; no components yet.

- [ ] RED: Wiki-enabled KB defaults to generic documents/material Wiki; generic source refs render as Schema; domain/section IDs are hardcoded; malformed 7/67 topology still renders.
- [ ] RED: the UI combines caller-selected Space/RAW/Wiki IDs, skips `SchemaWikiScopeV1` bootstrap, or calls a schema URL outside the exact scoped prefix.
- [ ] RED: unknown with value/Evidence, absent without explicit Evidence, release/member pin mismatch, Draft read as current/search, taxonomy reparent altering entity/version/field/citation identity.
- [ ] RED: knowledge-only citation opens `current`, missing page uses `|| 1`, revision/member drift opens, invalid bbox becomes full-page highlight.
- [ ] Implement closed-world TypeScript DTO parsers/reducers for Lane A/B exact fixtures; reject every drift before rendering.
- [ ] Keep `schema` and `材料 Wiki` as separate tabs and authorities. `NO_SCHEMA_WIKI_ACTIVE_RELEASE` is a first-class empty state, not a fallback trigger.
- [ ] Run:
  - `cd frontend && npm test -- src/views/knowledge/schema-wiki/schemaWikiContract.test.ts src/views/knowledge/schema-wiki/schemaWikiNavigation.test.ts src/components/schema-wiki/schemaCitationTarget.test.ts`
  - `cd frontend && npm run type-check`
- [ ] Commit the pure contract checkpoint only after A1/B vector identity is frozen.

Expected GREEN: no component can receive an unvalidated schema member or an unpinned citation target.

## Task 6: Lane C renders the pinned Schema Wiki and exact PDF citations

**Files:** Lane C components, router, KB view, i18n and package lock paths.

- [ ] Obtain explicit dependency approval for `pdfjs-dist`, `vitest`, `@vue/test-utils` and `happy-dom`. Keep `tsx --test` for pure TypeScript tests; add a bounded component-test script that loads the existing Vite Vue plugin and runs Vitest with `happy-dom`. If the viewer/runtime dependencies are not approved and no existing exact bbox viewer/test runtime exists, stop with `BBOX_VIEWER_UNAVAILABLE` instead of degrading acceptance.
- [ ] Build the Schema root, 7-section navigation, 67 field pages, Draft/Active/history badges and whole-release activation request using validated DTOs only.
- [ ] Display `present`, `absent_explicitly` and `unknown` exactly; unknown is `待补充` with no citation affordance.
- [ ] Use validated fixtures to drive the `CitationRevisionReadPort` response, select the exact PDF page and transform the validated bbox using the declared coordinate system. Do not claim live preview integration until the concrete revision-byte adapter gate is closed.
- [ ] Add `SchemaCitationViewer.test.ts` using Vitest + the existing Vite Vue plugin + `@vue/test-utils`/`happy-dom`; cover independent page 12 and page 27 DOM assertions with a visible bbox overlay. Missing/out-of-range page yields `PAGE_UNAVAILABLE`; invalid bbox yields `BBOX_UNAVAILABLE`.
- [ ] Prove the frontend cannot sign, self-approve or activate one page; it only forwards opaque named-human review and publish authorization for the complete draft.
- [ ] Prove a second domain fixture can be configured without changing components, while shipping no benefits content.
- [ ] Run:
  - `cd frontend && npm test`
  - `cd frontend && npm run test:schema-wiki-component -- src/components/schema-wiki/SchemaCitationViewer.test.ts`
  - `cd frontend && npm run type-check`
  - `cd frontend && npm run build`
  - `git diff --check`
  - scoped static scans for secrets, `current` preview fallback, `page || 1`, and unvalidated external URLs.
- [ ] Commit with `feat(schema-wiki): add release-pinned UI and exact citation viewer`.

Expected GREEN: the UI displays one pinned release consistently, and its component/reducer contract opens the exact revision/page/bbox or fails closed. Real bytes remain an end-to-end blocker until the server-side `CitationRevisionReadPort` has a concrete trusted adapter.

## Task 7: Integrate in one direction and prove the vertical slice

Provider-free integration checkpoint: commit
`4037224dbf30509e9a6144e08b9fe7e94ef0985d`, tree
`7afa856770956c6d751a159951f35cf7b91239fd`, exact closed owner union 51 paths. This
identity includes the exact-five-path UI reachability delta and four OpenSpec closeout
documents; this plan-only correction changes no production byte. The successful sealed
Candidate, production citation join, deployed release schema, Draft, named-human review
and activation remain live NO-GO gates rather than implied results of this checkpoint.

The reviewed production-readiness successor is frozen separately as tree
`db07de2e737a209a1cc8edf59c63914260bc810a` from final3 base
`0f6a958a203d6813bee057c7d87eb2ad9bc86a49`; its exact eight-path index SHA-256 is
`8da2663f054891265b58962e1dde0eb2ed8b95759018d217aaa3b3f10d778a63`. Integrating it
extends the closed owner/support union to 56 paths. It closes native custody replay,
non-nil DI and separated/redacted public-key verification wiring only; it deliberately
keeps real citation preview and the overall MVP at live NO-GO.

The provider-free immutable-citation stack then applies, in order, immutable revision
source custody, token-only citation bytes with a third signing ring, the Go Candidate
companion replay, the factory-provenance-sealed Python Candidate companion, and the exact
page/bbox UI. It preserves release vector SHA-256
`6783e3312199378a51065872278961f10c0e0f6510648e2ff1ce18823f10e6be` and expands the
closed owner/support union to 74 paths. The previous official DeepSeek exact8 run ended in
a typed failure with no Candidate; no new real model execution, Draft, review, activation
or live citation-byte request has been run against this stack.

- [ ] Merge/rebase in this order only: OpenSpec120 → Lane A1 → Lane B pack/compiler → Lane A2 service/CAS → Lane C UI.
- [ ] At every step, mechanically verify owner-path disjointness. Resolve only expected OpenSpec registry metadata in Lane B; no semantic conflict may be auto-resolved.
- [ ] Run the complete scoped matrix once on the integration candidate:
  - `openspec validate 120-schema-wiki-medical-596-1-mvp --strict`
  - Lane A Python/Go contract, service, handler and CAS tests from Tasks 1/4.
  - Lane B pack/compiler tests plus bounded public Candidate/057/119 compatibility.
  - Lane C unit/type-check/build tests from Tasks 5/6.
  - Ruff changed Python, strict mypy changed production/test modules, Go vet changed packages, `git diff --check`, exact-path and privacy/secret scans.
- [ ] Before any external write, verify the exact tenant/RAW-KB and three completed knowledge identities/attempts listed in the Mission Card facts, plus their frozen source/revision/manifest hashes. Treat rate `pages_affected=14` only as a processing count, never page authority.
- [ ] Run the server-side exact3 `dry_run=true` first. It must validate ordered
  terms→brochure→rate-table database authority and existing source rows in one
  `REPEATABLE READ READ ONLY` snapshot, return only redacted snapshot/source/result
  digests and `WOULD_INSERT|NOOP|CONFLICT_STOP` counts, and report `writes=0`. Any
  conflict is a whole dry-run STOP; `NOOP` requires full sealed authority equality.
- [ ] If that receipt has no conflict, authorize actual once. Actual fresh-rechecks and
  seals serially in the same order. If terms succeeds and brochure fails, retain the terms
  pin, do not run rate-table, and do not rollback/unseal or describe the three writes as atomic.
- [ ] Verify the live database has the existing `wiki_release_*` schema and a clean standard migration ledger. If absent, stop with `RELEASE_SCHEMA_NOT_DEPLOYED`; do not create ad-hoc tables or auto-migrate from the application.
- [ ] Freeze an explicit runbook decision for the two historical brochure `running` subspans. Do not silently treat them as current work, retry them or clean them inside this Mission.
- [ ] Use a real sealed Candidate and trusted citation-authority join for the real acceptance run. Terms citation authority must come from the sealed revision/page/bbox chain because generic terms `source_refs=0`. If Candidate or join is absent, report `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE`; do not substitute fixtures, the 46 generic pages or generic Wiki refs.
- [ ] Prepare one immutable Draft, obtain named-human approval and activate through the existing CAS in a separately authorized environment window.
- [ ] Verify the Active release contains exactly one 596-1 root, seven sections and 67 field pages; verify unknown pages have no fake value/Evidence.
- [ ] Verify page 12 and page 27 citations against exact revision bytes and bbox overlays.
- [ ] Inject one member/taxonomy/CAS failure before activation and prove the previous Active release remains current and unblended.
- [ ] Prove taxonomy reparent changes navigation/redirect only, leaving entity, version, field, Evidence and citation identities unchanged.
- [ ] Freeze final commit/tree/path/test evidence before any push/PR/Ready/merge decision.

## Blocking gates and stopping conditions

- **B0 — OpenSpec:** no production file changes before OpenSpec120 is accepted.
- **B1 — Candidate:** no real Candidate means no release draft and no generic fallback.
- **B2 — Citation authority:** code now closes the non-self-issued join through WeKnora
  knowledge, immutable attempt-bound source/resource, parse attempt, file/document identity,
  chunk and manifest, plus the factory-sealed Candidate companion and canonical
  `normalized_0_1e6` page/bbox receipt. Live acceptance still requires a newly generated
  real Candidate and deployed/replayed source rows; a hand-built ID map is not acceptable.
- **B3 — Draft custody:** pre-review Candidate/manifest review remains Lane B dossier custody. The server exposes only a reviewed immutable `preparation_id`; if preserving that preparation requires a new DB/platform instead of the existing Release preparation boundary, stop and narrow the adapter.
- **B4 — Exact revision preview:** the immutable source reader, third signing ring,
  five-minute opaque token and UI exact authority/page/bbox gates are implemented. Bytes
  are fetched only by token and verified by SHA-256 before PDF open; current/latest/
  presigned/material/page-1 fallback cannot pass. This code checkpoint is not live UI
  acceptance because the new real Candidate/model run and authorized live release flow
  have not occurred.
- **B5 — UI bbox:** without approved `pdfjs-dist`, Vitest, `@vue/test-utils` and `happy-dom` (or existing exact equivalents), UI integration stops; page-only navigation or coordinate-only unit tests are insufficient.
- **B6 — Atomicity:** any design that needs a second Head, new release tables, member-by-member activation or partial publication is rejected.
- **B7 — Path ownership:** CLOSED for the provider-free immutable-citation checkpoint: all
  74 changed paths are in the approved lane matrix, the seven bounded frontend support
  paths or the narrow immutable-source/token paths. Any future unplanned path or cross-lane
  write conflict still stops that lane for a plan amendment.
- **B8 — Stable identities:** the initial medical domain/category/Ping An entity/version/taxonomy must come from Lane B's code-owned factory. Caller-selectable self-consistent identities are rejected.
- **B9 — Human review:** the named-human decision must bind the exact `SchemaWikiReviewBundleV1`; Candidate-only approval cannot activate a mutated manifest.
- **B10 — Live schema:** absence of deployed `wiki_release_*` tables is a deployment blocker, not authority to add a new migration or fall back to ordinary `wiki_pages`.
- **B11 — Historical residue:** the two brochure `running` subspans require an explicit runbook accept/cleanup decision before real activation; implementation tests must not mutate them.

## Completion definition

Code/tests passing is not the Goal terminal. The MVP is complete only when one real sealed Candidate for `596-1` is compiled, reviewed and atomically activated as the sole WeKnora Active Schema Release; the UI and Agent read the same pinned member digests; all 67 fields preserve tri-state semantics; formal citations replay exact revisions/pages/bboxes; and failure leaves the previous Active release intact. Until then, status remains implementation complete or blocked, never “Schema Wiki MVP complete.”

## Governance reconciliation at merged main

### Docs-only owner and phase SPEC

- `SPEC-1 / unique entry`: `AGENTS.md`, pointer-only `CLAUDE.md`, `README.md` and
  `openspec/changes/README.md`.
- `SPEC-2 / OpenSpec 120`: its proposal, normative spec, tasks and validation report.
- `SPEC-3 / OpenSpec 122`: its proposal, tasks and validation report; the existing
  normative spec is read-only because its Requirement text already reflects COMPLETE67.
- `SPEC-4 / contribution gate`: `.github/pull_request_template.md`.
- `SPEC-5 / plan custody`: this plan file only.

These thirteen paths are the complete docs-only owner set for this reconciliation. No
production, migration, test, fixture, workflow or live-state path is authorized.

`main@bee91696131efa3a3aa5ea1339557eaa68e63f0a` merges PR #121 with green CI. The
packaged migration boundary is official head 75 plus enterprise head 5; the reviewed
migration tree is `e8446dff` and route manifest is `ffa548b9`. Exact3 is code-closed as one
`REPEATABLE READ READ ONLY` preflight snapshot followed, only after PASS, by fresh-rechecked
strict serial sealing with partial-stop semantics.

Delivery is still blocked/not run: no immutable `bee91696` image/SBOM/OCI proof, no three
deployment public-key ID rings, no clone rehearsal/migration/backfill, and no real provider,
Candidate, Draft, review, publish or activation. Colima is stopped, which makes live current
state unknown; it is not evidence of application failure. OpenSpec 122 remains
`COMPLETE_67` (51 preserved + 16 reviewed unknown, exact75) but semantic quality stays
`INCONCLUSIVE` until a real official DeepSeek Candidate and formal Golden evaluation run.
