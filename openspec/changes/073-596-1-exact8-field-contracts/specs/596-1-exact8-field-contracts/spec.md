# 596-1 Exact8 Field Contracts Specification

## ADDED Requirements

### Requirement: EFC1 exact8 identity and source authority are immutable

The task-local contract SHALL contain exactly the approved ordered eight field IDs,
their exact field names and their existing 052 authority class, primary material role
and support roles. It SHALL NOT alter the global Schema or infer authority from a model,
filename or Golden value.

#### Scenario: field order or source authority drifts

- **WHEN** an exact8 consumer replays a reordered, missing, extra or authority-drifted row
- **THEN** the canonical exact8 bundle hash differs and authority verification blocks

### Requirement: EFC2 only four no-decision fields are frozen

The contract SHALL freeze only `clause_version`, `zh_1ec5e3f2cc`,
`zh_3d8424595d` and `zh_f32c510a5e` as `FROZEN_NO_USER_DECISION_REQUIRED`.
The other four SHALL remain
`NONE_PENDING_USER_CONFIRMATION` and SHALL contain no choice, option, selected value or
default.

#### Scenario: pending field is inspected before user confirmation

- **WHEN** a caller reads the task-local exact8 contract
- **THEN** it sees only the pending state and decision-package identity, never a
  prefilled business choice

### Requirement: EFC3 pending fields bind the exact decision package

Every pending row and the authority request SHALL bind decision-package SHA-256
`43af184fc27295467b5130b1b88953c073049fd02309b78c53ac59d6f1937e26`.
A different, missing, malformed or placeholder identity SHALL fail closed.

#### Scenario: decision package drifts

- **WHEN** an otherwise valid request names another package hash
- **THEN** the result is `BLOCKED_ON_FIELD_CONTRACT_AUTHORITY` before any provider call

### Requirement: EFC4 exact external user receipt is mandatory

The verifier SHALL accept only an unexpired externally signed named-human receipt whose
subject exactly binds the exact8 bundle hash, decision-package hash, external pending
resolution-bundle hash and conversation provenance. The module SHALL expose verification
bytes but SHALL NOT expose a signer or create a user decision.

#### Scenario: receipt is missing

- **WHEN** the exact request has no external user receipt
- **THEN** the result is `BLOCKED_ON_FIELD_CONTRACT_AUTHORITY`, reason is
  `EXACT_USER_RECEIPT_MISSING`, and `provider_calls=0`

#### Scenario: exact external receipt verifies

- **WHEN** a named human signs the exact subject and every identity and time bound replays
- **THEN** authority status is verified but the four task-local rows remain
  `NONE_PENDING_USER_CONFIRMATION`; their business choices stay outside this module

### Requirement: EFC5 side effects and scope are zero

The contract and verifier SHALL be pure. Every blocked and verified result SHALL report
`provider_calls=0`, `release_actions=0` and `weknora_actions=0`. 073 SHALL change only
the registered seven paths and SHALL NOT read model answers or Golden values.

#### Scenario: malformed or service-issued receipt is evaluated

- **WHEN** receipt shape, actor, signature, subject, provenance, time or content hash fails
- **THEN** the verifier returns a typed block without provider, Release or WeKnora action
