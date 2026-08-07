# MinerU Derived Cross-page Binding Specification

## ADDED Requirements

### Requirement: MCB1 exact upstream custody replay

The derivation SHALL replay the complete 083 intake and require the rate 053
document/manifest to match its source, raw and sanitized artifact, parser,
attempt, snapshot, privacy and complete structural inventory. Caller-constructed
or drifted DTOs SHALL fail closed before candidate discovery.

#### Scenario: a locally self-consistent endpoint graph is foreign to the capture

- **WHEN** any source, parser, version, artifact, document or manifest identity drifts
- **THEN** derivation raises a fixed `BLOCKED` reason and emits no binding

### Requirement: MCB2 honest native observation boundary

MinerU 3.4.4 ambiguous marker custody SHALL remain a document-level native
observation. It SHALL never be represented as a native source/target relation.
The 062 envelope hashes both `cross_page=true` and `lines_deleted=true` without
retaining their typed identity; therefore even exactly one observation SHALL
return `NOT_AVAILABLE`. Absent facts are also `NOT_AVAILABLE`, while multiple
observations are `BLOCKED` as ambiguous.

The derivation SHALL accept no naked marker DTO. A future-089 authority SHALL
implement the task-local replay Protocol and return a closed receipt binding the
exact request digest, marker kind, structural path, observation hash, relation
kind and endpoint IDs/pages. The structural-path preimage SHALL mechanically
recompute the 062 observation hash. `lines_deleted` SHALL never satisfy the
required `cross_page` marker.

#### Scenario: typed marker kind or path drifts

- **WHEN** replay returns `lines_deleted`, a foreign structural path, a foreign
  request digest or an observation hash that does not recompute
- **THEN** derivation returns typed `BLOCKED` and emits no binding

#### Scenario: caller asks for a native endpoint relation

- **WHEN** the native envelope contains no explicit endpoint relation
- **THEN** output, if any, is labeled only `DERIVED_STRUCTURAL_RELATION`

### Requirement: MCB3 unique mechanical table derivation

A future table binding SHALL require two real, different 053 table endpoints on
adjacent pages; equal column counts; complete non-overlapping header-cell column
coverage; equal row/column spans and header content/structure digests; and one
unique compatible pair in the document. No body, Markdown, HTML, neighboring
text or repeated-header similarity outside these explicit facts may contribute.
These conditions are necessary but SHALL NOT substitute for a typed native
`cross_page` marker. With the future replay Protocol, the typed endpoint IDs and
pages SHALL also equal the sole compatible 053 pair; otherwise no binding is emitted.

#### Scenario: more than one pair is compatible

- **WHEN** two or more endpoint pairs satisfy the mechanical policy
- **THEN** derivation returns typed `BLOCKED` and no binding

### Requirement: MCB4 section proof remains unavailable

The implementation SHALL treat current 062-only explicit block facts as
insufficient and return typed `NOT_AVAILABLE`. A future typed section marker may
produce a binding only when its exact source and target block IDs each exist
once in the replayed 053 document, their pages equal the typed pages and differ,
and marker kind is `cross_page`. Adjacent text or sentence meaning SHALL not
fill the gap.

#### Scenario: two neighboring blocks look continuous

- **WHEN** no explicit stable section relation exists
- **THEN** no section binding is emitted

### Requirement: MCB5 immutable replayable non-authority DTO

`CrossPageRelationBindingV1` SHALL bind source, parser/config, intake, artifact,
raw/sanitized structure, cross-page evidence, typed marker receipt, policy,
native projection/observation, actual endpoint IDs/pages/locator facts and a
domain-separated replay digest. Its only success status SHALL be
`DERIVED_STRUCTURAL_BINDING_VERIFIED`; it SHALL be immutable, closed and
mechanically replayable, and SHALL expose no NATIVE, ADMIT, READY or persistence
status/action.

#### Scenario: any bound fact changes after construction

- **WHEN** replay sees a changed field or digest
- **THEN** it fails closed with zero replacement binding
