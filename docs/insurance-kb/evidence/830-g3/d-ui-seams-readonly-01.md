# G3 D UI/service seams — read-only preparation

Status: `READ_ONLY_PREPARATION`; no implementation authority and no code/runtime/provider effects.
Reviewed `lane-d-consolidated-contract-v2.md` at current byte SHA-256
`75c81f582b2ace94efba6d016f0d24c00eb3e10a836f6673612bb7aaa3bfb94d`.

## Existing seams that can be reused

1. **Frozen Catalog and Profile authority.**
   `frontend/src/api/schema-wiki/schemaPackCatalog830G3.ts` already performs scope
   bootstrap, sealed scoped GET, exact-key/NFC/full nested hash validation, fixed
   wire/content/id/version anchoring, and exposes each entry's ordered Profile
   sections. `SchemaPackCatalog830G3.vue` already renders the same Profile
   structure. D should consume this validated object to match overview
   `schema_pack_*` and `profile_*` identities and section/field ordering; it
   should not add a second Profile source or duplicate the 801 field definitions.

2. **G2 Candidate, Draft/Ready, and immutable member storage.**
   `types.CanonicalConceptCandidateBundle830G2`,
   `ConceptCandidateBundle830G2.SnapshotMembers`, and
   `validateConceptPreparation830G2` already provide the exact inner G2
   PageMember/FieldAssertion/definition/free-page semantics. `WikiReleasePreparation`
   already stores the immutable canonical Manifest and Members in both DRAFT and
   READY. `CreateConceptFreeWikiDraft830G2` shows the reusable pattern for
   `CandidateDigest`, reviewer raw receipt, policy binding, expected Head, and
   `createDraftAtExpectedHead`. There is no existing G2 whole-bundle browser GET
   or whole-batch review Vue to reuse directly; D needs the one contract-frozen
   batch preparation read described below rather than exposing the stored outer
   Candidate to the browser.

3. **Immutable preparation read pattern.**
   `LoadPreparationEntityPageGraph830G1` and
   `ReadSchemaPreparationMember` demonstrate the correct repository lookup:
   try `GetDraftPreparation`, then `GetReadyPreparation`, retain the actual
   status, require human Admin plus sealed dual-KB scope, and fully revalidate
   the stored immutable preparation. Frontend `entityPageGraph830G1.ts` supplies
   the matching preparation-scope bootstrap
   `/knowledgebase/:wiki/wiki/preparations/:preparation/schema-scope` and exact
   mutual exclusion of `release_id` and `preparation_id`. D can reuse that
   control flow, but its response must be the exact
   `batch-concept-preparation-read.830.g3.v1` DTO and its validator must be G3;
   the existing schema/G1 DTOs are not wire compatible.

4. **Active directory and pinned reads.**
   `loadConceptDirectory830G2` already implements the required sequence:
   scope bootstrap, generic `/current`, then the exact returned release at
   `/releases/:release_id/search?q=`, followed by pinned concept-page reads.
   The generic routes are already mounted in `routes_knowledge.go`; D needs no
   second current/search endpoint. `conceptDirectory830G2.ts` strictly parses
   G2/G1/legacy snapshots, so a G3 overview payload must be dispatched and
   validated in the new G3 API module before the existing Vue receives G3 data.

5. **Entity directory, FieldAssertion, and Profile rendering.**
   `ConceptDirectory830G2.vue` is the smallest existing entity-card shell and
   pinned page link builder. `ConceptFreeWiki830G2.vue` is the smallest existing
   field/free-page shell. Its API parser already checks exact G2
   FieldAssertion state/value/unknown/evidence plus `conditions`, `exceptions`,
   `valid_time`, owner/version and source scope; the current Vue only surfaces
   title/content/state and therefore needs the G3 display additions. The G3
   `entity-directory-entry.830.g3.v1` overview supplies formal name,
   classification, pack/Profile identity, quality/release status, and ordered
   sections; the new parser must prove each section field uniquely resolves to
   a same-owner field assertion and that the union equals the Profile exactly.

6. **Source navigation.**
   For Active pages, `conceptCitationTransport830G2`,
   `ConceptCitationViewer830G2.vue`, the PDF byte-hash check, and the existing
   sealed citation-content endpoint are the renderer/transport to reuse after
   the Go authority dispatch accepts a G3 outer candidate hash. Preparation
   pages must only show their frozen quote/page and the text “激活后可打开原件”;
   they must not call the Active preview/token transport. The G1 preparation
   citation implementation is therefore only a query/scope pattern, not the D
   source-opening behavior.

## Minimal future write-domain candidates

These are candidates from the consolidated contract, not authorization to edit:

- Harness/contract: new
  `harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py`.
- Go DTO: new `internal/types/concept_free_wiki_830_g3.go`.
- Go service: new `internal/application/service/concept_free_wiki_830_g3.go`;
  bounded contract dispatch in
  `internal/application/service/concept_free_wiki_830_g2.go`,
  `concept_source_authority_830_g2.go`, and `wiki_release.go`.
- Go HTTP: `internal/handler/schema_wiki.go` for the exact create variant and
  preparation-read handler; `internal/router/routes_schema_wiki.go` for the
  human-only sealed
  `GET .../schema/preparations/:preparation_id/batch-concept`. Active
  `/current`, `/search`, and `/activations` remain the existing generic routes.
- Frontend: new `frontend/src/api/schema-wiki/batchConcept830G3.ts` plus bounded
  G3 modes in `SchemaWikiCatalogEntry830G2.vue`, `ConceptDirectory830G2.vue`,
  and `ConceptFreeWiki830G2.vue`. Existing router name `conceptPage830G2` can
  carry either the exact `release_id` or exact `preparation_id`; no router or
  `KnowledgeBase.vue` change is required by the current route shape.
- If active page parsing cannot be wholly contained in `batchConcept830G3.ts`,
  the only additional frontend candidate is a narrow dispatcher in
  `conceptFreeWiki830G2.ts`; its G2 parser and wire remain unchanged. There is
  no reason to edit `conceptDirectory830G2.ts` if the new module owns G3
  current/search parsing and supplies the G3 view model.

## Exact dependencies that must close before handler/service/UI work

1. Freeze the Python strict outer DTO/builder/projector/composer and the
   canonical positive actual-base fixture: two medical MATCH plus critical
   illness/endowment/accident CREATE, exactly 342 FieldAssertions. It must
   include Catalog and confirmation, exact C inputs and resolution, bindings,
   two unknown-key alignments, old 134-field input, 132 exact carry fields,
   model delta raw, final logical raw, review raw, sources/base closure, and the
   four-key page manifest.
2. Freeze the Go mirror in `concept_free_wiki_830_g3.go`, including strict
   exact-key/null/NFC/duplicate/float rejection, all nested hash recomputation,
   G2 inner validation, G3 snapshot projection, overview directory DTO, and
   cross-language equality with the Python fixture. Handler cannot safely
   select a variant or service/UI safely consume snapshots before this wire is
   fixed.
3. Using those real serializers, measure the complete canonical create POST
   containing `preparation_id + batch_concept_candidate_bundle`. The current
   gate is `maxSchemaWikiRequestBytes = 8 << 20` in `schema_wiki.go`. Save total
   bytes, component byte counts, and all input SHA values. Only the actual 342
   vector is positive capacity evidence; 275 and the withdrawn 344 shape are
   invalid substitutes. If it exceeds 8 MiB, D remains BLOCKED and none of the
   handler/service/UI candidates above should be implemented.

## Concrete compatibility limits

- Existing `decodeSchemaWikiCreateDraftRequest` only recognizes exact
  `preparation_id + concept_candidate_bundle` for G2; G3 requires the separate
  exact key `batch_concept_candidate_bundle`. Adding G3 fields to the G2 raw
  bundle will be rejected by strict G2 validation.
- Existing schema preparation root/section/field handlers validate legacy
  schema manifests; they are not a substitute for the new G3 batch preparation
  GET. The new GET returns the manifest once, supports DRAFT and READY, and does
  not repeat entities or Catalog outside the overview projections.
- `readConceptPage830G2` only accepts `current`/`pinned` and the G2 read
  contract. Preparation and G3 modes require explicit dispatch; a caller must
  never be allowed to provide both release and preparation identity.
- The entry component currently ignores `route.query.preparation_id` and always
  loads Catalog plus Active directory in parallel. Its G3 branch must instead
  use preparation-scope bootstrap and the immutable preparation GET, display
  DRAFT as “待审核” and READY as “已审核但未发布”, and keep that preparation out
  of generic current/search.

No runtime, provider, database, HTTP, build, or product-file action was run for
this report.
