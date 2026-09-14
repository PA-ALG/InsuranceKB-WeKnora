# Replay heartbeat recovery — software evidence

Scope: existing G3-AUTO-3/4/6 and plan `docs/superpowers/plans/2026-09-15-g3-replay-heartbeat-recovery.md`. G3 and independent publication acceptance are not complete.

Task3am source `0ae8d97e3ec34ce2be85ff159b5b2a25cb3cab26` was built, smoke-tested and deployed successfully. Web recovery `b8a6ce3f-3931-59c1-8eea-53f3a7d0a947`, clicked 2026-09-14T21:56:54.988Z, failed identity after three `lease_expired` attempts. Root finalized at 22:03:20.7271Z: 385.74 seconds from click to failure. Sources succeeded on attempt 2 and routing succeeded. No new provider call, field plan, extraction or publication occurred. All three prior source parses remain completed and reusable. Compact field inputs have not yet been exercised by this live run.

The synchronous replay path blocked the event loop and acquired the job heartbeat row before repeatedly reading and hashing large source snapshots. Source reads and decoding also blocked the event loop. Both metrics and retry-button queries loaded complete payloads unnecessarily.

| Requirement | Implementation | Local verification | Status |
| --- | --- | --- | --- |
| G3-AUTO-4 task heartbeat | Thread offloading for replay, artifact preparation, source reads/decoding and routing | Barrier tests prove event-loop progress; actual mechanism REDs before implementation | PASS software |
| G3-AUTO-3/6 integrity and fencing | Full source/plan/call verification precedes the job fence; shared row locks retained in the same transaction; one replay validation per artifact batch | Ordering, SQL lock intent, multiple drafts, changed bytes and recorded call binding tests | PASS software |
| G3-AUTO-3 repeated recovery | Existing v3 plan binds immediate parent and original ancestor call; reject cycles, changed sources, changed calls, and new calls on a replay run | Repeated recovery with and without checkpoint, ancestry tamper cases, existing complete worker fixtures | PASS software |
| G3-AUTO-4 bounded status reads | Metrics use recorded receipt/call metadata; button hint selects source identifiers/digests only | Tests prohibit loading full source payloads on display paths; actual retry still rejects payload corruption | PASS software |

Root verification on final implementation: 34 passed / 2 deselected in 51.93s for replay fencing and non-worker identity recovery; two complete worker cases passed / 24 deselected in 198.42s. Compatibility suite initially produced 41 passed and one failed assertion in 213.79s: the old corruption case required the lightweight button hint to hash the full payload. That assertion was updated to the documented display contract and strengthened to require the actual retry action to raise. The complete four-case source-change group then passed in 8.53s. One existing upstream Starlette/httpx deprecation warning remains. No real provider calls were made by these tests.

Independent review of implementation diff `93e572e4652b574475a64a69f1a0a2b6d14a76dc133813a3963b0ec4f9cfbb75`: 0 BLOCKER. The reviewer-discovered new-call substitution was reproduced RED and fixed before this freeze. SQLite tests prove SQL intent and ordering, not actual PostgreSQL contention behavior. No lease, model, schema, database or resource limits were widened.

Task3an deployment reuses the existing API/worker, pinned dependency layers and runtime environment SHA `034db8e43de4046fc9d591f322ef1c1a34bf1f4d000cab95d98773ec9d41339b`. Old Task3am containers/image and environment are retained for rollback. The old API's slow terminal query is replaced only in the deployment preflight with a read-only SQL audit of finalizations/root states and all job states. All 12 existing runs were observed terminal, with 35 succeeded, 9 dead-letter and 6 blocked jobs and no active jobs. This does not change any business record.

At this software freeze, Task3an build, smoke, deployment and webpage recovery are NOT RUN; later exact receipts belong in `/private/tmp/g3-platform-independent-deploy-20260913`. Any future recovery must be performed through the webpage. Source parses, evidence and business outputs must not be assembled or changed by Codex. Runtime closure, real field extraction, publication, search/citation verification and 5–10 minute performance remain unproven.
