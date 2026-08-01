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

### Requirement: FCH7 named-human whole-batch decision receipt

PR2 SHALL consume a closed, canonical, Ed25519-verifiable decision receipt that
binds one named human principal, current tenant/Space/RAW-KB/Wiki-KB scope, exact
PR1 Candidate hash, exact human-batch hash, exact review-policy hash, decision,
issued/expiry times, nonce and signer key. Only `approve` MAY activate; `reject`,
missing/unknown/duplicate fields, invalid signature, stale time, principal/ACL
drift, or any Candidate/batch/policy mismatch SHALL fail before Release writes.
The receipt SHALL bind the whole batch and SHALL NOT permit per-item partial
approval. Exact signed fixture bytes SHALL be covered by one immutable
Python-to-Go vector.
The existing production activation handler SHALL accept only a closed request
containing both that canonical human receipt and the separate publish
authorization, and SHALL enter activation only through the reviewed boundary.
The lower-level atomic transaction helper SHALL NOT remain an exported
production activation path.

#### Scenario: reject or partial receipt attempts activation

- **WHEN** the receipt rejects the batch or any bound hash/principal byte drifts
- **THEN** activation fails typed and Release/member/Head/receipt state is unchanged

#### Scenario: legacy authorization bypasses the human receipt

- **WHEN** a caller submits only legacy publish authorization, omits the human
  receipt, or self-reports an opaque review digest
- **THEN** the handler fails closed before any Release/member/Head/receipt write

### Requirement: FCH8 atomic activation and idempotent receipt

PR2 activation SHALL reuse the existing five-table transaction: insert one
immutable Release and all members, CAS the sole WeKnora Head from the exact
release/epoch to epoch+1, then persist one immutable receipt. CAS loss or any
transaction fault SHALL roll back Release, members, Head and receipt together.
An exact nonce plus exact authorization digest retry SHALL return the committed
receipt; the same nonce with a different digest SHALL conflict.

#### Scenario: two candidates race from one Head

- **WHEN** two approved activations use the same expected release and epoch
- **THEN** exactly one wins and the loser leaves no Release/member/receipt orphan

### Requirement: FCH9 request-scoped pinned read with current ACL

One request SHALL resolve the WeKnora Head exactly once into an immutable pinned
release/epoch token. Page, payload and search reads under that token SHALL never
re-read or advance the Head, but every read SHALL independently revalidate the
current principal, binding and both KB ACLs. ACL shrink SHALL deny later reads
even though the immutable pin remains unchanged.
Every serving handler SHALL obtain that opaque pin once from current Head at
request start. A caller-supplied historical `release_id` SHALL NOT select read
authority and SHALL fail closed when it differs from the just-pinned Head.

#### Scenario: Head advances after request pin

- **WHEN** a request pins R0 and another activation advances the Head to R1
- **THEN** all reads under the first token return only R0, subject to fresh ACL

#### Scenario: URL asks for historical R0 while Head is R1

- **WHEN** page, payload or search receives caller `release_id=R0` after Head is R1
- **THEN** the request fails closed and returns no R0 content

### Requirement: FCH10 immutable historical revert by CAS only

Revert SHALL verify current access and a signed revert authorization, resolve an
existing immutable Release in the exact same scope, and CAS the sole Head from
the exact expected release/epoch to that historical Release at epoch+1. It SHALL
NOT create or rewrite a Release or member. Revert receipt/idempotency and
transaction rollback SHALL follow FCH8. Concurrent activate/revert from one Head
SHALL have exactly one winner.

#### Scenario: revert targets a foreign or mutable identity

- **WHEN** the target is absent, current, cross-scope or its preparation/hash custody drifts
- **THEN** revert fails closed and leaves all five tables unchanged
