# 039 P3 API/Worker Shell · implementation validation

> Date: 2026-07-28  
> Base: `40f3ae9e4b41fab51566c438da08c57d80e3089b`  
> Status: **Draft candidate; PostgreSQL acceptance NOT RUN**

## Delivered software scope

- one wheel exposes `wiki-api` and `wiki-worker`;
- fail-closed human/service principals and Space-scoped authorization;
- typed `WIKI_` configuration with secret redaction and P1 runtime limits;
- dependency-free liveness plus DB/Alembic-head readiness;
- API observations wired only to P1.9 read models;
- Worker wired only to P1 `JobStore`, with an empty production handler registry;
- shared signal/drain lifecycle, heartbeat cancellation, and no second completion path;
- zero migration, zero table/ORM change, zero WeKnora call, zero business handler.

## RED → GREEN evidence

Fresh corrective REDs observed in this implementation window:

1. production composition: four focused failures because API/P1 observations,
   Worker/P1 store, and lifecycle-aware Uvicorn assembly did not exist;
2. P1 runtime configuration: `max_attempts` remained the hard-coded value `3`
   instead of the configured value `7`;
3. heartbeat finalization: completion waited for the full heartbeat sleep and timed
   out before reporting success;
4. first review: an active drain ignored a repeated signal until its original
   deadline, the composed server counted one signal twice, and an installed wheel
   lacked its Alembic readiness metadata.

All four were closed with the minimum in-scope implementation. The inherited T1–T7
focused suite was retained and rerun after the corrective changes.

## Fresh local gates

| Gate | Result |
|---|---|
| 039 focused tests | `45 passed`, one dependency deprecation warning |
| P1 affected regression | `138 passed` |
| Installed-wheel role/readiness smoke | PASS |
| Ruff changed scope | PASS |
| mypy strict changed scope | PASS (`11` files checked) |
| OpenSpec 039 strict | PASS |
| diff/scope/secret/private checks | PASS |
| PostgreSQL 16 acceptance | **NOT RUN** by current mission boundary |
| full deterministic | **NOT RUN** |
| provider/model/WeKnora live | **NOT RUN** |

The TestClient warning comes from the installed FastAPI/Starlette compatibility layer;
it does not change P3 behavior and is BACKLOG, not a merge-success claim.

## Size review alarm

The seven `service_shell` source files total `1,296` physical lines, above the
approximately `900`-line review alarm. This remains one atomic process-shell invariant:
principal/config/health/app/worker/CLI must compose into a usable API and Worker, and
there is no second domain, migration, WeKnora adapter, or business handler to split.
The excess is therefore disclosed for reviewer adjudication rather than hidden or
split into non-runnable half-process PRs.

## Remaining merge gates

- T5/T6 real PostgreSQL multi-worker, lease takeover, and migration-readiness scenarios
  remain unchecked and **NOT RUN**.
- T8 remains incomplete until PostgreSQL evidence exists; its local
  static/OpenSpec/scope subset is PASS.
- T9 independent review has not yet approved the candidate.

This report does not claim Ready, production readiness, provider validation, or live
WeKnora validation.
