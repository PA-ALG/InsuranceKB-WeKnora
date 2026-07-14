# Test Portfolio Rebalance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebalance 016/017 test evidence into deterministic, PostgreSQL integration, and WeKnora live lanes while preserving all existing behavioral assertions and adding objective overlap audit tooling.

**Architecture:** Test-only support modules own reusable scenario construction; focused test modules own one responsibility. GitHub Actions runs deterministic and PostgreSQL integration as separate PR jobs, while a protected manual workflow runs real WeKnora tests. Coverage contexts produce advisory overlap candidates without deleting tests automatically.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, pytest-cov/coverage.py, SQLAlchemy, PostgreSQL 16, GitHub Actions, OpenSpec.

---

### Task 1: P0 live scope lifecycle

**Files:**
- Create: `harness/tests/support/__init__.py`
- Create: `harness/tests/support/live.py`
- Create: `harness/tests/test_live_support_022.py`
- Modify: `harness/tests/test_live.py`

- [ ] Add a failing deterministic test that creates a bound SQLite Space, enters the proposed live-scope context, and asserts `is_database_bound_scope(scope)` remains true inside.
- [ ] Run `.venv/bin/pytest tests/test_live_support_022.py -q` and confirm failure because the helper does not exist.
- [ ] Implement a context-managed helper that retains Session and Engine until context exit, then closes/disposes in nested `finally` blocks.
- [ ] Change the live fixture to `yield` from this helper.
- [ ] Assert the deterministic test observes invalid attestation only after context exit; rerun focused tests.

### Task 2: P0 CI lanes

**Files:**
- Modify: `harness/pyproject.toml`
- Modify: `harness/tests/test_source_revision_postgres_017.py`
- Create: `harness/tests/test_ci_lanes_022.py`
- Modify: `.github/workflows/harness-ci.yml`
- Create: `.github/workflows/harness-live.yml`
- Modify: `harness/.env.example`

- [ ] Add CI configuration contract tests that parse markers/workflows and collect sorted node manifests for `not live and not integration_postgres`, `integration_postgres`, and `live`; assert pairwise disjointness, full-union equality, exactly one PostgreSQL node in integration, four WeKnora nodes in live, PostgreSQL service/preflight and both zero-skip JUnit guards.
- [ ] Run `.venv/bin/pytest tests/test_ci_lanes_022.py -q` and focused collect-only commands; confirm RED against the current marker/workflow configuration.
- [ ] Register `integration_postgres`, move the real concurrency test to it, rename its connection variable to `HARNESS_TEST_POSTGRES_URL`, and keep timeout/cleanup semantics unchanged.
- [ ] Make explicit integration selection fail when `HARNESS_TEST_POSTGRES_URL` is absent; add a PostgreSQL 16 service job with explicit URL, health check, `-m integration_postgres --junitxml=...`, and a guard that requires tests > 0 and skipped = 0.
- [ ] Change deterministic CI to `-m "not live and not integration_postgres"`.
- [ ] Add a protected `workflow_dispatch` live workflow that maps all seven frozen secret/variable names, reports only missing names, runs `pytest -m live --junitxml=...`, and requires tests > 0 and skipped = 0.
- [ ] Run focused collection and local deterministic tests.

### Task 3: P1 bridge split

**Files:**
- Create: `harness/tests/support/source_bridge.py`
- Create: `harness/tests/test_source_bridge_contract_017.py`
- Modify: `harness/tests/test_source_bridge_live_017.py`

- [ ] Record the current collected node IDs: 12 non-live + 1 live.
- [ ] Move reusable orchestration and validation helpers into support without importing test modules.
- [ ] Move the 12 deterministic tests into the contract file; keep only the one endpoint E2E in the live file.
- [ ] Run collect-only commands and compare sorted normalized identity multisets, marker maps and counts with the baseline; preserve before/after manifests for validation.
- [ ] Run both files focused and Ruff/mypy for their imports.

### Task 4: P2 pipeline split

**Files:**
- Create: `harness/tests/support/source_pipeline.py`
- Create: `harness/tests/test_source_pipeline_checkpoint_017.py`
- Create: `harness/tests/test_source_pipeline_runtime_017.py`
- Create: `harness/tests/test_source_pipeline_cli_017.py`
- Delete: `harness/tests/test_source_pipeline_017.py`

- [ ] Record all 88 collected node names and a green baseline.
- [ ] Extract reusable model/source fakes and document builders into support.
- [ ] Move checkpoint/run-identity tests, runtime/artifact tests, and CLI/resource tests into the three responsibility files.
- [ ] Keep each test file under 1000 lines and preserve every test name/parameter case.
- [ ] Compare sorted normalized `(test function name, parameter id)` multisets, marker sets and counts ignoring file path; preserve before/after manifests, then run focused tests, Ruff and mypy.

### Task 5: P2 revision split

**Files:**
- Create: `harness/tests/support/source_revision.py`
- Create: `harness/tests/test_source_revision_notify_017.py`
- Create: `harness/tests/test_source_revision_import_017.py`
- Delete: `harness/tests/test_source_revision_017.py`

- [ ] Record all 51 collected node names and a green baseline.
- [ ] Extract scope/identity/claim/evidence/pred builders into support.
- [ ] Move notification/stale/race/invariant tests and importer/tombstone/aggregate tests into separate files.
- [ ] Keep each test file under 1000 lines and preserve every test name/parameter case.
- [ ] Compare sorted normalized `(test function name, parameter id)` multisets, marker sets and counts ignoring file path; preserve before/after manifests, then run focused tests, Ruff and mypy.

### Task 6: P3 overlap audit and governance

**Files:**
- Create: `harness/scripts/test_portfolio_audit.py`
- Create: `harness/tests/test_test_portfolio_audit_022.py`
- Modify: `docs/insurance-kb/10-development-guide.md`

- [ ] Write failing synthetic-coverage tests for production-only context inversion, phase suffix normalization, configurable Jaccard/minimum-shared thresholds including exact-threshold inclusion, stable ordering, report-only exit behavior, and non-zero exits for malformed/empty context inputs.
- [ ] Implement the minimal JSON audit CLI; its summary must contain context count, production line count, candidate count and thresholds. Run RED→GREEN focused tests.
- [ ] Document the exact production-package-only coverage-context commands and the rule that overlap is a review candidate, not deletion proof.
- [ ] Add the fixed five-column risk evidence table and three completion status definitions to the development guide.

### Task 6b: Coverage dependency integration

**Files:**
- Modify: `harness/pyproject.toml`
- Modify: `harness/uv.lock`
- Modify: `harness/tests/test_test_portfolio_audit_022.py`

- [ ] Add a real coverage smoke to the existing audit test module and confirm RED because `pytest-cov` is not installed; the smoke runs `--cov=insurance_harness --cov-context=test`, exports `coverage json --show-contexts`, and feeds a non-empty production-only artifact to the CLI.
- [ ] After Task 2 owns marker configuration, add `pytest-cov` in one serialized dependency update and regenerate the lockfile.
- [ ] Run the real coverage smoke GREEN and dependency consistency checks.

### Task 7: Integration and closeout

**Files:**
- Modify: `openspec/changes/022-test-portfolio-rebalance/tasks.md`
- Create: `openspec/changes/022-test-portfolio-rebalance/validation-report.md`
- Modify: `HANDOFF.md`
- Modify: `docs/insurance-kb/14-deployment-runbook.md`

- [ ] Run deterministic full suite with explicit lane expression.
- [ ] Use local PostgreSQL only for debugging; record `integration verified` only from a successful PostgreSQL 16 GitHub Actions job URL/commit SHA/time whose JUnit has tests > 0 and skipped = 0; otherwise record NOT VERIFIED.
- [ ] Run Ruff, mypy, diff check, collection inventory, and the coverage-context audit focused on scope modules.
- [ ] Create the validation report and populate the fixed five-column risk table plus three status definitions from the development guide.
- [ ] Record real WeKnora as PASS only if the protected workflow has a successful run URL/commit SHA/time and JUnit tests > 0 with skipped = 0; otherwise record NOT RUN.
- [ ] Dispatch independent spec and quality reviews, resolve findings, commit, push, and update PR #4.

### Parallel execution waves and ownership

- Wave 1 runs Tasks 1, 3, 4 and 5 in parallel. Task 1 alone creates/owns `harness/tests/support/__init__.py`; other tasks may add disjoint support modules but must not modify that initializer.
- Wave 2 runs Task 2 with sole ownership of marker configuration and both workflow files, while Task 6 owns only its script/tests/docs.
- Wave 3 serializes Task 6b so only one worker changes `harness/pyproject.toml` and `harness/uv.lock` after Task 2.
- Task 7 is a single integration pass; parallel workers do not commit shared-branch changes independently.
