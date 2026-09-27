# G3 parser transport configuration recovery

Existing G3-AUTO-3/4/6 scope and explicit user deployment/recovery authorization apply. Root is the sole deployment and repository writer; existing g3_admission_finish advises, g3_incremental_code_review independently reviews. No new environment, database, model or source processing mechanism.

## Frozen failure / RED

Fresh fifth run `7f9d6954-e605-43ef-81c5-43083d8a4a96` automatically failed at source at 2026-09-14T19:33:42.988855Z, 474.579855 seconds after final upload. Two documents completed with nine successful provider calls. Rate-table response was 91650587 bytes, exceeding the server's 52428800-byte limit. Product classification/extraction were NOT RUN. Existing release epoch9 unchanged. No intervention occurred during acceptance. Preserve this failed result.

## Bounded change

Reuse exact existing images and containers' configurations, networks and mounts. Set only DocReader `DOCREADER_GRPC_MAX_FILE_SIZE_MB=128` and APP `MAX_FILE_SIZE_MB=128`; both default to50 before change. Retain the previous stopped containers for rollback. APP YAML bytes must match existing SHA e0d039d635ce36e1fc9bd0e4900b678a32374cf13a34fcf04f414b30b12a9ab5 and be copied into the replacement before start. No image build, database migration, material write, provider call or publication belongs in deployment.

The APP variable also raises its direct API upload limit; existing UI/nginx50MiB remains. This is an accepted local G3 configuration coupling, not a permanent solution or a new per-file product limit.128MiB bounds the known87.4MiB response; it is not a memory preallocation and does not prove1GiB APP memory suffices. Preserve memory limits; observe real recovery. Future transport should separate upload size from response size and support bounded metadata chunks/artifacts rather than indefinite cap increases.

## Sequence and STOP

1. Freeze failed-run receipts and read exact image/container/config identities and terminal tasks.
2. Prepare a fail-closed deployment plan with only the two environment changes. Independent review before mutation. Current live oversize rejection is the configuration RED; no product test fixture may claim live pass.
3. Recreate only existing DocReader and APP using their same images. Stop immediately and restore original containers if either health/config verification fails. Preserve all receipts and rollback artifacts.
4. Verify process/config and webpage health. Mark these delivery checks separately from business recovery.
5. Use webpage reparse only on the failed rate table, then existing webpage source-retry operation. No Codex parse, product assembly, field supplementation, candidate or publish scripts.
6. Observe task terminal, calls, source reuse, stage durations, publication and evidence. This is recovery of a consumed sample, not a fresh independent acceptance. Never overwrite fresh5 failure or promise5–10minutes.

## Initial status

RED PASS (live failure reproduced by automatic parser retries); configuration/deployment/business recovery NOT RUN. G3 NOT COMPLETE.

## Configuration delivery receipt

Independent review closed the terminal-state allowlist finding; reviewed script SHA04583ad6bacd0c6cead58e041ac7b21828bfb7f76666308981c2ab7dd86b75ab,0BLOCKER. Deployment2026-09-14T19:48:20.362581Z→19:48:56.437733Z PASS. Same DocReader image ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868, new container03c15ccca36711d44512703af2b6d1f0d510cf024f900173f2497078d3cf1cb5. Same APP image d31218de5aa6f10e848881ba96e9b103d1a67f3c04b51ad050e5e34e624b3bb8,new container0313a56757801ea2e44d86b6e79faa47a3a6af42866c16329e6c137115da5c2d. Both old containers retained stopped under original-name + `-before-task3ah`. Live DocReader config and gRPC health PASS; APP health PASS; formal webpage API inventory37files/9terminalruns/head9 unchanged. Build0/provider0/business-write0. Business recovery remains NOT RUN until separately recorded. Receipt: `/private/tmp/g3-platform-independent-deploy-20260913/task3ah-receipt.json`.

## Observed resource failure and bounded configuration amendment

Webpage recovery began19:50:57.542Z; parser started19:50:59.864965Z. APP0313 exited19:52:48.694197863Z with OOMKilled=true/exit137 at its1GiB limit, while VM had5917MiB available and DocReader/worker were healthy. This is a failed recovery requiring intervention, not PASS. Receipt `rate-reparse-resource-observation.json` freezes the evidence. The literal previous instruction to preserve memory limits has now been tested and shown insufficient.

Within the existing user authorization, update this same stopped APP container's memory limit to2GiB (no swap) and start it; no image/source/network/mount change or newcontainer. Record before/after configuration and health. This is a local bounded recovery, not a scalability guarantee. Existing platform queue owns any stale source resumption; root observes and may only use available webpage controls, not queue/job mutations. If2GiB also fails, stop raising limits and address bounded native artifact transport/validation before another attempt. Do not classify queue recovery after a process kill as a fresh independent run.
