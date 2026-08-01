# Change: Durable extraction task, attempt, and receipt contract

## Status

`STAGE_3 / 052_BOUND / 053_EXACT_ADMISSION_INTEGRATED`

This change consumes the merged 052 public `MaterialProfile`, `FieldAuthority`,
and `ParsePolicyReceipt` DTOs plus the exact committed 053 `ParsedDocumentV1`,
`ParseManifestV1`, and `ParseQualityDecisionV1` contract. It does not mirror
their fields or hashes and grants no provider or production authority.

## Why

Child D needs a small, deterministic unit of extraction work. Without a
code-owned task identity and append-only attempt receipts, an implementation
could silently broaden one request to an entire product, retry without a bound,
lose failed-field provenance, or treat an empty/partial result as success.

## What changes

- Add a frozen `ExtractionTaskV1` identity scoped by exact Space,
  ProductVersion, SourceRevision, material, module, risk partition, ordered
  field set, C0 input references, and an explicit attempt budget.
- Bind every task to an exact 052-backed `ExtractionTaskProfileV1`: material
  profile and binding hash, parse-policy receipt, applicable field-authority
  group/mode, and the code-owned extraction attempt budget.
- Add typed initial/targeted-repair attempts and immutable receipts with
  canonical hashes and explicit per-field outcomes.
- Permit at most one targeted repair, derived only from unresolved fields in
  the complete initial receipt; verified candidates are never re-requested.
- Bind the targeted-repair attempt identity to the exact parent initial receipt
  hash, so equal unresolved subsets with different causal receipts remain
  distinct.
- Reject embedded glob characters and wildcard-semantic identity tokens rather
  than only whole-value `*`/`all` markers.
- Require explicit terminal/failure outcomes. Missing, blocked, failed, or
  exhausted work cannot become a candidate by default.
- Keep the task domain Golden-blind and non-authoritative: no Golden inputs,
  provider execution, release authority, persistence, worker, queue, DB, or
  migration.

## Stacked boundary

The former 053 seam is now the single concrete `ParsedArtifactAdmissionPort`.
It accepts only the exact 053 DTOs, revalidates their shared subject, manifest,
decision, 052 policy, and ADMIT closure. In particular, parser profile selection
must match the approved default/bounded-upgrade attempt, document and manifest
privacy/output policy must match the receipt, and pagination must be complete.
Only then does it derive opaque references from the DTOs' own computed hashes.
It neither copies the 053 DTO/hash definitions nor turns an extraction task
into production execution authority.

## Scope and path budget

Exactly nine paths are owned:

1. `openspec/changes/README.md`
2. this proposal
3. `tasks.md`
4. `validation-report.md`
5. `specs/extraction-task-receipt/spec.md`
6. `docs/superpowers/plans/2026-08-01-extraction-task-receipt.md`
7. `harness/src/insurance_harness/compiler/extraction_tasks.py`
8. `harness/src/insurance_harness/compiler/extraction_receipts.py`
9. `harness/tests/test_extraction_task_receipt_054.py`

Any tenth through eleventh path requires an explicit same-scope reason. A
twelfth path is a hard stop. No 053-owned path may be changed.

## Non-goals

- ParsedDocument/ParseManifest/quality-gate field design or admission
- provider/model calls or prompt/runtime orchestration
- a generic Agent, workflow, retry, queue, or repair platform
- Job/Worker/P1 persistence, DB, migration, ledger, or outbox changes
- candidate fusion, release, Golden comparison, or machine-auto authority
- WeKnora, live, PostgreSQL, CLI, or public API integration
