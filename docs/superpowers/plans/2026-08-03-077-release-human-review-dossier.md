# Release Human Review Dossier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a deterministic, display-only JSON and static HTML dossier for one complete CandidateAssembly so a named human can review changes, conflicts, retractions, risks, repairs, gaps and original Evidence locators without any default decision.

**Architecture:** A strict builder consumes the complete 059 CandidateAssembly plus the original 057 FieldCandidate inputs required to replay locator custody. It validates every hash edge, builds one immutable dossier model, serializes canonical JSON, and renders escaped static HTML from that same model. It performs no file/network/provider/Golden/DB/WeKnora/Release action.

**Tech Stack:** Python 3.12 dataclasses/Pydantic, existing C0/057/058/059 contracts, deterministic JSON, standard-library HTML escaping, pytest, Ruff, mypy, OpenSpec.

---

## Mission Card

- **Business goal:** Make the already-built Candidate/human_batch path understandable and auditable while real extraction waits for Golden review.
- **Owner:** worktree2, sole writer; `gpt-5.6-sol high`.
- **Dependencies:** merged 051, 057, 058, 059; 070 only as a negative no-self-approval boundary.
- **Delivery:** one PR, estimated 2 working days plus bounded review; strict seven owner paths; owner does not commit/push/PR.
- **Non-goals:** no ReviewDecision, approval control, default winner, provider, Golden, persistence, UI integration, API endpoint, WeKnora, release creation or activation.
- **Blockers:** original FieldCandidate locator inputs are unavailable, any hash edge cannot be revalidated, persistence/UI is required, or scope exceeds seven paths.

## File map

- Create: `openspec/changes/077-release-human-review-dossier/proposal.md`
- Create: `openspec/changes/077-release-human-review-dossier/tasks.md`
- Create: `openspec/changes/077-release-human-review-dossier/validation-report.md`
- Create: `openspec/changes/077-release-human-review-dossier/specs/release-human-review-dossier/spec.md`
- Create: `harness/src/insurance_harness/knowledge_compiler/review_dossier.py`
- Create: `harness/src/insurance_harness/knowledge_compiler/review_dossier_html.py`
- Create: `harness/tests/test_release_human_review_dossier_077.py`

### Task 1: Freeze display-only authority and custody

- [ ] Specify that the review unit is the complete CandidateAssembly, never an individual page.
- [ ] Freeze `fact_hash → candidate_snapshot_hash → recomputed FieldCandidate snapshot → Evidence locator` binding.
- [ ] Require `DISPLAY_ONLY_REQUIRES_NAMED_HUMAN` while preserving 059's original `NONE_REQUIRES_NAMED_HUMAN` authority.
- [ ] Prohibit decisions, selected/winner defaults, approval controls, publishing and external writes.
- [ ] Run OpenSpec strict to capture the incomplete-spec RED, then complete the four OpenSpec documents.

### Task 2: RED for complete review categories

- [ ] Add one fixture Candidate covering add, enrich, supersede, conflict, retract, high-risk, repair and gap.
- [ ] Assert enrich/supersede display under update while retaining the exact original 058 action.
- [ ] Assert conflict includes both incoming/prior facts and retract includes its proof/history.
- [ ] Run focused tests and confirm failure because the dossier modules do not exist.

### Task 3: RED for locator and hash custody

- [ ] Assert page, parent, content snapshot and available block/table/cell locator facts are preserved exactly.
- [ ] Add negatives for missing, duplicate, orphaned or mismatched Candidate, batch, fact, candidate-snapshot and repair-parent hashes.
- [ ] Prohibit matching locator data by field_id alone.
- [ ] Run focused tests and preserve the expected custody failures.

### Task 4: Implement minimal immutable dossier and JSON

- [ ] Define focused frozen DTOs and one strict builder.
- [ ] Recompute every public upstream identity; fail before output on mismatch.
- [ ] Produce canonical counts, grouped display entries, raw action labels, original hashes and locators.
- [ ] Serialize deterministic JSON and compute a domain-separated dossier hash.
- [ ] Prove input ordering does not alter the JSON bytes or hash.

### Task 5: Implement static HTML projection

- [ ] Render only from the validated dossier DTO, never from raw inputs.
- [ ] Escape all values; include no script, form, external resource, callback, selected state or approval control.
- [ ] Add tests proving JSON/HTML Candidate hash, category counts and locators agree.
- [ ] Add adversarial escaping tests for markup-like source text.

### Task 6: Safety boundaries and checkpoint

- [ ] Add AST/import checks preventing filesystem writes, provider, Golden, DB, WeKnora, Release or ReviewDecision dependencies.
- [ ] Run focused 077 and bounded 057/058/059/070 regressions.
- [ ] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-seven-path and private/secret scans.
- [ ] Record provider/model, Golden, DB, WeKnora, live and release as `NOT RUN / FORBIDDEN`.
- [ ] Freeze a stable tree and return it to total control; do not commit, push or open a PR.

## Acceptance

- The full Candidate is the only review unit and all review categories are visible in JSON and HTML.
- Every Evidence display entry has a mechanically replayable Candidate snapshot and original locator binding.
- Conflict has no default winner; risk has no default approval; repair is not treated as acceptance.
- HTML is deterministic, escaped, offline and contains no interactive decision surface.
- Any missing/orphaned/mismatched custody fails closed before output.
- Output contains no ReviewDecision, PublishAuthorization, release activation or serving-head mutation.
