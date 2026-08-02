# Offline Single-Arm Raw Score Specification

## ADDED Requirements

### Requirement: OSA1 known Golden states retain business values

The exact approved 049 Golden parser SHALL retain a non-empty value for both `present`
and `absent_explicitly`. Only `unknown` SHALL map to null. A missing, blank, wrong-typed
or discarded known-state value SHALL fail the Golden contract rather than count as an
exact match.

#### Scenario: absent-explicit value differs

- **WHEN** state matches `absent_explicitly` but the arm value differs from the exact
  Golden business value
- **THEN** state exact is true and absent exact is false

### Requirement: OSA2 raw single-arm metrics are separated

The single-arm result SHALL separately bind state exact, present exact, absent exact,
Golden-known Evidence coverage and raw critical18 exact numerator/denominator pairs.
Raw critical18 exact SHALL compare the complete known-state value and SHALL NOT derive
from a DTO that drops absent-explicit values.

#### Scenario: one critical absent value is discarded

- **WHEN** a critical `absent_explicitly` field has the correct state but lacks its
  exact business value
- **THEN** it contributes to state exact but not absent exact or raw critical18 exact

### Requirement: OSA3 non-approved models are unadmitted raw diagnostics

The single-arm scorer SHALL return status `UNADMITTED_RAW` after all parser, artifact,
Schema60, Golden and structural checks pass when the output's semantic model or arm
profile is not the approved production profile. It SHALL include `ARM_PROFILE_MISMATCH` and/or
`ARM_AUTHORITY_MISMATCH` and MAY disclose the answer-safe raw metrics, but SHALL NOT
become production, fallback, judge, Review, Release or serving authority.

#### Scenario: exact GPT-5.6-sol offline ceiling

- **WHEN** the exact MinerU input is scored with the frozen offline GPT-5.6-sol identity
- **THEN** the result is `UNADMITTED_RAW`, not `SCORED`, while its raw metrics remain
  deterministic and receipt-bound

### Requirement: OSA4 approved weak profile remains scored

The single-arm scorer SHALL retain status `SCORED` only for an arm whose approved
DeepSeek semantic identity, model identity and arm-profile identity all match. Product,
source, Schema, parser,
prompt, budget, normalizer, comparator or admission drift SHALL continue to block before
Golden parsing.

#### Scenario: approved DeepSeek MinerU arm

- **WHEN** every approved identity is exact
- **THEN** the result is `SCORED` and carries no profile or authority mismatch

### Requirement: OSA5 offline comparison preserves the boundary

The 066 offline ceiling SHALL consume exactly weak=`SCORED` and
strong=`UNADMITTED_RAW`. Reversed, two-scored, two-raw, missing or foreign statuses SHALL
block. The resulting comparison remains an offline diagnostic and SHALL NOT create any
production or Release action.

#### Scenario: strong result pretends to be scored

- **WHEN** the strong slot returns `SCORED`
- **THEN** 066 blocks before emitting a comparison receipt

### Requirement: OSA6 scope and side effects remain narrow

071 SHALL change only the registered nine paths. It SHALL perform no provider, network,
filesystem, DB, WeKnora, Golden mutation, Release or GitHub operation and SHALL NOT
change Golden values, critical18 membership or production routing.

#### Scenario: offline scoring completes

- **WHEN** the focused offline scorer and comparator run
- **THEN** no provider, production, Release or Golden mutation action occurs
