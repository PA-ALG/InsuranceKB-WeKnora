# 073 · Implementation Plan

> **For agentic workers:** use test-driven development and
> verification-before-completion. This plan is executed inline by the approved Owner.

**Goal:** Freeze only the four no-decision contracts and fail closed on the remaining
four until an exact external user receipt binds the approved decision package.

## Task 1 · RED: exact8 and missing-authority boundary

- [x] Add focused assertions for the exact ordered eight, 4/4 status split and 052
  source authority.
- [x] Prove that no pending row contains a choice, option or default.
- [x] Prove missing/foreign/stale/tampered/service receipts block with
  `provider_calls=0`.
- [x] Run the focused test and record the expected missing-module failure.

## Task 2 · GREEN: task-local immutable contract

- [x] Add the minimal frozen exact8 DTO and canonical bundle hash.
- [x] Add an external named-human receipt verifier with no signing or side-effect API.
- [x] Keep all four undecided rows `NONE_PENDING_USER_CONFIRMATION` after verification;
  the receipt only authenticates the external resolution bundle hash.

## Task 3 · Verification and freeze

- [x] Run focused 073 and bounded 069/070 regression tests.
- [x] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-seven scope and
  private/secret scans.
- [x] Freeze an exact temp-index tree; do not commit, push or create a PR.
