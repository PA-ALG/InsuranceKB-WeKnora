# 086 Marker-Preserving Intake Replay Seam Specification

## ADDED Requirements

### Requirement: MPRS1 default replay compatibility

The existing 086 replay mode MUST remain the default and MUST NOT synthesize,
infer or auto-fill marker evidence. A legacy input without a marker envelope
MUST retain its existing typed result.

#### Scenario: legacy no-marker input

- **WHEN** the compatibility mode is not explicitly selected, or no typed marker
  envelope exists
- **THEN** replay has the same bytes and typed result as the frozen predecessor

### Requirement: MPRS2 exact marker-envelope replay

The compatibility mode MUST retain the complete validated 091 envelope,
including kind, page, node type, local index, native member, structural path,
node evidence and replay preimage/digests. It MUST re-enter the public 083 intake
validator so every marker and envelope digest is recomputed rather than trusted.

#### Scenario: marker drop regression

- **WHEN** a valid 083/091 bundle is replayed through the frozen default path
- **THEN** the existing `INTAKE_REPLAY_FAILED` counterexample remains observable
  and the explicit 102 path succeeds without changing the supplied envelope

#### Scenario: mutated marker custody

- **WHEN** marker order, cardinality, kind, source, member, parser/version,
  structural path/node identity, raw ZIP or any replay digest drifts
- **THEN** replay returns a fixed typed failure and emits no binding or receipt entry

### Requirement: MPRS3 unchanged 086 relation authority

102 MUST pass only a revalidated 098 endpoint-pair replay object to the frozen
086 evaluator. It MUST NOT alter candidate selection, endpoint validation,
relation policy or binding digest rules.

#### Scenario: unique future table pair

- **WHEN** one complete synthetic marker and one unique compatible table pair
  satisfy 098 and frozen 086 policy
- **THEN** 086 returns `DERIVED_STRUCTURAL_BINDING_VERIFIED` and the binding is
  accepted by the existing 096 receipt-entry contract

#### Scenario: unavailable or ambiguous evidence

- **WHEN** evidence is `lines_deleted`, section-only without explicit block refs,
  or has zero/multiple candidates
- **THEN** the frozen typed `BLOCKED`/`NOT_AVAILABLE` result remains unchanged

### Requirement: MPRS4 privacy and authority boundary

The seam MUST be pure in-memory composition. It MUST NOT read a path, credential,
provider, model, Golden, database or WeKnora state and MUST NOT claim NATIVE,
ADMIT or READY.

#### Scenario: output inspection

- **WHEN** a binding or receipt entry is rendered
- **THEN** it contains only the already validated custody identities and no body,
  URL, secret or absolute filesystem path
