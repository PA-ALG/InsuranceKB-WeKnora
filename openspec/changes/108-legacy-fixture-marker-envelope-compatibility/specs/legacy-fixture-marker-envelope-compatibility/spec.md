# Legacy Fixture Marker-Envelope Compatibility Specification

## ADDED Requirements

### Requirement: LFMC1 explicit canonical marker fixtures

Every terms or rate legacy fixture that reaches the 083/091 intake MUST carry an
explicit marker provenance envelope. Each marker MUST declare kind, source,
page, node type, local index, native member and structural path. The fixture
MUST recompute the 091 marker/path/replay digests and capture identity.

#### Scenario: valid legacy fixture

- **WHEN** an existing 086 or 092 terms/rate fixture declares its markers
- **THEN** it passes the mandatory marker-envelope front door and reaches its
  unchanged original assertion

#### Scenario: marker mutation

- **WHEN** a test intentionally changes marker kind, page, path, member, source,
  parser/version or a derived hash
- **THEN** intake fails closed or the original invalid-marker assertion remains
  unchanged

### Requirement: LFMC2 zero authority synthesis

108 MUST be test-only. It MUST NOT add a production fallback, default marker,
empty-shell authority, naked trusted hash or relaxed validator. Brochure MUST
remain marker-free; zero-marker terms/rate fixtures MUST carry a canonical empty
envelope rather than omit the contract.

#### Scenario: production surface inspection

- **WHEN** the candidate diff is inspected
- **THEN** no production source or 102/105 module is modified

### Requirement: LFMC3 original business assertions preserved

The compatibility update MUST NOT change the business target or expected typed
reason of any affected test. A new failure after the marker front door MUST be
reported as a separate production blocker and MUST NOT be repaired in 108.

#### Scenario: bounded integration suite

- **WHEN** the original 086/092 modules run with canonical fixtures
- **THEN** the former 22 compatibility failures are green, or the first newly
  exposed production blocker is reported without production modification

### Requirement: LFMC4 privacy and execution boundary

Fixture content MUST remain synthetic and privacy-safe. 108 MUST NOT execute a
provider, parser capture, Golden scoring, database, WeKnora, live or full lane.

#### Scenario: validation

- **WHEN** focused/static/OpenSpec gates run
- **THEN** no credential, body, URL or absolute runtime path is emitted or added
