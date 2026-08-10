# 120 · Implementation Tasks

## Task 0 · Governance and OpenSpec

- [x] Commit the approved implementation plan by itself.
- [x] Record the strict missing-change RED before creating this change.
- [x] Freeze the A/B/C exact owner matrix, integration order and path-overlap STOP.
- [x] Register OpenSpec 120 as `plan-approved / implementation-not-started`.
- [x] Run strict OpenSpec validation and diff-check; record the exact result.

## Task 1 · Lane A canonical contracts

- [x] TDD the shared Python/Go canonical Domain, SchemaPack, Entity/Version, Taxonomy,
  Citation, member, release and preparation contracts plus one cross-language vector.
- [x] Derive valid member topology from the supplied validated SchemaPack; do not hardcode
  medical 7/67 rules in shared validators.
- [x] Freeze the non-circular citation/member binding equation and the root-member taxonomy
  payload required by pinned reads.
- [x] Commit the A1 interface before Lane B production imports it.

## Task 2 · Lane B medical pack

- [x] RED caller-selected schema/domain/entity/version/taxonomy, wrong 7-section order,
  missing/extra/duplicate fields and any ordered67 drift.
- [x] GREEN the code-owned `medical-schema67.v1` pack, stable Ping An eShengBao entity,
  product version `596-1`, initial medical taxonomy and 16/15/6/11/9/5/5 mapping.

## Task 3 · Lane B sealed Candidate compiler

- [x] RED absent/duck/self-rehashed/legacy Candidate inputs and prove zero release output
  plus `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE` with no generic fallback.
- [x] RED every tri-state, Evidence/revision/page/bbox/hash drift, non-circular citation
  binding, 75-member completeness, root taxonomy payload and deterministic vector.
- [x] RED manifest mutation and reused named-human receipt; bind exact Candidate, release,
  manifest, members, citation bindings and schema/entity/taxonomy identities in
  `SchemaWikiReviewBundleV1`.
- [x] GREEN only after the Lane A A1 interface commit is mechanically consumed.

## Task 4 · Lane A existing-release serving adapter

- [ ] The exact Lane A owner matrix is explicitly extended to the existing
  `internal/types/wiki_release.go`, `internal/application/repository/wiki_release.go` and
  `internal/application/service/wiki_release.go` for this bounded state-machine delta.
  No new table, migration, Head or CAS path is permitted.
- [ ] RED a caller-built generic `WikiReleasePreparation`, descriptor-only member, foreign
  payload or self-rehashed release/review bundle. The Schema entry must accept the exact
  validated Lane B release plus review bundle, retain all 75 actual typed payloads and
  reject before any repository write.
- [ ] RED/GREEN persistence in the same `wiki_release_preparations` table: create an
  immutable Draft whose existing `Manifest` column contains strict canonical
  `schema-wiki-preparation-custody.v1` bytes with the complete B release and exact review
  bundle. Its storage `ManifestDigest` hashes that envelope and must not be confused with
  the inner B `release.ManifestDigest`. Keep Draft out of current/pinned/Search/Agent
  serving and allow only its exact `preparation_id` + member revision preview for review.
- [ ] RED/GREEN PostgreSQL JSONB replay: Create derives the manifest/member authority
  digests from canonical concrete DTO bytes before write. Read accepts key-order and
  whitespace-equivalent JSONB serialization only after strict closed concrete decode,
  trailing-data rejection, canonical re-marshal and digest/snapshot-join replay. Raw DB
  text bytes are never authority; unknown fields, trailing JSON, value/type drift and
  self-rehash fail before output or transition. Review CAS preserves the JSONB logical
  values and binds the existing explicit authority columns/digests, with no migration.
- [ ] RED/GREEN exact stored custody: all 75 snapshots must equal the envelope members in
  order, kind, logical ref, release revision, member digest and actual canonical payload
  bytes. Descriptor-only, generic, snapshot reorder/substitution, inner-release manifest
  versus storage-envelope manifest substitution, unknown/noncanonical envelope and
  self-rehash attacks fail before persistence or output.
- [ ] RED/GREEN the Draft control-plane authorization boundary. CreateDraft, exact Draft
  preview and ReviewDraft must run only for a human JWT Admin+ through
  `DenyAPIKeyPrincipal -> g.Admin -> Wiki ACL/evidence -> scope resolution -> RAW
  ACL/evidence -> SealAccess -> handler`; the service must independently reject an API-key
  context and require trusted `TenantRole` Admin+ before any repository row lookup,
  verifier or preview-port
  access even when RBAC enforcement is disabled. API key, missing role, Viewer,
  Contributor, caller-supplied role/permission and Wiki-only/RAW-denied attacks must leave
  handler/repository/verifier/port calls at zero. Active current/pinned/Search reads remain
  Viewer+ and retain existing scoped API-key retrieve behavior.
- [ ] RED/GREEN `ReviewDraft`: parse and verify the concrete named-human receipt exactly
  once before state change, but only after reloading and replaying the complete custody
  envelope, exact scope and ordered 75-snapshot bijection; require approve, current
  principal/scope, time/signature,
  Candidate/policy and `HumanBatchHash == ReadyReceiptDigest == review_bundle_sha256`;
  atomically transition that same row Draft -> Ready with a compare-and-swap over exact
  scope, `preparation_id`, Draft status, old `PreparationDigest`, Candidate digest, review
  bundle digest, policy ID and custody-envelope `ManifestDigest`. Concurrent drift of any
  authority must return a typed conflict and perform no update. Reject, partial, expired,
  foreign or reused receipt leaves the Draft byte-identical and non-serving.
- [ ] RED/GREEN a Ready preparation still cannot activate without a separate exact publish
  authorization. Only existing `ActivateReviewed` may perform release/member/receipt/Head
  CAS; an unreviewed Draft or CAS failure leaves the previous Head and pins complete.
- [ ] TDD `GetHeadForWikiKB`, unique scope bootstrap, exact Wiki then derived RAW ACL, and
  distinct Draft/Ready/current/pinned reads with no client-overridable scope or generic
  fallback.
- [ ] RED/GREEN the exact Lane C route contract. Bootstrap returns closed
  `SchemaWikiScopeV1 {version, space_id, raw_kb_id, wiki_kb_id, scope_sha256}` from
  `GET /knowledgebase/:wiki_kb_id/wiki/schema-scope`; the scoped base exposes exact
  domains, taxonomy/current, entity-version/current, release root/section/field,
  preparation root/section/field and release field/citation preview paths. Reject route
  aliases, omitted/extra scope fields and any client body scope override.
- [ ] RED/GREEN current entity-version pinning: the exact current endpoint returns only
  `{version: 'schema-wiki-current-entity-version.v1', entity_id, entity_version_id,
  active_release_id, activation_epoch, root: SchemaRootPageV1}`. Release reads must use
  that exact release/epoch pair; entity path, version path, release ID or epoch drift and
  guessed/current/latest fallback fail before member output.
- [ ] RED/GREEN scope lifecycle. Active reads derive scope from the sole Head; preparation
  review/preview derive it from the immutable preparation. The first none/e0 CreateDraft
  may use only its exact path scope because no Head/row exists, after human JWT Admin+,
  Wiki then RAW ACL/evidence, seal and service no-conflicting-space/full-custody checks.
  Once a Head exists, any path mismatch fails before service state change or output.
- [ ] RED/GREEN every Draft/Ready/Active member or citation read: follow exact
  `PreparationID`, replay the complete stored release + bundle + 75-snapshot bijection +
  scope, and select citation authority only by logical slug and citation ID from immutable
  storage. Caller-supplied CitationTarget/binding, foreign `SpaceID`, current/latest
  substitution and partial-envelope reads fail before preview-port or content output.
- [ ] Reuse the single existing Wiki Release Head, CAS, activation, revert and pinning
  transaction; failed preparation/member/receipt/CAS leaves the prior Active intact.
- [ ] Freeze `CitationRevisionReadPort` and typed failures. Do not claim exact-revision
  preview GREEN until a concrete trusted adapter and wiring are separately frozen.
- [ ] Vet types, repository, service, handler and router packages.

## Task 5 · Lane C release-pinned UI

- [ ] TDD pure DTO/navigation/citation reducers, no-Active/no-Candidate typed states, exact
  7/67 medical rendering, tri-state fail-closed behavior and no generic fallback.
- [ ] Use Vitest with the existing Vue plugin and happy-dom for the production SFC test;
  keep pure TypeScript tests separate.
- [ ] Consume only the frozen A/B API and exact revision/page/bbox contract; never use
  current/latest bytes or page 1 as fallback.

## Task 6 · Integration and external stop gates

- [ ] Integrate A1 -> B -> A2 -> C without shared-path writes and run only the approved
  focused/bounded commands.
- [ ] Recheck the exact three completed knowledge identities and external hash/manifest
  custody; do not interpret `pages_affected=14` as total pages.
- [ ] Stop real prepare/activation until a sealed Candidate, trusted revision/page/bbox
  join, exact preview adapter, approved UI dependencies, deployed standard release tables
  and clean migration ledger exist.
- [ ] Define the brochure historical-running-subspan policy before a live run; do not
  mutate those runs in this Mission.
- [ ] Keep the 46 generic material Wiki pages isolated from Schema members.

## Global stop conditions

- Any lane touches another lane's listed path or requires an unlisted owner path.
- Candidate, Evidence, revision, schema, entity, taxonomy, manifest or review authority
  would need to be guessed or caller self-issued.
- A second Head/CAS/release model, generic fallback, partial activation, migration,
  provider, Golden, live DB write or current/latest citation substitution would be needed.
