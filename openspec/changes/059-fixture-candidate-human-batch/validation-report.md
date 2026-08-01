# 059 · Validation Report

## PR1 merged identity

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

## PR2 development checkpoint

- Base/HEAD/origin-main after the 060-only fast-forward:
  `1a8e36e032512e77474c83efbe1a97ed1c183b30`; `bfa6fe23...→1a8e36e0...`
  changes only 060 paths and has zero overlap with this candidate.
- Branch: `codex/059-release-cas-pinned-revert`.
- Open PR at creation: 0; isolated worktree; corrective strict eleven-path ceiling.
- Existing Release falsification baseline with isolated Go cache:
  `go test ./internal/application/service -run '^TestWikiReleaseFalsification' -count=1`
  → PASS.
- PR2 RED first failed at compile time on the absent human decision parser/verifier,
  reviewed activation, opaque pin and revert APIs; no production implementation
  existed at that point.
- Corrective RED reproduced: valid legacy raw authorization reached the old
  activation handler without a human receipt; caller URL selected historical R0
  after Head moved to R1; the prior activate/revert test was sequential only.
- Corrective GREEN rejects legacy raw/missing-human/self-reported-digest requests
  with zero Release/member/Head/receipt writes; page/payload/search each pin current
  Head at request start and reject caller-selected history.
- Handler and service `TestWikiRelease*` bounded suites: PASS. Repository
  `TestWikiRelease*`: PASS. Related service/repository/handler/types `go vet`: PASS.
- Barrier/goroutine activate-vs-revert single-winner test: PASS and stable for
  ten fresh iterations using one SQLite connection to remove engine lock noise.
- Named-human fixture verifies independently generated PR1 Candidate, human-batch
  and policy hashes plus canonical unsigned/signed bytes and Ed25519 signature.
- Reviewed activation covers approve/reject, current principal/ACL, expiry,
  signature, nonce and exact hash binding; exact retry survives expiry and a
  same-nonce different authorization digest conflicts.
- Request pin is opaque, observes Head once, keeps R0 after R1 activation and
  independently denies page/payload/search after ACL shrink. Production handlers
  cannot construct an explicit historical pin from their URL `release_id`.
- Revert CAS points only to a same-scope immutable historical Release, advances
  epoch without creating Release/member rows, is exactly idempotent, and receipt
  failure rolls back Head and receipt. Concurrent activate/revert contenders prove
  one expected-head winner.
- OpenSpec 059 strict, `git diff --check`, strict eleven-path scope and bounded
  focused gates: PASS. OpenSpec telemetry flush was offline and did not affect
  validator exit status.
- The broad service package was not used as a gate because an unrelated existing
  webhook test attempts to bind an IPv6 test port, which this sandbox forbids.
- Final successor candidate tree/temp-index identity: reported after freeze.
- External state writes/provider/live/PG/WeKnora: `NOT RUN`.
