# 100 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:test-driven-development`
> and execute these tasks inline in the isolated 100 worktree.

**Goal:** Build the narrow private 096 bytes → public 092 authority-input adapter.

**Architecture:** One module owns safe file custody, canonical 096 replay, cross-contract
checks, exact 098 dependency resolution and a frozen receipt-backed relation provider. It
does not derive relations or endpoints.

**Tech stack:** Python 3.12, Pydantic v2, existing canonical/083/086/092/096/098 contracts.

- [x] T1 Freeze main and 092/096/098 candidate identities; create isolated worktree.
- [x] T2 Write proposal/spec/plan before production code.
- [x] T3 RED: private file mode/symlink/TOCTOU/size and canonical JSON/duplicate/extra cases.
- [x] T4 RED: receipt/bundle/source/profile/parser/policy/context drift and current 098 absence.
- [x] T5 RED: synthetic exact two-map success, provider call counts and post-adaptation drift.
- [x] T6 GREEN: implement minimum safe reader, replay adapter, exact dependency resolver and provider.
- [x] T7 Run focused plus bounded 083/086/092/096/098/100, Ruff, strict mypy, OpenSpec,
  diff/scope/privacy checks; freeze exact candidate identity.
