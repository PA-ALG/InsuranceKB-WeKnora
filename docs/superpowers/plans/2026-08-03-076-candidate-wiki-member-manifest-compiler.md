# Candidate Wiki Member Manifest Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically compile a complete 059 CandidateAssembly plus verified value/Evidence preimages into Go-compatible Wiki release members, a change-log member and canonical manifest bytes without creating or activating a Release.

**Architecture:** A new pure Python compiler revalidates the 057/058/059 custody chain, merges affected-only changes against an exact base manifest, renders structured field pages and change log, and hashes the same closed member representation consumed by Go `WikiReleaseService.Prepare`. One frozen cross-language vector proves byte-for-byte canonical compatibility; production Go code remains unchanged.

**Tech Stack:** Python 3.12, existing C0/057/058/059 contracts, Go release canonicalizer read-only test, JSON fixture, pytest, Go test, Ruff, mypy, OpenSpec.

---

## Mission Card

- **Business goal:** Bridge the completed Candidate/human_batch domain to the existing Release Prepare boundary, closing the largest deterministic gap that does not depend on model quality.
- **Owner:** worktree1, sole writer; `gpt-5.6-sol high`.
- **Dependencies:** merged 051, 057, 058, 059, 065 and existing Go Release Prepare canonicalization.
- **Delivery:** one PR, 1–2 working days, exact eight owner paths; owner does not commit/push/PR.
- **Non-goals:** no provider/Golden/parser, human decision, ReadyReceipt, DB/migration, actual Prepare call, activation/CAS/Head/revert, WeKnora, page-template platform or production Go change.
- **Blockers:** missing value/Evidence preimages, incomplete base membership, Python/Go bytes mismatch requiring production changes, need for a conflict winner, main drift or ninth path.

## File map

- Create: `openspec/changes/076-candidate-wiki-member-manifest-compiler/proposal.md`
- Create: `openspec/changes/076-candidate-wiki-member-manifest-compiler/tasks.md`
- Create: `openspec/changes/076-candidate-wiki-member-manifest-compiler/validation-report.md`
- Create: `openspec/changes/076-candidate-wiki-member-manifest-compiler/specs/candidate-wiki-member-manifest-compiler/spec.md`
- Create: `harness/src/insurance_harness/knowledge_compiler/candidate_wiki_manifest.py`
- Create: `harness/tests/test_candidate_wiki_manifest_076.py`
- Create: `internal/application/service/testdata/076_candidate_wiki_manifest_vector.json`
- Create: `internal/application/service/wiki_release_manifest_076_test.go`

### Task 1: Freeze the draft-only compiler contract

- [ ] Specify closed WikiReleaseMember, base manifest and Candidate manifest DTOs matching the existing Go member fields.
- [ ] Freeze value/Evidence preimage revalidation, initial and incremental base rules, five ChangeSet actions, deterministic slug/page/change-log rules and failure-zero-output semantics.
- [ ] State explicitly that the result is an immutable draft with no decision, ReadyReceipt or serving authority.
- [ ] Run OpenSpec strict to capture the initial incomplete-spec RED, then complete the four OpenSpec documents.

### Task 2: Focused RED for missing compiler and vectors

- [ ] Add a Python test for one initial manifest and one R0→R1 update/delete/keep/add vector including conflict, Evidence and change log.
- [ ] Require a single public `compile_candidate_wiki_manifest` entrypoint and frozen output DTOs.
- [ ] Run focused tests and confirm module-missing RED.

### Task 3: RED for full custody and base identity

- [ ] Add failures for Candidate/batch/policy drift, non-bijective 057 verification links, value/Evidence preimage mismatch and cross-Space/ProductVersion/schema/source input.
- [ ] Add failures for direct/model-constructed objects, invalid initial/base identity, base manifest drift, affected-only input without complete base, duplicate slug and unsafe output facts.
- [ ] Prohibit placeholder Wiki pages containing only opaque hashes.

### Task 4: Minimal canonical compiler GREEN

- [ ] Implement focused frozen DTOs, full revalidation and base merge in the new module only.
- [ ] Derive stable scope slugs from ProductVersion plus scope hash; never use titles or values for addressing.
- [ ] Apply add/enrich/supersede/conflict/retract deterministically; preserve unaffected base members byte-for-byte.
- [ ] Retain all conflict facts/Evidence, remove retracted page membership while preserving proof in the change log.
- [ ] Render mechanical Markdown from closed structured payloads and compute member, manifest and C0 digests.

### Task 5: Determinism and mutation hardening

- [ ] Prove input iteration order does not affect members, bytes or hashes.
- [ ] Prove every Candidate/base/value/Evidence/action/member mutation changes identity or fails closed.
- [ ] Reject duplicate slugs, foreign contracts, hidden conflict winners and partial manifests.
- [ ] Prove zero filesystem/environment/network/subprocess/DB/provider/WeKnora surface.

### Task 6: Python-to-Go compatibility vector

- [ ] Freeze one independent JSON vector containing members, expected manifest bytes and manifest digest.
- [ ] Assert Python output matches the vector byte-for-byte.
- [ ] Add a Go test calling only existing `canonicalWikiReleaseManifest` and `digestWikiReleaseBytes` and assert identical ordering, bytes and digest.
- [ ] Stop if compatibility requires a Go production change; do not expand scope.

### Task 7: Bounded verification and checkpoint

- [ ] Run focused 076 and bounded 057/058/059 regressions.
- [ ] Run the focused Go vector test.
- [ ] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-eight-path and private/secret scans.
- [ ] Record provider/Golden/DB/PostgreSQL/WeKnora/live/full as `NOT RUN`.
- [ ] Freeze a stable tree and return it to total control; do not commit, push or open a PR.

## Acceptance

- The compiler produces complete, sorted, unique Wiki members plus one content-addressed change-log member and Go-compatible manifest bytes.
- Unaffected base members remain byte-for-byte unchanged; all five action types have deterministic semantics.
- Every readable fact and Evidence entry is backed by a mechanically recomputed 057/058/059 preimage chain.
- Conflict never selects a winner; retract removes current page membership but preserves immutable history.
- Python and unchanged Go canonicalizers produce identical manifest bytes and digest for the frozen vector.
- Any drift yields a typed error and no partial manifest; the output cannot be mistaken for a Ready or active Release.
