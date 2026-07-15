# Local WeKnora Live Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for bounded code tasks and superpowers:verification-before-completion before any completion, commit, push, or PR claim. The main agent alone owns Docker, credentials, GitHub environment mutation, and the final live run.

**Goal:** Build a repeatable, loopback-only real WeKnora environment with independently configurable remote models, then obtain exact-SHA, zero-skip evidence for PR #9's five frozen live tests through an isolated ephemeral runner.

**Architecture:** A new OpenSpec change `023-local-weknora-live-environment` owns local provisioning and the trusted workflow hardening. WeKnora and Harness PostgreSQL remain separate Compose data planes; a disposable runner container joins only their internal networks and receives only seven per-run live values. Model credentials remain in a mode-`0600` local file. WeKnora Chat/Embedding/ReRank profiles and Harness extraction are independent; extraction initially uses Bailian DeepSeek V4 Flash through the existing `HARNESS_LLM_*` contract.

**Tech Stack:** Python 3.12, pytest, Pydantic settings, httpx with `trust_env=False`, Docker Compose/Colima, WeKnora v0.6.3, PostgreSQL 16, GitHub Actions, `gh`, OpenSpec.

---

### Task 1: Create the isolated change and freeze the SDD contracts

**Files:**
- Create in a new worktree from `origin/main`: `openspec/changes/023-local-weknora-live-environment/proposal.md`
- Create: `openspec/changes/023-local-weknora-live-environment/design.md`
- Create: `openspec/changes/023-local-weknora-live-environment/specs/local-live/spec.md`
- Create: `openspec/changes/023-local-weknora-live-environment/tasks.md`
- Create: `docs/superpowers/specs/2026-07-15-local-weknora-live-environment-design.md`
- Create: `docs/superpowers/plans/2026-07-15-local-weknora-live-environment.md`

- [ ] Use `superpowers:using-git-worktrees` to create `.worktrees/local-live-023` on `codex/023-local-weknora-live-environment` from fresh `origin/main`; do not modify PR #9's branch for infrastructure code.
- [ ] Copy this approved design and plan into that worktree using `apply_patch`.
- [ ] Write requirements `R1.1` configurable/redacted model profiles, `R2.1` loopback and pinned images, `R3.1` idempotent WeKnora provisioning, `R3.2` PDF SHA ownership, `R4.1` trusted exact-SHA workflow, `R4.2` frozen five-node/JUnit gate, `R5.1` isolated ephemeral runner, `R5.2` unconditional cleanup, and `R6.1` auditable live evidence.
- [ ] Record that `HARNESS_LLM_BASE_URL`, `HARNESS_LLM_API_KEY`, and `HARNESS_LLM_MODEL_WEAK` select the extraction provider/model and default local profile is Bailian `deepseek-v4-flash`; changing them must not alter code, schemas, or KB identity.
- [ ] Run `openspec validate 023-local-weknora-live-environment --strict`; fix only spec defects before code.
- [ ] Obtain one bounded read-only spec review. Stop after one revision cycle unless a Critical finding remains.

### Task 2: Add a machine-readable, redacted local model configuration

**Files:**
- Modify: `.gitignore`
- Create: `.env.local-live.example`
- Create: `harness/src/insurance_harness/live_env/__init__.py`
- Create: `harness/src/insurance_harness/live_env/config.py`
- Create: `harness/src/insurance_harness/live_env/model_probe.py`
- Create: `harness/tests/test_local_live_config_023.py`
- Create: `harness/tests/test_local_live_model_probe_023.py`

- [ ] Write `test_r1_1_bailian_deepseek_extraction_profile_is_independently_configurable` RED. It must load the existing `HARNESS_LLM_*` names and prove switching `HARNESS_LLM_MODEL_WEAK` does not change WeKnora Chat/Embedding/ReRank profiles.
- [ ] Write RED tests for missing/duplicate keys, non-`0600` secret-file mode, HTTPS requirement for remote gateways, and output redaction. Tests must never contain a real credential.
- [ ] Add explicit WeKnora role keys for Chat, Embedding, and ReRank in `.env.local-live.example`; keep role credentials independent while allowing the same provider values to be repeated deliberately.
- [ ] Implement a strict dotenv loader that accepts only `KEY=value`, returns typed role profiles, refuses unknown security-sensitive aliases, reports only `SET`/`EMPTY`/invalid, and never prints URL, token, password, or response bodies.
- [ ] Implement four minimal OpenAI-compatible probes: Chat, Embedding, ReRank, and Harness extraction. Use `httpx.AsyncClient(trust_env=False)`; validate response shapes, use `max_tokens >= 4096` for reasoning extraction, and require non-empty `content` after the existing retry semantics.
- [ ] Assert the Embedding dimension is derived from the returned vector length. Run both focused modules RED→GREEN, then focused Ruff/mypy.

### Task 3: Make Compose local-only, reproducible, and testable

**Files:**
- Create: `deploy/local-live/docker-compose.weknora.override.yml`
- Create: `deploy/local-live/docker-compose.harness.override.yml`
- Create: `deploy/local-live/images.lock`
- Create: `harness/src/insurance_harness/live_env/compose.py`
- Create: `harness/tests/test_local_live_compose_023.py`
- Modify: `docs/insurance-kb/14-deployment-runbook.md`

- [ ] Write `test_r2_1_all_published_ports_are_loopback_only` RED by rendering both Compose projects and rejecting `0.0.0.0`, `::`, bare ports, or host networking.
- [ ] Write RED tests that reject the example Harness password, mutable `latest`, missing health checks, and image references that do not match the committed version/digest lock.
- [ ] Add overrides binding frontend, app, and Harness PostgreSQL to `127.0.0.1`; do not publish Redis, docreader, or WeKnora's platform PostgreSQL.
- [ ] Generate a random Harness PostgreSQL password into a separate ignored mode-`0600` runtime env file; never rewrite `.env.local-live`.
- [ ] Pin WeKnora to approved `v0.6.3`, pin PostgreSQL/Redis/docreader dependencies, resolve and record image digests before acceptance, and make the rendered-config verifier fail closed on drift.
- [ ] Add health and socket-binding checks. Run focused tests RED→GREEN without starting Docker.

### Task 4: Provision WeKnora and Harness resources idempotently

**Files:**
- Create: `harness/src/insurance_harness/adapters/weknora/admin_client.py`
- Create: `harness/src/insurance_harness/live_env/provision.py`
- Create: `harness/scripts/local_live.py`
- Create: `harness/tests/test_local_live_provisioning_023.py`
- Create: `harness/tests/test_local_live_cli_023.py`

- [ ] Write `R3.1` RED tests with `respx` for first-user administrator bootstrap, dedicated tenant, three role-specific remote model records, KB-RAW, KB-WIKI, least-privilege Tenant API Key, and bound KnowledgeSpace. Keep every WeKnora endpoint detail inside `adapters/weknora/`.
- [ ] Write RED ownership tests: stable resource names may be reused only when their environment marker, tenant, model role, Embedding dimension, and KB role all match; mismatch must fail closed.
- [ ] Write `R3.2` RED tests for a selected life-insurance PDF: SHA-256 match reuses one completed record; digest/KB mismatch uploads once; parse must complete with non-empty chunks; KB-WIKI receives no PDF.
- [ ] Implement minimal admin adapter methods and an idempotent provisioner. Do not read WeKnora databases or queues.
- [ ] Implement CLI phases `check`, `probe-models`, `up`, `provision`, `verify`, `run-local`, and `down`; default to non-destructive behavior and require explicit confirmation for any volume deletion.
- [ ] Store generated IDs and non-model runtime credentials in the separate ignored runtime file. Run focused RED→GREEN, Ruff, and mypy.

### Task 5: Harden the live workflow on a trusted main branch

**Files:**
- Modify: `.github/workflows/harness-live.yml`
- Create: `harness/live-nodes.txt`
- Create: `harness/scripts/run_live_gate.py`
- Create: `harness/tests/test_live_gate_023.py`
- Create: `harness/tests/test_live_workflow_security_023.py`
- Modify: `harness/tests/test_ci_lanes_022.py`
- Modify: `harness/scripts/check_junit.py`

- [ ] Freeze the five complete node IDs from the approved design in `harness/live-nodes.txt`; write `test_r4_2_live_manifest_equals_canonical_collection` RED and compare exact set equality, not count only.
- [ ] Write JUnit RED cases for `tests != 5`, any skip/failure/error, duplicate/missing node, and a substituted fifth test.
- [ ] Write workflow RED tests requiring `workflow_dispatch` inputs `pr_number`, full `head_sha`, and `runner_nonce`; a GitHub-hosted no-secret preflight; same-repository open-PR validation; immutable detached checkout; a unique self-hosted label; and an always-run GitHub-hosted postflight head recheck.
- [ ] Make `run_live_gate.py` compare collection with the manifest, execute those explicit nodes, and validate that JUnit contains exactly the same identities with `tests=5 skipped=0 failures=0 errors=0`.
- [ ] Change the live job to use only the seven frozen `HARNESS_LIVE_*` values from the protected environment. It must never receive `.env.local-live`, model gateway credentials, administrator credentials, the Docker socket, or a host path.
- [ ] Run workflow/security/JUnit focused tests RED→GREEN and ensure existing `test_ci_lanes_022.py` remains green.

### Task 6: Build the isolated ephemeral runner and cleanup controller

**Files:**
- Create: `deploy/local-live/runner/Dockerfile`
- Create: `deploy/local-live/runner/entrypoint.sh`
- Create: `deploy/local-live/runner/runner.lock`
- Create: `harness/src/insurance_harness/live_env/github_live.py`
- Create: `harness/tests/test_local_live_runner_023.py`
- Modify: `harness/scripts/local_live.py`

- [ ] Write `R5.1` RED tests for a random `insurancekb-live-<nonce>` name/label, official runner version+checksum lock, `--ephemeral`, one-job lifetime, non-root user, no Docker socket, no host-home/workspace mount, and attachment only to the two required internal networks.
- [ ] Write `R5.2` failure-injection RED tests proving every phase attempts cleanup without masking the primary error: delete the two GitHub secrets/five variables, revoke per-run WeKnora API Key, drop per-run PostgreSQL role, unregister runner, and remove container/anonymous volume/workspace/diagnostic logs.
- [ ] Implement exact-PR/SHA validation locally before mutation. Refuse forks, closed PRs, mutable refs, unexpected labels, or a head change.
- [ ] Mint a per-run Tenant key and PostgreSQL role with only the live tests' required capabilities; never copy persistent admin/model credentials to GitHub.
- [ ] Implement runner registration-token retrieval immediately before start, trusted-workflow dispatch, bounded polling with visible progress, cancellation handling, and `finally` cleanup.
- [ ] Run focused RED→GREEN, Ruff, mypy, and a Dockerfile/static policy test; do not dispatch GitHub yet.

### Task 7: Deterministic integration, review, and infrastructure PR checkpoint

**Files:**
- Modify: `openspec/changes/023-local-weknora-live-environment/tasks.md`
- Create: `openspec/changes/023-local-weknora-live-environment/validation-report.md`
- Modify: `HANDOFF.md`

- [ ] Run `openspec validate 023-local-weknora-live-environment --strict`.
- [ ] Run `cd harness && uv run ruff check .`.
- [ ] Run `cd harness && uv run mypy src tests`.
- [ ] Run `cd harness && uv run pytest -m "not live and not integration_postgres" -q`.
- [ ] Run `git diff --check`, ignored-file checks, rendered Compose checks, and all focused 023 contract tests.
- [ ] Request one bounded spec review and one bounded quality/security review; fix verified findings with RED tests.
- [ ] Record software evidence only. Leave real Docker, model probes, and live results as `NOT RUN`.
- [ ] Stop for human review and explicit commit/push authorization. The infrastructure workflow PR must be merged to `main` before Task 9 can dispatch PR #9's live run.

### Task 8: Deploy and verify the persistent local environment

**Runtime artifacts only; do not commit secrets:**
- Update locally: `.env.local-live`
- Generate locally: `.env.local-live.runtime`
- Use: `dataset/shouxian_product/`

- [ ] Change `.env.local-live` to mode `0600` and normalize it to the tracked example without echoing values. Confirm Bailian base URL/API Key and `HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash`; if the Bailian key is absent, report only that key name and pause before model probing.
- [ ] Run `local_live.py check` and all four model probes. Record only provider role, model name, status, latency, and observed Embedding dimension.
- [ ] With approved Docker escalation, pull/build pinned images, start the two Compose data planes, and verify health plus loopback-only bindings.
- [ ] Apply Harness Alembic migrations through `0005`, bootstrap/reuse the marked tenant/models/KBs/Space, and upload exactly one selected PDF by SHA-256.
- [ ] Verify parse completion and non-empty chunks, KB-WIKI ownership, and bound Space IDs.
- [ ] Run the exact five nodes locally through `run_live_gate.py`; require exact JUnit identities and zero skip/failure/error. Preserve sanitized evidence only.

### Task 9: Run the trusted GitHub gate for PR #9 and close OpenSpec 018 T7

**Files on PR #9 branch:**
- Modify: `openspec/changes/018-release-snapshot-read-model/tasks.md`
- Modify: `openspec/changes/018-release-snapshot-read-model/validation-report.md`
- Modify: `HANDOFF.md`
- Modify deployment/status docs only where their existing ledgers require reconciliation.

- [ ] Confirm the hardened workflow commit is on `main`, PR #9 remains open and same-repository, and its captured head SHA still matches the intended implementation commit.
- [ ] Create per-run Tenant/DB credentials and seven temporary GitHub live values; start the unique isolated runner; dispatch the trusted main workflow for the exact PR/SHA.
- [ ] Monitor with bounded polls. Require the five-node JUnit artifact with `tests=5 skipped=0 failures=0 errors=0` and the hosted postflight head-stability result.
- [ ] In mandatory cleanup, remove all seven GitHub values, revoke credentials, unregister/remove the runner, and prove no unique-label runner/container/workspace remains.
- [ ] Record this first run's URL, exact implementation SHA, time, JUnit identity set, and cleanup result in 018 validation evidence; check T7 only after all acceptance facts exist. After authorized commit/push of those evidence documents, freeze the branch—no further repository edits are allowed before review.
- [ ] Re-run deterministic, PostgreSQL, and the complete trusted five-node live gate against that final evidence-document SHA. The final live run must again perform mandatory cleanup and pass postflight head stability.
- [ ] Record the final-SHA run URL/JUnit/cleanup proof in a PR comment or check summary, not in another branch commit, to avoid an infinite evidence-SHA cycle. Obtain final bounded review and update PR #9 to Ready only when all three gates target the unchanged final SHA.

### Execution ownership and time boxes

- Main agent owns Tasks 1, 7, 8, and 9 plus all shared-file integration.
- Subagents may independently implement bounded portions of Tasks 2, 3, 4, 5, or 6 only when file ownership is disjoint; they must return RED→GREEN evidence and must not run Docker, inspect `.env.local-live`, mutate GitHub, commit, or push.
- First implementation RED is due within 15 minutes after Task 1 strict validation. Every implementation task must produce a test/diff/GREEN checkpoint within 30 minutes. Any command or agent with no new output for 60 seconds is polled or stopped; no opaque wait exceeds 10 minutes.
- No model call, Docker deployment, GitHub secret mutation, workflow dispatch, commit, push, or PR readiness claim occurs without the corresponding verification evidence and authorization boundary above.
