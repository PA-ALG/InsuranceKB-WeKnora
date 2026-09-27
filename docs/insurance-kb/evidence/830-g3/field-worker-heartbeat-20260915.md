# Field worker heartbeat — software evidence

Existing G3-AUTO-2/3/4/6; plan `docs/superpowers/plans/2026-09-15-g3-field-worker-heartbeat.md`. G3 remains incomplete.

Task3an source `5e62d5f98ede9b69e62a821e2df442148ff60e92` built, imported under runtime UID10001 and deployed successfully. Run `62073d58-d3e4-5371-9290-38da2eab35ef` was created solely through the webpage at22:42:30.679Z and finalized FAILED at23:01:47.257477Z on2026-09-14:1156.578477 seconds from click. Admission took57.412921s and the webpage initially reported an unconfirmed request; refresh found the single created task.

Source18.65s, routing20.77s, recorded identity replay180.39s and field planning73.82s each succeeded on attempt1. Nine field windows then reached dead-letter on attempt3 with `lease_expired`. All nine calls stayed reserved: zero dispatches, raw responses or field attempts. The aggregate extract stage failed with `FIELD_WINDOW_TERMINAL_RESULTS_INCOMPLETE`; root finalized. No compilation or publication occurred. The displayed zero failure-field count reflected absent field-result records, not successful extraction. One original classification and71 original source calls were reused; no new real model request occurred. Five-minute resource observation showed no OOM/restart; it does not prove full-run memory stability.

The production field source loader still read/decoded complete snapshots synchronously. Task restoration, request preparation/rendering and response projection also ran on the async loop. Reservation took the WikiJob lock before loading/comparing large task JSON. Eight private fixture mechanism tests failed as expected before implementation in11.76s. The added loader-gate factory initially did not exist; that new-contract failure is distinct from demonstrating an old cancellation race.

| Requirement | Implementation | Verification | Status |
| --- | --- | --- | --- |
| G3-AUTO-4 heartbeat and resource control | Source read/decode and pure task/request/result work move to threads; provider/begin/persist callbacks stay on original loop | Root56 heartbeat/worker/extraction tests passed7.47s; barrier and stale-generation controls | PASS software |
| G3-AUTO-4 cancelled source readers | Per-scope native source hydration gate remains held until underlying read completes; no cross-run cache | Cancelled waiter, queued cancellation and foreign-scope tests; all included above | PASS software |
| G3-AUTO-3/6 reservation integrity | Full task compare/cache selection under window FOR NO KEY UPDATE, then short WikiJob fence, then original call-lock order |1401-source×10-field ordering fixture; actual PostgreSQL dialect renders NO KEY UPDATE; no real PostgreSQL race test claimed | PASS software |
| G3-AUTO-3/4 native undispatched recovery | Extend existing v3 replay plan only for terminal incomplete extraction with all windows terminal and no field dispatch/request/raw/result | Positive replay RED3.51s; final10 tests passed13.89s, preserving original source and identity call | PASS software |
| G3-AUTO-3/6 scope and ancestry | Check job payload run/stage/window, collect related calls by run/window/job and require full binding; retain all source/identity checks | Foreign-run RED4.30s; reviewer payload RED2 cases5.29s and job-only call RED3.42s; all final10 green | PASS software |

Root compatibility verification:55 identity/recovery/store tests passed32.54s,2 deselected; two complete worker fixtures passed126.50s. Two existing SQLite datetime-adapter deprecation warnings remain. Initial new-test setup lacked imported fixtures; that setup error was corrected and is not RED evidence. Agent private regression62 passed10.08s; root results above are the integration evidence. All fixture provider calls are synthetic.

Final implementation review SHA `abb498f3956d711a543fe4717198569538bc22efbaa40dcad3ab841fe9897172`:0 BLOCKER, both earlier findings closed. Source/evidence rules, v1/v2 request replay, v3 recovery contract, model limits and job leases remain unchanged.

Task3ao future scripts independently reviewed0 BLOCKER: build `b4dacefc677085ffd5a457e19b341c4228696c246918a9e16ad2021a32e13b15`, smoke `96bf9d48b1cfef44f5b5091ad81e5a0c080a2bf76d1705e3143dd2c5171386d9`, deploy `bc78e0009df05a97cce6e14aa4897bf3e3c8c8576d998f67dd744f5bd71ed6f3`. Reuse existing API/worker/database/model settings and Task3an rollback environment; runtime env SHA `034db8e43de4046fc9d591f322ef1c1a34bf1f4d000cab95d98773ec9d41339b`. No migrations or business continuation scripts.

At this software freeze, Task3ao build/smoke/deployment and real recovery are NOT RUN. Subsequent exact receipts belong in `/private/tmp/g3-platform-independent-deploy-20260913`. Independent publication, search/evidence readback, fresh-product acceptance and5–10minute performance remain unproven. The57-second synchronous admission and repeated local source revalidation remain measured performance debt.
