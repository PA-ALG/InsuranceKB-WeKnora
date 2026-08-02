# 596-1 Golden18 Human Gate Specification

## ADDED Requirements

### Requirement: G18H1 exact authority and decisions

The gate SHALL bind the exact approved Golden18 authority hash and ordered P0-seven plus
P1-eleven field tuple. It SHALL require exactly one decision for every field in order,
with no duplicate, missing, extra or priority drift, and SHALL recompute the declared
decision hash. A decision may select the weak output, select the strong output, or
explicitly reject both for human diagnostic recording; the gate SHALL never generate or
default a decision. Only an exact eighteen-of-eighteen weak selection MAY verify. Any
strong selection SHALL return typed `WEAK_ARM_NOT_APPROVED`; any `reject_both` SHALL
return typed `HUMAN_DECISION_REJECTED`. Both outcomes SHALL keep Release and WeKnora
actions at zero.

#### Scenario: one field is omitted

- **WHEN** only seventeen decisions are provided
- **THEN** the result remains typed pending and no publication action exists

### Requirement: G18H2 exact subject and external named-human receipt

The gate SHALL compute one domain-separated subject from the authority, weak-output,
strong-output, score-report and decision hashes. Approval SHALL require an external,
closed receipt signed by an out-of-band trusted Ed25519 key for one exact named human.
The receipt SHALL bind that subject, decision hash, issue/expiry time, action and exact
source-thread, conversation and user-message provenance. The gate SHALL expose signing
bytes but no signing or self-approval API.

#### Scenario: service self-reports approval

- **WHEN** the receipt actor is a service, its signer is foreign, or provenance is a
  placeholder
- **THEN** the gate returns a typed block before any Release or WeKnora action

### Requirement: G18H3 freshness and tamper resistance

The gate SHALL use a caller-supplied timezone-aware observation time and reject a receipt
that is not yet valid or is expired at the exact boundary. Any subject, decision,
signature, receipt-hash, weak/strong output or score-report drift SHALL fail closed.

#### Scenario: a signed receipt is replayed after output drift

- **WHEN** either frozen output hash changes after the receipt was signed
- **THEN** exact subject verification blocks the replay

### Requirement: G18H4 pure typed outcome

The only successful state SHALL be `HUMAN_GATE_VERIFIED`, and it SHALL require all eighteen
decisions to select the weak arm plus an exact `approve` receipt. A strong diagnostic choice
or explicit human rejection SHALL return a typed block. Missing decisions or receipt SHALL
return typed pending. All other contract failures SHALL return typed block. The module SHALL
perform no filesystem,
environment, network, provider, DB, WeKnora, Golden or Release I/O.

#### Scenario: all eighteen decisions and receipt verify

- **WHEN** exact identities, decisions, signature, freshness and provenance all match
- **THEN** the gate returns a content-addressed verification result and performs zero
  publication action
