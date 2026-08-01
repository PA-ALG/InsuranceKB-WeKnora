# Extraction Evidence Verifier and Targeted Repair Specification

## ADDED Requirements

### Requirement: EEV1 exact parsed identity and locator closure

Every document Evidence candidate SHALL bind exact ProductVersion,
SourceRevision, parse attempt, ParsedDocument hash, ParseManifest hash, field,
locator kind/ref, page and parent chain. The verifier SHALL resolve the locator
against the admitted `ParsedDocumentV1`; page/block/table/cell kind, page parent,
and table parent SHALL match. The locator content snapshot hash SHALL equal the
resolved parsed element content hash.

#### Scenario: a page locator impersonates a table cell

- **WHEN** a table-derived value carries a page ref, wrong subject kind, or a
  cell whose page/table parent chain differs from the parsed document
- **THEN** verification fails typed and the field cannot enter a ChangeSet

### Requirement: EEV2 quote, value, and semantic support are distinct gates

Evidence SHALL carry immutable quote and value snapshots with code-verified
SHA-256 digests. A normalized quote SHALL occur in the bound locator content
snapshot, and the Evidence value snapshot SHALL equal the field candidate value
snapshot. Quote occurrence alone SHALL NOT prove semantic support: exact
ProductVersion, subject identity, and applicable condition IDs SHALL also match
the candidate scope.

#### Scenario: matching words describe another condition

- **WHEN** the quote exists in the exact locator but its declared subject,
  condition, or ProductVersion differs from the candidate
- **THEN** the quote gate may pass but semantic support fails typed

### Requirement: EEV3 bounded deterministic value rules

The verifier SHALL implement only the fixed rule families needed by this
change: table numeric, numeric+unit, enum, ISO date, inclusive range, and
arithmetic result. Decimal parsing, unit equality, enum membership, date
validity/order, range bounds, and arithmetic equality SHALL be deterministic
code. Values in Evidence quotes SHALL be matched as exact typed atoms, never
as substrings of larger numbers, units, enums, dates, or ranges. Numeric,
numeric-unit, and range atoms SHALL include their sign in the comparison, so a
positive candidate cannot match a negative quote while a negative candidate
can match its exact signed atom. Binary float and LLM/model judgment SHALL be
forbidden.

The implementation SHALL NOT expose a dynamic rule registry, plugin loader,
expression language, parser router, or generic repair platform.

#### Scenario: table arithmetic disagrees

- **WHEN** a frozen table value claims operands `10` and `20` sum to `31`
- **THEN** deterministic verification fails; a model opinion cannot override it

### Requirement: EEV4 `unknown` and `absent_explicitly` remain distinct

`unknown` SHALL carry no value or Evidence and SHALL yield a typed Gap, never a
verified absence. `absent_explicitly` SHALL carry no value but SHALL require
exact Evidence, an explicit rule allowing absence, and an exact approved
absence marker in the bound quote. An arbitrary positive quote SHALL NOT prove
absence. Missing or contradictory Evidence SHALL fail closed.

#### Scenario: unknown is promoted to absent

- **WHEN** an extractor has no supporting locator and reports `unknown`
- **THEN** the verifier emits a Gap and MUST NOT create an absent fact

### Requirement: EEV5 one targeted repair over failed fields only

A targeted repair plan SHALL contain exactly the canonical failed/Gap field IDs
from the initial verification, an explicit set of approved locator refs per
field, the parent verification hash, and a budget permitting one repair.
The initial verification identity SHALL match the current ProductVersion,
SourceRevision, parse attempt, ParsedDocument and ParseManifest exactly, and
every approved locator SHALL exist in that ParsedDocument.
Passed fields SHALL NOT enter the plan or be replaced by repair output. Repair
Evidence SHALL be limited to approved locator refs. A second repair, missing
budget, caller-added field, or unapproved locator SHALL fail closed.

After the single repair, remaining failures SHALL become typed Gap and
ReviewItem records. They SHALL NOT be silently promoted to success.

#### Scenario: repair rewrites a passed field

- **WHEN** repair output contains a field that passed initial verification
- **THEN** the repair is rejected and the original passed snapshot remains exact

### Requirement: EEV6 exact 054 receipt binding without copied authority

057 SHALL consume the merged 054 `ExtractionTaskV1`, `ReceiptChainV1`, and
`AttemptReceiptV1` DTOs directly. The task ProductVersion/SourceRevision and
ParsedDocument/ParseManifest artifact refs, the active receipt field partition,
candidate snapshot hashes, and unresolved reason codes SHALL match the exact
057 verification. Drift SHALL fail typed. 057 SHALL NOT copy 054 DTO fields or
hash algorithms, mint another receipt, or treat a valid receipt as execution,
admission, ChangeSet, or release authority.

#### Scenario: a valid receipt belongs to another parsed artifact

- **WHEN** the receipt chain is internally valid but the task's ParsedDocument
  or ParseManifest artifact ref differs from the 057 verification
- **THEN** binding fails typed and the original 054 receipt remains unchanged

### Requirement: EEV7 pure narrow boundary

057 SHALL contain only frozen Pydantic DTOs, hashing, normalization, validation,
fixed deterministic checks, repair planning and focused tests. It SHALL perform
no Golden reads, model/provider calls, filesystem/environment/network I/O,
database/migration/worker operations, WeKnora writes, parser selection, or
release actions.

#### Scenario: verifier construction is pure

- **WHEN** the caller verifies a batch or plans one targeted repair
- **THEN** only in-memory deterministic operations occur
