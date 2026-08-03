# 596-1 Incremental Update Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove with one deterministic 596-1-shaped synthetic fixture that a SourceRevision change affects only declared fields and produces exactly one enrich, supersede, conflict and retract action without changing unaffected facts.

**Architecture:** A task-local composer reuses the public 052/053/054/057/058/059 contracts. It loads a synthetic sixty-field fixture, revalidates custody, calls the existing incremental compiler and Candidate/HumanBatch builder, and emits only canonical receipts and hashes. It must not copy governance algorithms or touch real Golden/provider/DB/WeKnora/Release state.

**Tech Stack:** Python 3.12, existing knowledge compiler DTOs, canonical C0 hashing, JSON fixture, pytest, Ruff, mypy, OpenSpec.

---

## Mission Card

- **Business goal:** Demonstrate the update/conflict/retraction half of the MVP closed loop while model extraction is paused.
- **Owner:** worktree3, sole writer; `gpt-5.6-sol high`.
- **Dependencies:** merged C0, 052, 053, 054, 057, 058 and 059; no dependency on human review or 066–074.
- **Delivery:** one PR, estimated 1.5–2 working days, strict seven owner paths; owner does not commit/push/PR.
- **Non-goals:** no real product truth, Golden read, parser/model run, persistence, migration, API, UI, release or generic incremental platform.
- **Blockers:** need to modify an upstream contract, copy 058 algorithms, exceed seven paths, require a fifth action/field, or fail to prove the exact 4+56 partition.

## File map

- Create: `openspec/changes/078-596-1-incremental-update-vertical/proposal.md`
- Create: `openspec/changes/078-596-1-incremental-update-vertical/tasks.md`
- Create: `openspec/changes/078-596-1-incremental-update-vertical/validation-report.md`
- Create: `openspec/changes/078-596-1-incremental-update-vertical/specs/596-1-incremental-update-vertical/spec.md`
- Create: `harness/src/insurance_harness/knowledge_compiler/incremental_update_596_1.py`
- Create: `harness/tests/fixtures/incremental_update_596_1_078.json`
- Create: `harness/tests/test_596_1_incremental_update_vertical_078.py`

### Task 1: Freeze exact scope and synthetic fixture contract

- [ ] Specify ProductVersion 596-1, sixty unique field scopes, four declared affected fields and fifty-six unchanged fields.
- [ ] Assign one synthetic action per affected field: enrich, supersede, conflict and retract; prohibit add.
- [ ] State that fixture values are synthetic and may not load or resemble 049 expected answers.
- [ ] Run OpenSpec strict and preserve the initial incomplete-spec failure before completing the documents.

### Task 2: RED for fixture identity and partition

- [ ] Add a test requiring the module's single public runner.
- [ ] Add exact fixture loader, 60=4+56 bijection, stable ordering and canonical fixture hash tests.
- [ ] Add rejection tests for an extra field, duplicate scope, missing affected field, cross-Space/ProductVersion and identity drift.
- [ ] Run focused tests and verify the module-missing RED.

### Task 3: RED for four governance actions

- [ ] Same value plus new valid Evidence must produce only enrich.
- [ ] Different value plus deterministically higher authority or valid later effective time must produce only supersede.
- [ ] Different value with no deterministic authority winner must produce conflict while retaining both facts and all Evidence.
- [ ] Complete replacement plus explicit absence plus exclusive-support proof must produce retract without physical deletion.
- [ ] Add negatives proving unknown is not explicit absence and non-exclusive support cannot retract.

### Task 4: Minimal composition GREEN

- [ ] Revalidate 053 artifact, 054 attempt/receipt and 057 verification receipts.
- [ ] Call 058 `compile_incremental_changes`; do not copy authority/action/retraction logic.
- [ ] Call 059 `build_fixture_candidate_batch`; do not hand-build or self-approve a Candidate.
- [ ] Return canonical action map, ChangeSet/Candidate/Batch digests, fifty-six unchanged hashes and one 078 receipt.
- [ ] Run focused tests and make the exact four-action matrix green.

### Task 5: Mutation and custody hardening

- [ ] Prove input reordering leaves the result unchanged.
- [ ] Prove any managed mutation changes a digest or fails closed.
- [ ] Reject fifth changes, duplicate scopes, unchanged facts entering ChangeSet/Candidate, hidden conflict evidence and physical retract deletion.
- [ ] Prove zero Release action and no provider/Golden/DB/WeKnora import surface.

### Task 6: Bounded verification and checkpoint

- [ ] Run focused 078 plus bounded 052/053/057/058/059 regression tests.
- [ ] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-seven-path and private/secret scans.
- [ ] Record provider/model, Golden, DB/PostgreSQL, WeKnora, Release, live and migration as `NOT RUN / FORBIDDEN`.
- [ ] Freeze a stable tree and return it to total control; do not commit, push or open a PR.

## Acceptance

- Exactly sixty scopes partition into four affected and fifty-six unchanged.
- The ChangeSet contains exactly one enrich, supersede, conflict and retract, with no add.
- All fifty-six unaffected fact hashes remain identical and stay out of ChangeSet/Candidate.
- Conflict retains competing facts/Evidence; retract binds complete-scope explicit-absence exclusive-support proof and never deletes history.
- Candidate/HumanBatch precisely binds 054/057/058 custody; drift produces zero Candidate.
- Repeat input is deterministic and the change cannot be mistaken for real 596-1 knowledge or release admission.
