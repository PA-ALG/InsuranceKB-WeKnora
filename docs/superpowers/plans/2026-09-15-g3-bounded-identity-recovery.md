# G3 bounded identity preparation and lease-loss recovery

> For agentic workers: use the existing owner/reviewer lanes and test-first execution. Root alone applies and commits repository changes.

**Goal:** complete the user's existing G3-AUTO-3/4/6 requirements without expanding material preparation or retaining obsolete handlers.

**Architecture:** retain signed full source artifacts and existing product root finalization. Identity prepares only the actual homepage blocks plus at most one issuer block per material within pages 1–3. Provider requests, source provenance, ordinary field handling, published authority and existing environment stay unchanged. The worker distinguishes permanent lease loss from transient database failure.

**Tech stack:** existing Python Harness, asyncio worker, PostgreSQL jobs, signed native geometry.

## Observed failure and authority

The user explicitly authorized continuing G3, fixes, deployments and reasonable model calls in the existing environment. The original independent acceptance requirements remain controlling. This bounded repair follows the existing platform-independent design, G3-AUTO-3/4/6; no new product Goal, service or database.

Source 9319698a2796da3042df6750c5d48e6a208e106f; recovery run efa05c5a-292d-5724-9f71-ee8c422516a6. Rate recovery succeeded with 787 vectors, 42 distinct successful calls and no transport retry. Identity then expired three job leases before any model call reservation. It reached dead_letter at 2026-09-14T18:52:20.966520Z; root was leased but not started, product remained awaiting_sources. Worker occupied about 5.06 GiB. Resource pressure is observed, not proof of one exact GIL hotspot. Full geometry expansion and failure to cancel obsolete handlers are confirmed code paths. The root eventually finalized FAILED at 2026-09-14T19:00:27.385146Z, before the resource-recovery restart at 19:01:07Z; its delay was about eight minutes after dead-letter. Therefore finalization was automatic, not enabled by that restart. The restart released obsolete process work after failure and does not convert this acceptance to PASS.

## Frozen requirements

- G3-AUTO-3-ID: reuse existing full source custody; only project geometry needed by the identity prompt. Selecting identity input must preserve the old prompt's source ranges, locator references and explicit company-name rule. Do not classify by filenames or by Codex. Later extraction keeps access to all source evidence.
- G3-AUTO-4-LEASE: definitive lost lease/generation ends its handler, does not report success/failure with a stale generation, and frees local asyncio capacity. Temporary DB errors retain bounded heartbeat retry. Cancelling to_thread alone does not kill the underlying thread; expensive geometry loops must honor a cooperative cancellation signal if introduced. No claim of cancelled CPU without a test.
- G3-AUTO-4-FINAL: preserve progression→root finalizer; failure after lease exhaustion must produce a durable FAILED finalization. No GET-side manufactured terminal status or DB backfill.
- G3-AUTO-6-ID: source scope/hash/native page ranges/coordinates remain validated; full default projector behavior and historical bytes remain compatible. No unsigned or mismatched source acceptance.

## Task A — bounded identity geometry (owner g3_extraction_finish, patch only)

Paths: product_ingestion/source_geometry.py, identity.py, pipeline.py; tests/product_ingestion/test_source_geometry.py, test_identity.py (all under harness/src/insurance_harness or harness/tests respectively).

1. Prepare tests first: homepage plus true insurer block within first three pages, a large later page, and corrupted nonselected native metadata. Instrument character-box construction to prove later-page boxes are not instantiated. Assert selected prompt and locator output equal the former full projection route.
2. Root runs those tests on old implementation and records meaningful RED.
3. Implement explicit block selection without changing default all-source projection. Select by verified page-local source text, not whole overlapping chunk text. Retain full native validation, but avoid character object expansion for unselected pages/blocks.
4. Keep later corpus/field extraction inputs complete; no model calls in tests.
5. Root runs focused identity/source geometry regression and independent review.

## Task B — lease-loss handler cancellation (owner root)

Paths: service_shell/worker.py, tests/test_service_shell_worker_039.py, tests/product_ingestion/test_runtime.py; optional small jobs cancellation helper and bounded geometry cancellation checks only if needed after test evidence and reviewer agreement.

1. RED: blocked handler + heartbeat StaleGenerationError/LeaseExpiredError must cancel, release capacity and avoid any stale report; transient DB failure must keep handler running.
2. Implement permanent-loss handling while preserving shutdown and durable job transitions. Ensure heartbeat cleanup cannot self-await. Do not turn all IllegalTransition errors into transient failures without checking their meaning.
3. Test an expired identity job→reconciliation scan→root execution→FAILED finalization without model calls, using existing runtime/progression fixtures.
4. If an underlying CPU operation remains uncancellable, document and bound it; do not claim immediate thread termination.

## Delivery and verification

- Preserve all old failed results and deployment receipts.
- Review frozen patch, focused tests, no migration or APP/UI rebuild unless an actual dependency requires it.
- Build and smoke the existing Harness using known corrected nonroot directory permissions; deploy to existing API/worker only, exact image/source/config guards.
- Webpage explicit recovery remains the only business restart path. No manual candidate/field/publish scripts.
- After stabilization, test the previously unseen three-file sample via webpage under a frozen deployed version; record upload completion→searchable published evidence, all stage times/calls/missing/failed counts. G3 remains NOT COMPLETE until actual independent acceptance passes and remaining gaps are explicit.

## Software freeze result

A/B/C independent review: 0 BLOCKER, 45 local tests passed / 2 PostgreSQL exclusions. Root focused38 + runtime/progression14 passed. Initial RED and review-derived RED preserved. Synthetic 24.9MB native input projects only30 character objects in1.893s; not a live SLA. No hard thread cancellation was added; geometry preparation is reduced and async stale handlers cannot continue into subsequent stages. See docs/insurance-kb/evidence/830-g3/platform-recovery-20260915.md. Deployment remains NOT RUN until separately receipted.
