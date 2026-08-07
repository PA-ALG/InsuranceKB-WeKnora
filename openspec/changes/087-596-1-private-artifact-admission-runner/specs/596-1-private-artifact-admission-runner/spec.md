# 596-1 Private Artifact Admission Runner Specification

## ADDED Requirements

### Requirement: PAR1 exact private input boundary

The runner SHALL accept exactly four distinct paths: terms, brochure, rate-table custody
artifacts in that order and one relation receipt. It SHALL open each no-follow, require a
regular file with exact mode `0600`, and read it once. Missing, symlinked, duplicated,
reordered or incorrectly permissioned inputs SHALL fail before validator or assembler calls.

#### Scenario: one artifact is group-readable

- **WHEN** any input mode differs from `0600`
- **THEN** the result is typed input blocked with no validated identity or admitted output

### Requirement: PAR2 validators own content authority

Each artifact byte sequence SHALL be passed exactly once to the 083 validator with its fixed
expected role. Relation bytes SHALL be passed exactly once to the 086 validator. The runner
SHALL NOT parse raw JSON/structure, recompute hashes, infer parser facts or retry. Validator
failure or any role/hash/parser/attempt/relation drift SHALL fail closed.

#### Scenario: intake validator rejects parser identity

- **WHEN** the validator returns a typed failure or raises at the validation boundary
- **THEN** no later validator/assembler retry occurs and no partial result is exposed

### Requirement: PAR3 084 owns admission

After all validators succeed, the runner SHALL call the 084 adapter exactly once with the
three validated intakes and admitted relation bindings. It SHALL require provider and Golden
counters to remain zero. `BLOCKED_ON_CROSS_PAGE_BINDING` SHALL be preserved exactly with no
receipt or partial bundle.

#### Scenario: 084 remains cross-page blocked

- **WHEN** the assembler returns `BLOCKED_ON_CROSS_PAGE_BINDING`
- **THEN** the runner emits that status, zero identities/receipt digest and no partial brochure

### Requirement: PAR4 success is composition-only

A synthetic assembler success SHALL produce only `COMPOSITION_SEAM_VERIFIED`, three ordered
safe artifact identities and one common receipt digest. It SHALL NOT emit current-runtime READY,
ADMIT, Release or production authority.

#### Scenario: fake seam reaches its success branch

- **WHEN** all four fake validators and the fake assembler complete once within contract
- **THEN** output records composition seam verification without claiming real MinerU READY

### Requirement: PAR5 output is privacy-safe and atomic

The command SHALL emit exactly one canonical JSON object after the full run. It may contain
only allowlisted status, role, contract/hash identities, zero external-call counters and common
receipt digest. It SHALL contain no raw/body text, artifact bytes, filename or absolute path,
URL, secret, header or raw exception detail. No repository or final artifact file is written.

#### Scenario: dependency raises sensitive detail

- **WHEN** a validator raises an exception containing body, path, URL or secret text
- **THEN** the output contains only a fixed typed status and no attacker-controlled value
