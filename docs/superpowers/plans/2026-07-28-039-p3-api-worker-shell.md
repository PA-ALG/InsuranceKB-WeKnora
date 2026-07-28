# OpenSpec 039 P3 API/Worker Shell Implementation Plan

> **For Codex:** Execute this plan task-by-task with strict RED → GREEN evidence. The
> approved product and security design is OpenSpec 039; this plan does not reopen it.

**Goal:** Deliver the same-wheel `wiki-api` and `wiki-worker` process shell with
fail-closed principals, typed `WIKI_` configuration, truthful health, P1-backed worker
drain, and authorized P1.9 observations, without migrations or business handlers.

**Architecture:** Add one `insurance_harness.service_shell` package. Keep identity,
configuration, health/lifecycle, worker execution, HTTP surfaces, and CLI assembly
separate while sharing one lifecycle and settings model. All durable task correctness
delegates to the merged P1 `JobStore`; API observations call only P1.9 read models.

**Tech Stack:** Python 3.12, Pydantic Settings, FastAPI, Uvicorn, SQLAlchemy/Alembic,
pytest/pytest-asyncio.

---

### Task 1: Freeze typed principals

**Files:**
- Create: `harness/tests/test_service_shell_principal_039.py`
- Create: `harness/src/insurance_harness/service_shell/principal.py`
- Create: `harness/src/insurance_harness/service_shell/__init__.py`

1. Add tests for the closed human/service enums, missing/unknown/invalid credentials,
   unknown roles, no anonymous fallback, binding-derived Space scope, caller-supplied
   identity having no effect, and cross-capability rejection.
2. Run the focused file and record the expected import/contract RED.
3. Implement immutable principal models, typed authn/authz errors, a static provider
   behind one minting entry, and unique human-role/service-capability guards.
4. Re-run the focused file to GREEN.

### Task 2: Freeze typed `WIKI_` settings

**Files:**
- Create: `harness/tests/test_service_shell_config_health_039.py`
- Create: `harness/src/insurance_harness/service_shell/config.py`

1. Add tests for the prefix, aggregate missing-key errors, secret redaction, behavior
   differences between two settings sets, and `heartbeat >= lease` refusal.
2. Run the focused test selection to RED.
3. Implement one immutable settings model and sanitized loader/config error.
4. Re-run the focused selection to GREEN.

### Task 3: Separate liveness from truthful readiness

**Files:**
- Modify: `harness/tests/test_service_shell_config_health_039.py`
- Create: `harness/src/insurance_harness/service_shell/health.py`

1. Add tests for dependency-free liveness; first-check, DB failure, timeout, migration
   mismatch/multi-head/unreadable, freshness, and draining readiness behavior.
2. Run the focused test selection to RED.
3. Implement the shared lifecycle and readiness checker. Read the expected revision
   from packaged Alembic metadata and compare it exactly with the database revision.
4. Re-run the focused file to GREEN.

### Task 4: Register two mutually exclusive process surfaces

**Files:**
- Create: `harness/tests/test_service_shell_apps_039.py`
- Create: `harness/src/insurance_harness/service_shell/apps.py`
- Create: `harness/src/insurance_harness/service_shell/cli.py`
- Modify: `harness/pyproject.toml`

1. Add tests that both console scripts exist, API and Worker app factories are
   independently repeatable, API contains no claim loop, and Worker exposes probes only.
2. Run the focused file to RED.
3. Implement the app factories, CLI assembly, and two explicit script entries.
4. Re-run the focused file to GREEN.

### Task 5: Consume jobs only through P1

**Files:**
- Create: `harness/tests/test_service_shell_worker_039.py`
- Create: `harness/src/insurance_harness/service_shell/worker.py`

1. Add deterministic contract tests with a recording P1-shaped store for claim/start/
   heartbeat/typed completion, unknown job type, configured local concurrency, empty
   polling, transient bounded backoff, and loop survival.
2. Run the focused file to RED.
3. Implement an empty explicit handler registry and async worker loop that invokes only
   the P1 public API. Keep real PostgreSQL behavior for the PG selection below.
4. Re-run the deterministic file to GREEN.

### Task 6: Drain API and Worker without a second completion path

**Files:**
- Modify: `harness/tests/test_service_shell_worker_039.py`
- Modify: `harness/src/insurance_harness/service_shell/health.py`
- Modify: `harness/src/insurance_harness/service_shell/worker.py`

1. Add tests that drain immediately removes readiness, prevents new claim, allows
   in-flight completion until the deadline, then cancels handler + heartbeat, and a
   repeated signal requests immediate termination.
2. Run the focused selections to RED.
3. Implement bounded drain around the shared lifecycle. A timed-out task is abandoned
   without another P1 completion/failure call so lease expiry remains the sole recovery.
4. Re-run the focused selections to GREEN.

### Task 7: Authorize observations and preserve API purity

**Files:**
- Modify: `harness/tests/test_service_shell_apps_039.py`
- Modify: `harness/src/insurance_harness/service_shell/apps.py`

1. Add tests for Space-admin/super-admin success, lower-role/service/unauthenticated/
   cross-Space refusal, exact P1.9 mapping, response field allow-list, and absence of
   durable background APIs.
2. Run the focused selections to RED.
3. Add synchronous P1.9 observation routes with provider-backed principal minting and
   the frozen authorization guards; add no business route or background task.
4. Re-run the focused file to GREEN.

### Task 8: PostgreSQL and repository gates

1. Run all 039 focused tests.
2. Run the 039 `integration_postgres` selection against PostgreSQL 16 and verify JUnit
   `skipped=0`; if infrastructure is absent, report `NOT RUN` rather than pass.
3. Run Ruff and strict mypy on changed Python files.
4. Run `openspec validate 039-p3-api-worker-shell --strict`.
5. Run repository diff/scope/secret gates required by the current control documents.
6. Verify Alembic heads remain exactly the baseline and the diff contains no migration,
   ORM table, WeKnora call, or business handler.
7. Record README/HANDOFF as a final shared-governance integration item only; do not
   merge the conflicting README edit from the P2d lane.

### Task 9: Independent review handoff

Provide the dynamic review lane with the exact base/tree, changed files, RED/GREEN
commands, PostgreSQL evidence or honest `NOT RUN`, static/OpenSpec/scope/secret gate
output, and explicit BLOCKER/BACKLOG/REJECTED lists. Do not commit, push, or open a PR.
