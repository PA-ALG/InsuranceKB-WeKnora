# 091 Marker Evidence to Derived Relation Receipt Bridge Specification

## ADDED Requirements

### Requirement: RRB1 exact 091 intake replay

096 SHALL consume one closed 091-extended 083 bundle in exact terms → brochure →
rate order. It SHALL replay the complete bundle and bind each source, capture,
parser/config, raw/sanitized structure, native facts and marker provenance digest.
The `rate` role SHALL map only to receipt role `rate_table`; brochure SHALL never
produce a relation.

#### Scenario: any source or marker identity drifts

- **WHEN** source, parser, config, raw, sanitized, facts, marker, intake or bundle identity changes
- **THEN** the bridge returns `BLOCKED_ON_CROSS_PAGE_BINDING` and writes no receipt

### Requirement: RRB2 typed marker mapping is not endpoint invention

The adapter SHALL use 091 marker kind, zero-based page, node type and local index
to map uniquely to actual canonical 053 endpoints. A structural-path hash SHALL
remain custody evidence and SHALL NOT select an endpoint. `lines_deleted` SHALL
never satisfy `cross_page`. Missing, single-ended or multiple candidates, or any
page/local-index/path/source/parser/version/hash drift SHALL fail closed.

#### Scenario: the current 091 node is insufficient

- **WHEN** the marker evidence does not prove both canonical relation endpoints
- **THEN** the result is typed `BLOCKED_ON_CROSS_PAGE_BINDING`, not a synthetic relation

### Requirement: RRB3 frozen 086 derivation and replay

096 SHALL call the frozen 086 derivation for exactly one terms `section` and one
rate `table` relation. Both outputs SHALL replay through the public 086 replay
entry and SHALL equal status `DERIVED_STRUCTURAL_BINDING_VERIFIED`. Any binding,
policy, replay, endpoint, parser or source drift SHALL yield zero receipt.

#### Scenario: one of two derived bindings is unavailable

- **WHEN** either 086 call blocks, is unavailable or returns a drifted binding
- **THEN** neither relation is published

### Requirement: RRB4 closed canonical relation receipt

The immutable receipt SHALL contain exactly two ordered entries: terms/section
and rate_table/table. It SHALL bind the 083 bundle, each intake item and capture,
source/parser/config/raw/sanitized/marker, 086 policy/replay/binding hashes and
actual canonical endpoint IDs/pages/fact/locator digests. Its receipt digest SHALL
be domain-separated and mechanically replayable. It SHALL contain no brochure
relation and no NATIVE, ADMIT or READY claim.

#### Scenario: caller self-reports a receipt digest

- **WHEN** any receipt value is mutated and the caller supplies a replacement hash
- **THEN** replay recomputes the canonical digest and rejects it

### Requirement: RRB5 private atomic no-replace publication

The CLI SHALL publish one canonical JSON file only after the full receipt is
derived. The caller-supplied output root SHALL already be a real non-symlink
directory with mode `0700`; the final file SHALL be regular `0600`. Publication
SHALL use a same-directory private temporary file and one atomic no-replace
operation. Existing targets, symlinks, write failures or derivation failures SHALL
leave no partial final receipt.

#### Scenario: a concurrent target appears

- **WHEN** the final name exists before publication completes
- **THEN** publication fails closed, preserves that target and removes only its own temporary file

### Requirement: RRB6 bounded non-authoritative delivery

096 SHALL not call provider/model, read Golden, DB or WeKnora, and SHALL not emit
ADMIT/READY. The implementation SHALL remain task-local and SHALL not modify
091/086/092/094/095/087.

#### Scenario: successful receipt is consumed downstream

- **WHEN** 095, 087 or 092 reads the receipt
- **THEN** it receives replayable derived custody only and must perform its own authority checks
