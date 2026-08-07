# Bounded Real-capture Readiness Gate Specification

## ADDED Requirements

### Requirement: BCR1 frozen real public authority only

The formal gate SHALL use a code-owned ordered authority tuple for
`091 → 098 → 086 → 096 → 095/087 → 094`. Each entry binds exact contract/version,
implementation blob, public API schema, canonical preimage, context, policy and replay
hashes. Missing authority or implementation SHALL stop at the earliest dependency.
Caller-provided Protocol fakes, 097 synthetic rehearsal evidence and self-consistent
foreign identities SHALL NOT satisfy formal readiness.

#### Scenario: current main lacks 091 frozen authority

- **WHEN** formal readiness is evaluated on the current approved authority tuple
- **THEN** it returns `FROZEN_DEPENDENCY_AUTHORITY_UNAVAILABLE_091` before artifact or
  credential access

### Requirement: BCR2 exact three-source and private-access contract

The gate SHALL require exact ProductVersion `596-1`, fixed
`terms → brochure → rate_table` source SHA order, regular non-symlink artifact files at
mode `0600`, mode `0700` private parents and safe opaque path-identity hashes. It SHALL
not accept or output an absolute path, URL, credential, body or raw artifact.

#### Scenario: one artifact path or mode is unsafe

- **WHEN** a role is missing/reordered, a source hash drifts, a symlink is present or
  file/parent mode differs
- **THEN** readiness is blocked without inspecting artifact contents

### Requirement: BCR3 exact custody and relation chain

Every dependency evidence SHALL recompute its canonical preimage and receipt SHA-256,
bind the exact predecessor receipt and match its approved context/policy/replay hashes.
091 SHALL bind custody; 098 SHALL bind endpoint-derivation input; 086 SHALL bind a
verified relation; 096 SHALL bind its relation receipt; 095/087 SHALL bind the exact
dependency map; and 094 SHALL bind one invocation with retry/fallback zero.

#### Scenario: all hashes are recomputed around a foreign context

- **WHEN** a dependency changes context, policy, replay identity or predecessor receipt
- **THEN** the gate returns the exact dependency drift reason before later evaluation

### Requirement: BCR4 cross-page evidence remains fail closed

The readiness gate SHALL return `BLOCKED_ON_CROSS_PAGE_BINDING` for an old marker
with one endpoint, a missing endpoint, an unverified 086 binding or a missing 096
relation receipt. The gate
SHALL NOT infer an endpoint from path hashes, adjacent pages or Markdown and SHALL not
substitute the 097 future-complete synthetic fixture as evidence.

#### Scenario: 098 reports single-endpoint-only evidence

- **WHEN** all earlier identities match but 098 lacks an exact endpoint pair
- **THEN** readiness returns `BLOCKED_ON_CROSS_PAGE_BINDING` and later dependencies are
  not evaluated

### Requirement: BCR5 test-only future completeness

The readiness gate SHALL allow an explicit `TEST_ONLY_COMPLETE_FIXTURE` to exercise
every validation branch and return status `READY_FOR_ONE_BOUNDED_CAPTURE`, but its result SHALL be labelled
`TEST_ONLY` with `capture_authorized=false`. Only evidence class
`REAL_PUBLIC_ADAPTER`, pinned by the code-owned formal authority tuple, may eventually
return the same status with capture authorization.

#### Scenario: a complete future fixture is evaluated

- **WHEN** exact test identities, source order, permissions, predecessor chain,
  endpoint pair and wrapper policy all match
- **THEN** mechanical readiness is proven while capture remains unauthorized

### Requirement: BCR6 privacy-safe typed output

The result SHALL contain only a typed status/reason, evidence class, authorization
boolean, evaluated dependency IDs and safe contract/version/hash summaries. Any unsafe
reason, exception, external effect counter, credential marker, absolute path, raw body
or synthetic authority claim SHALL fail closed without being copied to output.

#### Scenario: a dependency reason contains sensitive text

- **WHEN** evidence includes a non-allowlisted reason string
- **THEN** the result uses a stable generic typed block and reveals none of the input

### Requirement: BCR7 bounded delivery

099 SHALL use at most seven paths: registry, four OpenSpec files, one task-local module
and one focused test. It SHALL add no deployment workflow, capture executor, credential
loader, migration, shared schema or generic readiness framework.

#### Scenario: implementation needs shared dependency edits

- **WHEN** GREEN requires an eighth path or modifying 091/098/086/096/095/087/094
- **THEN** implementation stops and reports the exact blocker instead of expanding
