# 039 P3 API/Worker Shell · implementation validation

> Date: 2026-07-28  
> Base: `40f3ae9e4b41fab51566c438da08c57d80e3089b`  
> Status: **Draft candidate; PostgreSQL T5/T6 acceptance PASS**

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
| PostgreSQL 16 T5/T6 exact nodes | PASS: `2` tests, `0` skipped, `0` failures, `0` errors |
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

## PostgreSQL 16 acceptance

The exact `integration_postgres` nodes ran against the repository's controlled
PostgreSQL 16 environment:

- `test_t5_postgres_two_workers_single_result_and_unknown_type_budget`;
- `test_t6_postgres_drain_reclaims_with_higher_generation_and_one_result`.

They prove two real Worker loops converge through P1 to single terminal results,
unknown job types consume their configured retry budget without stopping the loop,
and a drained/abandoned generation is recovered by a second Worker with a strictly
higher generation and one final result. The generated JUnit passed the repository
gate with `tests=2`, `skipped=0`, `failures=0`, and `errors=0`.

## Remaining merge gates

- T8 remains unchecked only for the explicitly deferred shared README/HANDOFF status
  integration; its code, test, PostgreSQL, static, OpenSpec, scope, and zero-migration
  gates are PASS.
- T9 implementation review approved the original exact head. The test-only PostgreSQL
  evidence delta remains gated on an exact-tree independent re-review before push.

This report does not claim Ready, production readiness, provider validation, or live
WeKnora validation.
