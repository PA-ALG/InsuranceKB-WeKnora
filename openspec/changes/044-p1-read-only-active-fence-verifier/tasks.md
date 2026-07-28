# 044 Tasks

## Contract Card

- **Single responsibility:** prove that an expected P1 worker fence is active
  without mutating P1 state.
- **Authority read:** current `wiki_jobs` row plus PostgreSQL database clock.
- **Writes:** none.
- **Transaction boundary:** one bounded read transaction; closed before the
  method returns.
- **Expected facts:** `space_id`, `job_id`, `lease_generation`, `running`
  state, exact `attempt`, unexpired lease.
- **Failure:** existing typed P1 errors, zero persistent changes.
- **Path budget:** one production file, two existing test files, this compact
  OpenSpec and implementation plan; zero migration.

## Tasks

- [x] T1 Freeze the delta spec and pass OpenSpec strict validation.
- [x] T2 Add deterministic REDs for success, each mismatch, DB-clock expiry,
      and zero writes.
- [x] T3 Implement the minimum read-only JobStore method and turn T2 GREEN.
- [x] T4 Add/run PostgreSQL 16 interleaving coverage for verify versus reclaim.
- [x] T5 Run focused regression, Ruff, mypy, OpenSpec strict, scope and diff
      checks; record exact NOT RUN lanes.
