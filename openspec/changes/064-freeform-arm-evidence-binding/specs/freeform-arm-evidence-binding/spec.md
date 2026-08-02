# Freeform Arm Evidence Binding Specification

## ADDED Requirements

### Requirement: FEB1 exact parsed identity is replayable

A freeform field Evidence receipt SHALL consume merged 053 `ParsedDocumentV1` and
`ParseManifestV1` objects directly. Every document and manifest SHALL form an exact
subject/parser/attempt/snapshot/document-hash pair. Every Evidence item SHALL bind its
exact source revision, parse attempt, ParsedDocument hash and ParseManifest hash.
Missing, foreign, malformed or cross-paired identity SHALL fail with a typed 057
contract error.

#### Scenario: Evidence points at another parse attempt

- **WHEN** an Evidence item names a source but changes its attempt, document hash or
  manifest hash
- **THEN** binding fails and no receipt is emitted

### Requirement: FEB2 locator and quote binding does not judge semantics

For page, block, table and cell Evidence, 057 SHALL resolve the exact locator in the
bound ParsedDocument and verify its kind, page, parent chain and content snapshot hash.
The normalized quote SHALL occur in the exact content snapshot. These checks prove only
mechanical custody; they SHALL NOT claim that a freeform value is semantically entailed
by the quote. Semantic correctness remains an 061 Golden-scoring responsibility.
The receipt SHALL also retain the arm-shaped source SHA, page, block/table/cell IDs,
row/column, header snapshot and spans. Supplied IDs and coordinates SHALL equal the
exact ParsedDocument structure. A supplied header snapshot SHALL hash to content of an
exact cell named by that table's `header_cell_ids`; it SHALL NOT be caller-attested.

#### Scenario: quote exists under the wrong locator kind

- **WHEN** the quote text exists but a cell ref is declared as a page, has the wrong
  page/table parent or carries different content bytes
- **THEN** binding fails typed without consulting a model or Golden

#### Scenario: a rate locator coordinate or header mutates

- **WHEN** a bound rate Evidence changes source SHA, page, structure ID, row, column,
  header snapshot or span
- **THEN** new binding fails typed and the old receipt no longer replays

### Requirement: FEB3 multi-Evidence and multi-source membership is exact

The binder SHALL allow one known field to bind multiple Evidence items across multiple
source revisions.
Evidence and document/manifest pairs SHALL be canonical, unique and form an exact
source membership closure: every supplied source SHALL have Evidence and every Evidence
source SHALL have one supplied exact pair. A known field requires at least one Evidence.
`unknown` SHALL carry no value, Evidence or document custody. Missing Evidence,
duplicate Evidence, an omitted multi-source member or noncanonical order SHALL fail.

#### Scenario: one member of a two-source field is omitted

- **WHEN** two exact document/manifest pairs are supplied but Evidence covers only one
- **THEN** binding fails and cannot silently downgrade the field to single-source

### Requirement: FEB4 receipt hash binds the complete field closure

The receipt SHALL bind contract version, ProductVersion, field ID, tri-state, exact
freeform value snapshot, canonical full Evidence tuple and every exact document and
manifest hash. Replaying identical inputs SHALL reproduce an equal receipt and C0 hash.
Changing field ID, state, value, Evidence content/quote/identity/locator, document hash
or manifest hash SHALL change the receipt hash or fail validation.

#### Scenario: value or one Evidence byte mutates

- **WHEN** a caller changes the freeform value snapshot or any bound Evidence byte
- **THEN** the recomputed receipt hash differs and the old receipt does not verify

### Requirement: FEB5 the extension remains a pure 057 boundary

064 SHALL modify only the existing 057 module and test. The production module SHALL not
import 061, read Golden, judge freeform semantics or perform filesystem, environment,
network, provider, parser, database, WeKnora or release operations. A future runner MAY
only map its arm DTO one-to-one into this parser-neutral input; it SHALL NOT infer
Evidence, repair identity or add authority.

#### Scenario: freeform wording differs while custody remains exact

- **WHEN** a field carries arbitrary nonblank freeform value text with exact mechanical
  Evidence binding
- **THEN** 057 may emit a binding receipt but makes no PASS claim about semantic accuracy
