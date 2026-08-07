# 096 · 091 Marker Evidence to Derived Relation Receipt Bridge

## Goal

Build one task-local bridge from the exact 091-extended 083 intake bundle to two
replayed 086 derived bindings and one private canonical 596-1 relation receipt.
The bridge is custody and transport only; it creates no native relation, parser
admission, Release, READY or serving authority.

## Design

- replay the exact ordered terms → brochure → rate 083 bundle;
- consume the 091 marker DTO fields directly and treat typed page/node/local-index
  as mapping evidence while retaining structural-path hashes as custody only;
- map the 083 `rate` role mechanically to receipt role `rate_table`;
- call frozen 086 for exactly one terms section and one rate table relation;
- require both returned bindings to replay as
  `DERIVED_STRUCTURAL_BINDING_VERIFIED` before materializing any receipt;
- bind source/parser/config/raw/sanitized/marker/policy/replay/binding hashes and
  actual canonical endpoints in a closed immutable receipt;
- publish canonical JSON only to a caller-owned empty private directory using
  same-directory atomic no-replace publication.

The current 091 shape does not supply two endpoint-authoritative typed nodes for
the terms section and may preserve both `cross_page` and `lines_deleted`
observations on one node. The production adapter therefore returns
`BLOCKED_ON_CROSS_PAGE_BINDING` and writes nothing until evidence is complete.
It never substitutes adjacency, a path hash or `lines_deleted` for a relation.

## Stacked dependencies

- 091 candidate tree: `405393826eeceb881e1f713cef42069c97e922cf`
- 086 successor tree: `ee48922b0804355b73b52df2e4e9e73d2e03870b`
- 092 candidate tree: `49efbd12084e8069c7a06364ac4835e0bb4e1e86`

096 owns no upstream DTO or evaluator. Any interface mismatch is closed in this
bridge; frozen 091/086/092 sources are not modified.

## Non-goals

No provider/model/Golden read, DB, WeKnora, ADMIT, READY, parser inference,
Markdown/body semantics, generic receipt platform, signature, queue or migration.
Brochure produces no relation.

## Path budget

Exactly eight 096-owned paths: registry, four OpenSpec files, one task-local
module, one thin CLI and one focused test.
