# Schema Wiki Medical 596-1 MVP Specification

## ADDED Requirements

### Requirement: SWM1 only a concrete sealed Candidate may compile

The compiler SHALL accept only the public concrete, freshly replayed
`Schema67CandidateV2` for product version `596-1`. It SHALL reject duck objects,
self-rehashed payloads, legacy Candidate types, reports and field subsets. If the Candidate
does not exist or fails replay, it SHALL return `SCHEMA_WIKI_COMPILATION_NOT_COMPLETE`,
produce no member, manifest, review bundle or preparation, and SHALL NOT fall back to the
generic material Wiki.

#### Scenario: Candidate is absent

- **WHEN** compilation is requested without the concrete sealed Candidate
- **THEN** zero Schema Wiki output exists and the typed incomplete state is returned

### Requirement: SWM2 the medical pack and initial entity hierarchy are code-owned

Lane B SHALL provide one code-owned `medical-schema67.v1` pack containing exactly seven
ordered sections with 16, 15, 6, 11, 9, 5 and 5 fields and an exact ordered67 bijection.
It SHALL also code-own the initial medical domain/category, stable Ping An eShengBao entity,
product version `596-1` and initial taxonomy. Shared Lane A validators SHALL validate member
topology against the supplied validated SchemaPack rather than hardcode medical counts.

#### Scenario: caller substitutes a self-consistent taxonomy

- **WHEN** the caller changes the entity, version, domain or initial taxonomy and recomputes
  dependent hashes
- **THEN** medical release compilation fails before any member exists

### Requirement: SWM3 every field preserves exact tri-state semantics

Every `present` field and every `absent_explicitly` field SHALL carry a value and at least
one replay-valid, revision-bound citation. Every `unknown` field SHALL carry no value and no
citation and SHALL retain a pending ReviewItem. Missing material SHALL remain unknown; only
explicit, replayable Evidence may authorize absent.

#### Scenario: unknown carries an inferred value

- **WHEN** an unknown field carries a value or citation
- **THEN** the complete release fails closed and no partial member set is emitted

### Requirement: SWM4 citation and member custody are non-circular and exact

`CitationTargetV1` SHALL bind the exact source-revision, parse/document/manifest, page,
locator, bbox, quote/content digest and logical member reference without including the
final member digest in its hash preimage. The member SHALL contain the citation hash. A
release-level `CitationMemberBindingV1`, outside that member's digest preimage, SHALL map
the citation hash to the final member digest, and the release manifest SHALL cover both.
Missing, current/latest, page-zero, page-one-fallback, invalid bbox, foreign revision or
hash-drift inputs SHALL fail closed.

#### Scenario: final member binding is mutated

- **WHEN** either a citation identity or its release-level final member binding changes
- **THEN** manifest/release replay rejects the entire draft

### Requirement: SWM5 the medical draft is complete and pinned-serving capable

The medical release SHALL contain exactly 75 content members: one entity-version root,
seven ordered section members and 67 ordered field members. The root member SHALL contain
the exact `TaxonomySnapshotV1`, redirects and schema navigation/index metadata so a pinned
release read can reconstruct the same navigation and fields. Generic material Wiki members
SHALL be rejected.

#### Scenario: root taxonomy payload drifts

- **WHEN** the root member taxonomy differs from the release/schema/taxonomy identities
- **THEN** preparation fails and the prior Active release remains unchanged

### Requirement: SWM6 named-human review is bound to the exact manifest

Lane B SHALL create `SchemaWikiReviewBundleV1` whose hash covers Candidate hash, release
draft hash, manifest digest, ordered member digests, citation bindings and exact
domain/taxonomy/schema/entity/version identities. The named-human receipt `HumanBatchHash`
and the existing `WikiReleasePreparation.ReadyReceiptDigest` SHALL equal that exact bundle
hash. The Schema entry SHALL accept the exact validated Lane B release and review bundle,
not a caller-created generic preparation, and SHALL retain every member's actual canonical
typed payload. A decision from another manifest SHALL never authorize preparation.

The persisted Schema preparation SHALL additionally contain a strict canonical
`schema-wiki-preparation-custody.v1` envelope with the complete
`KnowledgeWikiReleaseV1` and exact `SchemaWikiReviewBundleV1`. The existing preparation
`ManifestDigest` SHALL hash those envelope bytes. The inner
`KnowledgeWikiReleaseV1.ManifestDigest` SHALL retain its release-member/citation meaning;
the two digest domains SHALL be independently recomputed and SHALL NOT be interchanged.

The existing preparation `Manifest` and stored member snapshots SHALL be persisted as
PostgreSQL JSONB logical values. Create SHALL derive their authority digests from exact
canonical typed JSON bytes before persistence. Read SHALL NOT compare or trust the raw text
serialization returned by PostgreSQL. It SHALL strict closed-decode into the concrete
custody/member DTO, reject unknown fields and trailing JSON, canonical re-marshal the typed
value, recompute its digest, and then verify the exact envelope-to-snapshot join. A change
limited to JSONB key order or insignificant whitespace SHALL remain equivalent after this
typed canonical replay; a value, type, unknown-field, trailing-data or self-hash drift SHALL
fail closed. Draft review CAS SHALL preserve these JSONB logical values while comparing the
existing explicit authority columns and digests. This SHALL require no migration.

#### Scenario: a decision is reused after one member changes

- **WHEN** any member, citation binding or manifest digest changes after review
- **THEN** preparation fails before the existing Wiki Release transaction starts

#### Scenario: caller supplies a generic preparation

- **WHEN** a caller supplies a self-consistent generic preparation or only member
  descriptors/digests instead of the validated Lane B release and review bundle
- **THEN** the request fails before a Draft row or partial member output exists

#### Scenario: storage envelope and release manifest digests are substituted

- **WHEN** either digest is copied into the other's field or either canonical preimage is
  changed and self-rehashed
- **THEN** Schema preparation fails before persistence, review or member output

#### Scenario: PostgreSQL returns an equivalent JSONB serialization

- **WHEN** stored custody or member JSON differs only in object-key order or insignificant
  whitespace
- **THEN** strict concrete decode and canonical re-marshal reproduce the original authority
  digest and the snapshot join succeeds without trusting the returned text bytes

#### Scenario: stored JSONB authority drifts

- **WHEN** stored custody or member JSON contains an unknown field, trailing JSON, changed
  typed value or a recomputed self-issued hash
- **THEN** canonical replay fails before Draft preview, review transition or Active output

### Requirement: SWM7 activation and reads use the single existing release authority

The implementation SHALL persist the immutable payload-bearing Draft in the existing
`wiki_release_preparations` table. The same row SHALL transition Draft to Ready only after
`ReviewDraft` reloads and replays the complete custody envelope, exact scope and ordered
75-snapshot bijection, then parses and verifies one concrete named-human approval before
any state change. The atomic transition SHALL compare exact scope, `preparation_id`, Draft status,
the previously read `PreparationDigest`, Candidate digest, review-bundle digest, policy ID
and custody-envelope `ManifestDigest`; concurrent authority drift SHALL return a typed
conflict without changing the row. Reject, partial, expired or invalid review SHALL leave
that Draft unchanged. Draft
SHALL never enter current, pinned, Search or Agent serving; review preview SHALL use exact
`preparation_id` and member revision identity. Ready SHALL still require a separate publish
authorization, and only the existing `ActivateReviewed`, Head CAS, revert and pinned-read
authority may activate it. The implementation SHALL add no second Head, CAS, release table
or migration and SHALL never activate a partial member set. No Active release SHALL return
`NO_SCHEMA_WIKI_ACTIVE_RELEASE` with no generic fallback.

Production verification SHALL wire the existing named-human and publish-authorization
verifiers from distinct strict Ed25519 public-key rings. The application configuration
SHALL expose no private-key field, SHALL reject malformed, duplicate or cross-ring reused
key IDs/material, and SHALL exclude the complete signing configuration and key bytes from
JSON output. Empty configuration SHALL remain a reject-all state rather than an implicit
development signer.

CreateDraft, exact Draft preview and ReviewDraft SHALL be human JWT control-plane
operations restricted to a trusted tenant role of Admin or Owner. Their route middleware
order SHALL be `DenyAPIKeyPrincipal`, `Admin`, Wiki ACL/evidence, scope resolution, derived
RAW ACL/evidence, `SealAccess`, then handler. Their service entrypoints SHALL independently
reject API-key context and require trusted-context Admin+ before any repository row lookup,
verifier or preview-port call, even when tenant RBAC enforcement is disabled. No caller-supplied role or
permission field is authority. Active current/pinned/Search reads SHALL remain Viewer+ and
MAY retain the existing scoped API-key retrieve authority.

Every Draft, Ready and Active Schema read SHALL follow the stored `PreparationID`, decode
the strict custody envelope, replay the complete release and review bundle, and require an
exact ordered bijection between all 75 release members and stored snapshots including
canonical payload bytes. Citation preview SHALL accept only logical slug and citation ID,
derive the `CitationTargetV1` and binding from the replayed member authority, and require
each `CitationTargetV1.SpaceID` to equal the exact release scope before invoking the preview
port. Generic, partial, foreign-scope or caller-supplied citation authority SHALL fail
closed.

#### Scenario: one new member fails before CAS

- **WHEN** any member, taxonomy, receipt or CAS validation for a new release fails
- **THEN** the existing Active Head and every existing pin remain unchanged

#### Scenario: review fails before Draft to Ready

- **WHEN** named-human verification rejects, expires or partially decides the exact bundle
- **THEN** the persisted Draft remains byte-identical, non-serving and in Draft state

#### Scenario: Draft changes between verification read and transition

- **WHEN** the stored Draft `PreparationDigest` differs from the exact digest read and
  verified by ReviewDraft
- **THEN** the compare-and-swap returns a typed conflict and changes no status or digest

#### Scenario: Ready lacks separate publish authorization

- **WHEN** a reviewed Ready preparation is presented without the exact publish authorization
- **THEN** `ActivateReviewed` does not run and the existing Head remains unchanged

#### Scenario: one signer is reused across approval domains

- **WHEN** the same key ID or public-key bytes are configured for named-human review and
  publish authorization, or signing configuration is serialized through the application
  config object
- **THEN** configuration validation rejects the reuse and no key bytes appear in JSON

#### Scenario: machine principal or insufficient human role reaches Draft control plane

- **WHEN** an API-key principal, missing trusted role, Viewer or Contributor requests
  CreateDraft, exact Draft preview or ReviewDraft, including while RBAC is disabled
- **THEN** the request is rejected before handler state change and before any repository
  row lookup, named-human verifier or preview-port call; preview reveals no row existence

#### Scenario: Active read uses existing retrieve authority

- **WHEN** a Viewer+ JWT principal or correctly scoped API-key principal reads current,
  pinned or Search Schema members
- **THEN** the existing dual-ACL/pin checks apply without granting any Draft operation

#### Scenario: stored member or citation drifts from custody envelope

- **WHEN** any snapshot byte/digest/order/revision or citation `SpaceID` differs from the
  complete release selected through the stored `PreparationID`
- **THEN** the read returns a typed failure before member bytes or citation preview output

### Requirement: SWM8 scope bootstrap enforces derived RAW and Wiki ACL

The Lane C bootstrap route SHALL be exactly
`GET /api/v1/knowledgebase/:wiki_kb_id/wiki/schema-scope`. Its response SHALL be the closed
`SchemaWikiScopeV1` object with exactly `version`, `space_id`, `raw_kb_id`, `wiki_kb_id` and
`scope_sha256`. Every Lane C read after bootstrap SHALL use the exact scoped base
`/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema`
and only these read suffixes:

- `/domains`;
- `/taxonomy/current`;
- `/entities/:entity_id/versions/:version_id/current`;
- `/releases/:release_id/root`, `/sections/:section_id` and `/fields/:field_id`;
- `/preparations/:preparation_id/root`, `/sections/:section_id` and
  `/fields/:field_id`; and
- `/releases/:release_id/fields/:field_id/citations/:citation_id/preview`.

`GET .../entities/:entity_id/versions/:version_id/current` SHALL return exactly the closed
`SchemaWikiCurrentEntityVersionV1` payload
`{version: 'schema-wiki-current-entity-version.v1', entity_id, entity_version_id,
active_release_id, activation_epoch, root: SchemaRootPageV1}`. Its exact
`active_release_id` and `activation_epoch` SHALL be the sole trusted pin for all following
`/releases/:release_id/...` reads. `SchemaWikiScopeV1` SHALL contain no release identity.
A caller-supplied, guessed, current/latest or independently refreshed release ID SHALL NOT
replace the pin.

Active bootstrap and reads SHALL resolve exactly one release scope from the sole authorized
Head. Preparation review and preview SHALL derive the same authority from the immutable
preparation. Those derived values SHALL inject non-overridable space and RAW KB route
parameters, authorize the derived RAW KB using the existing `KBAccessRead` middleware and
recorded ACL evidence, and only then seal the existing dual ACL context. Active-read
Human/JWT and scoped API-key principals SHALL follow the same Wiki/RAW ACL and seal checks.
Draft control-plane routes SHALL additionally apply the human JWT Admin+ boundary defined
in SWM7. Cross-tenant, zero, multiple, Wiki-only or RAW-denied scopes SHALL reveal no schema
scope.

The sole bootstrap exception SHALL be the initial none/e0
`POST .../schema/preparations`, for which no Head or preparation row yet exists. It MAY use
the exact `space_id`, `raw_kb_id` and `wiki_kb_id` from the URL path only; no request body
field may supply or override them. Human JWT Admin+, Wiki then RAW ACL/evidence, `SealAccess`
and the service's no-conflicting-space and full-custody validation SHALL all complete before
the first row is written. When a Head exists, every path scope component SHALL exactly equal
the Head-derived scope. This exception SHALL NOT be treated as a caller-signed scope.

#### Scenario: principal may read Wiki but not the derived RAW KB

- **WHEN** the bootstrap resolves a RAW KB for which the principal lacks read access
- **THEN** no `SchemaWikiScopeV1`, release seal or member data is returned

#### Scenario: first preparation is created before any Head exists

- **WHEN** a human JWT Admin+ submits the initial none/e0 preparation using an exact path
  scope and the body omits scope authority
- **THEN** Wiki and RAW ACL/evidence, seal, no-conflicting-space and complete custody checks
  authorize that one bootstrap before persistence

#### Scenario: caller overrides or conflicts with scope

- **WHEN** a body supplies scope authority, a preparation-derived scope differs from the
  path, or an existing Head differs from any path component
- **THEN** the request fails before repository state change, member output or scope data

#### Scenario: current entity-version pin drifts

- **WHEN** the current response entity/version differs from the requested path, or a
  subsequent release member request changes `active_release_id` or `activation_epoch`
- **THEN** the read fails before root, section, field or citation output and does not retry
  against current/latest

#### Scenario: caller guesses a release without a current pin

- **WHEN** a caller constructs `/releases/:release_id/...` from scope alone or supplies an
  arbitrary release ID without the closed current entity-version response
- **THEN** no release member or citation preview is returned

### Requirement: SWM9 exact revision preview remains fail closed until authority exists

Lane A SHALL freeze a `CitationRevisionReadPort`, typed preview errors and a production
native replay adapter. That adapter SHALL replay only server-derived tenant/scope,
knowledge, source revision/parse attempt, file/document identity, chunk membership and the
recomputed revision manifest. It SHALL return typed unavailable and zero bytes after that
replay while immutable attempt-bound blob and canonical coordinate-space/page/bbox
authority are absent. It SHALL NOT use current/latest, presigned bytes or page 1, and SHALL
NOT claim real exact-revision preview acceptance until the remaining authority is proven.

#### Scenario: native custody replays but immutable preview authority is unavailable

- **WHEN** native knowledge/revision/chunk/manifest custody replays successfully but no
  immutable attempt-bound blob or canonical coordinate-space/page/bbox authority exists
- **THEN** a typed unavailable result is returned and no document is opened

### Requirement: SWM10 live acceptance obeys external stop gates

Real prepare/activation SHALL remain blocked until the exact three completed knowledge
identities and sealed hashes/manifests are revalidated, a sealed Candidate exists, the
trusted revision/page/bbox join and exact preview adapter exist, the standard release
tables are deployed with a clean migration ledger, UI dependencies are approved, and the
two historical brochure running subspans have an accepted runbook policy. The existing 46
generic Wiki pages and rate `pages_affected=14` SHALL NOT be treated as Schema authority.

#### Scenario: release tables are absent in live WeKnora

- **WHEN** the live preflight finds no deployed `wiki_release_*` tables
- **THEN** implementation tests may continue offline but real preparation and activation
  remain blocked without creating a Mission-local migration

### Requirement: SWM11 lane ownership is closed world

Each lane SHALL write only its exact approved owner paths and integrate in the order A1
contracts, B compiler, A2 serving, C UI. A shared-path collision, unlisted wiring path,
provider/Golden/live DB requirement or second authority SHALL stop implementation until the
plan and this change are explicitly amended. Lane A is explicitly authorized to make the
bounded existing-row state-machine changes in `internal/types/wiki_release.go`,
`internal/application/repository/wiki_release.go` and
`internal/application/service/wiki_release.go`; this authorization does not permit a new
table, migration, Head, CAS or approval model.

The production-readiness amendment additionally authorizes only
`internal/application/service/schema_wiki_citation_revision.go`, its focused test,
`internal/config/config.go`, `internal/config/schema_wiki_signing_test.go` and
`internal/container/schema_wiki_production_readiness_test.go`. These paths may implement
native citation replay, distinct public-key verifier wiring and JSON redaction only; they
SHALL NOT add immutable blob inference, a second approval model, private signing keys,
current/latest fallback or a platform-wide key service.

The actual backend DI/mount authority is `internal/router/router.go`, whose `NewRouter`
path registers the 13 Schema Wiki routes directly. `internal/router/routes_knowledge.go`
is not a missing mount and remains unchanged. The bounded integration-support paths are
`frontend/src/components/schema-wiki/pdfJsPort.ts`,
`frontend/src/components/sessionSidebarBuckets.ts`,
`frontend/src/i18n/locales/{en-US.ts,ko-KR.ts,ru-RU.ts}`,
`frontend/src/views/agent/AgentEditorModal.vue` and
`frontend/src/views/system/SystemSettings.vue`; they support the approved citation viewer
and whole-frontend verification and SHALL NOT substitute for an approved Schema Wiki
owner path or introduce Schema authority.

#### Scenario: a lane needs an unlisted dependency path

- **WHEN** implementation requires writing a file owned by another lane or outside its list
- **THEN** the lane stops without modifying that path or creating a parallel contract
