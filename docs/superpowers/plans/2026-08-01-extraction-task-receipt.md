# 054 extraction task/attempt/receipt implementation plan

> **Delivery state:** Stage 3 binds merged 052 and the exact committed 053
> admission DTOs; it remains pure and non-authoritative.

**Goal:** Add a small pure-domain contract for material × module × risk-scoped
extraction tasks, an explicit one-or-two-attempt budget, immutable typed
receipts, and at most one unresolved-field repair.

**Architecture:** Two frozen Pydantic modules under the existing compiler
package. `extraction_tasks.py` owns the 052-backed task profile, task identity,
and budgets;
`extraction_receipts.py` owns attempts, per-field outcomes, receipt chains, and
repair derivation. The only 053 boundary is one adapter consuming the exact
public DTOs and returning opaque C0 references computed from their own hashes.

**Scope:** Nine paths. No persistence, runtime, queue, worker, provider, model,
Golden, release, CLI, API, migration, or WeKnora integration.

## Task 1: Freeze OpenSpec and path custody

Files: the five OpenSpec paths plus this plan.

1. Register 053 as an external stacked dependency and 054 as Stage 1.
2. Freeze ETR1–ETR8 and the exact path budget.
3. Validate that no 053-owned path is touched.

## Task 2: Focused RED before production code

File: `harness/tests/test_extraction_task_receipt_054.py`

Add no more than eight focused tests covering:

1. deterministic task identity and rejection of duplicate/non-canonical fields,
   wildcard identity, over-budget fields, malformed refs, and Golden inputs;
2. initial attempt identity and exact task-field coverage;
3. explicit field/attempt outcomes with no default success;
4. receipt hash and cross-task/attempt drift rejection;
5. one targeted repair derived only from unresolved fields;
6. no repair after success, no repair-of-repair, and no third attempt;
7. frozen/extra-forbid JSON round-trip behavior; and
8. source/import scan proving the pure no-053/no-Golden/no-I/O boundary.

Run:

`uv run pytest tests/test_extraction_task_receipt_054.py -q`

Expected RED: import failure because the two production modules do not exist.
Record the exact failure before adding production code.

## Task 3: Independent domain GREEN

Files:

- `harness/src/insurance_harness/compiler/extraction_tasks.py`
- `harness/src/insurance_harness/compiler/extraction_receipts.py`

Implement only:

- `ArtifactRefV1`, `AttemptBudgetV1`, `ExtractionTaskV1`,
  `build_extraction_task`, and `build_initial_attempt`;
- `AttemptRequestV1`, `FieldOutcomeV1`, `AttemptReceiptV1`,
  `ReceiptChainV1`, `build_attempt_receipt`, and
  `build_targeted_repair`;
- canonical hashes using the existing C0 `canonical_hash` helper;
- strict frozen models, exact builtin scalar/container validation, and typed
  fail-closed errors.

Do not add a 053 adapter or a stub that guesses its fields.

Run the focused test until green, then run Ruff and strict mypy on the three
owned code/test paths.

## Task 4: Consume merged 052 and retain one 053 seam

1. Rebase the unchanged nine-path WIP onto main containing merged 052.
2. RED-test policy, authority, binding-hash, and extraction-budget drift.
3. Add `ExtractionTaskProfileV1` using only merged public 052 DTOs.
4. Keep `ParsePolicyReceipt.max_parser_attempts` distinct from the extraction
   task's one-initial-plus-one-targeted-repair maximum.
5. Declare, but do not implement, one 053 admission protocol.

## Task 5: Close FINAL findings and integrate exact 053

1. Bind every receipt chain to the exact task and require initial field closure.
2. Add parent initial receipt hash to repair identity and canonical hash.
3. Reject embedded glob/wildcard semantics in task identities.
4. Replace the protocol-only seam with one exact 053 DTO adapter; copy no DTO
   or hash definition.
5. Recheck the three evaluator-owned ADMIT prerequisites at that adapter:
   attempt/parser profile, receipt-bound privacy/output policy, and complete
   pagination.

## Task 6: Freeze Stage 3

1. Validate OpenSpec 054 strictly.
2. Run diff-check, exact scope, private-path, and secret scans.
3. Update tasks/validation with actual evidence only.
4. Freeze the uncommitted checkpoint and report the exact tree/paths.
5. Do not commit, push, or create PR before independent delta review.
