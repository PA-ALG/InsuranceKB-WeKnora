# Local WeKnora Live Environment Design

> Date: 2026-07-15
> Status: business design approved; credentials remain local and must never enter Git or logs.

## Goal

Build a persistent real WeKnora test environment on the developer Mac, use it for repeatable local validation, and execute the controlled `harness-live` GitHub workflow inside an isolated, disposable self-hosted runner container so OpenSpec 018 R6.4 can obtain zero-skip evidence without granting PR code access to the developer account.

## Scope and boundaries

In scope:

- upstream WeKnora app, frontend, PostgreSQL, Redis and docreader through the existing Compose stack;
- the independent Harness PostgreSQL from `docker-compose.harness.yml`;
- remote API-backed WeKnora chat, Embedding and ReRank models;
- configurable Harness extraction model, initially Bailian DeepSeek V4 Flash;
- one tenant, KB-RAW, KB-WIKI, a least-privilege Tenant API Key, a bound KnowledgeSpace and one parsed life-insurance PDF;
- all five existing `live` pytest nodes;
- an official GitHub Actions runner package, pinned by version and checksum, registered with `--ephemeral` inside a disposable container only for a controlled live run.

Out of scope:

- public exposure of local WeKnora or PostgreSQL;
- an always-on self-hosted runner;
- production Helm deployment, HA, distributed locking or source-ordering work from OpenSpec 021;
- changing extraction behavior merely to make the environment pass.

## Architecture

The Mac hosts two isolated data planes and one disposable execution plane:

1. The upstream WeKnora Compose network owns WeKnora's platform PostgreSQL, Redis, docreader, app and frontend.
2. `docker-compose.harness.yml` owns a separate PostgreSQL 16 instance. Live tests create random schemas and clean them with `DROP SCHEMA ... CASCADE`.
3. A runner container built from the official GitHub Actions runner tarball joins only the WeKnora app network and Harness PostgreSQL network. It has no Docker socket, no host-home mount and no persistent workspace.

For human/local access, a local-live Compose override binds WeKnora app/frontend and Harness PostgreSQL explicitly to `127.0.0.1`. Startup fails if `docker compose port` or socket inspection reports `0.0.0.0` or `::`. The fixed Harness password from the example Compose is replaced by a generated local password passed through an ignored runtime env file.

Because the repository is public, no runner executes as the developer's macOS user and no persistent runner is permitted. Each run receives a unique runner name and label such as `insurancekb-live-<nonce>`, registers with `--ephemeral`, executes at most one approved job, and is then removed together with its container, anonymous volume, `_work` tree and diagnostic logs. No tunnel or public database port is introduced.

## Trusted workflow and exact-SHA approval

The self-hosted live workflow definition must come from protected `main`, not from the PR branch under test. This infrastructure hardening is delivered separately before OpenSpec 018 live acceptance; PR #9 stays Draft until the trusted workflow is available on `main`.

The trusted `workflow_dispatch` accepts `pr_number`, `head_sha` and a per-run `runner_nonce`. A GitHub-hosted preflight job, with no live secrets, verifies all of the following before the environment job is queued:

- the PR is open and belongs to `PA-ALG/InsuranceKB-WeKnora`, not a fork;
- the requested `head_sha` exactly matches the PR head at approval time;
- the runner nonce has the expected randomly generated format;
- the checkout ref is the immutable full SHA, not a mutable branch.

The live job uses the unique label derived from the nonce, checks out the detached approved SHA, and asserts `git rev-parse HEAD` before installing dependencies. After JUnit upload, a GitHub-hosted postflight job re-reads the PR and rejects the run if the PR head changed during execution.

## Model configuration

Model roles are intentionally independent:

### WeKnora platform models

- Chat: remote API model selected from local configuration. The initial local value is the user-provided MiniMax M2.5 profile; it can later be changed without altering Harness extraction.
- Embedding: `Qwen/Qwen3-VL-Embedding-8B` through the user-provided remote API gateway.
- ReRank: `Qwen/Qwen3-VL-Reranker-8B`, following the confirmed WeKnora UI configuration pattern.
- Provider style: SiliconFlow/OpenAI-compatible API. Base URL and API Key stay local.

Before creating KB-RAW/KB-WIKI, bootstrap validates all three platform endpoints: a minimal chat completion, one Embedding request and one ReRank request. It derives the vector dimension from the returned Embedding length, compares it with WeKnora's model record and never hard-codes it from memory. Provider type is the WeKnora SiliconFlow/OpenAI-compatible remote API implementation, and each probe validates both HTTP status and the expected response shape.

### Harness extraction model

Harness keeps its existing configuration contract:

- `HARNESS_LLM_BASE_URL`
- `HARNESS_LLM_API_KEY`
- `HARNESS_LLM_MODEL_WEAK`
- `HARNESS_LLM_MODEL_JUDGE_FALLBACK` when gateway judging is used

The initial extraction profile is Bailian's OpenAI-compatible endpoint with DeepSeek V4 Flash. Bootstrap runs the same minimal completion contract used by the Harness client, including non-empty `content` handling for reasoning models. Switching the extraction model means changing the three active configuration values; code, database schema and WeKnora KBs do not change. The WeKnora chat model and Harness extraction model may use different providers and credentials.

## Secret handling

`.env.local-live` is the sole human-maintained model credential input and is already ignored by Git. Before use it is changed to mode `0600`. It contains the WeKnora model gateway profile and the independently switchable Harness extraction profile. Remote model URLs and credentials never leave the Mac and are never uploaded to GitHub.

The bootstrap process may report a key as `SET`, `EMPTY` or invalid, but must never print a URL, credential, database password or API response containing a token. Local generated identifiers are stored in a separate ignored mode-`0600` runtime file so that human-supplied model credentials are not rewritten.

Only the seven existing live values are temporarily transferred to the GitHub `harness-live` environment. `HARNESS_LIVE_API_KEY` and `HARNESS_LIVE_DB_URL` are secrets; the other five are variables. They are deleted from the GitHub environment in the mandatory post-run cleanup, whether the workflow succeeds, fails or is cancelled.

The GitHub runner registration token is requested immediately before a run and is never written to `.env.local-live`.

For every GitHub run, bootstrap creates a dedicated WeKnora Tenant API Key limited to the retrieve/ingest capabilities required by the five node IDs and a dedicated PostgreSQL role with `NOSUPERUSER NOCREATEDB NOCREATEROLE` plus only database connect/schema-create privileges. Both use random credentials, are placed in GitHub only for that run, and are revoked after the runner exits. Long-lived local administrator credentials never enter a runner job.

## Provisioning flow

1. Verify Docker/Colima capacity and connectivity.
2. Normalize/validate model configuration without echoing values; probe WeKnora chat/Embedding/ReRank and Harness Bailian DeepSeek endpoints.
3. Pin the WeKnora release to the project's approved version (`v0.6.3`) and record the resolved image digests; do not use mutable `latest`.
4. Generate local-only Compose passwords, apply the loopback-only override and start the five-service WeKnora minimum plus Harness PostgreSQL.
5. Wait for every health check, assert loopback-only host bindings and apply Harness Alembic migrations through `0005`.
6. Establish the initial system administrator through the documented first-user bootstrap, create/reuse a dedicated local test tenant, and keep the administrator credential local.
7. Register the three WeKnora remote models with the system administrator, create/reuse KB-RAW and KB-WIKI with the observed Embedding dimension, and verify KB ownership. KB-WIKI accepts Harness pages only and receives no source PDF.
8. Select one life-insurance PDF by SHA-256. Reuse a completed knowledge record only when the KB and digest both match; otherwise upload once, wait for parse completion and require non-empty chunks.
9. Create or reuse a bound KnowledgeSpace that records the real tenant, raw KB and wiki KB identifiers.
10. Save the resulting local live identifiers, run the exact five nodes locally, and verify zero skip.
11. For a GitHub run, mint per-run Tenant/DB credentials, set the two temporary secrets and five variables, build/start the isolated unique-label runner container, and dispatch the trusted main workflow for the exact PR SHA.
12. After success/failure/cancellation, remove GitHub live values, revoke the per-run API Key/DB role, remove runner registration/container/volumes/logs, and confirm the PR head is unchanged.

Every persistent provisioning step is idempotent by stable names and verifies ownership before reuse. A mismatch fails closed instead of adopting an unrelated tenant, KB, Space or knowledge record. KB-WIKI may contain prior Harness pages; preflight removes only stale pages bearing this environment's exact ownership marker and refuses unknown/non-Harness pages. It does not require a globally empty reused KB.

## Failure handling and cleanup

- Any of the four model endpoint probes failing stops before Docker provisioning.
- Compose health failure leaves containers available for log inspection; it does not recreate volumes automatically.
- Parse timeout preserves the uploaded knowledge for diagnosis.
- Live page tests delete only pages carrying their generated ownership metadata.
- Live database tests use random schemas and drop only those schemas.
- Runner setup failure does not alter the persistent local environment. Cleanup removes any registration, unique container, anonymous volume, workspace, diagnostic log, temporary GitHub value, Tenant API Key and DB role even after cancellation.
- No automatic volume deletion is performed. Destructive cleanup requires an explicit later request.

## Verification

The accepted WeKnora live collection is frozen to these five complete pytest node IDs:

1. `tests/test_knowledge_publisher.py::test_k5_5_live_publish_and_rollback_roundtrip`
2. `tests/test_live.py::test_live_knowledge_endpoint_shape`
3. `tests/test_live.py::test_live_wiki_page_crud_roundtrip`
4. `tests/test_release_snapshot_live_018.py::test_r6_4_live_release_v1_v2_rollback_roundtrip`
5. `tests/test_source_bridge_live_017.py::test_live_source_bridge_compiler_import_evidence_backlink`

Both the local bootstrap and trusted GitHub workflow compare pytest collection with this list for exact set equality before execution. Matching only the count is insufficient.

Local acceptance:

- WeKnora and Harness PostgreSQL health checks pass;
- model probes succeed and Embedding dimension is observed at runtime;
- KB-RAW contains exactly one selected completed PDF knowledge for the recorded SHA-256, with non-empty chunks;
- KB-WIKI has no unknown/unowned pages; any retained page has the expected environment ownership marker;
- the bound Space resolves to the expected tenant/raw/wiki IDs;
- the live collection equals the five-node list above, then executes with `skipped=0` and all pass.

GitHub acceptance:

- the workflow definition comes from protected `main` and the preflight approves PR #9's exact same-repository head SHA;
- the workflow runs on the unique-label isolated ephemeral runner container and detached approved SHA;
- runtime collection must equal the five node IDs above and the canonical `WEKNORA_NODES` set; JUnit must report exactly those five tests with `tests=5 skipped=0 failures=0 errors=0`;
- postflight confirms PR head stability and cleanup proves the runner/container/workspace/temp credentials/GitHub values are gone;
- the run URL, commit SHA and time are recorded in OpenSpec 018 validation evidence;
- T7 is checked and PR #9 is changed from Draft to Ready only after both local and GitHub acceptance pass.
