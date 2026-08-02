# 065 validation report

## Identity

- Base/HEAD/origin-main: `0ce3149f9e99ed7606352bbd149c2b7838d7ec23`
- Branch: `codex/065-release-proof-596-1`
- Path ceiling: 6; README and production paths unchanged
- Pre-replay exact candidate tree: `7d9c0e7c38966cb3176f55b626e63e5d56462422` on
  `414e0384e9ca8cfb74a8f254d144af45c228c192`; strict six additions and real index empty.
- Integration replay: WIP was stashed, `origin/main` fetched and verified exact
  `243894857e888abd94dded9d55424d458c2ec10b`, the clean branch advanced by `ff-only`, and the
  stash restored without conflict. The intervening merged 067 seven-path change has zero overlap
  with the 065 strict-six paths; no README, 067 or production path is modified by 065.
- Final mechanical replay: the same strict-six WIP was saved again, `origin/main` fetched and
  verified exact `0ce3149f9e99ed7606352bbd149c2b7838d7ec23`, and the branch advanced by `ff-only`
  before a conflict-free restore. The intervening 068 strict-eight change has zero overlap; 065
  does not modify 068, 067, README or any production path.

## Current evidence

- Fresh API preflight: merged 059 `Prepare`, `ActivateReviewed`, `Revert`, `BeginPinnedRead`,
  `ReadPinned*`, `SearchPinned`, `GetHead`, `GetReceipt` and `CountState` are available.
- Baseline 059 focused command: stopped during first cold compile with no test result; not claimed
  PASS or FAIL.
- First RED: expected compile failure in `cmd/release-proof-596-1/main_test.go`; the absent
  `proofInputHashes`, `proofRunInput` and `runReleaseProof` symbols prove there is no implementation
  yet. The test requires six exact external hashes and asserts Release operation count remains zero
  for missing, uppercase, short and non-hex inputs.
- OpenSpec065 strict: `PASS` (local specification validation exited 0; optional telemetry could not
  reach `edge.openspec.dev` and did not affect validation).

## GREEN evidence

- Focused runner: `PASS`, `go test ./cmd/release-proof-596-1 -count=1` (eight top-level tests,
  ten parameterized negative subcases, final package runtime 5.475s): exact
  hash/authority zero-operation rejection; real 059 `none/e0 -> R0/e1 -> R1/e2 -> R0/e3`;
  deterministic CAS barrier with two arrivals, one winner, one typed loser and explicit non-PG mode;
  separate real 059 revert to R0/e3; pinned R0 read
  after R1 plus fresh ACL denial; activate/revert receipt-fault rollback; deterministic privacy-safe
  receipt; independent C0 domain vector.
- Integration RED: first real sequence run exposed that the receipt used the after-revert rather
  than after-rollback count snapshot (`preparations=2`, expected `3`); GREEN binds all four snapshots.
- Review RED: a re-signed R1 `review_decision_digest` drift produced two Release operations before
  rejection; GREEN preflights all six authorization envelopes and all three named-human receipts.
- Fault-manifest RED: a validly re-signed fault preparation with a drifted declared manifest reached
  the thirteenth Release operation (`ActivateReviewed`). GREEN now compares the 059-computed fault
  manifest immediately after `Prepare` and stops after operation twelve, before fault activation.
- Concurrency RED: the initial one-connection SQLite setup serialized both goroutines; forcing two
  shared-memory transactions to the repository CAS hook produced raw `database table is locked`, not
  a typed CAS conflict. Both results were rejected as PostgreSQL/CAS evidence. Per Total Control's
  original Mission boundary, GREEN restores a deterministic task-local CAS single-winner proof,
  labels it `DETERMINISTIC_CONCURRENCY_PROOF_NOT_PG`, and independently executes the real 059 revert
  with exact R0/e3/count custody. External PostgreSQL concurrency remains NOT RUN.
- Fresh corrective focused runner: `PASS`, package runtime 2.331s.
- Fresh existing 059 PR2 compatibility: `PASS`, package runtime 2.943s.
- Fresh focused `go vet`: `PASS`.
- Post-main-replay focused runner: `PASS`, package runtime 4.770s.
- Post-main-replay existing 059 compatibility: `PASS`; service 2.933s, handler 3.820s.
- Post-main-replay focused `go vet`: `PASS`. Initial sandbox runs could not access the user-level
  Go build cache; the conclusive commands used isolated
  `GOCACHE=/private/tmp/065-go-build-cache-20260802` without changing source or test scope.
- Final post-068 replay runner: `PASS`, package runtime 2.813s.
- Final post-068 059 compatibility: `PASS`; service 4.585s, handler 5.492s.
- Final post-068 focused `go vet`: `PASS`, using the same isolated warm Go build cache.
- OpenSpec065 strict: `PASS`; optional PostHog telemetry could not resolve its network endpoint and
  did not affect the validator result.
- `git diff --check`, strict-six scope, real-index-empty, UTF-8/LF and high-signal private/secret
  scans: `PASS` before candidate freeze.

## NOT RUN

External PostgreSQL, provider, live, WeKnora, full, commit, push and PR are not run.
