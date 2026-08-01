# Fixture Candidate and Human Batch Envelope Specification

## ADDED Requirements

### Requirement: FCH1 accepted 058 contract is the only ChangeSet authority

059 SHALL directly consume the immutable ChangeSet aggregate, items, actions and
canonical identity/digest verification exported by an accepted exact 058
commit. It SHALL NOT copy, narrow, widen or locally redefine any 058 DTO, hash,
action, comparator or conflict authority. Until that exact commit is supplied,
059 implementation SHALL remain blocked by an executable RED seam.

#### Scenario: local surrogate makes progress without 058

- **WHEN** a caller or implementation supplies a locally defined ChangeSet-like
  object while the accepted 058 public contract is unavailable
- **THEN** 059 remains typed blocked and produces no Candidate or human batch

### Requirement: FCH2 Candidate binds one exact verified compilation scope

`FixtureCandidateV1` SHALL bind one exact immutable 058 ChangeSet. An explicit
content-addressed link SHALL join every imported 058 fact hash to one exact
verified 057 verification hash and candidate snapshot hash; 059 SHALL embed the
imported 057/058 objects rather than copy their DTO or hash logic. Its canonical payload
SHALL include Space, ProductVersion, schema, all source revision identities,
ChangeSet identity/digest and receipt identities. Every item SHALL agree with
that scope. Missing, ambiguous, invalid, cross-Space, cross-ProductVersion,
cross-schema, cross-source, unverified receipt or digest drift SHALL fail closed
before any Candidate or human batch is returned.

Space and schema authority SHALL be derived from embedded, exact 054
`ReceiptChainV1.task` values and its `schema_contract` ArtifactRef, with one
validated 054 chain for every embedded 057 verification. Caller-supplied schema
labels or hashes SHALL NOT mint this authority. Receipt chains, verifications,
fact links and repair resolutions SHALL form exact unique bijections; a repair
field or parent verification SHALL NOT be overwritten by a later receipt.
Every repair SHALL preserve each parent PASS result byte-for-byte. Its final
gaps SHALL exactly match every non-PASS result's field and reason codes, and its
review items SHALL exactly match the corresponding field, first reason code and
parent verification hash.

The Candidate SHALL be a non-serving fixture artifact. It SHALL NOT assert
approval, Release, active Head or online read authority.

#### Scenario: one receipt belongs to another source revision

- **WHEN** the ChangeSet is internally valid but one referenced 057 receipt is
  missing, invalid or bound to another source revision
- **THEN** Candidate construction fails typed and returns no partial artifact

### Requirement: FCH3 canonical Candidate hash is stable and mutation-sensitive

Candidate members and identities SHALL be normalized into a documented
canonical order and hashed only with the merged C0 canonical envelope/codec.
Semantically identical input orderings SHALL produce identical canonical bytes
and hash. Mutating any bound identity, item, fact, Evidence reference, receipt
reference or review flag byte SHALL change the hash or fail validation.

#### Scenario: input order changes without semantic change

- **WHEN** the same exact ChangeSet members and receipt references arrive in a
  different iteration order
- **THEN** Candidate canonical bytes and hash remain identical

### Requirement: FCH4 human batch is deterministic and non-authoritative

`HumanBatchV1` SHALL bind the exact Candidate hash and deterministically include
review items for every conflict, high-risk or repair-needed ChangeSet item.
It MAY summarize ordinary non-blocking changes, but SHALL NOT invent a review
requirement, decision, reviewer, approval or auto-approval. Empty review-item
membership SHALL NOT itself authorize publication.

Its canonical ordering and C0 hash SHALL be stable under input reordering and
mutation-sensitive to every included item, reason, risk/repair flag, competing
fact and Evidence reference.

The exported Candidate assembly validator SHALL recompute source membership,
receipt custody and the exact required review-item membership from its embedded
Candidate and policy. These invariants SHALL hold for direct DTO construction
and validated copy operations, not only for the convenience builder.

#### Scenario: high-risk item is omitted

- **WHEN** an exact ChangeSet contains a high-risk or repair-needed item but the
  proposed human batch does not contain its bound review item
- **THEN** construction fails closed; no apparently complete batch is returned

### Requirement: FCH5 conflicts retain all competing facts and Evidence

A conflict review item SHALL retain every competing fact snapshot and its own
Evidence references exactly as supplied by accepted 058. Candidate assembly
SHALL NOT select a winner, merge incompatible Evidence, attach new Evidence to
an old value, or discard a competing side. Ambiguous or incomplete conflict
custody SHALL fail closed.

#### Scenario: conflict drops one side

- **WHEN** a conflict contains two competing facts but the batch contains only
  one fact or combines their Evidence
- **THEN** construction is rejected and no human review envelope is emitted

### Requirement: FCH6 PR1 is a pure fixture boundary

059 PR1 SHALL contain only frozen Pydantic DTOs, deterministic validation,
canonical serialization/hash and focused in-memory tests. It SHALL perform no
filesystem/environment/network I/O, DB/migration, queue/workflow, provider/live,
WeKnora operation, Golden read, ReviewDecision, Release, CAS activation, pinned
read or revert. Those publication actions belong only to a separately approved
PR2 after PR1 is merged.

#### Scenario: Candidate creation attempts to publish

- **WHEN** construction would call a serving, review-decision, activation or
  revert boundary
- **THEN** the PR1 contract rejects the operation; Active Head remains unchanged
