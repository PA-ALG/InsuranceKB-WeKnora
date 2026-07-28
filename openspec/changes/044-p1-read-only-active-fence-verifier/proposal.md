# 044 · P1 Read-only Active Fence Verifier

> Status: implementation authorized by the user Mission Card on 2026-07-28.
>
> Authority: production architecture §12 and P1; OpenSpec 035 P1.3; OpenSpec
> 043 P2D.1/P2D provider pre-call dependency.

## Why

P2d must deny an external provider call when its worker job is no longer the
current active execution. The existing P1 `heartbeat` proves a lease by
renewing it, so using it for authorization would mutate state on the decision
path and make a denied call non-zero-write. P2d also must not read
`wiki_jobs` directly.

## What

Add one P1-owned `JobStore.verify_active_fence` read API. It reads the current
job row and database clock and succeeds only for the exact
Space/job/generation/`running`/attempt/unexpired-lease tuple supplied by the
caller. It returns the current immutable `JobSnapshot`.

Both success and rejection are persistently read-only: no lease renewal, state
transition, Outbox append, receipt, or other row write.

## Non-goals

- P2d provider/ACL/profile implementation;
- heartbeat, claim, start, reclaim, or task transitions;
- capability/token issuance;
- schema or migration changes;
- changes to P3, WeKnora, or external transports.

## Impact

The production change is one method in the existing P1 JobStore. Tests extend
the existing deterministic and PostgreSQL P1 suites. No new dependency,
service, table, migration, or runtime configuration is introduced.
