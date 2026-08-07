# 596-1 No-provider Full Synthetic Vertical Rehearsal Specification

## ADDED Requirements

### Requirement: NPV1 exact synthetic input and order

097 SHALL accept only ProductVersion `596-1` and the exact ordered roles and source
SHA-256 identities `terms → brochure → rate_table`. The capture port and every later
dependency port SHALL be invoked at most once, with retry and fallback disabled.
Synthetic artifact identities SHALL bind structurally realistic page/block/table
endpoint facts but SHALL contain no business answer or Golden value.

#### Scenario: source order or identity drifts

- **WHEN** a role is missing, duplicated, reordered or bound to a foreign source hash
- **THEN** rehearsal is typed blocked before 091 and no later dependency is invoked

### Requirement: NPV2 exact public dependency chain

The rehearsal SHALL use narrow injected ports for the frozen public contracts in
dependency order `091 custody → 096 relation receipt → 095/087 wiring → 094 wrapper`.
It SHALL not copy or replace their validators. Every stage SHALL expose immutable
canonical preimage bytes and SHA-256; 096 additionally SHALL expose relation manifest
and decision preimages. 097 SHALL recompute these hashes and require each successor to
bind the exact predecessor receipt, manifest and decision identities.

#### Scenario: one receipt is recomputed around a foreign predecessor

- **WHEN** a stage has a self-consistent receipt but its predecessor binding drifts
- **THEN** rehearsal is typed blocked before invoking the next dependency

### Requirement: NPV3 cross-page facts are never inferred

The current 091 single-endpoint observation SHALL result in exact
`BLOCKED_ON_CROSS_PAGE_BINDING` with zero 095/087 and 094 calls. 097 SHALL NOT derive
the missing endpoint from path hashes, page adjacency or Markdown. A future synthetic
complete-endpoint fixture MAY proceed only when 096 supplies two distinct-page actual
block endpoints for the terms section and two distinct-page actual table endpoints for
the rate table, and every endpoint exists in the corresponding captured artifact.

#### Scenario: current 091 evidence has one endpoint

- **WHEN** 096 returns `BLOCKED_ON_CROSS_PAGE_BINDING`
- **THEN** 097 returns the same status and reason, without partial receipt or success

### Requirement: NPV4 fail-closed reason and external-effect boundary

Any safe typed failure from capture, 091, 096, 095/087 or 094 SHALL be propagated
verbatim and all later ports SHALL remain uncalled. Exception text, unsafe reason text,
non-zero provider/model/Golden/DB/PG/WeKnora/live counters, retry or fallback SHALL
produce a stable task-local block with no success chain.

#### Scenario: a dependency reports a non-zero external counter

- **WHEN** any stage reports one external read, call or write
- **THEN** 097 returns `EXTERNAL_EFFECT_CONTRACT_VIOLATION` and no success digest

### Requirement: NPV5 synthetic success is compatibility only

For a complete-endpoint fixture, exact chain replay SHALL return only
`SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED` plus safe hashes and invocation counts. It
SHALL NOT return ADMIT, READY, Golden quality, human approval or Release authority.
The final chain digest SHALL bind the exact 091 receipt, 096 receipt/manifest/decision,
095/087 wiring receipt and 094 wrapper receipt hashes.

#### Scenario: future Protocol fixtures are mutually compatible

- **WHEN** all exact synthetic facts and predecessor bindings replay successfully
- **THEN** the rehearsal emits the compatibility-only terminal and all five ports have
  exactly one invocation

### Requirement: NPV6 bounded delivery

097 SHALL use at most seven paths: registry, four OpenSpec files, one task-local module
and one focused test. It SHALL not modify dependency implementations, add a migration,
schema, provider adapter, shared runtime or generic orchestration framework.

#### Scenario: GREEN needs an eighth path or shared dependency edit

- **WHEN** the task cannot close within the bounded seams
- **THEN** implementation stops with the exact blocker instead of expanding scope
