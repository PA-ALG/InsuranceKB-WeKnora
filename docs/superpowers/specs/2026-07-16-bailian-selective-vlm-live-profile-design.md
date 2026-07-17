# Bailian Profiles and Selective VLM for Local WeKnora

> Date: 2026-07-16
> Status: business direction approved; written design awaiting final review before implementation.
> Parent change: OpenSpec 023 local WeKnora live environment.

This document supersedes the model-profile, model-probe and affected provisioning passages in `2026-07-15-local-weknora-live-environment-design.md`; the trusted workflow, runner isolation and frozen five-node design remain unchanged.

## Goal

Replace the unusable SiliconFlow local-live profiles with verified Aliyun Bailian/DashScope profiles, and add an independently configurable WeKnora vision-language model for selected image-heavy or scanned documents. Ordinary documents must keep the existing text parsing path and make no VLM calls.

This is an environment and adapter hardening increment. It does not change insurance extraction semantics, the frozen five-node 018 live gate, or upstream WeKnora Go/Vue code.

## Model roles

The local-live environment has five independently configurable roles:

| Role | Initial model | Protocol | Purpose |
|---|---|---|---|
| WeKnora Chat | `deepseek-v4-flash` | DashScope OpenAI-compatible chat | WeKnora conversation |
| WeKnora Embedding | `qwen3.7-text-embedding` | DashScope OpenAI-compatible embeddings | Text retrieval; dimension is discovered from the response |
| WeKnora ReRank | `qwen3-rerank` | DashScope native rerank endpoint | Text result reranking |
| WeKnora VLLM | `qwen3.7-plus` | DashScope OpenAI-compatible vision chat | OCR and image caption for explicitly selected uploads |
| Harness extraction | `deepseek-v4-flash` | DashScope OpenAI-compatible chat | Structured insurance extraction |

`qwen3.7-plus` is the default VLLM because insurance documents contain nested responsibility tables, small exclusions, footnotes and multi-column layouts where extraction quality matters more than the latency of a selectively invoked model. Operators may switch the VLLM profile to `qwen3.6-flash` without a code or schema change. `qwen3.5-ocr` is not a second first-version VLLM: current WeKnora uses one VLLM model for both OCR and caption, so dual-model OCR/caption routing would require an upstream core change and belongs to a later change.

The roles may share one DashScope credential in the local file, but their model, base URL, provider, endpoint protocol and key fields remain independent. No code may infer that two roles share a key.

## Provider-aware configuration and probes

Every WeKnora profile carries an explicit provider and uses WeKnora's remote source contract:

- `source=remote` for all remote models;
- `provider=aliyun` for these initial Bailian profiles;
- `type=KnowledgeQA`, `Embedding`, `Rerank` or `VLLM` according to the role;
- `supports_vision=true` for the VLLM model only.

The provisioning adapter must not hard-code `siliconflow` as either provider or source. The first Bailian ReRank profile is a typed `dashscope_native` protocol with the exact endpoint `https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank`. Its probe and persisted WeKnora model both use the same resolved endpoint, request envelope (`model`, `input.query`, `input.documents`, `parameters`) and `output.results` response shape. The adapter must never append the legacy `/rerank` path or probe a compatible endpoint while registering the native one.

All five probes run before persistent WeKnora mutation:

- Chat and extraction require HTTP success and non-empty completion content.
- Embedding requires a non-empty numeric vector and records its observed dimension.
- ReRank requires native `output.results`; indices must be unique integers within the input range, scores must be finite numbers, and the configured minimum result count must be present.
- VLLM submits the committed non-sensitive visual-canary fixture and requires the response to contain that canary, not merely non-empty text.

Probe logs expose only role, provider, model, status, duration, and embedding dimension where applicable. They must not expose the URL, API key, authorization header, request body, response body, prompt or parsed document content. HTTP clients keep `trust_env=False`. A failed probe stops before tenant/model/KB mutation.

## Selective VLM routing

VLM use is default-off at the knowledge-base level. Provisioning registers the VLLM model and records its stable role identity, but KB-RAW is created with `vlm_config.enabled=false` and `vlm_config.model_id=""`. Reusing KB-RAW requires an explicit attestation of those exact REST fields; a pre-existing KB with either a true enabled flag or any non-empty VLLM model ID fails closed. Omitting an upload override alone is not proof of zero VLM routing because WeKnora inherits the KB configuration.

An upload opts in only when its multipart request supplies `enable_multimodel=true` and serializes the following object as the `process_config` form field:

```json
{
  "enable_multimodel": true,
  "vlm_config": {
    "enabled": true,
    "model_id": "<provisioned-vllm-id>"
  }
}
```

The upload client accepts an optional typed process configuration and serializes it to the multipart `process_config` string field. Omitting it preserves the existing upload payload exactly. The provisioning flow uses the override only for a dedicated, non-sensitive multimodal smoke fixture; the selected ordinary life-insurance PDF continues through the text path without VLM overrides and only after the KB-level disabled-state attestation passes.

The first version intentionally has no automatic page classifier, no file-name heuristic and no silent fallback. Production-style auto-routing based on scan density, image/table count or OCR confidence requires separate quality/cost evidence and a new OpenSpec change.

## Resource identity and idempotency

The persistent resource graph gains `model:vlm` beside Chat, Embedding and ReRank. Model reuse requires environment marker, tenant, model role, type, provider, model name and endpoint fingerprint to match. The endpoint fingerprint is SHA-256 over a canonical URL that lowercases scheme/host, removes a default port, rejects user-info/query/fragment, preserves the normalized path and removes a trailing slash except at root. It is recomputed from the local desired URL and the model URL returned by WeKnora; only the digest is stored in ignored runtime state.

After every direct preprobe succeeds, provisioning creates or reuses each WeKnora model. It then refreshes the current API key through the dedicated `PUT /models/:id/credentials` subresource, keeping the stable model ID and storing no key fingerprint. Chat, Embedding and ReRank are tested again through `POST /models/:id/debug` without resupplying the key. HTTP 200 and outer `success=true` are insufficient: `data.ok` must be exactly true; Chat must contain non-empty content; Embedding must contain a finite numeric vector whose dimension equals the direct-preprobe dimension; ReRank must return the same unique in-range indices, finite scores and minimum count contract. `data.error` and `raw_response` are never logged or written to evidence. VLLM is tested through the opt-in smoke below. A failure at this stage prevents KB/knowledge mutation, although an idempotent model record or refreshed credential may remain for the next run.

KB-RAW reuse additionally requires `embedding_model_id` to equal the newly attested Bailian Embedding model ID, `vlm_config.enabled` to be false and `vlm_config.model_id` to be the empty string. These invariants are checked against the real create/list/get REST response, not only local runtime state. A same-name resource with different ownership, model binding or KB processing state fails closed.

The VLLM model ID is recorded in ignored mode-`0600` runtime state. API keys and raw endpoints are not recorded there. Re-running provisioning reuses the same VLLM identity and must not create duplicate model or smoke-knowledge records.

The multimodal smoke fixture is content-addressed by KB identity plus SHA-256 and contains a unique non-sensitive visual canary. A matching completed record is reusable only when at least one `image_ocr` child chunk has a non-empty `parent_chunk_id` and its in-memory content assertion finds the canary; any `image_caption` chunk that is present must also have a non-empty parent ID. The canary content and model output are never written into evidence.

For a failed, cancelled or incomplete matching smoke record, an operator or an explicitly requested provisioning retry calls `POST /knowledge/:id/reparse` with the same typed object under JSON field `process_config`. Empty-body reparse is not used. The retry reuses the persisted knowledge ID and source, replaces its process override with the explicit VLLM override, increments the parse attempt and waits again for a terminal state. A second failure preserves the record and reports knowledge ID, attempt, status and sanitized error class; it does not loop automatically or re-upload a duplicate.

## Failure semantics

- A profile validation or any of the five direct preprobe failures causes zero persistent mutation. Stored-model debug is a post-model-mutation verification stage and may leave an idempotent model record or refreshed credential, but it still prevents all KB and knowledge mutation.
- An explicitly opted-in VLM upload that fails parsing remains available for one explicit same-config reparse; there is no unbounded automatic retry.
- There is no automatic downgrade from `qwen3.7-plus` to a cheaper model; a lower-cost profile requires an explicit configuration change and a new probe.
- An ordinary upload never becomes multimodal because a VLM exists in the tenant.
- Cleanup never deletes unrelated tenant models, KB content or persistent volumes.

## Acceptance

The increment is accepted only when all of the following hold:

1. Unit/contract tests prove provider/source/type payloads, native ReRank endpoint/envelope/response handling, endpoint canonicalization, credential refresh, stored-model verification and pre-mutation fail-closed behavior.
2. Deterministic tests prove KB-RAW creation persists `vlm_config.enabled=false`, `vlm_config.model_id=""` and the desired `embedding_model_id`; reuse attests those exact fields, and any mismatch fails before ordinary upload.
3. A deterministic test proves an ordinary upload omits `process_config` and `enable_multimodel` only after the KB disabled-state attestation, so its effective process configuration cannot route to VLM.
4. A deterministic test proves an opted-in multipart upload carries `enable_multimodel=true` and the exact serialized `process_config` override with the provisioned VLLM ID.
5. In the real local WeKnora environment, all five Bailian probes pass; Embedding dimension is observed rather than hard-coded.
6. A committed non-sensitive multimodal fixture is uploaded with explicit opt-in and reaches completed state; at least one `image_ocr` child chunk has a non-empty parent ID and its in-memory content assertion contains the expected visual canary. Any caption child also has a non-empty parent ID. Evidence records only counts, stable IDs, fixture SHA and sanitized status—not canary text or model output.
7. The ordinary life-insurance PDF completes without a VLM override and still has non-empty chunks after the live KB disabled-state attestation.
8. The existing frozen five-node live collection remains exactly five nodes and finishes with `tests=5 skipped=0 failures=0 errors=0`.
9. Fault injection covers all five roles and proves exceptions, logs, stdout and stderr contain none of the configured URL, key, authorization value, prompt, request body or response body.
10. A failed smoke record can be reparsed once with the same explicit override and attempt/status evidence; repeated failure is preserved without duplicate upload or loop.
11. Ruff, mypy strict, non-live pytest, PostgreSQL integration and OpenSpec strict gates pass on the final SHA.

The VLM smoke is a provisioning/local-live acceptance step, not a sixth node in the trusted PR #9 workflow. It has a dedicated stable local command, records the exact implementation SHA and sanitized evidence, and is rerun on the final SHA. This preserves the previously reviewed five-node gate while verifying the new core path on the real environment. `supports_vision=true` is capability metadata only and is never accepted as proof that an image was processed.

## SDD/TDD delivery boundary

Before function code changes, OpenSpec 023 must be amended to cover the fifth WeKnora model role, provider-aware profiles, selective upload override, VLM smoke acceptance and updated task/validation evidence. Tests named for the amended requirement clauses must fail first. No upstream WeKnora Go/Vue modification is permitted unless a new design demonstrates that the existing `VLLM` and per-upload `process_config` contracts are insufficient.
