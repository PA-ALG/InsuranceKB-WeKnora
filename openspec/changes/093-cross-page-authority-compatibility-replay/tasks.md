# 093 · Implementation tasks

## T1 · Contract and vectors

- [x] Inspect the frozen 089, 086 and 090 candidate contracts without modifying them.
- [x] Freeze exact terms/rate-table source roles, relation kinds, endpoints and pages.
- [x] Freeze the two-boundary compatibility matrix and canonical replay identities.

## T2 · TDD RED

- [x] Prove the current frozen 089→086 shape is blocked at the marker authority boundary.
- [x] Prove the current frozen 086→090 shape is blocked at the injection context boundary.
- [x] Cover missing fields, role/kind confusion, encoding/order/hash and identity drifts.

## T3 · GREEN

- [x] Implement the minimal strict bytes/DTO verifier and typed result.
- [x] Produce a fixed replay vector with deterministic bytes and result hash.
- [x] Expose the minimal 091/092 compatibility matrix without admission authority.

## T4 · Verification

- [x] Focused tests, bounded canonical regression, Ruff and strict mypy.
- [x] OpenSpec093 strict, diff-check, exact-seven scope and privacy checks.
- [x] Freeze an exact candidate without commit, push or PR.

## Stop conditions

- A public implementation file outside this task-local module/test is needed.
- Compatibility could be claimed only by inventing endpoints, policy identity or hashes.
- Scope exceeds seven paths or requires a global schema/framework.
