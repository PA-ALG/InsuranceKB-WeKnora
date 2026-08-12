# 120 · Schema Wiki Medical 596-1 MVP

## Goal

Compile one real, sealed Schema67 `Schema67CandidateV2` for product version `596-1`
into one deterministic medical-insurance `KnowledgeWikiReleaseV1`, persist the exact
payload-bearing draft in the existing Wiki Release preparation table, review that manifest
as one named-human batch, transition the same preparation to Ready, and serve only an
activated, release-pinned 1-root + 7-section + 67-field Schema Wiki.

If the sealed Candidate, trusted Evidence-to-revision join, reviewed preparation or
existing Active Head is unavailable, the system SHALL return a typed incomplete/not-active
state. It SHALL NOT convert, copy or fall back to the live generic material Wiki.

## Architecture boundaries

- **Lane A · public contracts and serving foundation** validates topology against the
  supplied validated `SchemaPackV1`, defines the non-circular citation/release contract,
  maps reviewed schema preparations to the existing Wiki Release service, and adds
  release-pinned schema reads under the existing dual ACL. It reuses the single existing
  Head, CAS activation, revert and pinning authority; it adds no release table or Head.
  The immutable-citation delta adds only an attempt-bound revision-source/resource record,
  an exact byte reader and a third, citation-token-only signing ring. Its exact3 dry-run
  uses one narrow read-only repeatable-read repository snapshot and safe digest/count
  receipts; actual sealing remains ordered, fresh-rechecked and partial-stop rather than
  pretending that three source rows are one atomic write.
- **Lane B · medical compiler** code-owns `medical-schema67.v1`, the initial medical
  domain/category, the stable Ping An eShengBao entity, product version `596-1`, the
  initial taxonomy, sealed-Candidate compilation, the factory-provenance-sealed Evidence
  companion, the review bundle and the exact cross-language release vector.
- **Lane C · UI and citations** consumes only frozen A/B DTOs, renders Active or reviewed
  preparation state, and opens token-only exact-revision PDF bytes after SHA-256 validation
  at the required page/bbox. It cannot mint review authority, use current/latest bytes or
  substitute page 1.

Integration order is A1 contracts -> B medical compiler -> A2 serving adapter -> C UI.
No lane may edit another lane's paths. Any physical path overlap, unlisted dependency
wiring, or need for a second authority is a mandatory STOP and plan amendment.

## Exact owner matrix

### Lane A only

- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_contracts.py`
- `harness/tests/test_schema_wiki_contracts.py`
- `internal/types/schema_wiki.go`
- `internal/types/schema_wiki_test.go`
- `internal/types/knowledge_revision.go`, `internal/types/knowledge_revision_test.go`,
  `internal/types/schema_wiki_citation_content_test.go`
- `internal/types/wiki_release.go` only to add the persisted Draft state used by the
  existing `wiki_release_preparations` model; no table or migration change.
- `internal/application/service/schema_wiki.go`
- `internal/application/service/schema_wiki_citation_revision.go`
- `internal/application/service/schema_wiki_citation_revision_test.go`
- `internal/application/service/schema_wiki_citation_content.go`
- `internal/application/service/schema_wiki_citation_content_test.go`
- `internal/application/service/schema_wiki_test.go`
- `internal/application/service/testdata/schema_wiki_contract_vector.json`
- `internal/config/config.go`
- `internal/config/schema_wiki_signing_test.go`
- `internal/config/schema_wiki_citation_token_signing_test.go`
- `internal/handler/schema_wiki.go`
- `internal/handler/schema_wiki_test.go`
- `internal/router/routes_schema_wiki.go`
- `internal/router/routes_schema_wiki_test.go`
- `internal/application/repository/wiki_release_scope_test.go`
- `internal/application/repository/wiki_release.go`
- `internal/application/service/wiki_release.go`
- `internal/container/container.go`
- `internal/container/schema_wiki_production_readiness_test.go`
- `internal/router/router.go`, the approved mechanical DI/direct-mount path that registers
  all 13 Schema Wiki routes in the real `/api/v1` router. The earlier expectation that
  `internal/router/routes_knowledge.go` would be the mount point is superseded by this
  existing direct registration; `routes_knowledge.go` remains unchanged and is not a
  missing reachability path.
- The narrow immutable-source/resource custody paths and
  `migrations/enterprise/versioned/000004_knowledge_revision_sources.{up,down}.sql` and
  `000005_knowledge_revision_source_binding.{up,down}.sql` listed in the approved plan;
  these do not add a Release table, Head or approval model.

### Lane B only

- `docs/superpowers/plans/2026-08-10-schema-wiki-mvp.md`, the four OpenSpec 120 documents
  and this registry row;
- `harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py`
- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py`
- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_candidate_evidence_join_596_1.py`
- `harness/tests/test_medical_schema_pack_596_1.py`
- `harness/tests/test_schema_wiki_candidate_evidence_authority_121.py`
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

### Integration support paths only

These paths are necessary mechanical support for the approved Lane C paths. They do not
replace, broaden or satisfy any approved Schema Wiki owner path by themselves:

- `frontend/src/components/schema-wiki/pdfJsPort.ts` provides the bounded PDF.js port used
  by the approved citation viewer.
- `frontend/src/components/sessionSidebarBuckets.ts`,
  `frontend/src/i18n/locales/{en-US.ts,ko-KR.ts,ru-RU.ts}`,
  `frontend/src/views/agent/AgentEditorModal.vue`, and
  `frontend/src/views/system/SystemSettings.vue` are the six exact typecheck/build hygiene
  paths required to make the integrated frontend verifiable. They do not change Schema
  Wiki routes, contracts, release semantics or authority.

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
- The Schema entry accepts the exact validated Lane B `KnowledgeWikiReleaseV1` together
  with its exact validated `SchemaWikiReviewBundleV1`; it never accepts a caller-built
  generic `WikiReleasePreparation`. It maps every member's actual canonical typed payload
  into the existing preparation row without reducing it to a descriptor or digest.
- Without a migration, the Schema Draft reuses `WikiReleasePreparation.Manifest` to store
  strict canonical bytes for `schema-wiki-preparation-custody.v1`. That closed envelope
  contains the complete `KnowledgeWikiReleaseV1` and exact `SchemaWikiReviewBundleV1`.
  `WikiReleasePreparation.ManifestDigest` hashes the custody-envelope bytes; it is a
  different digest domain from `KnowledgeWikiReleaseV1.ManifestDigest`, which continues to
  bind the release's ordered 75 members and citation bindings. Neither value may be
  substituted for the other.
- `WikiReleasePreparation.Manifest` and its stored member snapshots are PostgreSQL JSONB
  values. Create computes each authority digest from the exact canonical typed JSON bytes
  before persistence. Read never treats PostgreSQL's returned key order or whitespace as
  authority: it performs strict closed decode into the concrete custody/member DTO, rejects
  unknown fields and trailing JSON, canonical re-marshals the typed value, recomputes the
  digest, and only then verifies the envelope-to-snapshot join. JSONB-equivalent text is
  accepted only when that typed canonical replay is identical; value, type or self-hash
  drift fails closed. The Draft review CAS preserves the JSONB logical values and compares
  their explicit authority columns/digests; this requires no migration.
- The 75 stored member snapshots must be an exact ordered bijection with the envelope's
  release members: kind, logical ref, release revision, member digest and actual canonical
  payload bytes all match. Draft, Ready and Active reads load the preparation identified by
  `PreparationID`, replay the complete release/bundle/scope closure and reject any snapshot
  substitution before returning content. Citation reads accept only logical slug plus
  citation ID, select the citation from stored authority and require every selected
  `CitationTarget.SpaceID` to equal the exact release scope.
- `SchemaWikiReviewBundleV1` binds Candidate hash, release draft hash, manifest digest,
  ordered member digests, citation bindings and domain/taxonomy/schema/entity/version.
  The named-human receipt `HumanBatchHash` and the existing preparation
  `ReadyReceiptDigest` must equal this bundle hash. A reused decision or changed manifest
  fails closed.
- The same `wiki_release_preparations` row follows the closed state machine persisted
  Draft -> concrete named-human `ReviewDraft` -> Ready. Draft never enters current,
  pinned, Search or Agent serving; its exact member/revision preview is addressed only by
  `preparation_id`. Reject, partial, expired or invalid review leaves the exact Draft
  unchanged. Before named-human verification or transition, `ReviewDraft` reloads and
  replays the complete custody envelope, scope and exact ordered 75-snapshot bijection.
  The Draft -> Ready update is an exact compare-and-swap over scope,
  `preparation_id`, Draft status, the previously read `PreparationDigest`, Candidate,
  review-bundle, policy and custody-envelope manifest authority columns; concurrent content
  or identity drift returns a typed conflict with no state change. Ready still
  requires a separate publish authorization before the existing
  `ActivateReviewed` transaction may advance the sole Head. Activation and revert remain
  the existing whole-release operations.
- Schema Draft creation, exact Draft preview and `ReviewDraft` are human control-plane
  operations. They require an authenticated JWT principal with trusted tenant role Admin+
  and use the exact route order `DenyAPIKeyPrincipal -> Admin -> Wiki ACL/evidence -> scope
  resolution -> RAW ACL/evidence -> SealAccess -> handler`. The service repeats the
  fail-closed API-key denial and Admin+ check from trusted request context before any
  repository row lookup, verifier or preview-port call, including while tenant RBAC enforcement is
  disabled. Callers cannot submit role or permission fields. Active current/pinned/Search
  reads remain Viewer+ and may use the existing scoped API-key retrieve authority.
- The Lane C bootstrap is exactly
  `GET /api/v1/knowledgebase/:wiki_kb_id/wiki/schema-scope` and returns the closed
  `SchemaWikiScopeV1 {version, space_id, raw_kb_id, wiki_kb_id, scope_sha256}`. Every other
  UI read is below
  `/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema`:
  `/domains`, `/taxonomy/current`,
  `/entities/:entity_id/versions/:version_id/current`,
  `/releases/:release_id/{root|sections/:section_id|fields/:field_id}`,
  `/preparations/:preparation_id/{root|sections/:section_id|fields/:field_id}`, and
  `/releases/:release_id/fields/:field_id/citations/:citation_id/preview`. These paths and
  response scope fields are the exact Lane C contract; aliases such as a separate
  `/drafts` read surface are not authority.
- `/entities/:entity_id/versions/:version_id/current` returns exactly the closed
  `{version: 'schema-wiki-current-entity-version.v1', entity_id, entity_version_id,
  active_release_id, activation_epoch, root: SchemaRootPageV1}`. Its
  `active_release_id` and `activation_epoch` are the only trusted pin for subsequent
  `/releases/:release_id/...` reads. `SchemaWikiScopeV1` intentionally contains no release
  ID; callers may neither guess one nor substitute current/latest behavior.
- Active bootstrap and reads derive scope from the sole Head. Preparation review and
  preview derive it from the immutable preparation. Only the initial none/e0
  `POST .../schema/preparations`, when neither Head nor preparation exists, may bootstrap
  from the exact path scope. The request body cannot supply or override scope; the human
  JWT Admin+, Wiki then RAW ACL/evidence, seal and service-level no-conflicting-space/full-
  custody checks all run before persistence. If a Head exists, every path scope component
  must exactly match it. This is a bounded first-release bootstrap rule, not caller-issued
  scope authority.
- `internal/application/repository/wiki_release.go` and
  `internal/application/service/wiki_release.go` may receive only the narrow existing-row
  Draft persistence/atomic review-transition changes above. This Mission adds no table,
  migration, Head, CAS or parallel approval model.
- The production citation adapter may replay only the native knowledge, revision, chunk and
  manifest custody currently available from WeKnora. It returns typed unavailable and zero
  bytes after that replay because no immutable attempt-bound blob or canonical page/bbox
  coordinate-space authority exists; it never substitutes current/latest, presigned bytes
  or page 1.
- `internal/config/config.go` accepts distinct public Ed25519 key rings for the existing
  named-human and publish-authorization verifiers. It has no private-key field, rejects
  cross-ring key ID or material reuse, and excludes signing configuration/key bytes from
  JSON output. Empty configuration remains a safe reject-all deployment state.

## Fresh WeKnora preflight and stop conditions

The current external facts are tenant `10003`, RAW KB
`b1f1764c-443d-46b8-98e3-d5aa5e55eb42`, completed terms knowledge
`f987fc16-222a-4246-8ca0-22c1a81dd6d9` attempt 2, completed brochure knowledge
`1265a343-c408-4620-8eed-c4f6a2adadc2` attempt 1, and completed rate knowledge
`32402c40-6131-4049-8080-cc5b68188cd3` attempt 1. Their sealed hashes and manifests stay
in external custody and must enter a trusted revision/page/bbox join.

Implementation and real acceptance SHALL stop while any of these remains true:

- no successfully sealed `Schema67CandidateV2` exists;
- the native Evidence-to-WeKnora knowledge/source-revision/chunk/manifest join is replayed,
  but the immutable attempt-bound revision bytes plus canonical coordinate-space/page/bbox
  authority are not frozen; generic terms `source_refs` provenance is zero and cannot be
  guessed;
- the live database has no deployed `wiki_release_*` tables or a clean standard migration
  ledger; this Mission adds no migration and does not claim Draft/Head availability;
- the native replay adapter remains typed unavailable/zero bytes because the immutable
  revision-blob and page/bbox adapter is absent;
- the two historical brochure `running` subspans lack an explicit runbook policy;
- the UI bbox dependencies are not approved and locked.

The existing 46 live generic Wiki pages are material-only output and SHALL NOT be migrated
into Schema fields. The observed rate `pages_affected=14` is not total-page authority.

## Non-goals

No provider/model/Golden run, Candidate fabrication, generic Wiki migration, second Head,
new release schema, migration, partial activation, generic CMS/search platform, benefits
business content, page-1 fallback, current/latest preview substitution, live DB write or
WeKnora deployment is authorized by this change.

## Integrated delivery boundary at `main@bee91696`

The bounded repository implementation is merged. It packages official migration head 75
and enterprise head 5 (including `000005`), and its exact3 contract, Draft/preparation
token authority without an Active Head, Active Head/pin reads, immutable-source guards and
fallback prohibitions are code-complete. The reviewed integration identities record
migration tree `e8446dff` and route manifest `ffa548b9`.

This is not deployment acceptance. No immutable `bee91696` image, SBOM or OCI provenance
has been frozen; the three deployment public-key ID rings are absent; live Colima is
stopped, so current live state is unknown rather than failed. Clone rehearsal, migration,
backfill, provider/model execution, Candidate creation, Draft, review, publish and
activation are `NOT RUN`.
