# Issuer policy live recovery follow-up — 2026-09-22

## Verdict

- **BLOCKER: 0**
- **BACKLOG: 1** — the modern checkpoint path does not replay a previously recorded identity response after a deterministic local adapter fix. If zero-send reprojection is still a desired product capability, it needs an explicit checkpoint contract and pipeline test; it is not supplied by `retry_calls` today. This does not block the current `b696618c-c20f-577f-bbc6-a6d06af47bb4` recovery because the user explicitly authorized another Gemini recovery, and the observed snapshot records that new identity call as successful.
- **REJECTED: 3** — reject the prior review's claim that 368c recovery would necessarily replay the recorded raw response with no provider call; reject describing a173 as a checkpoint-v7 `retry_calls` recovery on the supplied evidence; reject treating a173's provider HTTP 400 as an issuer-alias or identity-adapter regression.

## Corrected finding

The statement in `/private/tmp/issuer-policy-independent-review-20260922.md` that the 368c response "enters the established recorded-identity replay path" and is adapted "without another model send" was incorrect. It inferred behavior from the presence of a recorded response and absence of `compile_request`, but did not follow the actual retry entry point.

The public `retry-processing` route calls the store's current `retry_processing` implementation. The active store implementation creates a `checkpoint:` child and a checkpoint plan. `processing_recovery_plan()` recognizes only the separate `processing-recovery.v1/v2/v3:` identities, so a checkpoint child has no `RecordedIdentityRecoveryPlan`. In `pipeline.py`, identity replay is selected only when that legacy plan exists and has mode `REPLAY_RECORDED_IDENTITY`; otherwise it calls `execute_stage_call`. A checkpoint's `retry_calls` are verified audit references to a prior terminal semantic failure. They are not consumed by the pipeline as replay instructions.

This behavior is intentional in the current test contract. `test_real_worker_retries_identity_once_and_reuses_all_sources` first records one semantically invalid identity response, creates a checkpoint retry, and then requires a second identity request with a different call ID while reusing the source captures. The public checkpoint test also requires a v5 plan with one `retry_calls` reference, zero `reused_call_ids`, and zero `reused_usage`. By contrast, the no-send behavior is covered only by `test_legacy_recorded_identity_recovery_replays_original_receipts_and_provenance`, whose fixture explicitly swaps in `_legacy_retry_processing` and expects `REPLAY_RECORDED_IDENTITY`.

Therefore a173's new identity request is allowed by the present checkpoint contract. The retry reference establishes that the old call ended in a narrow, intact semantic failure; it does not mean the old raw bytes will be projected again. A user-triggered retry authorizes the contract-defined new attempt. The later b696 recovery additionally has the user's explicit Gemini authorization.

## Live evidence

`tmp/g3-browser-acceptance-20260922/observed-runs.json` records:

- a173 as a child of 368c, `workflow_version: 3`;
- a173 checkpoint success from `05:46:18.595184Z` to `05:46:19.333006Z`;
- one a173 identity call dispatched at `05:46:23.223002Z`, recorded with diagnostic `provider_http_status`, followed by terminal stage reason `IDENTITY_MODEL_CALL_FAILED:provider_http_status`;
- b696 as a child of a173, also `workflow_version: 3`, with a new identity call recorded successfully at `07:51:29.615941Z` and subsequent stages progressing. The supplied snapshot contains no finalization, so this report makes no business-completion claim.

The a173 record proves a new send and a provider rejection. It does not implicate issuer canonicalization or evidence-reference normalization because the response never reached successful local semantic projection.

## Checkpoint version correction

The supplied evidence does not include a173's checkpoint plan bytes, so its exact plan version should not be asserted from the snapshot alone. It does, however, exclude v7:

- a173 is persisted with `workflow_version: 3`;
- `CheckpointPlan.workflow_version` returns 2 for v7, and v7 requires `execution_workflow_version == 2`;
- the validator permits non-empty `retry_calls` only on v3, v5, and v6, not v7;
- the corresponding workflow-v3 identity semantic-failure test explicitly expects checkpoint v5.

Accordingly, the phrase "checkpoint v7 的 retry_calls" is internally inconsistent with the checked code, and the observed a173 child is not evidence for it. A precise live plan identity would require the checkpoint artifact or receipt, which was not part of `observed-runs.json`.

## Classification details

### BACKLOG B1 — modern recorded-raw reprojection capability

The implementation plan says the 368c raw response can be reused and that this confirmed issuer relationship does not require another Gemini call. The modern checkpoint implementation does not currently provide that behavior. This is a real capability/documentation gap, but it no longer blocks the user-authorized b696 attempt. Any later change should keep the legacy and checkpoint contracts distinct and add a RED proving: exact recorded request/raw/policy identity, deterministic adapter-only reprojection, zero provider dispatch, preserved original call audit, and fail-closed behavior on drift or unknown dispatch.

### REJECTED R1 — current alias patch caused the new call

No. The branch choice predates and is independent of issuer alias normalization. The checkpoint pipeline chose `execute_stage_call` because there was no legacy replay plan.

### REJECTED R2 — `retry_calls` means replay

No. Its checked role is admission/verification evidence for the prior semantic failure. The current worker test requires a new call and records no reused call IDs or usage.

### REJECTED R3 — provider HTTP 400 is a product semantic failure

No. a173 stopped at the recorded provider transport rejection. It did not produce a successful identity response for the adapter or alias policy to evaluate.

## Read-only boundary

Reviewed HEAD `ec0721083c955af67d996aed883f6eab16fa9393`, the supplied observed-run and recorded-response files, the active checkpoint/pipeline/store contracts, and their focused tests. No run, model, database, deployment, repository file, or business state was changed. The active b696 task was not queried or operated beyond reading the supplied snapshot.
