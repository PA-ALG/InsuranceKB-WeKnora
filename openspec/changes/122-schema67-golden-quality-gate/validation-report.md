# 122 · Validation Report

Status: `IMPLEMENTATION-GREEN / QUALITY-INCONCLUSIVE / REVIEWED-SOURCE-MIGRATION-IN-PROGRESS`

Review-surface delta: `BACKEND-IMPLEMENTATION-GREEN / FRONTEND-NOT-RUN`

## Identity and truth boundary

- Implementation base: merged Schema Wiki main commit
  `69e2084805d2411be94742fd7fe4de86b2c9221d`.
- Previous official exact8 result: typed failure; Candidate absent.
- Current provider-zero `45 present / 1 absent_explicitly / 21 unknown`: fixture-only
  contract evidence, not a real quality measurement.
- New provider/model calls: `0`.
- Exact latest71 human Review: `COMPLETED`, with user-attested reviewer identity `linyao`;
  annotator provenance `claude-fable-5` and confirming attestor `workspace-owner-houjing`
  remain separate layers. Original review time and cryptographic approval receipt are not
  present in the existing bytes and are not invented.
- Schema67 successor migration: `67 REVIEWED / 0 PENDING_RESIDUAL`; 51 reviewed rows remain
  byte-identical and 16 current-material gaps are `unknown` with no value/Evidence/page and
  `NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS`.
- Frozen status split: `source_review_status=COMPLETED`,
  `schema67_mapping_status=COMPLETE_67`, and
  `golden_admission_status=BLOCKED_RECEIPT_UNVERIFIED`. The attestation
  creation time is not the unknown original `reviewed_at` and carries no signature.
- Official scoring, DB, WeKnora, Draft, release review, activation and live actions:
  `NOT RUN`.
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

The review-surface successor retains and reads a future successful evaluation as follows:
the full signed receipt, redacted aggregate and private ordered-67 dossier become one
canonical evaluation bundle embedded in the existing Schema Wiki preparation custody
manifest. It adds no table, migration, Head or CAS. FAIL, `FIXTURE_ONLY`, `INCONCLUSIVE`,
missing or stale evaluations remain offline-only and cannot create a Draft. The exact
preparation-scoped summary/dossier/Evidence-preview routes are read-only, Admin/Owner and
Wiki/RAW dual-ACL bound; dossier/Evidence additionally bind the named reviewer. This delta
implements those backend routes and reuses the immutable-revision third signing ring under
a distinct preparation-Evidence token domain. It does not implement the frontend surface or
execute any live request.

The same private route now returns the closed Dossier V2 wrapper with an exact67
review-successor projection. Formal routing requires residual count zero, named reviewer
`linyao`, known `reviewed_at`, `VERIFIED` whole-batch receipt and exact Candidate Evidence
IDs from stored JoinReceipts. The current complete67 mapping remains receipt-unverified,
so it is explicitly unavailable to Draft/review routes and causes
repository writes `0`; its source Review nevertheless remains completed.

The distinct `golden-quality/successor-status` route now exposes only that current
three-layer state from a deployment-owned canonical provider. Its DTO binds the exact
596-1 scope and artifact hashes, `linyao`/`claude-fable-5` provenance separation, nullable
original review time, attestor event, ordered complete67 mapping and unverified admission
block. Missing provider configuration is typed unavailable. It contains no field values,
Evidence, PASS claim, signature or release action and performs no repository write.

Formal Dossier V2 factory provenance remains
`WAITING_FOR_CONCRETE_VERIFIED_WHOLE_BATCH_RECEIPT`. A literal `VERIFIED` label or bare
receipt digest is not elevated to trusted approval; the current Dossier V2 wire/vector and
its residual-zero admission rules remain unchanged.

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
- Canonical Python evaluation-bundle vector: PASS (`1 passed`).
- Focused Go review-surface types/service/handler/router: PASS; includes existing
  preparation JSONB replay, non-PASS repository calls `0`, named-human dossier access,
  server-selected Evidence and token-only bytes.
- Review-surface Ruff, strict mypy and Go vet: PASS.
- Successor-status closed DTO/provider/service/handler/router/config/container focused
  tests: PASS; unknown/trailing/noncanonical, hash/status/count/order/scope drift and
  API-key/Viewer access fail closed.
- Review-surface frontend tests, database writes and live HTTP calls: `NOT RUN`.

Passing these implementation gates SHALL NOT change semantic quality from `INCONCLUSIVE`
or authorize a model run. Task 2 does not restart human review: it preserves the 51 direct
rows, records 16 current-material gaps as non-blocking unknowns, and must obtain the
required cryptographic approvals before the successor becomes an evaluator-authoritative
Golden. Task 5 still requires a separately authorized new execution identity and one-shot
evaluation. Until both complete, no Schema Wiki Draft may be created from this gate.
