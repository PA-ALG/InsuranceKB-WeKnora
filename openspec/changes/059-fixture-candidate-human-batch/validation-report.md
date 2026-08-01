# 059 · Validation Report

## Stable candidate identity

- Base/HEAD: `4196dd02d003b0641061e5c2e46ba03c355c19d4`
- Branch: `codex/059-fixture-candidate-human-batch`
- Dependency: 057 merged; 058 merged as PR #86, merge head
  `07c4cd31d729c57d19f3de1118354e05b4092b0d`
- State: `QUALITY CORRECTIVE COMPLETE / AWAITING DELTA REVIEW`
- Exact candidate tree/temp-index SHA: reported out of band after staging to avoid
  a self-referential document hash

## RED / GREEN evidence

- The focused test intentionally fails with typed marker
  `OPEN_SPEC_059_BLOCKED_ON_ACCEPTED_058_COMMIT`.
- After accepted 058 arrived, the real seam RED failed collection with
  `ModuleNotFoundError: insurance_harness.knowledge_compiler.candidate_batches`.
- Focused GREEN before external review: `8 passed`.
- Source-custody corrective RED proved a repair-only 057 revision was omitted
  from the Candidate source set; GREEN binds the union of fact and verification
  source revisions.
- External Quality RED proved direct DTO construction and `model_copy`
  revalidation could omit required review membership or weaken conflict Evidence
  custody while preserving Candidate hash binding.
- Spec/API/Data RED proved caller-supplied schema identity, missing repair-only
  source custody and duplicate repair-field receipts were not closed by the
  exported aggregate.
- Aggregate GREEN embeds exact 054 ReceiptChain values, derives Space/schema
  authority, and recomputes source/receipt/repair plus exact
  conflict/high-risk/repair-needed fact and Evidence membership.
- Final repair-preservation RED proved a caller could jointly rewrite a parent
  PASS result into FAIL and forge matching gap/review records. GREEN preserves
  every parent PASS byte and derives exact gap/review tuples from final non-PASS
  results.
- Final focused GREEN: `14 passed`.
- Final 054+057+058+059 bounded regression: `106 passed`.
- Isolated-process operation guards blocked filesystem, environment, network,
  subprocess and SQLAlchemy engine entry points during fixture construction;
  construction completed with zero guarded operation. Transitive module loading
  was therefore assessed as loading, not an FCH6 I/O operation.

## Gates at this checkpoint

- 057 bounded baseline before edits: `50 passed`.
- Ruff focused: `PASS`.
- strict mypy on the two changed Python files: `PASS`.
- OpenSpec 059 strict: `PASS`.
- `git diff --check`, strict seven-path scope, private/secret and UTF-8/LF
  scans: `PASS`.
- Exact candidate tree/index SHA are reported out of band after final freeze.

## NOT RUN

provider, model, live, database, PostgreSQL, WeKnora, Golden, full suite,
commit, push, PR, Ready, merge.
