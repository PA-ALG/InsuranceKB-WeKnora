# Marker Authority Readiness Wiring

## ADDED Requirements

### Requirement: MARW1 — Actual 101 authority is replayed before use

The wiring SHALL accept only `MarkerAuthorityEnvelopeV1`, validate the exact
contract/product/source order and `UNBOUND` relation authority, recompute every
canonical preimage/hash used by the composition, and cross-bind terms and rate
source/member/parser/version/marker facts to the intake supplied to actual 098.

Any naked hash, missing preimage, source/role/member/parser/version/marker-map
drift, or non-`UNBOUND` authority SHALL fail closed with no readiness result.

#### Scenario: Drifted public authority is rejected

- **WHEN** any bound authority fact or its canonical preimage/hash drifts
- **THEN** the result SHALL be `MARKER_AUTHORITY_INVALID`
- **AND** capture SHALL remain unauthorized

### Requirement: MARW2 — Actual 098 evidence is mechanically translated

After the terms authority exists, the wiring SHALL invoke the actual 098
endpoint-pair API and translate the actual 101 and 098 contract, implementation,
schema, context, policy, replay and receipt identities into 099 evidence.

It SHALL NOT infer a relation, endpoint, page, source role or marker fact.

#### Scenario: Rate-table pair is replayed

- **GIVEN** exact 101 authority, exact matching intake and a verified terms binding
- **WHEN** the future-fixture composition runs
- **THEN** it SHALL call 098 exactly once
- **AND** the 098 replay digest SHALL be bound into 099 evidence

### Requirement: MARW3 — Current earliest blocker is exact

Until 103 supplies a verified terms-section binding, the formal result SHALL be
`TERMS_SECTION_BINDING_UNAVAILABLE`, SHALL NOT invoke 098 or 099, and SHALL have
`capture_authorized=false`.

#### Scenario: Current authority lacks terms binding

- **GIVEN** a valid current 101 envelope
- **WHEN** the formal wiring is evaluated
- **THEN** it SHALL return `TERMS_SECTION_BINDING_UNAVAILABLE`
- **AND** 098 and 099 SHALL each be called zero times

### Requirement: MARW4 — Future completeness remains test-only

An explicitly separate future-fixture entry point SHALL compose a verified 103
binding and downstream 102/096/100/095 evidence through actual 098 and 099. It
SHALL require `TEST_ONLY_COMPLETE_FIXTURE`, reject fake/synthetic evidence in
the formal path, and return `READY_FOR_ONE_BOUNDED_CAPTURE` only with
`evidence_class=TEST_ONLY` and `capture_authorized=false`.

#### Scenario: Complete future fixture is not capture authority

- **GIVEN** complete test-only future dependency evidence
- **WHEN** the future-fixture composition reaches 099 readiness
- **THEN** its status MAY be `READY_FOR_ONE_BOUNDED_CAPTURE`
- **BUT** its evidence class SHALL be `TEST_ONLY`
- **AND** `capture_authorized` SHALL be false

### Requirement: MARW5 — Zero external effects

The wiring SHALL be pure in-memory composition. It SHALL read no credentials or
private artifacts and perform no capture, provider/model/Golden/DB/PG/WeKnora,
filesystem-output or release action.

#### Scenario: Wiring remains pure

- **WHEN** either entry point is evaluated
- **THEN** provider, model, Golden, DB, PG, WeKnora and capture calls SHALL be zero
- **AND** no private artifact or credential SHALL be read
