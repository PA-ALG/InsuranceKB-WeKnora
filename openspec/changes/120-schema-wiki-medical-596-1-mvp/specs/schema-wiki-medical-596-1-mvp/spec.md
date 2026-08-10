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
hash. A decision from another manifest SHALL never authorize preparation.

#### Scenario: a decision is reused after one member changes

- **WHEN** any member, citation binding or manifest digest changes after review
- **THEN** preparation fails before the existing Wiki Release transaction starts

### Requirement: SWM7 activation and reads use the single existing release authority

The implementation SHALL reuse the existing Wiki Release preparation, named-human
activation, Head CAS, revert and pinned-read service. It SHALL add no second Head, CAS or
release table and SHALL never activate a partial member set. Reviewed immutable draft reads
SHALL use `preparation_id`; Active and pinned reads SHALL use the existing release/epoch
authority. No Active release SHALL return `NO_SCHEMA_WIKI_ACTIVE_RELEASE` with no generic
fallback.

#### Scenario: one new member fails before CAS

- **WHEN** any member, taxonomy, receipt or CAS validation for a new release fails
- **THEN** the existing Active Head and every existing pin remain unchanged

### Requirement: SWM8 scope bootstrap enforces derived RAW and Wiki ACL

The schema-scope route SHALL resolve exactly one release scope from the authorized Wiki KB,
inject non-overridable space and RAW KB route parameters, authorize the derived RAW KB using
the existing `KBAccessRead` middleware and recorded ACL evidence, and only then seal the
existing dual ACL context. Human/JWT and API-key principals SHALL follow the same checks.
Cross-tenant, zero, multiple, Wiki-only or RAW-denied scopes SHALL reveal no schema scope.

#### Scenario: principal may read Wiki but not the derived RAW KB

- **WHEN** the bootstrap resolves a RAW KB for which the principal lacks read access
- **THEN** no `SchemaWikiScopeV1`, release seal or member data is returned

### Requirement: SWM9 exact revision preview remains fail closed until authority exists

Lane A SHALL freeze a `CitationRevisionReadPort` and typed preview errors, but SHALL NOT
claim real exact-revision preview acceptance until a trusted adapter proves the immutable
revision bytes and the citation's knowledge/source-revision/parse/document/manifest/page/
bbox identities. The UI SHALL not substitute current/latest bytes or page 1.

#### Scenario: preview adapter is unavailable

- **WHEN** a citation is selected before the trusted adapter is frozen
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
plan and this change are explicitly amended.

#### Scenario: a lane needs an unlisted dependency path

- **WHEN** implementation requires writing a file owned by another lane or outside its list
- **THEN** the lane stops without modifying that path or creating a parallel contract
