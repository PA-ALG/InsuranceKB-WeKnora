# Golden v2 Human Review Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed, offline intake and materialization contract that can turn the original 596-1 P0-seven plus P1-eleven workbook decisions into an immutable Golden v2 only after all eighteen decisions and one external named-human receipt verify.

**Architecture:** Keep Golden v1 byte-for-byte immutable. A pure Python module binds the exact v1 JSONL hash, workbook hash, three source hashes and ordered eighteen-field authority; it validates external decisions, produces canonical signing bytes, verifies the out-of-band receipt, and materializes an in-memory sixty-record successor where only approved fields may change. It does not parse Excel, call a provider, write a release, or reuse the later weak/strong selection gate as business authority.

**Tech Stack:** Python 3.12, Pydantic GoldenRecord, canonical C0 hashing, Ed25519 verification, pytest, Ruff, mypy, OpenSpec.

---

## Mission Card

- **Business goal:** Prepare the shortest safe path from the user's original eighteen workbook decisions to Golden v2 while extraction/model experiments remain suspended.
- **Why now:** This work is independent of model quality and removes post-review integration delay without deciding any business value in advance.
- **Owner:** worktree4, sole writer for the Golden domain; `gpt-5.6-sol high`.
- **Dependencies:** authoritative main `d7e8c524bc81c4ff1cc5ff6e009565d0c4730a89`, formal v1 `596.jsonl` SHA-256 `562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`, workbook SHA-256 `ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf`, existing GoldenRecord/build-release utilities, and the original P0-7/P1-11 ordered tuple.
- **Delivery:** one small PR, estimated 1–1.5 working days; owner does not commit/push/PR.
- **Exact scope:** six owner paths below; shared `openspec/changes/README.md` remains total-control owned.
- **Non-goals:** no workbook rewriting, no automatic decisions, no `高危职业`/`产品档次` review expansion, no weak/strong model selection, no provider, no Golden answer generation, no WeKnora/DB/Release activation.
- **Blockers:** any missing/ambiguous decision, `需业务专家`, unmapped `不适用`, identity drift, attempt to change a non-review field, absent external signature authority, need to edit v1, or need for a seventh owner path.

## File map

- Create: `openspec/changes/075-golden-v2-human-review-intake/proposal.md`
- Create: `openspec/changes/075-golden-v2-human-review-intake/tasks.md`
- Create: `openspec/changes/075-golden-v2-human-review-intake/validation-report.md`
- Create: `openspec/changes/075-golden-v2-human-review-intake/specs/golden-v2-human-review-intake/spec.md`
- Create: `harness/src/insurance_harness/goldenset/golden_v2_review_intake_596_1.py`
- Create: `harness/tests/test_golden_v2_review_intake_596_1_075.py`

### Task 1: Freeze the business boundary in OpenSpec

- [ ] Write a failing specification checklist that requires the exact workbook/v1/source identities, exact ordered eighteen fields, no nineteenth field, v1 immutability, external named-human authority, and zero model/external writes.
- [ ] Record that `高危职业` and `产品档次` retain v1 and are not decision inputs.
- [ ] Record that `需业务专家` and `不适用` cannot be silently mapped to the three-state Golden schema.
- [ ] Run strict OpenSpec validation and confirm it fails while the normative files are incomplete.
- [ ] Complete proposal/spec/tasks with no implementation or provider claims.

### Task 2: RED for exact identity and decision bijection

- [ ] Add tests for exact v1/workbook/source hashes and the ordered P0-seven/P1-eleven tuple.
- [ ] Add tests rejecting missing, duplicate, extra, reordered, priority-drifted and non-review field decisions.
- [ ] Add explicit rejection tests for `zh_2df7d6256c` and `zh_b7ceabc3c0` as review additions.
- [ ] Run the focused test and verify failure because the module does not exist.

### Task 3: Implement the minimal decision envelope

- [ ] Define frozen DTOs for selection `accept_recommendation | keep_current | custom | needs_expert | not_applicable`, current/recommended/custom record digests, reason and provenance.
- [ ] Implement canonical decision hashing and typed `PENDING`, `BLOCKED`, `READY_FOR_EXTERNAL_APPROVAL` results.
- [ ] Require complete custom GoldenRecord semantics; reject a custom present/absent record without replayable Evidence and reject an unknown record with a value.
- [ ] Keep `needs_expert` and unmapped `not_applicable` pending with zero successor records.
- [ ] Run focused tests and verify the identity/bijection cases pass.

### Task 4: RED/GREEN for external named-human receipt

- [ ] Add tests for canonical subject bytes binding v1, workbook, sources, decision hash, actor, expiry and conversation provenance.
- [ ] Add negative tests for service/self approval, placeholder actor, foreign key, stale receipt, changed decision and changed workbook hash.
- [ ] Expose signing bytes and verification only; do not expose a signer or default approval API.
- [ ] Run focused tests and verify only the exact named-human receipt yields `HUMAN_DECISIONS_VERIFIED`.

### Task 5: RED/GREEN for deterministic sixty-record materialization

- [ ] Add a synthetic sixty-record fixture in the test file; do not load 049 expected values.
- [ ] Assert `keep_current` preserves the exact input record, `accept_recommendation` selects the bound recommendation, and `custom` selects the complete custom record.
- [ ] Assert only the eighteen authorized fields may differ and the other forty-two record hashes remain identical.
- [ ] Implement pure in-memory materialization and one domain-separated successor receipt; do not create directories or write JSONL.
- [ ] Assert repeat input gives repeat output and any managed-byte mutation changes the receipt or blocks.

### Task 6: Bounded verification and checkpoint

- [ ] Run focused 075 tests.
- [ ] Run bounded GoldenRecord/build-release and 070 tuple regression tests without invoking the 070 weak/strong gate as authority.
- [ ] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-six-path, private/absolute-path and secret scans.
- [ ] Record provider/model/Golden write/DB/WeKnora/live/Release activation as `NOT RUN / FORBIDDEN`.
- [ ] Freeze a stable tree and hand it to total control; do not commit, push or open a PR.

## Acceptance

- Exact original 18 decisions form a bijection: P0=7, P1=11, total=18.
- High-risk occupation and product tier remain byte-equivalent to v1 and cannot enter the decision set.
- No decision is generated, inferred or defaulted; unresolved choices produce zero successor.
- A valid external named-human receipt is required before materialization.
- A verified synthetic run yields exactly sixty records, at most eighteen changed, forty-two unchanged by hash, deterministic ordering and a content-addressed successor receipt.
- Golden v1 files remain untouched; no v2 directory is created until the real completed workbook and explicit human receipt are supplied later.
