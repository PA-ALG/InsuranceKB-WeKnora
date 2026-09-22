# G3 independent platform recovery — 2026-09-15

G3 remains **NOT COMPLETE** under the user's platform-independent acceptance standard. The original assisted FLOW result does not satisfy this newer standard.

## Billing and source recovery

The free-quota notice does not establish insufficient cash balance. The user supplied a positive balance screenshot; the saved Qwen embedding configuration succeeded on a short probe, and the restored rate-table processing succeeded on 2026-09-15 China time. Original HTTP 429 and its exact provider message remain preserved. No recharge, key replacement or billing-setting change was required for this recovery.

Original failed product run: `f0776a58-90a8-419c-ae0a-7e6d3c478996`. Product: 平安盛世金越养老年金保险（分红型）. Original failed attempt and 109 model dispatch receipts are unchanged.

Webpage rate-table reparse produced ParseAttempt 2. The platform reused the verified original DocReader artifact; it recomputed chunks under current configuration and wrote 787 vectors. There were 42 distinct new dispatches (41 embedding, 1 summary), all HTTP 200, no transport retries or repeated request hashes. The two previously completed documents retained their original processing; their 9 calls were reused, not repeated. Raw traces are retained in private evidence.

## Product recovery failed before semantic model dispatch

Webpage source retry created `efa05c5a-292d-5724-9f71-ee8c422516a6`. Its source and routing stages succeeded. Identity preparation expired three job leases before any stage-model-call row was reserved; Gemini calls were **0**. The identity job entered dead-letter at `2026-09-14T18:52:20.966520Z`. The root automatically finalized `FAILED / PRODUCT_STAGE_FAILED:identity` at `19:00:27.385146Z`.

Recovery action started at `18:43:24.250Z`; action-to-failed was 1023.135 seconds (17m03s), including webpage observation and the later explicit source retry. This is a failed recovery duration, **not upload-to-publication performance**. Extraction, validation, compilation, review and publication were NOT RUN; ordinary missing/failed field counts are unavailable, not zero-quality-success.

Worker was restarted at `19:01:07Z`, after automatic finalization, to release obsolete processing resources. Therefore restart was not necessary to manufacture its terminal state. Observed worker memory was about 5.06 GiB, no OOM/restart/throttle before intervention. Current published head remains epoch 9 / `release-2f46c14c-5f6f-46cb-8eb2-e6afc7e5933e`.

## Task3ag software verification

Plan: `docs/superpowers/plans/2026-09-15-g3-bounded-identity-recovery.md`; existing requirements G3-AUTO-3/4/6. Classification now projects the same homepage and optional issuer evidence it previously offered, without constructing later-page character objects. Full source custody and native-page validation remain. Worker abandons permanently lost generations without success/failure reports, including cancellation cleanup that returns or raises. Existing root finalization protocol is unchanged.

- Initial worker RED: 3 failed / 1 passed; review-derived cleanup RED: 6 failed / 3 passed.
- Geometry RED: 8 failed on old implementation after fixture/full-projection setup succeeded.
- Focused identity/geometry/worker GREEN: 38 passed, 2 PostgreSQL tests excluded.
- Runtime/progression GREEN: 14 passed, including SQLite lease exhaustion → reconciliation → root → durable FAILED / zero model calls.
- Independent combined review: 0 BLOCKER; 45 tests passed, 2 PostgreSQL tests excluded. Ruff and diff checks pass.
- Synthetic native geometry: 270046 text characters, 24892845 native bytes; selected projection 1.893 s, 30 constructed character objects, maximum event-loop heartbeat gap 0.220 s, whole probe peak RSS 460013568 bytes. This is synthetic host evidence, not a live throughput claim. Cancelling `to_thread` does not kill an already executing thread.

Task3ag build/deployment and new webpage acceptance are **NOT RUN** at this software freeze. Exact later receipts must independently establish deployment and business results. No new services/databases, APP/UI rebuild, schema field completion campaign or manual business continuation are part of this repair.

Private evidence directory: `/private/tmp/g3-platform-independent-deploy-20260913`; receipts include `task3ae-af-web-recovery-result.json`, `rate-recovery-observations.private.jsonl`, `recovery-run-observations.jsonl`, `task3ag-worker-process-restart.json`, `task3ag-*-red.log`, `task3ag-focused-green.log`, `task3ag-runtime-green.log`, `task3ag-review-files.json`, `task3ag-synthetic-geometry-result.json`.
