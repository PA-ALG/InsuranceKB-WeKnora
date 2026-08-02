# 065 implementation plan

## Task 1: SDD and preflight

- [x] Verify authoritative base, number availability, Owner conflicts and merged 059 APIs.
- [x] Freeze the six-path ceiling and the no-production-change stop condition.

## Task 2: RED

- [x] Add the RED for missing or malformed external hashes failing before any Release operation.
- [x] Prove the exact Head/CAS sequence, a deterministic task-local CAS single winner,
  and zero orphan writes; keep real PostgreSQL concurrency for the final external proof.
- [x] Prove pinned-read stability, fresh ACL denial, same-scope revert and injected rollback.
- [x] Freeze an independent C0 domain vector, deterministic receipt and privacy negatives.
- [x] Add resigned envelope/preparation drift REDs, including fault-activation manifest drift
  stopping after `Prepare` and before `ActivateReviewed`.

## Task 3: Minimal GREEN

- [x] Add one task-local runner that composes only merged 059 service/repository APIs.
- [x] Keep all authority external and emit only the closed privacy-safe proof receipt.
- [x] Label the deterministic single-winner CAS proof as non-PG and prove the real 059 revert separately.

## Task 4: Verification and freeze

- [x] Run focused Go tests, relevant 059 compatibility, vet, OpenSpec065 strict, diff/scope and
  private/secret gates.
- [x] Freeze an exact candidate without commit, push, PR or external execution.
