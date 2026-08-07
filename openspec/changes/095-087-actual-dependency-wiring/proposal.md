# 095 · 087 Actual Dependency Wiring

## Goal

Replace 087's deliberately synthetic composition seam with one bounded adapter that
connects the exact frozen 091/083 intake, the frozen 096/086 receipt replay boundary,
and the frozen 092 relation-bound admission entry. The adapter proves call-graph
compatibility only; it does not claim real MinerU readiness.

## Stacked identities

- authoritative base: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`;
- 087 candidate tree: `cda609d08f3e9d5ae8088fca036d3fb67189d601`;
- 091 candidate tree: `405393826eeceb881e1f713cef42069c97e922cf`;
- 092 candidate tree: `49efbd12084e8069c7a06364ac4835e0bb4e1e86`;
- 096 candidate tree: `11867ea8318119c5199fbbffc1f8ac9a38c4afee`.

The exact 096 public replay accepts an already parsed
`DerivedRelationReceipt5961V1`; it does not accept private receipt bytes and it does not
return 092 source authorities, material-profile resolutions or typed marker maps. 095
does not copy or replace that authority. The production resolver therefore returns
`DEPENDENCY_UNAVAILABLE` before file I/O until an upstream public bytes-to-092 validator
exists with the exact consumer Protocol.

## Design

1. Reuse 087's no-follow, exact-`0600`, distinct-inode, one-read boundary for the
   four private inputs.
2. Pass the three capture byte strings together, in exact terms → brochure → rate
   order, to the exact public 091/083 bundle intake. Do not parse JSON or recompute a hash.
3. Require a 096 validator port that accepts the relation-receipt bytes and exact intake
   bundle, replays the public 086 binding contract, and returns only the exact 092 input
   DTOs/callable. The frozen 096 candidate does not yet implement this port, so the real
   production resolution stays typed and pre-I/O blocked.
4. Call the exact public 092 `assemble_relation_bound_admission_596_1` once. 095 does
   not map `rate` to `rate_table`; that remains exclusively inside 092.
5. Preserve `DEPENDENCY_UNAVAILABLE` and `BLOCKED_ON_CROSS_PAGE_BINDING` exactly.
   Every other invalid boundary is a fixed, privacy-safe typed block with no partial
   identity or receipt.
6. Only a synthetic exact dependency set that reaches the 092 success shape may emit
   `COMPOSITION_SEAM_VERIFIED`. It is not `READY`, `ADMIT`, Release or serving authority.

## Non-goals

No provider/model/Golden, DB, WeKnora, live/full run, parser, raw JSON parser, digest
implementation, endpoint inference, receipt signature, queue or workflow platform. No
changes to 091/092/096/094 core paths.

## Path budget

Seven 095-owned paths: registry, four OpenSpec files, one adapter module and one
focused test. 087 remains byte-identical.
