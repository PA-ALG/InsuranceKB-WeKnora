# P1 Read-only Active Fence Verifier Implementation Plan

> Date: 2026-07-28
>
> Mission Card: approved in the planning thread before implementation.

## Goal

Expose one P1-owned public read API that lets a downstream worker gate prove that
an expected job fence is still active immediately before external I/O.

The verifier checks the current PostgreSQL job row and database clock for:

- exact `space_id` and `job_id`;
- exact `lease_generation`;
- `state == running`;
- exact `attempt`;
- an unexpired lease.

Success and failure must not renew the lease, change state, append Outbox events,
or persist any other row change.

## Non-goals

- heartbeat or lease renewal;
- claim/start/reclaim/state progression;
- P2d provider, ACL, profile, or authorization logic;
- a reusable capability/token framework;
- schema or migration changes;
- changes to WeKnora or P3.

## Files

- `openspec/changes/044-p1-read-only-active-fence-verifier/`
- `openspec/changes/README.md`
- `harness/src/insurance_harness/jobs/store.py`
- `harness/tests/test_job_store_035.py`
- `harness/tests/test_job_store_postgres_035.py`

## TDD sequence

1. Add deterministic tests for success, Space/job scope failure, stale
   generation, non-running state, attempt mismatch, expired lease, and zero
   persistent writes.
2. Run the new deterministic nodes and confirm RED because
   `JobStore.verify_active_fence` does not exist.
3. Implement the minimum read-only method by reusing P1 input validation,
   generation fencing, database clock, active-lease validation, and
   `JobSnapshot`.
4. Add a PostgreSQL 16 interleaving test proving verification and reclaim
   serialize to either a valid pre-reclaim success or a typed post-reclaim
   rejection, never a stale success.
5. Run focused deterministic and PostgreSQL tests, Ruff, mypy, OpenSpec strict,
   and diff checks. Do not run provider, WeKnora live, or full suites.

## Acceptance

- The public method returns the current immutable `JobSnapshot` only when all
  five expected fence facts match.
- All mismatch paths use existing P1 typed errors.
- Success and every failure leave the job and Outbox tables byte-for-byte
  unchanged except for database-internal lock activity.
- The method closes its database transaction before returning and never holds a
  transaction across provider I/O.
- No migration or new table is introduced.
