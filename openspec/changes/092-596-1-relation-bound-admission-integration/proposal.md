# 092 · 596-1 Relation-bound Admission Integration

## Goal

Close the missing task-local path from one exact 083 three-source custody bundle,
through 052 material authority and 086 derived section/table bindings, into a
future-090 trusted 060 build and the existing 061 admission gate.

## Design

- replay the complete 083 bundle before reading any nested value;
- map only the frozen 083 `rate` role to the registered 052 `rate_table` role;
- require caller-supplied, prevalidated Space/source/revision/attempt/snapshot
  identities for all three sources and resolve the frozen 052 profile for each;
- build preliminary 053 facts through the real 060 builder without relation
  authority; require a typed page/node/local-index map to resolve both 089 marker
  nodes uniquely against the canonical 053 blocks or tables; then derive exact
  terms-section and rate-table 086 bindings;
- treat the 089 structural-path hash only as custody evidence, never as endpoint
  authority, and fail closed while the current one-node marker shape is
  insufficient;
- explicitly map 086 relation kinds and nested endpoints to the future-090 flat
  input, reconstruct policy/replay context from the admitted parse inputs, and
  recompute the 090 binding hash rather than forwarding caller-reported values;
- build three final receipts in terms → brochure → rate-table order and expose a
  bundle only when every 060 decision is `ADMIT` and the existing 061 gate returns
  `READY_FOR_QUALITY_FALSIFICATION`;
- return fixed typed blocked outcomes with no partial receipt exposure.

## Stacked dependency

The implementation is based on exact 083 head
`96d7e02c08f89d4fcaad629b2e8cc8e41dcf7e37` and consumes frozen 086 successor
tree `ee48922b0804355b73b52df2e4e9e73d2e03870b`. Until the actual 090 candidate is
frozen, an independent task-local Protocol fixture proves the expected callable,
replay and receipt boundary. Replacing that fixture with 090 must be a mechanical
identity rebase, not a second authority implementation.

The 093 compatibility replay confirmed that the current 089 marker exposes a
structural-path hash and node metadata but not a complete source/target endpoint
authority, and that frozen 086 and 090 use different relation-kind, endpoint and
context layouts. 092 therefore blocks the current insufficient marker shape and
freezes the exact typed bridge and explicit 090 translation required for a later
mechanical rebase.

## Non-goals

No provider/model/Golden read, raw JSON parser, filesystem/runtime lookup, DB,
WeKnora, migration, Release, Candidate, signature, queue or generic admission
platform. This change does not modify 052/053/060/061/083/084/086/087/089/090/091.

## Path budget

Exactly seven 092-owned paths: the registry row, four OpenSpec files, one
task-local integration module and one focused test. The six task-specific 086
paths are byte-identical to the approved successor; the shared registry is only
mechanically extended with the 092 row and a non-authoritative future placeholder.
