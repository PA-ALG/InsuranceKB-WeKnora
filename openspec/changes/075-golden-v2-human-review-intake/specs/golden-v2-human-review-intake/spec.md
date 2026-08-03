# Golden v2 Human Review Intake Specification

## ADDED Requirements

### Requirement: G2I1 exact frozen identities and review authority

The intake SHALL bind Golden v1 SHA-256
`562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`,
workbook SHA-256
`ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf`,
and exactly these source SHA-256 identities in their declared authority order:
`88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc`,
`5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279`,
and `7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb`.
It SHALL bind the original ordered P0-seven plus P1-eleven tuple and require a bijection:
no missing, duplicate, extra, reordered, renamed or priority-drifted decision is valid.
`zh_2df7d6256c` and `zh_b7ceabc3c0` SHALL remain outside the decision authority and
byte-equivalent to v1.

#### Scenario: a nineteenth field is supplied

- **WHEN** a caller adds either excluded field or any other field to the eighteen rows
- **THEN** intake is typed blocked and produces zero successor records

### Requirement: G2I2 explicit replayable decision envelope

Every decision SHALL select exactly one of `accept_recommendation`, `keep_current`,
`custom`, `needs_expert` or `not_applicable` and SHALL bind the digest of its exact
current record, its exact recommended record when applicable, its complete custom record
when applicable, a non-blank reason outside the bounded placeholder vocabulary and
provenance. The bounded placeholder vocabulary SHALL include `TODO`, `TBD`,
`placeholder`, `unknown`, `待定`, `待确认` and `未知`, while a complete
explanation that merely contains one of those words SHALL remain valid. Placeholder
comparison SHALL normalize Unicode and whitespace, strip only surrounding common ASCII
and Chinese punctuation, and then perform exact vocabulary comparison. Intake SHALL recompute its
canonical decision hash. `accept_recommendation` SHALL require a complete bound
recommendation; `custom` SHALL require complete GoldenRecord semantics. A custom
`present` or `absent_explicitly` record SHALL carry replayable Evidence, while a custom
`unknown` record SHALL have a null value and no positive Evidence. Decisions SHALL never
be inferred or defaulted.

#### Scenario: review remains unresolved

- **WHEN** any selection is `needs_expert` or `not_applicable`
- **THEN** result remains typed pending and produces zero successor records; in this
  Mission `not_applicable` is always pending because no mapping exists

#### Scenario: placeholder reason carries surrounding punctuation

- **WHEN** a reason is exactly `TODO!`, `TBD???`, `待定。` or `未知！`
- **THEN** the normalized reason is rejected as a placeholder, while a substantive
  sentence that merely contains `unknown` or `TODO` remains valid

### Requirement: G2I3 external named-human receipt

The module SHALL expose canonical signing bytes and verification only, with no signer,
approval mint or default-approval API. The signed subject SHALL bind v1, workbook, all
three sources, the exact decisions hash, named-human actor, freshness window and exact
conversation provenance. Verification SHALL reject a service or self-reported approval,
placeholder actor, foreign key, malformed signature, stale or future receipt, changed
decision, changed workbook or changed provenance. Only an exact out-of-band trusted
named-human Ed25519 receipt MAY yield `HUMAN_DECISIONS_VERIFIED`.
The publicly constructible verification result SHALL be diagnostic only and SHALL NOT be
accepted as materialization authority. Materialization SHALL receive the original receipt,
authority and observation time and SHALL internally replay the complete intake, including
recomputing the decisions hash from the actual request rows.

#### Scenario: workbook identity changes after signing

- **WHEN** a receipt is replayed against a different workbook hash
- **THEN** receipt verification is typed blocked and no materialization occurs

### Requirement: G2I4 pure deterministic successor materialization

The formal materialization entry SHALL accept the actual v1 JSONL bytes, hash those bytes
against the fixed v1 identity before parsing, and derive exactly sixty complete
GoldenRecord values from those bytes. Arbitrary caller-supplied record tuples SHALL NOT
be labelled as a formal v1 successor. A private synthetic test helper MAY exercise the
selection mechanics only if its result is explicitly bound as `SYNTHETIC_TEST_ONLY`.
After internally replaying named-human verification, materialization SHALL preserve input
ordering, select the exact current record for `keep_current`, the exact recommendation
for `accept_recommendation`, and the exact complete record for `custom`. Only the
eighteen authorized field positions MAY change; all other forty-two canonical record
hashes SHALL remain identical. High-risk occupation and product tier SHALL remain
byte-equivalent to formal v1. The output SHALL be in memory only and SHALL include a
domain-separated content-addressed successor receipt bound to the actual artifact hash
and artifact profile.

#### Scenario: the same verified synthetic input is replayed

- **WHEN** the exact sixty records, decisions and receipt are supplied twice
- **THEN** the synthetic test profile ordering, record content and successor receipt are
  identical without claiming formal v1 identity

#### Scenario: arbitrary synthetic bytes use the formal entry

- **WHEN** supplied bytes do not hash to the fixed formal v1 JSONL identity
- **THEN** materialization is typed blocked before parsing and produces zero records

### Requirement: G2I5 immutable and offline boundary

The module SHALL perform no filesystem or environment read/write, Excel parsing,
provider/model/scoring call, DB/migration, WeKnora, live, Release activation or production
action. It SHALL not read or mutate Golden v1 and SHALL not create a Golden v2 directory
or JSONL. Any unresolved or invalid input SHALL return zero successor records.

#### Scenario: no external human receipt exists

- **WHEN** all eighteen decisions are structurally complete but the receipt is absent
- **THEN** status is `READY_FOR_EXTERNAL_APPROVAL`, signing bytes may be obtained, and
  successor records remain empty
