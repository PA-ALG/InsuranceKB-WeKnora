# Schema67 Human Annotation Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one non-authoritative, deterministic human annotation and adjudication kit for the Ping An eShengBao medical-insurance Schema67 Golden workflow without producing an approved Golden or calling a model.

**Architecture:** A narrow Python module consumes only the exact old S0-Q 60-row human-approved migration input and the exact 71-row model draft, projects both through explicit source-to-Schema67 mapping tables, and emits one closed canonical JSON kit. The kit contains exact current source-revision preflight identities, 67 ordered PENDING annotation rows, page 12/27 work items, reviewer placeholders and a PENDING whole-batch receipt template. Validation rebuilds the expected kit from exact input bytes and requires exact equality, so outer self-rehashing cannot turn proposals into Golden authority.

**Tech Stack:** Python 3.12, Pydantic v2, canonical JSON/SHA-256, pytest, Ruff, strict mypy.

---

## Frozen scope

**Create exactly:**

- `docs/superpowers/plans/2026-08-11-schema67-human-annotation-kit.md`
- `harness/src/insurance_harness/goldenset/schema67_human_annotation_kit_596_1.py`
- `harness/tests/test_schema67_human_annotation_kit_596_1.py`
- `dataset/goldenset-drafts/schema67-human-annotation-kit-596-1/kit.json`

The already-frozen OpenSpec 122 is a dependency, not an owner path. This change does not
modify CandidateV2, evaluator, release compiler, provider runner, DB/migrations, WeKnora,
frontend or serving authority.

## Authority inputs

- Old S0-Q human-approved migration input: exact 60 rows, `596.jsonl` SHA-256
  `562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`. Its scope
  remains `S0-Q only`; every reuse is `PROPOSED_MIGRATION/PENDING`.
- Model draft: exact 71 rows, `annotations.jsonl` SHA-256
  `25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4`. Every row
  remains `MODEL_SUGGESTION/PENDING`, including 23 high-risk, 11 mandatory-review and
  8 tri-state-conflict suggestions.
- Schema topology: code-owned `medical-schema67.v1` exact ordered67.
- Current revision preflight: exact terms/brochure/rate knowledge IDs, parse attempts,
  file hashes, chunk-manifest hashes/counts and page counts. These are annotation inputs;
  Evidence and bbox remain pending until attempt-bound sealed capture exists.

## Task 1: RED the non-authoritative kit contract

**Files:**

- Create: `harness/tests/test_schema67_human_annotation_kit_596_1.py`

- [ ] Import the wished-for builder, loader, validator and safe-summary API.
- [ ] Assert exact old60/draft71 hashes and source counts.
- [ ] Assert both explicit mapping tables cover every source row and every ordered67
  target using only `reuse/rename/split/merge/new/N-A`.
- [ ] Assert all old60 outputs are `PROPOSED_MIGRATION/PENDING` and all draft71 outputs
  are `MODEL_SUGGESTION/PENDING`.
- [ ] Assert exactly 67 ordered annotations, every state/value/Evidence/reviewer decision
  is pending/empty and every bbox is `PENDING_CAPTURE`.
- [ ] Assert page12/page27 terms/brochure work stays pending while rate page12/page27 is
  `PROHIBITED_PAGE_OUT_OF_RANGE` before any Evidence use.
- [ ] Assert reviewer slots contain role/ID placeholders only and whole-batch receipt is
  PENDING with no approval/signature/hash.
- [ ] Assert missing/extra/reordered fields, unknown JSON, noncanonical JSON, outer
  self-rehash, approved status, copied Material Wiki value and source/hash drift fail.
- [ ] Assert safe summary exposes counts only and cannot emit Golden.

Run:

```bash
cd harness
PYTHONPATH="$PWD/src" /path/to/shared/.venv/bin/pytest \
  tests/test_schema67_human_annotation_kit_596_1.py -q
```

Expected RED: import failure because the production module does not exist.

## Task 2: GREEN the closed DTO and explicit mapping

**Files:**

- Create: `harness/src/insurance_harness/goldenset/schema67_human_annotation_kit_596_1.py`
- Test: `harness/tests/test_schema67_human_annotation_kit_596_1.py`

- [ ] Define frozen, `extra="forbid"`, revalidated Pydantic DTOs for source identities,
  mappings, revision preflight, PENDING annotations, page work, reviewer slots, receipt
  template, complete kit and safe summary.
- [ ] Bind exact source file hashes/counts and the code-owned SchemaPack hash/order.
- [ ] Encode explicit old60→67 and draft71→67 mappings; validate action cardinality,
  exact source coverage and complete target coverage. Duplicate targets are legal only for
  explicit merge rows.
- [ ] Build 67 blank PENDING rows without copying a value, state, quote, locator or bbox
  from either source or Material Wiki.
- [ ] Canonicalize with sorted-key compact UTF-8 JSON, hash the complete preimage and
  reject duplicate keys, unknown/trailing/noncanonical/self-rehashed payloads.
- [ ] Make validation rebuild the exact expected kit from the two exact input byte
  streams; reject any authority mutation even if the outer hash is recomputed.
- [ ] Implement a fixed-schema safe summary containing counts/status only.

Run the focused test and require GREEN.

## Task 3: Freeze the canonical draft artifact

**Files:**

- Create: `dataset/goldenset-drafts/schema67-human-annotation-kit-596-1/kit.json`
- Modify only if a test proves necessary: the Task 2 source/test files.

- [ ] Generate bytes from the builder using the exact committed old60/draft71 inputs.
- [ ] Add the generated bytes through `apply_patch` and assert byte equality with a fresh
  builder run.
- [ ] Load the committed artifact through the closed loader and require exact validation.
- [ ] Confirm the artifact contains no local path, raw secret, approved Golden, model
  result, Candidate or Material Wiki value.

## Task 4: One bounded verification and freeze

- [ ] Run focused pytest once.
- [ ] Run the relevant medical SchemaPack test as the bounded compatibility gate.
- [ ] Run Ruff on the exact source/test and strict mypy on the exact production module.
- [ ] Run OpenSpec 122 strict validation, `git diff --check`, exact-path and privacy scans.
- [ ] Commit exact4 with `feat(golden): add pending Schema67 human annotation kit`.
- [ ] Freeze commit/tree and one durable read-only candidate index; do not push.
- [ ] Send the exact identity to worktree3 for independent review.

## STOP rules

- Any provider/model/live/DB/WeKnora call.
- Any automatic promotion of old60 or draft71 values/states/Evidence into annotation rows.
- Any generated `APPROVED`, Golden hash/receipt, real reviewer identity or signature.
- Any page1/full-page bbox fallback; any rate page12/page27 acceptance.
- Any Material Wiki fallback or Candidate/production interface change.
- Any mapping or source mutation hidden by recomputing only the outer kit hash.
