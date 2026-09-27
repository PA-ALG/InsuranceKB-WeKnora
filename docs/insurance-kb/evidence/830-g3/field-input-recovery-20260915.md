# Field input recovery — software evidence

Scope: existing G3-AUTO-2/3/4/6. Plan: `docs/superpowers/plans/2026-09-15-g3-field-input-recovery.md`. This is not a fresh-upload acceptance or G3 completion.

Actual run d9ae11aa-642b-5519-95fc-24c6847b52dc failed at 2026-09-14T21:31:25.796682Z after 384.51 seconds from webpage recovery. Source, routing and identity completed; field planning repeated three times and failed on configured model context capacity. One classification call was recorded; 71 previous source calls were reused. No field extraction, compilation or publication occurred. Free-quota exhaustion did not establish account insolvency; actual subsequent embedding calls returned HTTP 200.

| Requirement | Change | Verification | Status |
| --- | --- | --- | --- |
| G3-AUTO-2/6 bounded extraction with preserved evidence | v2 field targets omit repeated full allowed_sources; expose exact offered source refs; full local task/hash/dependencies remain | 1401-source RED at 1 and 10 fields; final extraction and planning suite 51 passed in 16.23s | PASS software |
| G3-AUTO-3 recorded-result reuse | Strict original v1 and compact v2 request replay; exact source/quote bounds, task and scope checks remain | Legacy/new replay, modified targets/sources/spans and unavailable offered quote tests; no redispatch | PASS software |
| G3-AUTO-4 terminal planning failure | ModelPolicyDenied in planning becomes non-retryable; pure preflight still distinguishes unrelated policy errors | Real-worker RED attempt 3 instead of 1; then RED recovery unavailable; final worker uses one failed planning attempt | PASS software |
| G3-AUTO-3/4 native recovery | Extend existing v3 recorded-identity recovery to failed field_plan before any window/field attempt; retain original run and source snapshot bindings | Final compact and two full worker recovery cases: 15 passed in 124.90s; classify calls remain 1, source captures 3, activation 1 in synthetic boundary | PASS software |

Before compact implementation, identity/recovery/planning suite: 53 passed in 243.06s, one upstream Starlette/httpx deprecation warning. Final Ruff and diff whitespace checks passed. Independent review of final six-file diff `bd10026a606282023d2ec1e3d2bb46d041a1b4a4263830398d98355c112c997b`: 0 BLOCKER. These are local synthetic tests, zero real provider calls.

Synthetic 1401-source measurements: single field content 85,001 bytes, HTTP 86,718; ten fields content 98,006 bytes, HTTP 100,551. Existing limits remain 300,000/2,000,000 in this fixture. Actual live request sizes and extraction outcomes remain NOT RUN at this source freeze.

Task3am delivery scripts independently reviewed, 0 BLOCKER: build SHA450bc2a64259b6072ef427dea6d78e96dc51f48753a06b7c6e6ddb57ff441f21; smoke SHAb29bb72596d7c293e0260b08492e680a4861195312832e720fa17d917fdd2da2; deploy SHA997e77c5b8f4a4524fdd460bbabc1dc187191e60685d8074b5df5eb2bca64fff. Reuse Task3al runtime env SHA034db8e43de4046fc9d591f322ef1c1a34bf1f4d000cab95d98773ec9d41339b; no model/DB/APP changes. Current build, smoke, deployment and real recovery remain NOT RUN here; their subsequent exact receipts belong in the deployment evidence directory.
