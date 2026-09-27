# Fifth independent platform acceptance — source failure

G3 remains NOT COMPLETE. The fresh sample was uploaded through the existing G3 webpage; no code/config change, manual continuation or Codex material processing occurred during this run.

- Product: 平安盛世金越（至尊版26）年金保险（分红型）; three original PDFs,4495300 bytes, all previously unseen by inventory hash.
- Run: `7f9d6954-e605-43ef-81c5-43083d8a4a96`.
- Final upload HTTP200:2026-09-14T19:25:48.409Z.
- Automatic terminal:2026-09-14T19:33:42.988855Z,`failed`, `PRODUCT_STAGE_FAILED:source`.
- Upload to failure:474.579855seconds. This is not upload-to-published time.
- APP source9319698a2796da3042df6750c5d48e6a208e106f/image d31218de5aa6f10e848881ba96e9b103d1a67f3c04b51ad050e5e34e624b3bb8.
- Harness source383b371ad2967d60a7f9567c844cd85cbe4d1d31/image695bb60f3967f83b65f2f7edbcbf57b9e4c66cc59423a8f75daae5afe45e9c15.
- Serving head unchanged:epoch9,release-2f46c14c-5f6f-46cb-8eb2-e6afc7e5933e.

|Material|Parse seconds|Chunk seconds|Embedding seconds|Provider calls|Result|
|---|---:|---:|---:|---:|---|
|产品说明书|8.249|0.261|5.245|4|Completed|
|保险条款|8.758|0.218|5.436|5|Completed|
|费率表|286.163 across four attempts|NOT RUN|NOT RUN|0|Failed|

The two completed documents' nine provider calls all returnedHTTP200. Counts include their source summaries/summary vectors; stage values above exclude their asynchronous summary duration. The rate-table parser made four attempts (initial plus three automatic retries), taking77.787,65.803,62.911,79.662seconds. Its response was91650587bytes, exceeding52428800bytes. Exact stored error: `ResourceExhausted: SERVER: Sent message larger than max (91650587 vs. 52428800)`.

Classification, field extraction, validation, knowledge compilation, review and publication were NOT RUN. Missing/failed field counts are unavailable, not zero. The product task's current summary displays0modelcalls with an incomplete-count flag; the independent per-source spans establish the actual9calls. This summary undercount remains a platform observability issue.

This failure is unrelated to balance or model context. The previous recovered rate-table source had already completed42distinct provider calls with allHTTP200, and the two current documents also succeeded. The user's free-quota notice does not demonstrate an account balance failure.

Private local receipts are under `/private/tmp/g3-platform-independent-deploy-20260913/`: `platform-fresh-fifth-freeze.json`, `platform-fresh-fifth-result.json`, `fifth-upload-http-receipts.json`, `fifth-fee-all-attempts.private.json`, `fifth-asynq-error.json`, `fifth-source-observations.private.jsonl`, `fifth-terminal-runtime.private.json`.

The next separately authorized action is configuration recovery in `docs/superpowers/plans/2026-09-15-g3-parser-transport-recovery.md`. It cannot turn this fresh acceptance into PASS. A recovery run reuses the same product and must be reported separately.
