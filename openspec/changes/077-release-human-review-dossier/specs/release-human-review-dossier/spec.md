# Release Human Review Dossier Specification

## ADDED Requirements

### Requirement: RHD1 complete Candidate is the sole review unit

The builder SHALL accept exactly one complete, revalidated 059 `CandidateAssemblyV1` and
SHALL bind the output to its candidate hash and human-batch hash. The dossier authority
SHALL be `DISPLAY_ONLY_REQUIRES_NAMED_HUMAN` while retaining the upstream batch authority
`NONE_REQUIRES_NAMED_HUMAN`. It SHALL expose no decision, selected choice, winner,
approval, publish or persistence operation.

#### Scenario: caller requests one field only

- **WHEN** the supplied review inputs do not cover the complete Candidate
- **THEN** construction fails closed before JSON or HTML exists

### Requirement: RHD2 original FieldCandidate locator custody is mechanically replayed

For every 059 `FactVerificationLinkV1`, the builder SHALL require exactly one original 057
`FieldCandidateV1` whose recomputed `candidate_snapshot_hash` equals the link. It SHALL
require exact field, ProductVersion, verification result and fact bindings and SHALL retain
the original Evidence page, subject kind/ref, parent refs, content snapshot/hash, quote/hash,
value/hash and support scope. The fact value hash SHALL equal SHA-256 of the exact canonical
057 value snapshot. Every Evidence parse-attempt id, parsed-document hash and parse-manifest
hash SHALL equal the enclosing linked `VerificationBatchV1`; its source-revision id SHALL
equal that batch's source-revision id, and its support-scope ProductVersion SHALL equal the
fact and Candidate ProductVersion. Missing, duplicate, orphaned or mismatched inputs SHALL
fail closed; `field_id` alone SHALL never authorize a match.

#### Scenario: same field has a foreign locator snapshot

- **WHEN** a FieldCandidate has the expected field id but a different snapshot hash
- **THEN** construction fails with typed locator-custody error and produces no output

### Requirement: RHD3 all review categories remain explicit and neutral

The dossier SHALL classify exact 058 actions as add, update, conflict or retract for display;
enrich and supersede SHALL appear under update while retaining their raw action. Conflict
SHALL include all incoming and prior facts without a default winner. Retraction SHALL retain
its proof hash and prior history. High-risk, repair and unresolved gap items SHALL remain
separately visible, and repair SHALL never be treated as acceptance.

#### Scenario: Candidate contains conflict and repair-needed entries

- **WHEN** the complete Candidate is rendered
- **THEN** both categories and their exact upstream hashes are visible without any selected
  or approved state

### Requirement: RHD4 JSON identity is deterministic and immutable

The builder SHALL create one frozen dossier model, canonicalize all collections, serialize
deterministic UTF-8 JSON and compute a domain-separated dossier hash. Reordering equivalent
caller inputs SHALL not change bytes or hash; changing any bound Candidate, fact, Evidence,
repair, gap or policy identity SHALL change the hash or fail closed.

#### Scenario: original FieldCandidate order changes

- **WHEN** the same exact members are supplied in another order
- **THEN** the JSON bytes and dossier hash remain identical

### Requirement: RHD5 static HTML is an escaped projection of the dossier

HTML SHALL be rendered only from the validated dossier model. It SHALL be deterministic,
offline and escaped, and SHALL contain no script, form, external resource, callback,
selected state or approval control. Candidate hash, category counts and locator facts SHALL
agree with the JSON projection. It SHALL display the already-validated Evidence content,
quote and value digests, parse identity and support scope, plus repair parent/plan identity,
per-result status/reasons and gap reason codes.

#### Scenario: Evidence text resembles markup

- **WHEN** a source snapshot contains HTML-like text
- **THEN** the static dossier displays escaped text and introduces no executable markup

### Requirement: RHD6 implementation remains pure and display-only

The task-local modules SHALL perform no filesystem, environment, network, provider, model,
Golden, database, WeKnora, Release or serving-head operation and SHALL not import
`ReviewDecision` authority. Serialization SHALL return bytes/strings to the caller only.

#### Scenario: implementation boundary is inspected

- **WHEN** the focused safety test examines imports and public callables
- **THEN** no forbidden authority or I/O surface is present
