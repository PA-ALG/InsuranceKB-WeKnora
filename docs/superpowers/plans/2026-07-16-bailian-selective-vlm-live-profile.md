# Bailian Selective VLM Live Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blocked SiliconFlow local-live profiles with provider-aware Bailian profiles and prove a default-off, per-upload `qwen3.7-plus` VLM path on real WeKnora without changing the frozen five-node live gate.

**Architecture:** Keep direct provider probes in the local-only controller, then create/reuse and attest four WeKnora model resources before any KB mutation. Model credentials are refreshed through WeKnora's secret subresource and stored models are verified through the platform path. KB-RAW remains text-only by persisted contract; only a content-addressed canary fixture receives a multipart `process_config` VLM override and an explicit one-shot reparse path.

**Tech Stack:** Python 3.12, Pydantic, httpx/respx, pytest/pytest-asyncio, Pillow fixture generation, WeKnora v0.6.3 REST, OpenSpec, Ruff, mypy strict.

**Repository constraint:** `CLAUDE.md` requires human validation before AI commit/push. Tasks 1–5 first produce a reviewed, deterministic, provisionally live-tested diff. After the user validates it, commit/push fixes the candidate SHA; all merge gates are then rerun on that exact SHA. Final real-local evidence is posted externally in the PR comment/check summary so recording it does not change the accepted SHA.

---

## File map

- `openspec/changes/023-local-weknora-live-environment/{proposal.md,design.md,tasks.md,specs/local-live/spec.md}`: normative R1.2/R3.3 contracts before function code.
- `harness/src/insurance_harness/live_env/config.py`: typed provider/protocol profiles and fifth VLLM role.
- `harness/src/insurance_harness/live_env/model_probe.py`: five sanitized direct provider probes, including DashScope native rerank and VLM canary.
- `harness/src/insurance_harness/adapters/weknora/admin_client.py`: credentials/debug/reparse/multipart process-config REST primitives and strict response attestation.
- `harness/src/insurance_harness/live_env/provision.py`: endpoint/model/KB binding identity plus ordinary and VLM knowledge contracts.
- `harness/src/insurance_harness/live_env/local_provisioning.py`: provider-aware payloads, four WeKnora models, credential refresh/debug order, runtime state and smoke orchestration.
- `harness/scripts/local_live.py`: stable `smoke-vlm` local command and sanitized result.
- `harness/tests/fixtures/local_live/vlm-canary.png`: deterministic, non-sensitive visual canary fixture.
- `.env.local-live.example`, `docs/insurance-kb/14-deployment-runbook.md`, `HANDOFF.md`, OpenSpec validation: operator profile and evidence.

### Task 1: Amend OpenSpec 023 before function code

**Files:**
- Modify: `openspec/changes/023-local-weknora-live-environment/proposal.md`
- Modify: `openspec/changes/023-local-weknora-live-environment/design.md`
- Modify: `openspec/changes/023-local-weknora-live-environment/specs/local-live/spec.md`
- Modify: `openspec/changes/023-local-weknora-live-environment/tasks.md`

- [ ] Add R1.2 requiring explicit `source=remote`, provider/protocol, `KnowledgeQA`/`Embedding`/`Rerank`/`VLLM`, five direct probes, native DashScope rerank, visual canary and all-role zero-leak failure injection.
- [ ] Add R3.3 requiring credential refresh, `data.ok` stored-model verification, endpoint fingerprint, desired `embedding_model_id`, exact disabled `vlm_config`, ordinary upload with no override, selected multipart VLM override, child-chunk canary and one explicit reparse.
- [ ] State that VLM smoke is a dedicated final-SHA local acceptance command and not a sixth trusted PR #9 live node.
- [ ] Add T6a/T6b task rows and preserve existing T7/T8 meaning.
- [ ] Run `openspec validate 023-local-weknora-live-environment --strict`; expected PASS.

### Task 2: Provider-aware profiles and five direct probes

**Files:**
- Modify: `harness/src/insurance_harness/live_env/config.py`
- Modify: `harness/src/insurance_harness/live_env/model_probe.py`
- Modify: `harness/tests/test_local_live_config_023.py`
- Modify: `harness/tests/test_local_live_model_probe_023.py`
- Create: `harness/tests/fixtures/local_live/vlm-canary.png`
- Modify: `.env.local-live.example`

- [ ] RED: add `test_r1_2_*` cases for independent provider/protocol fields, VLLM profile, Bailian defaults, canonical URL rejection and secret-safe repr.
- [ ] Run `cd harness && uv run pytest tests/test_local_live_config_023.py -q`; expect new R1.2 failures because VLLM/provider/protocol are absent.
- [ ] GREEN: extend `ModelProfile` with provider/protocol and `LocalLiveConfig` with `weknora_vllm`; require all five local profiles while keeping values separately configurable.
- [ ] RED: add direct-probe tests for exact DashScope native rerank envelope/`output.results`, unique in-range indices/finite scores, VLM data-URI canary, runtime embedding dimension and parametrized five-role exception/log/stdout/stderr redaction.
- [ ] Run `cd harness && uv run pytest tests/test_local_live_model_probe_023.py -q`; expect protocol/VLLM failures.
- [ ] GREEN: resolve typed endpoints, use a single strict numeric validator, probe the committed canary through `/chat/completions`, and keep `_redacted` as the only exported failure boundary.
- [ ] Update `.env.local-live.example` to `aliyun`, `openai_compatible`/`dashscope_native`, `deepseek-v4-flash`, `qwen3.7-text-embedding`, `qwen3-rerank`, and `qwen3.7-plus`, with empty keys.
- [ ] Run both focused files; expected PASS. Run Ruff/mypy on touched paths.

### Task 3: Stored-model and resource-identity hardening

**Files:**
- Modify: `harness/src/insurance_harness/adapters/weknora/admin_client.py`
- Modify: `harness/src/insurance_harness/live_env/provision.py`
- Modify: `harness/tests/test_local_live_provisioning_023.py`

- [ ] RED: add R3.3 client tests for `PUT /models/:id/credentials`, multipart `POST /models/:id/debug`, strict `data.ok`, role-specific `raw_response` validation, suppression of `data.error/raw_response` from logs/evidence, and optional multipart `process_config` serialization.
- [ ] Run the exact new node IDs; expect missing methods/fields.
- [ ] GREEN: add typed secret-update/debug helpers without allowing `_request` to flatten away the outer debug status. Debug requests use multipart `input`; ReRank also serializes `documents`, and options are serialized when needed. Require Chat `raw_response.content` non-empty, Embedding `raw_response` to be a finite vector with dimension equal to the direct probe, and ReRank `raw_response` to contain the configured minimum of unique in-range integer indices with finite scores. Add optional upload MIME/process-config fields while preserving the old upload body byte-for-byte when absent.
- [ ] RED: extend `OwnedResource`/`DesiredResource` tests for type/provider/model/endpoint fingerprint, and KB `embedding_model_id` plus exact disabled `vlm_config` attestation.
- [ ] GREEN: implement canonical endpoint SHA-256 and parse real model/KB REST responses into identity fields. Same-name mismatches fail closed.
- [ ] RED: prove an ordinary PDF upload occurs only after disabled-KB attestation and sends neither `enable_multimodel` nor `process_config`.
- [ ] GREEN: keep the ordinary `_ensure_pdf` path unchanged at the wire while making KB binding invariants load-bearing.
- [ ] Run `cd harness && uv run pytest tests/test_local_live_provisioning_023.py -q`; expected PASS.

### Task 4: VLLM provisioning, selective smoke and explicit retry

**Files:**
- Modify: `harness/src/insurance_harness/live_env/local_provisioning.py`
- Modify: `harness/src/insurance_harness/live_env/provision.py`
- Modify: `harness/src/insurance_harness/adapters/weknora/admin_client.py`
- Modify: `harness/scripts/local_live.py`
- Modify: `harness/tests/test_local_live_provisioning_023.py`
- Modify: `harness/tests/test_local_live_cli_023.py`

- [ ] RED: require provider-aware model payloads with `source=remote`, four legal WeKnora types, `supports_vision=true` only for VLLM, and runtime `LOCAL_LIVE_VLLM_MODEL_ID`/endpoint digests. Add an event-recording orchestration test for the exact order: five direct probes → four model ensure/credential refresh operations → three stored-model debug checks → KB mutation.
- [ ] RED: parameterize every credential-refresh failure and every Chat/Embedding/ReRank `data.ok` or role-shape failure; in all cases assert KB/knowledge mutation counts remain zero.
- [ ] GREEN: add `vlm_model` to `ProvisionPlan`/result, register `model:vlm`, refresh all four WeKnora credentials after five direct probes, debug Chat/Embedding/ReRank, then create/attest KB resources.
- [ ] RED: add selected-upload tests asserting multipart `enable_multimodel=true` and serialized `process_config` with the provisioned VLLM ID. Add respx contracts for typed chunk queries that explicitly request `chunk_type=image_ocr` and `chunk_type=image_caption`, follow response totals across pagination, and completely retrieve both sets; keep the ordinary PDF default text-chunk request unchanged. Require an `image_ocr` child with parent ID and in-memory canary, and require every present `image_caption` child to have a parent ID.
- [ ] GREEN: implement content-addressed VLM smoke lookup/upload/wait/chunk attestation without recording model output or canary in evidence. Existing failed/cancelled/incomplete records are reported and preserved; `smoke-vlm` never reparses them automatically.
- [ ] RED: add an explicit `retry-vlm --knowledge-id <id>` CLI/API contract for exactly one `POST /knowledge/:id/reparse` with the same VLLM `process_config`, incremented attempt and no duplicate upload/unbounded loop. Missing ID, completed knowledge and automatic invocation from `smoke-vlm` fail closed.
- [ ] GREEN: implement the explicit one-shot reparse command and sanitized terminal status.
- [ ] RED/GREEN: add `smoke-vlm` and `retry-vlm` CLI dispatch and no sixth entry in `WEKNORA_NODES`. A dirty run reports `HEAD`, `dirty=true` and a diff digest and is explicitly provisional; only a clean committed run may report an exact accepted implementation SHA.
- [ ] Run focused config/probe/provisioning/CLI/live-gate files; expected PASS.

### Task 5: Documentation, deterministic gates and real local acceptance

**Files:**
- Modify: `docs/insurance-kb/14-deployment-runbook.md`
- Modify: `docs/superpowers/specs/2026-07-15-local-weknora-live-environment-design.md`
- Modify: `openspec/changes/023-local-weknora-live-environment/validation-report.md`
- Modify: `openspec/changes/023-local-weknora-live-environment/tasks.md`
- Modify: `HANDOFF.md`
- Local-only update: `.env.local-live`

- [ ] Update the old model passages so they explicitly defer to the approved 2026-07-16 design and contain no stale SiliconFlow profile.
- [ ] Securely normalize local `.env.local-live` to the verified Bailian models using the existing key; never print or commit it.
- [ ] Run `cd harness && uv run ruff check . && uv run mypy src tests`.
- [ ] Run `cd harness && uv run pytest -m "not live and not integration_postgres" -q`.
- [ ] Run PostgreSQL integration and verify JUnit has no skip/failure.
- [ ] Start/verify local WeKnora, run five direct probes, idempotent provision, ordinary PDF path, `smoke-vlm`, then frozen five-node live collection; require `tests=5 skipped=0 failures=0 errors=0`.
- [ ] Before commit, record tracked documentation as `provisional` or `NOT RUN on final SHA`; never put an uncommitted-tree run under the old HEAD SHA. Run OpenSpec strict and `git diff --check`, then request final spec and quality review.
- [ ] Present the reviewed diff plus provisional local evidence to the user for human validation. After approval, commit/push the complete tracked batch and freeze the candidate SHA.
- [ ] On the exact committed/pushed SHA, rerun Ruff, mypy, full non-live, PostgreSQL integration, five direct probes, idempotent provision, ordinary PDF path, `smoke-vlm`, and frozen five-node live; require `tests=5 skipped=0 failures=0 errors=0`.
- [ ] Post only sanitized final-SHA model status, embedding dimension, resource IDs/digests, VLM child counts, fixture SHA, JUnit counts and cleanup state in PR #10 comment/check summary. Do not commit after this successful run.
- [ ] If any final-SHA gate fails and code/docs must change, create a new reviewed commit and repeat every final-SHA gate. Mark PR #10 ready only when deterministic/PostgreSQL CI and all real-local gates refer to the same unchanged SHA.
