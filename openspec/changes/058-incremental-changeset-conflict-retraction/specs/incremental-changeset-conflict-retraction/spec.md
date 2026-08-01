# Incremental ChangeSet, conflict, and retraction specification

## ADDED Requirements

### Requirement: ICR1 exact scope and source authority

Every fact SHALL bind exact Space, ProductVersion, subject, field, business-time
interval, region, channel, population, and normalized conditions. Every source
observation SHALL bind exact source/revision, material role, reliable time, and
Evidence hashes. Compilation SHALL join it to one supplied, revalidated 052
MaterialProfile catalog and exact MaterialProfileResolution set using catalog,
binding, source, role, Space, and ProductVersion identities. The source revision
SHALL occur in the fact's non-empty supporting revision set for both `known` and
`unknown` observations. Callers SHALL NOT supply
their own FieldAuthority. Inputs from another Space, ProductVersion, catalog, or
binding policy SHALL fail before a ChangeSet draft is returned.

Authority SHALL be finite and code-owned: the 052 primary material role outranks
an approved support role; equal-role authority can supersede only when its
reliable time is strictly newer. A model score, filename, fuzzy match, or caller
rank SHALL NOT create authority.

#### Scenario: cross-Space candidate

- **WHEN** any candidate, baseline fact, or retraction proof belongs to another
  Space or ProductVersion
- **THEN** compilation fails with a typed scope error and emits no draft

### Requirement: ICR2 immutable affected-only ChangeSet

`compile_incremental_changes` SHALL return one immutable ChangeSet draft whose
input hash, ordered ChangeItems, and ChangeSet hash use C0 `canonical_hash`.
Changing any scoped input SHALL change the appropriate hash. Reordering an
equivalent input set SHALL NOT change the result.

The input-hash preimage SHALL include the requested root Space,
ProductVersion, and 052 catalog identity even when all three input sets are
empty. Empty compilations for different roots SHALL NOT share an input hash.

Only exact scopes named by verified candidates or explicit retraction proofs
SHALL produce ChangeItems. Unaffected baseline facts SHALL not be copied,
rewritten, or implicitly withdrawn.

#### Scenario: one affected field

- **WHEN** one of several baseline fields receives a verified candidate
- **THEN** the draft contains only that field's ChangeItem

### Requirement: ICR3 deterministic five-way classification

The compiler SHALL classify each affected scope as exactly one of:

- `add`: verified known fact with no active baseline;
- `enrich`: equal value with new Evidence/support custody;
- `supersede`: different value whose source authority deterministically outranks
  every differing active baseline;
- `conflict`: different value without one deterministic authority winner;
- `retract`: explicit admitted exclusive-support retraction proof.

Different values SHALL never be enriched together. Conflict and retract SHALL
remain draft/review facts and SHALL NOT mutate a Claim or active knowledge.
The presence of one same-value baseline SHALL NOT force conflict when every
different-value baseline is lower-authority; that case SHALL be `supersede`.

#### Scenario: equal authority disagreement

- **WHEN** two equally authoritative, equally reliable facts disagree
- **THEN** the action is `conflict`, preserving both fact and Evidence hashes

### Requirement: ICR4 explicit exclusive-support retraction

A retract SHALL be proposed only when an explicit proof binds the exact field
scope, old and replacement SourceRevision, complete new authoritative scope,
explicit absence, proof Evidence, and the baseline fact's sole supporting source
revision. Missing input and `unknown` state are not explicit absence and SHALL
never create retract.

If the baseline has multiple supporting source revisions, the proof targets a
different scope/source, or completeness/exclusive support is absent, compilation
SHALL fail closed rather than silently delete or downgrade knowledge.

#### Scenario: source-exclusive field disappears

- **WHEN** a complete new authoritative revision explicitly omits an exact
  scope and the old fact is supported only by its predecessor revision
- **THEN** one `retract` ChangeItem is emitted with old/new revision and proof
  Evidence custody; no Claim is deleted

### Requirement: ICR5 strict known/unknown behavior

Known facts SHALL carry an exact value hash and non-empty Evidence hashes.
`unknown` SHALL carry neither and SHALL produce no ChangeItem. Duplicate scopes,
duplicate Evidence/support refs, malformed hashes, wildcard identities,
case-insensitive whole-token `all`, `any`, or `unknown` identities, missing
authority, unknown fields, or extra DTO members SHALL fail closed. Legitimate
composite identities such as `all-approved-channels` SHALL remain valid because
the unresolved-token rule applies only to the complete token.
Every externally supplied fact and proof SHALL be reconstructed and revalidated
at compile entry so `model_copy`/`model_construct` cannot bypass these rules.
All digest fields SHALL be strict lowercase 64-hex values.

#### Scenario: unknown refresh

- **WHEN** the incoming affected scope is `unknown`
- **THEN** no add, supersede, conflict, or retract item is produced

### Requirement: ICR6 pure non-authority boundary

The 058 modules SHALL be pure deterministic DTOs and builders. They SHALL NOT
import ORM/session/DB, migration, provider/model, network, filesystem, runtime
worker, WeKnora, Candidate, ReviewDecision, PublishAuthorization, or Release.
The ChangeSet is a draft fact only and grants no review, publish, or serving
authority.

The 058 modules SHALL live under the pure `knowledge_compiler` namespace and SHALL NOT
eagerly import SQLAlchemy, legacy knowledge models, or publisher modules. The
existing knowledge package exports and runtime initialization contract SHALL
remain byte-for-byte unchanged.

#### Scenario: caller asks draft to publish

- **WHEN** a caller receives a valid ChangeSet draft
- **THEN** no active knowledge changes; later review/release contracts remain
  mandatory and outside 058
