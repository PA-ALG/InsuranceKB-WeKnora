# Enterprise Knowledge Compiler Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one falsifiable `596-1` vertical slice that turns three exact insurance PDFs into verified incremental knowledge, a human-approved versioned WeKnora Wiki Release, and a proven revert, while preserving one serving authority.

**Architecture:** Execute `A → C → B → {D,E} → F → G`. C first freezes material/template scope and required structural capabilities; B then admits parser-neutral structure against that exact profile without a dependency cycle. D and E independently build narrow extraction/verification and incremental fusion; F connects only frozen fixtures to Candidate/Release/revert; G is the sole provider/parser experiment and reads Golden only after outputs are frozen.

**Tech Stack:** Python 3.12 Harness, Pydantic v2, existing C0/W1/TemplatePackage/P1/P3/Golden contracts, versioned WeKnora REST, PostgreSQL only where a child Contract Card independently proves persistence is required.

---

## 0. Delivery rules

- 051 merge completes A but authorizes no child implementation by itself.
- Every child first reserves the then-current OpenSpec number and freezes its own Contract Card,
  exact base, path budget, threat matrix and acceptance commands.
- No child reuses a dirty/frozen historical worktree or old 028/031 runtime blob.
- C then B use deterministic fixtures only; D uses fakes/recorded fixtures; E is deterministic;
  F uses fixture artifacts and a controlled release environment; only G can call parser/model
  providers or read the 049 Golden.
- Ordinary implementation PR target: 5–12 logical paths and one domain invariant. A Mission may
  use multiple small PRs; it must stop before a second invariant gets folded into one PR.
- No child pre-reserves a migration in this parent plan. If a child proves a migration necessary,
  it reserves the next real main head in that child OpenSpec.
- Findings are classified `BLOCKER / BACKLOG / REJECTED`; only reproducible violations of the
  current Mission acceptance block delivery.

## Task A: Merge the 051 parent architecture

**Files:**
- Modify: `openspec/changes/README.md`
- Create: `openspec/changes/051-enterprise-knowledge-compiler-architecture/proposal.md`
- Create: `openspec/changes/051-enterprise-knowledge-compiler-architecture/tasks.md`
- Create: `openspec/changes/051-enterprise-knowledge-compiler-architecture/validation-report.md`
- Create: `openspec/changes/051-enterprise-knowledge-compiler-architecture/specs/enterprise-knowledge-compiler-architecture/spec.md`
- Create: `docs/superpowers/specs/2026-08-01-enterprise-knowledge-compiler-architecture.md`
- Create: `docs/superpowers/plans/2026-08-01-enterprise-knowledge-compiler-architecture.md`

- [ ] **Step A1: Freeze the seven-path candidate**

Run:

```bash
DO_NOT_TRACK=1 openspec validate 051-enterprise-knowledge-compiler-architecture --strict
git diff --check 0f231f9841ab31dde4bad15b958c4cd83c316086
```

Expected: OpenSpec valid; no whitespace errors; exactly seven approved paths.

- [ ] **Step A2: Run independent Spec and Delivery/YAGNI review**

Expected: both reviews bind the same exact tree and return no Critical/Important finding. Any
finding is corrected in the same seven paths and reviewed again.

- [ ] **Step A3: Handoff for controlled integration**

Expected: total control, not the writer lane, decides commit/push/PR/merge. Merge marks only
`architecture frozen`; no feature, parser, quality or release status changes.

## Task B: Add parser-neutral structured artifact and quality admission

**Mission boundary:** one domain invariant: one exact SourceRevision/parse attempt becomes one
admitted parser-neutral structure or a typed insufficient result.

**Dependency:** Execute only after Task C freezes exact MaterialProfile required capabilities.

**Proposed files (child OpenSpec freezes the exact allowlist):**
- Create: `harness/src/insurance_harness/compiler/parsed_documents.py`
- Create: `harness/src/insurance_harness/compiler/parse_quality.py`
- Modify: `harness/src/insurance_harness/compiler/__init__.py`
- Create: `harness/tests/test_parsed_document_contract.py`
- Create: `harness/tests/test_parse_quality_admission.py`
- Create/modify: child OpenSpec proposal/tasks/spec/validation

- [ ] **Step B1: Write RED for identity and manifest mixing**

Tests SHALL reject page/table/cell rows from different W1 generations, count/digest drift,
snapshot pagination drift, concurrent reparse/delete and parser identity drift before downstream
model calls.

- [ ] **Step B2: Write RED for required structure and privacy**

For deterministic terms/brochure/rate-table fixtures, assert missing locators, incomplete table
grid/span/header/cross-page facts, unsupported profiles and output-policy violations map to the
frozen typed reason families.

- [ ] **Step B3: Implement the smallest V1 contracts**

Add only `ParsedDocumentV1`, `ParseManifestV1`, `ParseQualityDecisionV1` and deterministic
validation. Reuse SourceRevision/W1/FrozenW1Bundle and C0; no DB, proto, vendor union or parser.

- [ ] **Step B4: Calibrate thresholds without choosing a vendor**

Use `596-1`-shaped deterministic fixtures to freeze a threshold version for required facts.
Record fixture-only status; do not claim the real three PDFs are admitted.

- [ ] **Step B5: Verify and review**

Run exact focused tests, Ruff, strict mypy, OpenSpec strict, diff/scope, private-path and secret
scans. Require
independent Spec and Quality approval before merge.

## Task C: Connect MaterialProfile to the existing TemplatePackage resolver

**Mission boundary:** one domain invariant: an approved material/product identity resolves one
exact template chain without inference or cross-Space fallback.

**Order:** Execute immediately after A and before B. C uses deterministic fixtures and does not
claim `596-1` production admission; B later closes that gate with all three exact PDFs.

**Proposed files:**
- Create: `harness/src/insurance_harness/template_packages/material_profiles.py`
- Create: `harness/src/insurance_harness/template_packages/catalog.py`
- Modify: `harness/src/insurance_harness/template_packages/models.py`
- Modify: `harness/src/insurance_harness/template_packages/resolver.py`
- Create: `harness/tests/test_material_profile_catalog.py`
- Create: `harness/tests/test_material_template_resolution.py`
- Create/modify: child OpenSpec proposal/tasks/spec/validation

- [ ] **Step C1: Write RED for product-family inference and fallback**

Reject filename/model-derived family IDs, unapproved layer versions, cross-Space/ProductVersion
fallback, ambiguous mixed materials and caller-selected authority.

- [ ] **Step C2: Write RED for material authority**

Prove classification cannot promote marketing/PPT into terms authority; terms, brochure,
rate-table, FAQ, benefits, structured JSON and scanned input retain field-level responsibilities.

- [ ] **Step C3: Implement the narrow profile/catalog seam**

Reuse the current four-level resolver and domain content hash. Add exact MaterialProfile mapping,
one approved default parser plus at most one approved bounded upgrade, approved broader-chain
fallback and a receipt that records missing layers and chosen chain. Do not create a persistent
registry or second hash authority.

- [ ] **Step C4: Freeze a `596-1` catalog fixture**

Cover terms/brochure/rate-table and the 60-field Schema slice. Mark it fixture/catalog complete,
not real production admission until B receives all three exact admitted artifacts.

- [ ] **Step C5: Verify and review**

Run focused tests, Ruff, strict mypy, OpenSpec strict, diff/scope, private-path and secret scans.
Merge only the
catalog/resolution invariant.

## Task D: Build narrow extraction, Evidence verification and bounded repair

**Mission boundary:** verified field candidates from one admitted task; no fusion or release.
Split into D1 task/receipt and D2 verifier/repair PRs if the path or logic budget exceeds one small
PR.

**Proposed files:**
- Create: `harness/src/insurance_harness/compiler/extraction_tasks.py`
- Create: `harness/src/insurance_harness/compiler/extraction_receipts.py`
- Create: `harness/src/insurance_harness/compiler/locators.py`
- Create: `harness/src/insurance_harness/compiler/verifiers.py`
- Create: `harness/src/insurance_harness/compiler/targeted_repair.py`
- Modify: `harness/src/insurance_harness/compiler/llm.py`
- Test: `harness/tests/test_extraction_task_contract.py`
- Test: `harness/tests/test_extraction_evidence_verifier.py`
- Test: `harness/tests/test_extraction_targeted_repair.py`

- [ ] **Step D1: RED task admission**

Reject whole-product/60-field one-shot tasks, mixed parse attempts, unapproved template/model plan,
unbounded field sets, missing locators and receipt/C0 drift.

- [ ] **Step D2: GREEN task/attempt/receipt**

Implement material×module×risk partitioning and append-only attempt receipts using existing Job/
Worker identities. Use fakes or recorded outputs only; provider calls remain zero.

- [ ] **Step D3: RED Evidence and business rules**

Cover quote-present-but-wrong-subject, wrong ProductVersion, invalid page/cell, table numeric
transcription, units/enums/dates/ranges/arithmetic, unknown vs absent and structured JSON pointer.

- [ ] **Step D4: GREEN fixed roles and bounded repair**

Locator finds candidates; Extractor emits narrow candidates; Deterministic Verifier admits or
rejects; Repairer can only revisit failed fields with exact budgets. Preserve verified fields.

- [ ] **Step D5: Verify no silent failure**

Every exhaustion/unsupported/no-consensus result produces typed unknown/Gap/ReviewItem and a
receipt; zero accepted candidate on failure. Run focused/static/OpenSpec gates and independent
review.

## Task E: Build incremental ChangeSet, conflicts and retractions

**Mission boundary:** deterministic comparison of verified candidates; no model/provider or Wiki
activation. E may run in parallel with D after B.

**Proposed files:**
- Create: `harness/src/insurance_harness/knowledge/source_authority.py`
- Create: `harness/src/insurance_harness/knowledge/incremental_changes.py`
- Create: `harness/src/insurance_harness/knowledge/retractions.py`
- Modify: existing ChangeSet/merge module selected by the child Contract Card
- Test: `harness/tests/test_incremental_changeset.py`
- Test: `harness/tests/test_field_source_authority.py`
- Test: `harness/tests/test_source_exclusive_retraction.py`

- [ ] **Step E1: RED five actions and scope alignment**

Cover add/enrich/supersede/conflict/retract across ProductVersion/time/region/channel/population/
condition; prove different scope is not a conflict and differing values never share Evidence.

- [ ] **Step E2: RED authority and classification separation**

Reject model/classifier authority promotion, low-authority overwrite, missing registration and
caller-supplied trust. Preserve both conflicting candidates and decision basis.

- [ ] **Step E3: RED affected-only recompilation and source-exclusive retraction**

New material may fill one unknown without rewriting stable fields. Retraction requires complete
replacement scope and proof that old support was exclusive; source disable/delete/legal erasure
remain distinct.

- [ ] **Step E4: Implement deterministic ChangeSet compilation**

Reuse current Claim/Evidence/ChangeSet vocabulary and typed ReviewItem; avoid new generic rule
engine. All changes are immutable and idempotent.

- [ ] **Step E5: Verify and review**

Run focused concurrency/idempotency tests only if this Mission writes durable state; otherwise
pure deterministic tests. Apply Ruff/mypy/OpenSpec/diff/scope and independent review.

## Task F: Connect the fixture-only vertical Release slice

**Mission boundary:** one fixture Candidate becomes one human-approved WeKnora Release and can be
reverted; knowledge quality is not claimed. Split Candidate compilation and Release integration if
they cannot remain independently usable small PRs.

**Proposed files:**
- Create/modify: deterministic Wiki compiler under `harness/src/insurance_harness/knowledge/`
- Create/modify: Candidate/Review integration under existing `knowledge/` and `workbench/`
- Create/modify: versioned WeKnora adapter under `harness/src/insurance_harness/adapters/weknora/`
- Test: `harness/tests/test_knowledge_compiler_candidate.py`
- Test: `harness/tests/test_candidate_human_batch.py`
- Test: `harness/tests/test_weknora_release_revert_vertical.py`

- [ ] **Step F1: RED direct model/Wiki and second Head bypasses**

Reject model-written page, raw fallback, mutable member after approval, Harness-local Active,
cross-release mixed read and single-page rollback.

- [ ] **Step F2: GREEN deterministic Candidate compilation**

Compile pages/membership/changelog from fixture accepted ChangeSet, bind base release/epoch and C0
identity, and require one exact human_batch decision.

- [ ] **Step F3: GREEN versioned activation and revert**

Use the already accepted WeKnora sole serving authority contract. Prove activation CAS single
winner, pinned read, current ACL, failure zero publish and atomic revert to an immutable release.

- [ ] **Step F4: Verify provider/model zero**

The entire F suite uses fixture artifacts and a controlled WeKnora Release path; model/parser
calls are zero. Passing F means release mechanics feasible, not `596-1` quality ready.

## Task G: Falsify the complete `596-1` compiler slice

**Mission boundary:** one product, three exact PDFs, 60 fields, one approved parser chain per
material profile, one approved weak-model plan, one human_batch Release and one revert.

**Files:** child Mission freezes a task-local runner/report plus approved artifact paths; no public
experiment platform. Reuse the 049 Golden read-only.

- [ ] **Step G1: Freeze all identities before provider access**

Require exact terms/brochure/rate-table bytes and admitted B artifacts, C catalog, Schema60,
parser chains, prompt/template/model plan, field batches, Evidence verifier, budgets,
EvaluationProtocol and human workflow. Missing any item returns typed BLOCKED with calls=0.

- [ ] **Step G2: Run parser candidates without Golden access**

Use the exact three PDFs to produce content-addressed parse artifacts. Candidate comparison is an
offline admission exercise, not production parallel voting. Do not hardwire MinerU/
Unlimited-OCR/VLM before results.

- [ ] **Step G3: Run the staged weak-model compiler**

Execute material×module×risk tasks with the D budget. Freeze all raw extraction and verified output
hashes before opening the 049 Golden. No fallback to a second model or whole-product prompt.

- [ ] **Step G4: Score deterministically after freeze**

Report fixed-denominator 60-field tri-state/value, coverage/abstention, Evidence locator/quote/
structure, high-risk fields, missing/hallucinated/silent errors, calls/tokens/latency. Use only the
pre-approved Metric IDs and thresholds.

- [ ] **Step G5: Apply the human gate and demonstrate Wiki lifecycle**

If all frozen gates pass, create an exact Candidate, obtain named human approval, activate the
versioned Wiki Release, prove visible/pinned reads, and revert. If any gate fails, emit NOT
FEASIBLE/BLOCKED and leave Active unchanged.

- [ ] **Step G6: Record the winner without platformizing**

Approve one versioned MaterialProfile/parser chain per material role. If no candidate clearly
passes, keep the result inconclusive and choose the next smallest parser input improvement; do not
build dynamic routing, add products or tune against the Golden.

## Final program acceptance

The program is complete only when all of the following are evidenced on exact identities:

1. three PDFs each have an admitted single-attempt structure;
2. all 60 fields have typed final outcomes, with no silent drop;
3. accepted values have valid Evidence and business-rule receipts;
4. the second-material update story demonstrates add/enrich/conflict/retract without unrelated
   rewrites;
5. a named human approves an immutable Candidate;
6. WeKnora serves one pinned version and raw is not an answer fallback;
7. revert atomically restores a prior immutable Release;
8. parser/model outputs were frozen before Golden access;
9. all failures preserve the previous Active Release and produce typed evidence;
10. no second runtime, second Active Head or generic parser/Agent platform was introduced.
