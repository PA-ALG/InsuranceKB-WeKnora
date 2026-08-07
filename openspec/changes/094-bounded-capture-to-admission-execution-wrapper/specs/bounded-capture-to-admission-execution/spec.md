# 596-1 Bounded Capture-to-Admission Execution Wrapper

## ADDED Requirements

### Requirement: BCA1 exact frozen input authority

The wrapper SHALL bind the exact ordered roles `terms`, `brochure`, `rate_table`, their approved
596-1 PDF SHA-256 values, one expected capture executable SHA-256, the fixed capture module
identity, and exact capture/intake/admission contract hashes before capture.

#### Scenario: identity drift

- **WHEN** any source, role, executable, module or contract identity is missing or drifted
- **THEN** the wrapper returns a fixed typed blocked status before capture and 087 calls

### Requirement: BCA2 one ordered execution

The wrapper SHALL execute capture exactly once. Only after successful custody validation SHALL it
call 087 exactly once with `terms → brochure → rate_table` artifacts and one exact relation
receipt. Retry, fallback and parallel execution are forbidden.

#### Scenario: capture fails

- **WHEN** the one capture invocation raises, returns non-success or produces invalid custody
- **THEN** 087 invocation count is zero and the wrapper returns a fixed capture blocked status

#### Scenario: 087 blocks

- **WHEN** 087 returns an allowlisted blocked status
- **THEN** the wrapper preserves that exact status and exposes no artifact or receipt identity

### Requirement: BCA3 private custody

Before capture the output root SHALL be a new direct child of `/private/tmp`. After capture it
SHALL be a non-symlink directory with mode `0700`, containing only exact `terms`, `brochure` and
`rate` directories at mode `0700`; each SHALL contain only
`mineru-native-structure.json`, a non-symlink regular file at mode `0600`. The independent relation
receipt SHALL be a non-symlink regular `0600` file with its exact caller-approved SHA-256.

#### Scenario: namespace or mode drift

- **WHEN** a symlink, duplicate inode, unexpected file, wrong mode or byte hash is observed
- **THEN** the wrapper blocks before 087 and never publishes a partial final result

### Requirement: BCA4 credential and output privacy

The MinerU credential SHALL enter only as a parent-process `SecretStr` and the capture child
environment. It SHALL NOT occur in argv, captured stdout/stderr, a receipt, result or exception.
The wrapper SHALL discard child stdout/stderr and expose only allowlisted status and hashes; raw
body, URL, private absolute path and dependency exception text are forbidden.

#### Scenario: dependency raises sensitive text

- **WHEN** capture or 087 raises an exception containing a secret, URL, body or absolute path
- **THEN** the emitted result contains only the fixed typed status and safe counters

### Requirement: BCA5 unique dependency and safe success

The existing Go `cmd/mineru-capture-596-1` command SHALL be the only capture dependency. A
successful result SHALL bind three artifact byte hashes, three 087 outer hashes, the common 087
receipt digest and all dependency contract identities. It SHALL claim neither Golden scoring nor
Release authority.

#### Scenario: exact synthetic success

- **WHEN** injected fake capture and 087 adapters satisfy every frozen identity and custody check
- **THEN** the result is `CAPTURE_TO_ADMISSION_VERIFIED`, capture count is one, 087 count is one,
  and no provider was actually called by the test

### Requirement: BCA6 dependency staging

091, 092 and 087 SHALL be consumed only through narrow Protocols until their exact implementations
are merged. An unavailable adapter SHALL fail before credential or filesystem access.

#### Scenario: composition missing

- **WHEN** the CLI has no composed dependency set
- **THEN** it returns `DEPENDENCY_UNAVAILABLE` with zero capture and 087 calls
