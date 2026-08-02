# 070 · Implementation Tasks

## T1 · Contract and RED

- [x] Freeze exact Golden18 authority, ordered P0/P1 tuple, decision vocabulary and
  external-receipt boundary.
- [x] Add RED for missing module and load-bearing pending/block/verification behavior.

## T2 · Pure gate

- [x] Recompute the exact 18-decision hash and exact approval subject.
- [x] Verify named-human Ed25519 receipt, freshness and conversation provenance.
- [x] Return typed pending/block/verified results with no Release or WeKnora action.

## T3 · Verification and freeze

- [x] Focused tests, Ruff, strict mypy, OpenSpec strict, diff/scope/private/secret checks.
- [x] Freeze exact seven-path candidate identity for independent review.

## T4 · Offline-ceiling corrective

- [x] Reproduce the all-strong signed approval incorrectly reaching
  `HUMAN_GATE_VERIFIED`.
- [x] Block any strong choice as `WEAK_ARM_NOT_APPROVED` and any `reject_both` as
  `HUMAN_DECISION_REJECTED`, with zero Release/WeKnora action.
- [x] Rerun focused/bounded/static/OpenSpec/scope/privacy gates and freeze the successor.

## Stop conditions

- A Golden value, provider, DB, WeKnora or Release call is required.
- A production signer or generic approval platform would be needed.
- An eighth path is required.
