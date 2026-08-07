# MinerU Native Section-Anchor Evidence Specification

## ADDED Requirements

### Requirement: NSA1 exact custody replay

The extractor MUST revalidate the exact 083 bundle and 101 terms marker
authority, including source, parser, version, config, capture, raw ZIP, native
member, sanitized structure, marker path/node and envelope hashes. All emitted
digests MUST have typed canonical preimages.

#### Scenario: identity drift

- **WHEN** any bound identity, preimage or digest changes
- **THEN** extraction returns fixed typed `BLOCKED` and emits no authority

### Requirement: NSA2 structural-only anchor

The extractor MUST prefer explicit native hierarchy facts. When they are not
available, it MAY use only the nearest preceding structured title/section
block, the complete contiguous reading-order interval, the next-page first
content block, and proof that the interval contains no new title/section
boundary. It MUST NOT inspect or compare title text, body text, Markdown,
semantic similarity or model output.

#### Scenario: complete structural interval

- **WHEN** one cross-page terms marker, one next-page first content block and
  one unchanged native outline stack are uniquely replayable
- **THEN** a privacy-safe `SECTION_ANCHOR_EVIDENCE_VERIFIED` authority is emitted

#### Scenario: structural facts insufficient

- **WHEN** the anchor is absent or ambiguous, a new heading intervenes, the
  page gap is not one, or reading order is incomplete
- **THEN** extraction returns typed `NOT_AVAILABLE` or `BLOCKED` with zero evidence

### Requirement: NSA3 boundary and node classes

Header/footer/page-number nodes MUST be excluded from content and anchor
candidates. Multiple heading levels MUST update a deterministic outline stack.
`lines_deleted`, unknown marker kinds, duplicate pages/nodes, zero or multiple
endpoint candidates and malformed hierarchy facts MUST fail closed.

#### Scenario: non-authoritative or malformed node

- **WHEN** a header/footer is presented as an endpoint, `lines_deleted` is
  presented as a section marker, or hierarchy/page ordering is malformed
- **THEN** extraction rejects it without selecting an alternative node

### Requirement: NSA4 103-compatible replay

The verified authority MUST implement the frozen 103 request protocol and bind
the actual canonical source/target endpoint IDs, pages and locator digests. It
MUST return only section-anchor evidence; it MUST NOT claim NATIVE relation,
ADMIT or READY.

#### Scenario: endpoint request replay

- **WHEN** 103 presents the exact source/target request bound by the evidence
- **THEN** the authority returns equal non-empty ancestry and outline hashes;
  any request drift fails closed

### Requirement: NSA5 privacy

The evidence, exception, representation and validation report MUST contain no
title/body text, Markdown, URL, credential or absolute path. Structural path
identities MAY appear only as canonical hashes in the public evidence.

#### Scenario: private native content

- **WHEN** the native artifact includes title/body values that are not required
  for structural identity
- **THEN** those values are neither inspected for equivalence nor emitted
