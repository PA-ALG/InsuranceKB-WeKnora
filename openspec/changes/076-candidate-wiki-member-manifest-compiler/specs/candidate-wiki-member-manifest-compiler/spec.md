# Candidate Wiki Member Manifest Compiler Specification

## ADDED Requirements

### Requirement: CWM1 exact draft compiler authority

076 SHALL revalidate one complete 059 `CandidateAssemblyV1` and SHALL emit only an immutable
draft manifest. The output SHALL bind the exact Candidate, human batch, review policy, Space,
ProductVersion, schema artifact, source revisions and base identity. It SHALL contain no human or
machine decision, ReadyReceipt, Release, Active Head, serving authorization or publication claim.

#### Scenario: draft is treated as publication authority

- **WHEN** a caller omits or mutates any bound Candidate/base identity or attempts to pass a
  decision/Ready/Release field
- **THEN** compilation fails typed and returns no member or manifest output

### Requirement: CWM2 exact 057 Candidate and full Evidence custody

Every rendered fact SHALL consume one revalidated exact 057 `FieldCandidateV1`. Its recomputed
`candidate_snapshot_hash` SHALL equal the corresponding 059 `FactVerificationLinkV1` hash, and the
mapping SHALL be a bijection. The value snapshot SHALL be derived from the exact Candidate value and
its SHA-256 SHALL equal the imported 058 fact `value_hash`. Every 058 Evidence hash SHALL be
recomputed from the complete exact 057 `EvidenceSnapshotV1`, including parse/document/manifest,
locator subject/parents/content witness, quote, value and support scope. A reduced parallel Evidence
schema is forbidden. Every Evidence SHALL also equal its linked 057 `VerificationBatchV1` and
receipt custody for source revision, parse attempt, parsed document and parse manifest identity.

#### Scenario: opaque hashes or mismatched readable content

- **WHEN** a Candidate is missing/extra, a fact link carries a bogus snapshot hash, or any value,
  full Evidence locator/preimage, VerificationBatch or receipt identity differs from the exact
  imported custody
- **THEN** compilation fails typed; it never emits a placeholder page made only of opaque hashes

### Requirement: CWM3 complete initial or incremental base

An initial compile SHALL use the explicit empty-base identity. An incremental compile SHALL consume
one complete, canonically validated Go-compatible base manifest plus an explicit task-local
`ReleaseBaseAuthorityPort`. The port SHALL resolve the expected release, activation epoch, manifest
digest and member count independently from the supplied member bytes; the compiler SHALL NOT accept
a caller-created raw binding as authority. Incremental mode without that port SHALL fail closed.
Every page and change-log payload SHALL be strictly parsed as a closed DTO and SHALL reproduce its
Markdown, revision and member digest. Every non-add affected scope SHALL already have its derived
page slug; every add slug SHALL be absent. Duplicate slugs, extra payload fields, foreign
scope/schema, malformed members or a partial/drifted base SHALL fail closed.

#### Scenario: affected-only fragment is supplied as a base

- **WHEN** a caller omits the authority port, supplies a self-consistent truncated/forged base or a
  matching attacker-created DTO, changes readable content, adds an unknown payload field, or a
  non-add change lacks its exact current page
- **THEN** compilation fails typed and emits no partial manifest

### Requirement: CWM4 deterministic five-action page semantics

076 SHALL derive field page slugs only from ProductVersion and exact scope hash. `add` creates one
page; `enrich` preserves the value while adding verified support; `supersede` replaces the current
page with the higher-authority incoming fact; `conflict` retains all competing fact and Evidence
preimages without selecting a winner; `retract` removes current page membership. Unaffected base
members SHALL remain byte-for-byte unchanged.

#### Scenario: conflict or retract is compiled

- **WHEN** an exact conflict and an exact retract are present
- **THEN** the conflict page contains every competing side with no winner and the retracted page is
  absent while both actions remain in the immutable change log

### Requirement: CWM5 closed pages and immutable change log

Every page SHALL contain a closed structured payload and mechanical Markdown derived only from
validated preimages. One deterministic change-log member SHALL bind the Candidate, base, each exact
action, before/after member identities and retraction proof identity. Titles/values SHALL NOT control
addressing, and output SHALL reject bounded secret-shaped values/Evidence (including common
password, token, API-key, bearer, secret and private-key assignment/header forms), absolute paths,
unsafe control characters and non-NFC text.

#### Scenario: unsafe or non-closed output is requested

- **WHEN** a Candidate contains a secret-shaped value/Evidence, decomposed Unicode, an absolute
  path, newline-bearing identifier or a payload field outside the closed DTO
- **THEN** compilation fails typed before any output is returned

### Requirement: CWM6 C0 and unchanged-Go byte compatibility

Members SHALL be sorted by `logical_slug`, unique, NFC-normalized and encoded with the exact existing
Go `WikiReleaseMemberSnapshot` JSON field names and ordering. Payload bytes SHALL be canonical JSON.
The whole manifest SHALL equal the bytes returned by unchanged `canonicalWikiReleaseManifest`; its
digest SHALL equal unchanged `digestWikiReleaseBytes`.

#### Scenario: Python-to-Go frozen vector

- **WHEN** Python and the existing Go canonicalizer consume the frozen incremental non-ASCII 076
  vector
- **THEN** both produce byte-for-byte identical manifest bytes and lowercase SHA-256 digest

### Requirement: CWM7 pure deterministic and failure-zero-output boundary

The same semantic inputs in any iteration order SHALL yield identical members, bytes and hashes;
mutating any bound Candidate/base authority/action/member byte SHALL change identity or fail. Every
compile-time validation failure SHALL surface only as `CandidateWikiManifestError` with no partial
draft. 076
SHALL perform no filesystem, environment, network, subprocess, database, provider, Golden,
WeKnora, Prepare, activation, Head or revert operation.

#### Scenario: invalid input or external operation is attempted

- **WHEN** any input validation fails or compilation would require an external operation
- **THEN** one typed error is returned with no partial output and no external operation
