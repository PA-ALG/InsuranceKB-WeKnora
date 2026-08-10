# 120 · Schema Wiki Medical 596-1 MVP

## Goal

Compile one real, sealed Schema67 `Schema67CandidateV2` for product version `596-1`
into one deterministic medical-insurance `KnowledgeWikiReleaseV1`, review the exact
manifest as one named-human batch, prepare it through the existing Wiki Release service,
and serve only an activated, release-pinned 1-root + 7-section + 67-field Schema Wiki.

If the sealed Candidate, trusted Evidence-to-revision join, reviewed preparation or
existing Active Head is unavailable, the system SHALL return a typed incomplete/not-active
state. It SHALL NOT convert, copy or fall back to the live generic material Wiki.

## Architecture boundaries

- **Lane A · public contracts and serving foundation** validates topology against the
  supplied validated `SchemaPackV1`, defines the non-circular citation/release contract,
  maps reviewed schema preparations to the existing Wiki Release service, and adds
  release-pinned schema reads under the existing dual ACL. It reuses the single existing
  Head, CAS activation, revert and pinning authority; it adds no release table or Head.
- **Lane B · medical compiler** code-owns `medical-schema67.v1`, the initial medical
  domain/category, the stable Ping An eShengBao entity, product version `596-1`, the
  initial taxonomy, sealed-Candidate compilation, the review bundle and the exact
  cross-language release vector.
- **Lane C · UI and citations** consumes only frozen A/B DTOs, renders Active or reviewed
  preparation state, and opens exact-revision PDF bytes at the required page/bbox. It
  cannot mint review authority, use current/latest bytes or substitute page 1.

Integration order is A1 contracts -> B medical compiler -> A2 serving adapter -> C UI.
No lane may edit another lane's paths. Any physical path overlap, unlisted dependency
wiring, or need for a second authority is a mandatory STOP and plan amendment.

## Exact owner matrix

### Lane A only

- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py`
- `harness/tests/test_schema_wiki_contracts.py`
- `internal/types/schema_wiki.go`
- `internal/types/schema_wiki_test.go`
- `internal/application/service/schema_wiki.go`
- `internal/application/service/schema_wiki_test.go`
- `internal/application/service/testdata/schema_wiki_contract_vector.json`
- `internal/handler/schema_wiki.go`
- `internal/handler/schema_wiki_test.go`
- `internal/router/routes_schema_wiki.go`
- `internal/router/routes_schema_wiki_test.go`
- `internal/application/repository/wiki_release_scope_test.go`
- `internal/router/routes_knowledge.go`
- `internal/application/repository/wiki_release.go`
- `internal/container/container.go`
- `internal/router/router.go`

### Lane B only

- the four OpenSpec 120 documents and this registry row;
- `harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py`
- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py`
- `harness/tests/test_medical_schema_pack_596_1.py`
- `harness/tests/test_schema_wiki_release_596_1.py`
- `internal/application/service/testdata/schema_wiki_release_596_1_vector.json`

### Lane C only

- `frontend/package.json`, `frontend/package-lock.json`,
  `frontend/src/router/index.ts`, `frontend/src/views/knowledge/KnowledgeBase.vue`,
  `frontend/src/i18n/locales/zh-CN.ts`, `frontend/src/i18n/locales/en-US.ts`;
- `frontend/src/api/schema-wiki/index.ts`;
- all new files under `frontend/src/views/knowledge/schema-wiki/` named in the approved
  plan, and `frontend/src/components/schema-wiki/{schemaCitationTarget.ts,
  schemaCitationTarget.test.ts,SchemaCitationViewer.vue,SchemaCitationViewer.test.ts}`.

## Frozen release and review model

- A shared Lane A validator derives the release topology from the supplied validated
  SchemaPack. Only Lane B's code-owned medical pack requires exactly 1 root, 7 ordered
  sections and the approved ordered 67 fields (16/15/6/11/9/5/5).
- `present` and `absent_explicitly` each require a value plus at least one replay-valid,
  revision-bound citation. `unknown` has no value and no citation and carries a pending
  ReviewItem; it is never converted into absent.
- A `CitationTargetV1` hashes source/replay identity and a logical member reference, not
  the final member digest. A release-level `CitationMemberBindingV1`, outside the member
  digest preimage, binds each citation hash to the final member digest. The release and
  manifest cover both sets, avoiding a circular hash equation.
- The entity-version root member contains the exact taxonomy snapshot, redirects and
  schema navigation/index metadata. The release still contains exactly 75 content members
  and pinned reads can reconstruct the same taxonomy as the field pages.
- `SchemaWikiReviewBundleV1` binds Candidate hash, release draft hash, manifest digest,
  ordered member digests, citation bindings and domain/taxonomy/schema/entity/version.
  The named-human receipt `HumanBatchHash` and the existing preparation
  `ReadyReceiptDigest` must equal this bundle hash. A reused decision or changed manifest
  fails closed.
- Before activation, HTTP reads use `preparation_id`, never a nonexistent draft
  `release_id`. Activation and revert remain the existing whole-release operations.

## Fresh WeKnora preflight and stop conditions

The current external facts are tenant `10003`, RAW KB
`b1f1764c-443d-46b8-98e3-d5aa5e55eb42`, completed terms knowledge
`f987fc16-222a-4246-8ca0-22c1a81dd6d9` attempt 2, completed brochure knowledge
`1265a343-c408-4620-8eed-c4f6a2adadc2` attempt 1, and completed rate knowledge
`32402c40-6131-4049-8080-cc5b68188cd3` attempt 1. Their sealed hashes and manifests stay
in external custody and must enter a trusted revision/page/bbox join.

Implementation and real acceptance SHALL stop while any of these remains true:

- no successfully sealed `Schema67CandidateV2` exists;
- the 057/ParsedDocument Evidence-to-WeKnora knowledge/source-revision/chunk/exact-revision
  bytes/page/bbox join is not frozen; generic terms `source_refs` provenance is zero and
  cannot be guessed;
- the live database has no deployed `wiki_release_*` tables or a clean standard migration
  ledger; this Mission adds no migration and does not claim Draft/Head availability;
- the exact-revision preview adapter is absent (A1 freezes only a fail-closed Port);
- the two historical brochure `running` subspans lack an explicit runbook policy;
- the UI bbox dependencies are not approved and locked.

The existing 46 live generic Wiki pages are material-only output and SHALL NOT be migrated
into Schema fields. The observed rate `pages_affected=14` is not total-page authority.

## Non-goals

No provider/model/Golden run, Candidate fabrication, generic Wiki migration, second Head,
new release schema, migration, partial activation, generic CMS/search platform, benefits
business content, page-1 fallback, current/latest preview substitution, live DB write or
WeKnora deployment is authorized by this change.
