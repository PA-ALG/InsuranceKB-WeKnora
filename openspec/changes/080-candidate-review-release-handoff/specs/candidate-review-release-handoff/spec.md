# Candidate Review Release Handoff Specification

## ADDED Requirements

### Requirement: CRH1 one Candidate drives all projections

The builder SHALL revalidate exactly one complete 059 `CandidateAssemblyV1` and SHALL pass
that same Candidate and exact 057 `FieldCandidateV1` set to the unchanged 076 and 077 public
builders. The resulting manifest, dossier and preparation vector SHALL all carry the exact
Candidate hash, human-batch hash, review-policy hash, Space and ProductVersion derived from
that one Candidate. No caller-supplied duplicate Candidate identity SHALL be accepted.

#### Scenario: one projection is built from a different Candidate

- **WHEN** any projection carries another Candidate, batch, policy or scope identity
- **THEN** construction or replay fails closed before a handoff is returned

### Requirement: CRH2 existing 076 and 077 custody remains authoritative

The handoff SHALL contain the complete immutable 076 member/manifest draft and complete 077
review dossier returned by their existing builders. It SHALL NOT reproduce their FieldFact,
Evidence, ChangeSet, locator, member or rendering validation. Any Candidate, FieldFact,
Evidence, ChangeSet, base, member or manifest mutation rejected by 076 or 077 SHALL produce
one typed handoff failure and no partial output.

#### Scenario: Evidence or Wiki member identity drifts

- **WHEN** the supplied Evidence custody or a materialized member differs from the exact
  Candidate chain
- **THEN** the handoff is rejected and no other projection is exposed

### Requirement: CRH3 preparation vector is input-only and 059-consumable

The preparation vector SHALL bind the Candidate digest, complete canonical 076 manifest and
members, exact human-batch hash, review-policy hash, base release identity, Space and
ProductVersion. It SHALL explicitly carry preparation-only authority and SHALL contain no
human decision digest, signature, approval, Ready state, Release or Active Head. A later 059
consumer MAY combine it with independently verified named-human authority; 080 SHALL NOT do
so.

#### Scenario: caller requests approval or activation material

- **WHEN** 080 is asked to mint a decision, signature, ReadyReceipt, Release or Head
- **THEN** no such field or operation exists at this boundary

### Requirement: CRH4 cross-verification is mechanical

The aggregate SHALL be immutable and domain-hashed. Its validator SHALL revalidate every
nested public DTO and require exact equality across Candidate, dossier and preparation
Candidate/batch/policy identities; exact Space/ProductVersion and ChangeSet custody; exact
manifest bytes/digest/member set; and exact base release identity. Callers SHALL NOT be able
to authorize a binding by supplying a matching free-form hash.

#### Scenario: a nested hash is recomputed around foreign content

- **WHEN** any nested object is changed and its local hash is made self-consistent
- **THEN** the independent cross-edge comparison still fails closed

### Requirement: CRH5 deterministic failure-zero-output boundary

Equivalent input ordering SHALL produce identical nested bytes and handoff hash. The builder
SHALL construct all three projections in memory and return them only after complete
cross-validation. It SHALL perform no filesystem, environment, network, subprocess,
database, provider, Golden, WeKnora, signing, preparation persistence or serving operation.

#### Scenario: validation fails after one projection is computed

- **WHEN** a later projection or cross-edge fails validation
- **THEN** only a typed error is raised and no partial aggregate or external output exists
