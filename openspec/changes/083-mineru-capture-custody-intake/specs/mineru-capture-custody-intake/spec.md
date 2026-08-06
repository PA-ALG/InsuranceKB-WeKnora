# MinerU Capture Custody Intake Specification

## ADDED Requirements

### Requirement: MCI1 bytes-only closed custody

The intake SHALL accept exactly three `bytes` payloads and SHALL reject non-UTF-8,
duplicate-key, non-integral typed counters, trailing-data, missing-key and extra-key JSON. It SHALL perform
no filesystem, environment, credential, network, provider, database or WeKnora operation.

#### Scenario: caller supplies a path or an extended payload

- **WHEN** input is not bytes or any object contains an unknown member
- **THEN** intake raises a fixed typed reason and returns no bundle

### Requirement: MCI2 exact 596-1 capture identity

The three positional payloads SHALL be terms, brochure and rate in that order and SHALL
carry their frozen source SHA-256 values. Each SHALL bind attempt `2`, role
`bounded_upgrade`, generation `0`, the frozen MinerU engine/implementation/native-schema/
model/config identity, allocation `1`, upload `1`, status GET count `1..190`, ZIP GET `1`
and status `completed`. Sanitized-structure bytes, content bytes and the Go capture-identity
preimage SHALL be independently recomputed.

#### Scenario: a locally self-consistent but foreign capture is supplied

- **WHEN** any role, source, attempt, parser, call, status or capture edge differs
- **THEN** the complete intake fails closed

### Requirement: MCI3 native cross-page envelope replay

Terms SHALL carry the exact `cross_page_sections` envelope, rate SHALL carry
`cross_page_tables`, and brochure SHALL omit the optional envelope. Member inventory and
projection digests SHALL be replayed from the closed typed envelope. Status/count/relation
invariants SHALL match the existing native-fact contract; no relation is inferred.

#### Scenario: cross-page evidence is relabelled or locally mutated

- **WHEN** capability, source, member inventory, status, observations or relations drift
- **THEN** the payload is rejected without constructing a bundle

### Requirement: MCI4 immutable ordered bundle

Successful intake SHALL return immutable typed source records in exact terms → brochure →
rate order and one canonical domain-separated bundle digest. The digest SHALL bind each
role, source, capture identity and per-source intake digest. Equivalent bytes SHALL produce
the same result.

#### Scenario: bundle order changes

- **WHEN** otherwise valid source payloads are reordered
- **THEN** exact positional source validation rejects the bundle

### Requirement: MCI5 privacy-safe failure and representation

The intake SHALL keep raw content and sanitized structure only inside the validated
immutable DTO and SHALL exclude them from `repr` and ordinary model serialization. Absolute local paths,
credential-like material, signed URLs and secret-bearing structural members SHALL fail
closed. Exceptions SHALL expose only fixed reason codes and SHALL never echo input bytes.

#### Scenario: hostile content contains a secret or private path

- **WHEN** a fully rehashed payload contains prohibited private material
- **THEN** intake raises a fixed typed error whose string and representation contain none
  of that material

### Requirement: MCI6 custody is not admission

The API SHALL expose no builder for `ParsedDocument`, `ParseManifest`, Golden scoring or
ADMIT. Its status identifies capture-custody validation only.

#### Scenario: downstream requests parsed-document authority

- **WHEN** capture intake succeeds
- **THEN** the result remains non-authoritative evidence input and grants no parse or
  release decision
