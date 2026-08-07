# 087 Actual Dependency Wiring Specification

## ADDED Requirements

### Requirement: ADW1 exact private-file and dependency preflight

095 SHALL resolve the exact 091/083, 096/086 and 092 public dependency surfaces before
opening any input. Missing modules, symbols or incompatible call signatures SHALL return
`DEPENDENCY_UNAVAILABLE` with zero file reads and zero partial output. Once resolved, the
four files SHALL retain 087's exact order, regular-file, no-follow, `0600`, unique-inode
and one-read guarantees.

#### Scenario: 096 implementation is absent

- **WHEN** the separately owned 096 public validator cannot be resolved exactly
- **THEN** the result is `DEPENDENCY_UNAVAILABLE` before any path is opened

### Requirement: ADW2 exact 091/083 bundle intake

095 SHALL call `intake_mineru_capture_bundle_596_1` exactly once with an exact tuple of
terms, brochure and rate bytes. It SHALL pass the returned immutable bundle directly to
the relation validator and 092. It SHALL NOT parse raw JSON, recompute hashes, synthesize
IDs or turn rate into rate_table.

#### Scenario: input order or bundle identity drifts

- **WHEN** source order, role, bundle identity or any underlying bytes drift
- **THEN** intake blocks, relation/admission calls remain zero and no partial receipt is exposed

### Requirement: ADW3 096/086 receipt validation boundary

095 SHALL call an exact 096 validator once with relation-receipt bytes, the exact intake
bundle and the public 086 replay authority required by that validator Protocol. Its result
must supply the exact 092 source-authority, material-profile, marker-map and relation-provider
inputs without a local duplicate DTO or hash implementation. `BLOCKED_ON_CROSS_PAGE_BINDING`
SHALL propagate unchanged; missing or incompatible authority SHALL fail closed. The frozen
096 DTO-only replay is incompatible with this bytes-to-092 Protocol and SHALL therefore
resolve to `DEPENDENCY_UNAVAILABLE` before input bytes are opened.

#### Scenario: receipt validation raises sensitive detail

- **WHEN** the validator raises with a secret, URL, body or absolute path
- **THEN** the result contains only a fixed typed status and no attacker-controlled text

#### Scenario: frozen 096 exposes DTO replay but not bytes-to-092 authority

- **WHEN** the exact 096 public callable accepts only a parsed receipt DTO and returns no 092 authority inputs
- **THEN** production resolution is `DEPENDENCY_UNAVAILABLE` before file I/O and no local adapter invents those inputs

### Requirement: ADW4 exact 092 admission call

095 SHALL invoke `assemble_relation_bound_admission_596_1` exactly once with the exact
083 bundle and validator-supplied public inputs, plus the existing exact trusted builder.
It SHALL accept only zero provider/Golden counters and the exact successful 092 status
with a valid integration digest. All drift, DTO mismatch or exception paths SHALL expose
zero receipt.

#### Scenario: rate role reaches admission

- **WHEN** the exact intake bundle is passed to 092
- **THEN** 095 preserves its `rate` role and only 092 performs `rate` → `rate_table`

### Requirement: ADW5 composition-only result

Only the exact synthetic success path SHALL emit `COMPOSITION_SEAM_VERIFIED` and the
092 integration digest. It SHALL never emit `READY`, `ADMIT`, a Release identity or a
real MinerU success claim. Provider/model/Golden/DB/WeKnora counters remain zero.

#### Scenario: 092 remains relation blocked

- **WHEN** exact public composition returns a cross-page dependency block
- **THEN** output is `BLOCKED_ON_CROSS_PAGE_BINDING` with zero partial identity or digest
