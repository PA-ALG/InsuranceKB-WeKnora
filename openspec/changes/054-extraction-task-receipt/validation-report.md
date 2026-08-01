# Validation report: 054 extraction task and receipt

## Candidate state

- Base/head: `16ae691d7c4c1edfc4857b55b50d3c18c97e7f9b`
- Base tree: `0e706faea3e7bd4d7095f9b41414e0df5828384d`
- Branch: `codex/054-extraction-task-receipt`
- Delivery state: `STAGE_3 / 052_BOUND / 053_EXACT_ADMISSION_INTEGRATED`
- Commit/push/PR: `NOT RUN`

## Baseline evidence

- `uv run pytest tests/test_material_profile_template_binding_052.py -q`
  - `15 passed`

## Stage-1 evidence

- Focused RED:
  - `uv run pytest tests/test_extraction_task_receipt_054.py -q`
  - collection stopped with the expected `ModuleNotFoundError` for
    `insurance_harness.compiler.extraction_receipts` before either production
    module existed.
- Focused GREEN:
  - the same command at the final Stage-1 checkpoint: `8 passed in 1.87s`.
- Ruff:
  - the two production files plus focused test: `All checks passed!`.
- strict mypy:
  - the two production files plus focused test: `Success: no issues found in 3
    source files`.
- OpenSpec 054 strict:
  - `Change '054-extraction-task-receipt' is valid`.
- diff/scope/private/secret:
  - `git diff --check`: pass;
  - exact changed paths: 9, all within the frozen budget;
  - real index: empty;
  - private path and secret-pattern scan: no matches.

## Historical Stage-1 boundary

- Implemented: immutable task identity, explicit attempt budget, typed attempt
  and receipt identities, exact per-field closure, one unresolved-field repair,
  Golden-blind inputs, and no-success default behavior.
- Not implemented: any 053 import, field mirror, production admission adapter,
  provider call, persistence, worker, queue, or runtime integration.
- At that checkpoint the 053 gate was open; it is closed by Stage 3 below.

## Historical Stage-2 evidence

- Safety rebase:
  - the nine-path WIP was archived in stash
    `codex-054-stage1-edd65fd4-before-main-711372`;
  - the branch fast-forwarded to exact main `711372b2...`;
  - stash restoration had only the expected README status conflict, resolved
    mechanically; the real index is empty and the safety stash is retained.
- Focused RED:
  - `uv run pytest tests/test_extraction_task_receipt_054.py -q`
  - `10 failed, 1 passed`; failures were the missing
    `ExtractionTaskProfileV1`, profile builder, and 053 protocol seam.
- Focused GREEN before final gates:
  - the same command: `11 passed in 0.17s`.
- Final focused integration:
  - `uv run pytest tests/test_extraction_task_receipt_054.py
    tests/test_material_profile_template_binding_052.py -q`;
  - `40 passed in 1.01s`.
- Ruff: `All checks passed!` for the two production files and focused test.
- strict mypy: `Success: no issues found in 3 source files`.
- OpenSpec 054 strict: `Change '054-extraction-task-receipt' is valid` (the
  later telemetry flush warning was non-authoritative and did not alter the
  validator result).
- Diff/scope/private/secret: pass; exact nine paths, real index empty, no
  private host path or credential-shaped content.
- Implemented at that checkpoint: exact merged-052 profile/policy/authority binding, independent
  parser-vs-extraction budgets, binding-hash closure, and one unimplemented 053
  protocol seam.
- The protocol-only state was superseded after 053 committed.

## Stage-3 FINAL corrective evidence

- Safe integration base:
  - exact 053 head `74f74102...` was fetched and verified as a descendant of
    the prior 054 base;
  - after GREEN, the WIP was protected again and fast-forwarded to exact merged
    main `16ae691d...`;
  - README is byte-identical to main and retains the current 052–056 statuses.
- B1 initial closure RED→GREEN:
  - a two-field initial receipt against a three-field task first failed the
    expected test because `ReceiptChainV1` did not bind its task;
  - the chain now embeds the exact task and rejects
    `initial_receipt_fields_mismatch`.
- B1 repair causation RED→GREEN:
  - two initial receipts with the same unresolved subset first produced repair
    attempts with no `parent_receipt_hash`;
  - repair attempts and receipts now bind the exact parent receipt hash in
    their canonical identity, producing distinct attempt hashes.
- B2 wildcard RED→GREEN:
  - embedded `space-*`, `coverage-*`, `risk-?`, and `version-all` identities
    were initially accepted;
  - the bounded code-owned identity check now rejects glob characters and
    wildcard-semantic tokens.
- Exact 053 integration RED→GREEN:
  - the protocol-only port initially raised `Protocols cannot be instantiated`;
  - the concrete port now consumes the exact 053 DTOs, validates ADMIT and
    cross-artifact closure, and derives opaque refs from their computed hashes;
  - a drifted quality-decision manifest hash fails with
    `parse_artifact_admission_mismatch`.
- Final ADMIT-closure RED→GREEN:
  - attempt 1 using the bounded-upgrade profile and attempt 2 using the default
    profile were both initially accepted; both now fail against the exact
    parser profile selected by the receipt for that attempt;
  - independently drifted document/manifest privacy or output policy refs were
    initially accepted; both now must exactly match the receipt;
  - a self-consistent manifest with `pagination_complete=false` was initially
    accepted and now fails before any input-reference bundle is returned;
  - the focused corrective selection changed from five expected `DID NOT
    RAISE` failures to `5 passed, 13 deselected`.
- Final focused integration:
  - `uv run pytest tests/test_extraction_task_receipt_054.py
    tests/test_parsed_document_contract_053.py
    tests/test_material_profile_template_binding_052.py -q`;
  - `60 passed in 3.87s`; the standalone 054 suite is `18 passed in 1.60s`.
- Ruff: `All checks passed!`.
- strict mypy: `Success: no issues found in 3 source files`.
- OpenSpec 054 strict: `Change '054-extraction-task-receipt' is valid`; the
  later telemetry flush warning did not alter the successful validator result.
- Diff/scope/private/secret: pass; exact eight changed paths within the frozen
  nine-path budget, README byte-identical to main, and real index empty.
- Child E native evidence remains repository-external and unchanged.

## Explicitly not run

- full suite
- provider/model/live/WeKnora
- PostgreSQL/DB/migration
- production worker/queue/runtime integration

The adapter closes only the pure exact-DTO composition boundary. It does not
grant provider execution, CandidateRelease, or production authority.
