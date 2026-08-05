# Golden18 XLSX Import Bridge Specification

## ADDED Requirements

### Requirement: XIB1 exact workbook and layout identity

The bridge SHALL accept workbook bytes plus a caller-declared expected SHA-256 and
SHALL recompute that digest before parsing. It SHALL bind the approved blank-template
SHA-256 `ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf`,
product `596-1`, the public 075 ordered eighteen fields, P0-seven/P1-eleven
cardinality, three exact visible sheets, fixed review-table dimensions and headers,
and the five-choice decision vocabulary. The completed workbook digest SHALL be
distinctly bound; it SHALL NOT be mislabeled as the blank-template digest.

#### Scenario: the completed bytes or workbook shape drift

- **WHEN** the declared digest, sheet, header, row/column shape, visibility, field
  order, formula policy or decision vocabulary differs
- **THEN** the bridge is typed blocked and emits no 075 request

### Requirement: XIB2 blank and partial decisions remain pending

Blank or partially filled decision cells SHALL yield
`AWAITING_18_HUMAN_DECISIONS`, the exact ordered pending field IDs and P0/P1/total
counts. The bridge SHALL neither default a choice nor emit a partial 075 request.

#### Scenario: the approved workbook has no decisions

- **WHEN** all eighteen decision cells are blank
- **THEN** all eighteen fields are reported pending and the 075 request is absent

### Requirement: XIB3 exact public 075 conversion

Only a complete workbook MAY be converted. The bridge SHALL exact-match displayed
current/recommended/custom semantics to caller-provided replayable GoldenRecord
authority, build public 075 DTOs in the approved order, and replay public 075 hashing
and evaluation. Every decision reason SHALL bind the exact completed-workbook digest
without exposing workbook free text. `custom` SHALL require a complete caller-provided
custom record; no Evidence or value may be inferred from a neighboring cell.

#### Scenario: a complete synthetic workbook is valid

- **WHEN** all eighteen synthetic decisions and their record authority match exactly
- **THEN** one public 075 request is emitted and 075 returns either pending business
  resolution or ready for external approval, never human-verified or materialized

### Requirement: XIB4 adversarial fail-closed parsing

The bridge SHALL typed-block duplicate, missing, extra or reordered fields; hidden or
added sheets/rows/columns; unexpected formulas; Excel errors; illegal decision values;
malformed OOXML; and record/hash drift. Formulas are permitted only at the exact
approved status/count cells and SHALL match the frozen expressions. Any rejected or
incomplete input SHALL produce zero 075 request and zero external action.

#### Scenario: an input cell contains a formula

- **WHEN** a decision, custom tri-state or custom value cell contains a formula or
  Excel error value
- **THEN** the bridge is typed blocked before constructing a 075 DTO

### Requirement: XIB5 offline privacy and authority boundary

The bridge SHALL read only supplied bytes and explicit caller context. It SHALL not
read a path or environment, log workbook free text or answers, sign or mint a human
receipt, read/write Golden data, call a model/provider, access DB/WeKnora/Release, or
write a file. Public results SHALL contain only typed codes, counts, field IDs and
cryptographic identities plus an optional public 075 request.

#### Scenario: parsing fails on sensitive cell text

- **WHEN** malformed input contains arbitrary free text
- **THEN** the typed result contains no such text and no chained exception authority
