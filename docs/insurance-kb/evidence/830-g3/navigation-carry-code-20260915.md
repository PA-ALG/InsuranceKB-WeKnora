# Task3at incremental navigation carry — code evidence

G3 remains incomplete. The existing-product real recovery and subsequent fresh-product three-original webpage acceptance remain required. This changes only the existing compiler/worker checkpoint contract; no database migration, APP/UI rebuild, model refill, or manual business continuation.

Base commit: `4b1ece885a0d2b7b4847df7a5bb0ca6ca4d3091a`. Frozen code identity: `/private/tmp/g3-platform-independent-deploy-20260913/task3at-review-identity-02.json`, SHA256 `7517c42292dcf51509af57dcf718ef8e203811865e94b2ca278a3d9ef37dde75`.

| Requirement | Implementation | Verification | Code |
|---|---|---|---|
| G3-AUTO-1/6: preserve published navigation | strict typed assignments from verified base included in compiler manifest/hash | exact bytes, absent entity rejected; full pipeline saves parent navigation unchanged | PASS |
| G3-AUTO-3: invalidate only changed output | candidate artifact contract v2 and existing metadata prefix selection | 6 cases: obsolete/mismatched output resumes compilation, upstream retained; current output reused | PASS |
| G3-AUTO-3/6: successful output reuse | original candidate bytes and producer preparation identity retained | request rejection and lost response recover with zero reassembly/source/model calls; original outcomes/responses unchanged | PASS |
| G3-AUTO-5: deployed platform | existing Harness only, unchanged migration head 0018/APP/UI | build/deploy receipts required after code freeze | NOT RUN |

Valid RED: full navigation pipeline 1 failed in 78.72s because saved candidate omitted the parent navigation; compiler interface tests 2 failed in 38.57s; artifact metadata 4 failed/2 passed in 4.08s. Initial fixture canonicalization/import setup failures are not counted as RED.

GREEN: navigation/compiler + artifact contract + both full recovery scenarios, 10 passed in 341.22s; existing checkpoint contract 14 passed in 20.54s. Ruff and diff checks pass. These are fixture tests, not real publication acceptance.

First independent review reproduced an additional empty-navigation compatibility defect: Go may emit explicit null for its optional slice. The trusted projection reader now maps only null/missing to an empty tuple, preserving strict typed validation for nonempty rows. The original expression TypeError is recorded in `task3at-independent-review-01.md`; a missing-new-helper test is retained separately and is not presented as that original-defect reproduction. Final null/unit verification and delta review are recorded below when complete.

Real preceding run `16339470-f954-564e-b7ae-60f7515b050b`: FAILED after 405.081412s (07:35:46.838Z webpage click to 07:42:31.919412Z terminal), zero new/10 reused semantic calls, 21 verified/31 missing/30 failed fields. Candidate persisted at SHA256 `9ebbe5b355d0445683dd87f1f42051ef3b85999be9f8096391007be764f2e16a`, 10,201,079 bytes; Go pure canonical/types validation passed against those exact bytes. Read-only comparison proved the candidate omitted the parent's one navigation assignment, triggering the unchanged APP history gate. That candidate and its parent remain immutable. A new platform recovery must invalidate only that obsolete compilation output.

Delivery at source freeze: software validation as above; new container health/provisioning/local live NOT RUN; provider probe NOT RUN (zero); GitHub live NOT RUN. A failed run's elapsed time is not a successful end-to-end timing result.

Final delta: null/omitted/empty and strict malformed-row rejection, plus nonempty helper-to-candidate exact-byte and absent-entity tests: 3 passed in 113.42s. Independent final review: 0 BLOCKER / 0 BACKLOG / 0 REJECTED, report SHA256 `478fd950495aabb18924f8d6ce23f61e6637e888e2f4fe51b6c44d13badcc161`. First null blocker is closed; all frozen production/test/script hashes match. No additional full historical rerun was necessary for this isolated empty-collection normalization.
