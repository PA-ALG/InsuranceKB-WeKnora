# Task3au source selection — code evidence

G3 is incomplete. This fixes the actual source gate's selection of current materials; real source verification/publication and fresh-product webpage acceptance are not inferred from code tests.

Base commit: `c37e0813c82c935d6d2f6d600da17662adc34ea1`. Final implementation identity: `task3au-review-identity-02.json` SHA256 `09b4f22253f588a48011a9c7a4ee9df8c1022d460ff302257d85768082f5fda0` under `/private/tmp/g3-platform-independent-deploy-20260913/`.

The real immutable candidate from run `50e6e0b2-701b-54a2-8081-4a5f0cdb89a3` contains eight bindings (seven exact published parents and one current product), three current corpus materials, and thirteen material IDs across all bindings. The old service selection demanded all thirteen and deterministically rejected the ten absent historical IDs. The existing types contract already distinguishes current resolution refs from carried bindings. That existing decision is now exposed through `CurrentBatchBindingIDs830G3` and used by the source gate. A current MATCH/refresh on a historical entity remains selected. No corpus intersection fallback or historical entity exemption is introduced.

All binding/definition/field/page evidence checks and legacy current-source/revocation checks after selection remain unchanged. Full candidate and actual published-base checks precede source admission. No real candidate, old response, field outcome, source, model configuration, or database schema was changed.

| Requirement | Implementation | Verification | Code |
|---|---|---|---|
| G3-AUTO-1/3 | reuse current-resolution selector in actual corpus gate | expected current one vs old five RED; current existing MATCH retained; corrupt refs rejected | PASS |
| G3-AUTO-6 | no skipped current source or history evidence | missing current corpus rejected; existing live source drift/revocation, durable reuse and transfer authority tests | PASS |
| G3-AUTO-5 | same APP, database, Harness and UI | only APP build/deploy pending, same configuration/resources | NOT RUN |

Before RED, the old all-bindings selection loop was extracted without changing behavior, and the real gate was wired to that helper. The helper test then failed semantically in 5.267s (wanted one current material, received five including four carried materials). Only after that failure was selection switched to the existing types decision. This is not a mock selector or a claim of complete source-authority integration.

GREEN: six bounded service tests passed in 64.291s; corrected types selector test passed in 2.074s. The initial combined run is retained as FAILED because a test wrongly assumed every parent binding was noncurrent; the fixture actually refreshes one existing entity. Production selection was not changed to satisfy that mistaken assertion. Final test explicitly checks one current parent plus unaffected carried parents, immutable input, and corrupt current ref rejection.

Independent first review: production/script BLOCKER 0; test assumption corrected; native integration fixture BACKLOG retained. The checked transfer fixture has two block IDs but a registered receipt claiming one chunk; its full native source authority is not covered by its existing fake-verifier integration test. Detailed limitation: `/private/tmp/g3-task3au-source-gate-fixture-limitation.md`. No synthetic or real source was altered to manufacture a full-gate pass. Real webpage recovery is still required.

Prior Task3at actual attempt: click08:21:11.971Z to failed08:28:44.410085Z =452.439085s. Checkpoint110.764780s and compilation119.473018s both single generation. Preparation three HTTP503 responses, exact `CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE`, with HTTP times65.166786388/63.153116507/53.413164716s; task retry, not lease recovery. Zero new/ten reused semantic calls,21 verified/31 missing/30 failed fields. Original nine response bytes and all82 full field-row fingerprints match their baseline. Saved candidate-v2 SHA256 `c007b78e0b94e6c8e0fa20c167eb921acfff17c23e8f00779324bb43e35c7903`,10,202,320bytes, retains the exact original navigation. Recovery must reuse this output, not recompile or extract.

At code freeze: local software as above; new APP container health/provisioning/local live NOT RUN; provider probe NOT RUN(zero); GitHub live NOT RUN. Existing Task3at Harness and Task3as UI remain deployed. No database migration is required.

Final independent review: 0 BLOCKER,1 documented native-fixture coverage BACKLOG. Review SHA256 `b751319d1ce413cd159d6c68d8aeec78ab4ba0ea1d70e8a623c98c855d160398`. All frozen implementation/test/deployment hashes match.
