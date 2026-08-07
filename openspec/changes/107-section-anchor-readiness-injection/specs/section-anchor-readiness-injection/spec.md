# Section-anchor readiness injection specification

## ADDED Requirements

### Requirement: SAR1 · Current authority is unavailable and side-effect free

The system MUST fail closed before any downstream call when actual 106 evidence is unavailable.

When a frozen actual OpenSpec 106 evidence provider is absent or reports not available, the
formal 107 entry point MUST return `SECTION_ANCHOR_EVIDENCE_UNAVAILABLE`. It SHALL NOT call
103, 102/086, 096, 104, 098 or 099, and SHALL never authorize capture.

#### Scenario: Actual 106 evidence is unavailable

- **WHEN** no frozen actual 106 provider can supply the exact section-anchor evidence
- **THEN** 107 returns `SECTION_ANCHOR_EVIDENCE_UNAVAILABLE`
- **AND** no downstream dependency is called and capture remains unauthorized

### Requirement: SAR2 · Exact anchor custody replay

Before invoking 103, the explicit future-complete path SHALL recompute and exactly bind the
terms source SHA, raw ZIP/member identity, parser model/version/config/identity, canonical
ParsedDocument and ParseManifest hashes, marker identity, reading-order preimage, source and
target anchor intervals, ancestry, outline anchors and evidence digest. Missing, duplicate,
wrong-role, wrong-page, wrong-member, wrong-parser, reordered or hash-drifted evidence SHALL
fail closed.

#### Scenario: Anchor custody drifts

- **WHEN** any bound source, parser, member, marker, reading-order, interval, ancestry,
  outline or canonical digest fact differs from its recomputed value
- **THEN** 107 returns a typed blocked outcome before downstream readiness evaluation

### Requirement: SAR3 · Existing authorities remain authoritative

107 SHALL inject validated ancestry and outline facts through the public 103 Protocol and
invoke the real 103 → 102/086 → 096 terms binding. It SHALL then supply the resulting
receipt to the public 104 seam, which invokes actual 098 and 099. 107 SHALL NOT copy or weaken
any relation, endpoint, readiness or receipt algorithm.

#### Scenario: Exact evidence reaches existing authorities

- **WHEN** a test-only complete fixture satisfies the exact 106 evidence contract
- **THEN** 107 delegates terms derivation to 103 and readiness wiring to 104
- **AND** it does not replace any 102/086/096/098/099 authority

### Requirement: SAR4 · Future completeness is test-only

The system MUST keep every future-complete fixture test-only and capture-unauthorized.

A complete synthetic future fixture MAY prove that the dependency chain can mechanically
advance to a later readiness outcome, but its evidence class MUST be `TEST_ONLY` and
`capture_authorized` SHALL remain false. A Protocol fake or synthetic hash SHALL NOT satisfy
the formal current path.

#### Scenario: Complete fixture is not production authority

- **WHEN** the future-complete fixture traverses the full mechanical chain
- **THEN** its result remains `TEST_ONLY`
- **AND** `capture_authorized` is false

### Requirement: SAR5 · Privacy and scope

Outputs SHALL contain only fixed statuses and hashes. No body, Markdown, raw artifact,
credential, URL or absolute path may be emitted. Provider, model, Golden, DB, PG, WeKnora,
live and full executions are forbidden.

#### Scenario: Result remains privacy-safe

- **WHEN** 107 emits any typed outcome
- **THEN** the result contains only fixed status values and hashes
- **AND** it contains no source body, Markdown, raw artifact, credential, URL or absolute path
