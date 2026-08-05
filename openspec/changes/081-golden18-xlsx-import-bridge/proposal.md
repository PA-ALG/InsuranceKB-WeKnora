# 081 · Golden18 XLSX Import Bridge

## Goal

Provide one task-local, offline and fail-closed bridge from the approved 596-1
P0/P1 review workbook to the public 075 review-intake request. The bridge reads
only caller-supplied bytes, preserves the original workbook-template identity,
binds the exact completed-workbook bytes, and never creates or modifies a Golden.

## Scope

- Bind the approved blank workbook SHA-256, exact product/version, ordered P0-seven
  plus P1-eleven fields, three visible sheets, exact tables/headers and decision
  vocabulary.
- Return `AWAITING_18_HUMAN_DECISIONS` for the approved blank decision state, with
  exact pending fields and counts and no 075 request.
- Convert a complete synthetic workbook only when caller-supplied current,
  recommended and custom record authority exactly matches the displayed cells.
- Reuse the public 075 DTO/hash/replay contract. Do not sign, approve, materialize,
  write a Golden, or create a second review authority.

## Non-goals

No general Excel importer, workbook generation, Golden read/write, named-human
receipt, signing, model/provider, DB, WeKnora, Release, migration, live or production
action. Future workbook layouts require a new versioned Mission.
