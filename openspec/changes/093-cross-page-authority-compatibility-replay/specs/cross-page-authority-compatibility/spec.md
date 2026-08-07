# Cross-page authority compatibility replay specification

## ADDED Requirements

### Requirement: CAR1 exact task-local replay envelope

093 SHALL accept only canonical JSON bytes for one fixed 596-1 replay envelope containing
exactly ordered `terms` and `rate_table` sources. Source role SHALL be derived only from the
approved source SHA, never from a filename or a caller alias. The terms vector SHALL describe
a section relation between two actual cross-page block endpoints; the rate-table vector SHALL
describe a table continuation between two actual cross-page table endpoints.

#### Scenario: rate role is shortened to rate

- **WHEN** a fully rehashed vector uses `rate` instead of `rate_table`
- **THEN** replay returns typed `BLOCKED` at the vector identity boundary

### Requirement: CAR2 089 marker to 086 binding boundary

Replay SHALL distinguish `cross_page` from `lines_deleted`, bind the exact source/parser/version,
marker item/envelope hashes, zero-based marker page and canonical structural-path identity, and
verify that the 089 producer exposes every endpoint/page/relation field required by the 086
consumer. Missing endpoint authority SHALL be reported at `089_TO_086`; it SHALL NOT be inferred
from adjacent blocks/tables or from the fixture.

#### Scenario: current 089 companion is replayed

- **WHEN** the companion contains typed marker provenance but intentionally no endpoints
- **THEN** the result is `BLOCKED / MARKER_ENDPOINT_AUTHORITY_NOT_EXPOSED`

### Requirement: CAR3 086 binding to 090 injection boundary

Replay SHALL compare the exact 086 relation binding with the 090 Protocol, including contract,
continuation relation kind, source SHA, parser ID/build/config, raw/sanitized hashes,
material-profile binding, policy-context hash, replay-context hash, ordered endpoint IDs and
canonical injection binding hash. A nested endpoint DTO or a self-consistent foreign policy/hash
SHALL NOT be treated as compatible.

#### Scenario: current 086 binding is replayed

- **WHEN** it contains `table|section`, nested endpoints and its own policy/replay digest but lacks
  the 090 injection context fields
- **THEN** the matrix reports `BLOCKED / INJECTION_CONTEXT_NOT_BOUND` at `086_TO_090`

### Requirement: CAR4 canonical bytes and precise drift attribution

Replay SHALL reject non-canonical JSON, duplicate/extra/missing fields, changed key ordering or
encoding, changed domain/hash algorithm, source/parser/version/policy/endpoint/page drift,
`rate`/`rate_table` confusion and `cross_page`/`lines_deleted` confusion. Each failure SHALL name
exactly one boundary and a fixed reason code without including untrusted values.

#### Scenario: hashes are recomputed using sorted plain JSON SHA-256

- **WHEN** all payload hashes are internally consistent under the wrong preimage algorithm
- **THEN** replay returns typed `BLOCKED` at the first affected boundary

### Requirement: CAR5 no authority elevation

The verifier result SHALL be only `COMPATIBILITY_VERIFIED` or typed `BLOCKED`. It SHALL NOT emit
an 086 binding, mutate a 090 input, call 060, or claim ParseQuality ADMIT, 061 READY, Release or
provider authority. The exported matrix is informative compatibility evidence for091/092 only.

#### Scenario: all compatibility fields match

- **WHEN** a future exact vector satisfies both boundary contracts
- **THEN** 093 may return `COMPATIBILITY_VERIFIED` but no downstream action

### Requirement: CAR6 bounded delivery

093 SHALL change exactly seven paths: registry, four OpenSpec files, one task-local module and one
focused test. It SHALL NOT modify089/086/090/084/087, public schemas or runtime services.

#### Scenario: compatibility needs a production adapter

- **WHEN** verification discovers a real mismatch
- **THEN** 093 records the unique owner/path and stops rather than implementing the adapter
