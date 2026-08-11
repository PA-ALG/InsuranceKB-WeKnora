# 122 · Validation Report

Status: `IMPLEMENTATION-GREEN / QUALITY-INCONCLUSIVE / REAL-GOLDEN-NOT-RUN`

Review-surface delta: `CONTRACT-FROZEN / IMPLEMENTATION-NOT-RUN`

## Identity and truth boundary

- Implementation base: merged Schema Wiki main commit
  `69e2084805d2411be94742fd7fe4de86b2c9221d`.
- Previous official exact8 result: typed failure; Candidate absent.
- Current provider-zero `45 present / 1 absent_explicitly / 21 unknown`: fixture-only
  contract evidence, not a real quality measurement.
- New provider/model calls: `0`.
- Real named-human Golden creation, official scoring, DB, WeKnora, migration, Draft,
  review, activation and live actions: `NOT RUN`.
- Synthetic test-only Golden inputs exercise deterministic metrics and PASS/FAIL plumbing;
  they are not an official Golden or semantic acceptance result.

## Implemented bounded scope

The implementation adds one product-specific Golden DTO/evaluator module and focused test,
extends the existing Schema Wiki release contract/builder with a PASS-only quality receipt,
adds two distinct domain-separated named-human Golden approvals, and verifies a separately
signed canonical quality receipt at the existing Go `CreateSchemaDraft` seam before any
repository access. The Go verifier is fail-closed when its deployment-owned public-key ring
is absent. The Python evaluation method accepts no verifier or signer argument: a sealed
authority is composed once from exactly two distinct configured human public keys and an
external evaluator signing credential source; duplicate public material and missing
production composition fail before scoring. The Go container separately injects the
configured evaluator receipt public-key ring. It does
not change CandidateV2, provider/model code, runner, database schema, migration, serving
Head, frontend or generic Material Wiki behavior.

This docs-only successor freezes how a future successful evaluation is retained and read:
the full signed receipt, redacted aggregate and private ordered-67 dossier become one
canonical evaluation bundle embedded in the existing Schema Wiki preparation custody
manifest. It adds no table, migration, Head or CAS. FAIL, `FIXTURE_ONLY`, `INCONCLUSIVE`,
missing or stale evaluations remain offline-only and cannot create a Draft. The exact
preparation-scoped summary/dossier/Evidence-preview routes are read-only, Admin/Owner and
Wiki/RAW dual-ACL bound; dossier/Evidence additionally bind the named reviewer. This delta
does not implement or execute those routes.

## Validation gates

- Focused Python evaluator/release/contracts: PASS.
- Focused Go Schema Wiki receipt and pre-persistence rejection: PASS.
- Provider-zero `45/1/21` fixture: `FIXTURE_ONLY`, no PASS receipt or Draft authority.
- Wrong value, stale page/bbox, missing Candidate, foreign Evidence authority, non-PASS,
  reparsed or self-rehashed receipt: fail closed before Draft persistence.
- Self-approved Golden, duplicate/foreign human approval, caller-signed/unknown-key quality
  receipt, signature/content substitution and replay: fail closed; Go repository calls `0`.
- Per-call key injection is absent; duplicate approver public material under different IDs,
  missing evaluator signer identity/credential or an unconfigured Go verifier fail closed.
- Present-value precision/recall use normalized atom TP/FP/FN and macro field F1; bbox IoU
  reports the actual sum of per-fragment IoU values over `count × 1,000,000`, while the
  separately named highlight metric retains threshold pass counts.
- Public aggregate omits canonical field values; private dossier remains separately hashed.
- Ruff, strict mypy, Go formatting and focused type/service gates: PASS.
- Provider/model/live/DB/WeKnora calls: `0`; Draft/review/activation actions: `0`.
- Review-surface backend/frontend tests, database writes and HTTP calls: `NOT RUN`; only
  the contract and route/DTO boundaries are frozen by this successor.

Passing these implementation gates SHALL NOT change semantic quality from `INCONCLUSIVE`
or authorize a model run. Task 2 still requires a separately frozen real named-human Golden,
and Task 5 still requires a separately authorized new execution identity and one-shot
evaluation. Until both complete, no Schema Wiki Draft may be created from this gate.
