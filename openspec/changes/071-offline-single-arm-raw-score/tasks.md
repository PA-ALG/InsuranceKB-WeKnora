# 071 · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use test-driven development and
> verification-before-completion. This plan is executed inline by the approved Owner.

**Goal:** Make the single-arm offline score descriptive and exact without weakening
any profile, authority, Golden or Evidence gate.

**Architecture:** Extend the existing 067 seam rather than create a second scorer. The
existing exact Golden parser and field evaluations remain the single arithmetic source;
a small raw-metric projection and explicit authority status are bound into the existing
C0 score receipt. The 066 offline comparator accepts the strong raw status only in its
strong slot.

**Tech stack:** Python 3.12 dataclasses, existing C0 canonical hash, pytest, Ruff, mypy,
OpenSpec.

## Task 1 · RED: Golden value and raw metric contract

- [x] Add a regression proving the exact 049 parser retains both non-empty
  `absent_explicitly` values.
- [x] Add focused assertions for state/present/absent/Evidence/raw-critical18 counts.
- [x] Run the focused tests and record the expected missing-contract failures.

## Task 2 · GREEN: explicit single-arm raw status

- [x] Add the minimal raw metric DTO derived from the existing field evaluations.
- [x] Return `UNADMITTED_RAW` plus profile/authority reasons for GPT/non-approved model
  identity; approved DeepSeek remains `SCORED`.
- [x] Bind the raw metrics and status into the existing score receipt.

## Task 3 · GREEN: offline ceiling integration

- [x] Require 066 weak=`SCORED`, strong=`UNADMITTED_RAW`.
- [x] Preserve its offline-only strong receipt, no-judge/no-fallback/no-Release boundary.

## Task 4 · Verification and freeze

- [x] Run focused 067/066 and bounded 061 tests.
- [x] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-nine scope and
  private/secret scans.
- [x] Freeze an exact temp-index tree; do not commit, push or create a PR.
