# actual-marker-endpoint-pair-derivation-input-bridge Specification

## ADDED Requirements

### Requirement: MEP1 closed input authority

The bridge MUST accept only an exact 083 three-source bundle plus an exact 053
ParsedDocument/ParseManifest pair. It MUST bind source, parser/config, intake,
capture, raw/sanitized structure, native member, cross-page facts, 091 marker
provenance and frozen 086 policy identities.

#### Scenario: identity drift

- **WHEN** any source/parser/version/member/raw/projection/intake/document/manifest
  identity changes
- **THEN** the bridge returns a fixed typed failure and emits no candidate input

### Requirement: MEP2 exact source-marker replay

Exactly one `cross_page` observation MUST map by kind, zero-based page index,
node type and local index to one canonical endpoint. Its 091 structural-path
hash MUST replay from the top-level native path and its marker/replay digests
MUST remain exact. `lines_deleted` MUST NOT be relation evidence.

#### Scenario: incomplete current custody

- **WHEN** the current evidence contains `lines_deleted`, a nested/unreplayable
  path, or zero/multiple source nodes
- **THEN** the bridge returns the precise typed reason and emits no input

### Requirement: MEP3 frozen table target rule

A table target MUST be on the immediately following physical page, have the
same exact column count, and have a complete non-overlapping header whose cell
content hash, structure hash, column, row span and column span are exactly equal.
Exactly one compatible pair MUST exist under the 086 policy.

#### Scenario: candidate cardinality

- **WHEN** the compatible target count is zero or greater than one
- **THEN** the bridge returns typed `NOT_AVAILABLE` or `BLOCKED` respectively
  and emits no candidate input

### Requirement: MEP4 derived input is not authority

The immutable candidate input MUST record actual endpoint IDs/pages and all
structural preimages/digests. It MAY implement the frozen 086 replay protocol,
but MUST NOT claim NATIVE, relation receipt, ADMIT or READY. Only a successful
086 replay may return `DERIVED_STRUCTURAL_BINDING_VERIFIED`.

#### Scenario: future-complete evidence

- **WHEN** a synthetic future 091 fixture has one exact marker and one unique
  compatible canonical endpoint pair, and 086 preserves that marker during its
  intake replay
- **THEN** the bridge input replays through the remaining 086 evaluator and its
  binding is accepted by the existing 096 receipt-entry contract

#### Scenario: frozen 086 predecessor

- **WHEN** the unchanged frozen 086 replay drops the required 091 marker envelope
- **THEN** the integration remains typed blocked and 098 does not claim a
  relation or receipt

### Requirement: MEP5 section honesty and privacy

Section bindings MUST require explicit typed source and target block references.
Because the current frozen 083/053 shape has no such continuation authority, the
bridge MUST return `SECTION_ENDPOINT_RULE_NOT_AVAILABLE`. Error/DTO repr MUST not
contain captured body, Markdown, URL, secret or absolute filesystem path.

#### Scenario: semantic temptation

- **WHEN** only adjacent text, repeated header-looking text or Markdown exists
- **THEN** the bridge returns `NOT_AVAILABLE` without constructing endpoints
