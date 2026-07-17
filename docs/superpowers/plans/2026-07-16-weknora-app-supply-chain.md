# WeKnora App Trusted Supply Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a clean, traceable WeKnora app containing scoped Tenant API Key support and model-debug log redaction, then consume it only by GHCR manifest digest.

**Architecture:** A committed JSON source lock and checksum-locked patch define the app source. A trusted-main, dispatch-only GitHub workflow verifies the lock, builds the exact upstream source, emits provenance/SBOM, and pushes GHCR; local-live remains a digest-only consumer.

**Tech Stack:** GitHub Actions, Docker Buildx/BuildKit, GHCR, Python 3.12 standard library, Go tests, pytest, OpenSpec.

**Repository constraint:** `CLAUDE.md` forbids AI commit/push. This session prepares and verifies the diff; a human must commit/merge the bootstrap change before the package-write workflow can be dispatched.

---

## File map

- `deploy/local-live/weknora-app-source.lock.json`: exact upstream/source/patch/platform/GHCR identity.
- `deploy/local-live/patches/model-debug-access-log-redaction.patch`: minimal downstream security patch applied to clean upstream source.
- `harness/scripts/verify_weknora_app_source.py`: deterministic source-lock and checkout verifier used by tests and workflow.
- `.github/workflows/weknora-app-local-live-image.yml`: trusted-main build, test, push, provenance, and SBOM workflow.
- `harness/tests/test_local_live_supply_chain_023.py`: R2.1/R3.1/R3.3 supply-chain contract tests.
- `.dockerignore`: local secret exclusion defense in depth.
- `openspec/changes/023-local-weknora-live-environment/*`, `HANDOFF.md`: SDD task state and bootstrap/live boundary.

### Task 1: Lock the source and verifier contract

**Files:**
- Create: `harness/tests/test_local_live_supply_chain_023.py`
- Create: `harness/scripts/verify_weknora_app_source.py`
- Create: `deploy/local-live/weknora-app-source.lock.json`

- [ ] Write `test_r2_1_*` RED tests requiring the exact repository, commit, tree, `docker/Dockerfile.app` hash, full security ancestor SHAs, target platform, GHCR repository, and patch hash.
- [ ] Run `cd harness && uv run pytest tests/test_local_live_supply_chain_023.py -q`; expect missing lock/verifier failures.
- [ ] Implement a standard-library verifier that rejects unknown lock keys, non-full SHAs, wrong checkout identities, missing ancestors, wrong Dockerfile/patch hashes, unsupported platforms, and mutable/non-GHCR image repositories.
- [ ] Add the exact JSON source lock and rerun the focused tests to GREEN.

### Task 2: Create and prove the downstream security patch

**Files:**
- Create: `deploy/local-live/patches/model-debug-access-log-redaction.patch`
- Modify: `internal/middleware/logger.go`
- Modify: `internal/middleware/logger_test.go`
- Test: `harness/tests/test_local_live_supply_chain_023.py`

- [ ] Add a RED test that exports the locked upstream tree, verifies `git apply --check`, applies the patch, and asserts the focused R3.3 test passes in the patched source.
- [ ] Create the minimal patch that omits model-debug response envelopes while preserving ordinary response-field sanitization, excludes `.env.*` in the actual upstream build context, pins `golang-migrate` to `v4.19.1`, and checksum-verifies a versioned uv installer.
- [ ] Record its SHA-256 in the source lock.
- [ ] Run `go test ./internal/middleware -run R3_3 -count=1` in the fork and the patch applicability contract; expect GREEN.

### Task 3: Add the trusted GHCR workflow

**Files:**
- Create: `.github/workflows/weknora-app-local-live-image.yml`
- Modify: `harness/tests/test_local_live_supply_chain_023.py`

- [ ] Add RED tests requiring dispatch from `main`, minimal permissions, full action SHA pins, isolated upstream checkout, verifier invocation, patch check/application, focused Go test, locked platform, GHCR-only push, OCI labels, BuildKit `provenance: mode=max`, SBOM, and immutable digest output.
- [ ] Implement the smallest workflow satisfying those contracts. It must not run on `pull_request`, accept a caller-controlled repository/commit/platform, or read repository/model secrets.
- [ ] Rerun focused supply-chain tests to GREEN and run `git diff --check`.

### Task 4: Verify the bootstrap diff

**Files:**
- Modify: `openspec/changes/023-local-weknora-live-environment/tasks.md`
- Modify: `HANDOFF.md`

- [ ] Run focused supply-chain pytest and `go test ./internal/middleware -run R3_3 -count=1`.
- [ ] Run `cd harness && uv run ruff check .` and `cd harness && uv run mypy src tests`.
- [ ] Run `cd harness && uv run pytest -m "not live and not integration_postgres" -q`.
- [ ] Run `openspec validate 023-local-weknora-live-environment --strict` and `git diff --check`.
- [ ] Record that GHCR publication, digest write-back, PostgreSQL migration backup, and T7 live remain `NOT RUN` until the trusted workflow is merged to `main`.
- [ ] Present the diff to the user for human commit/merge; do not commit or push from this AI session.

### Task 5: Post-merge publication and digest write-back

**Files:**
- Modify after trusted build: `deploy/local-live/images.lock`
- Modify after trusted build: `deploy/local-live/docker-compose.weknora.override.yml`
- Modify after final acceptance: OpenSpec validation/HANDOFF evidence or external PR check summary as allowed by R6.1.

- [ ] Dispatch the trusted workflow from `main` and wait no longer than ten minutes without polling; workflow itself has an explicit timeout.
- [ ] Verify the GHCR manifest digest, platform, provenance, SBOM, and GitHub attestation.
- [ ] Back up the current WeKnora PostgreSQL database before the first start of the new app.
- [ ] TDD the exact digest write-back and require lock/Compose equality; never accept a mutable tag alone.
- [ ] Pull the digest and run real provision, five direct model probes, stored-model checks, ordinary PDF, `smoke-vlm`, and frozen five-node live with `tests=5 skipped=0`.
- [ ] Rerun every final-SHA deterministic/PostgreSQL/OpenSpec/live gate before marking PR ready.
