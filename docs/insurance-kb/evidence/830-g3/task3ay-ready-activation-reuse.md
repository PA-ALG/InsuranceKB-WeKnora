# Task3ay: Ready activation reuse

Status: targeted code validation, independent review, build, smoke and existing APP deployment passed; actual publication and G3 acceptance remain pending.

Task3ax deployed d9d30adac65339187d45d22f3d445d8596c837d8. Actual webpage recovery 1cb14bbf-e098-52db-9c00-c24afb56292d ran 2026-09-15 13:18:52.257Z to 13:51:52.456396Z (1980.199396 seconds), then failed after three publish transport timeouts. Parsing, identity, extraction were reused; synthesis, compilation, preparation and automatic review succeeded. There were 21 verified, 31 not-provided and 30 failed fields, zero new and ten reused model calls. Two cross-page fields retained their original values and raw responses while gaining accurate per-page evidence fragments. No successful activation or verification was observed. Read-only preflight after the run found epoch 9 and zero nonterminal worker jobs.

The private activation repeated full semantic validation after both public activation routes had already validated the Ready preparation, checked current sources and saved the existing signed read projection. Task3ay reuses that projection in this final private step. Signature, current permissions, source checks, policy, expiry, base/head comparison, receipt replay and CAS remain in their existing public/private path.

Storage may change JSON escaping and whitespace. The existing G3 wire canonicalizer is exposed through a small wrapper and applied only to a validation copy at the private activation boundary; the original stored manifest is unchanged. It retains exact source Unicode code points and integer precision, rejects duplicate keys/invalid Unicode/non-integer numbers/trailing data, and does not compile or semantically validate a candidate. The reader/metadata GET contract is unchanged. Activation additionally requires nonempty members, because metadata GET legitimately allows an omitted list.

Validation evidence lives under /private/tmp/g3-platform-independent-deploy-20260913:

- task3ay-activation-red.log: the public activation test observed two complete validations instead of one; expected RED.
- task3ay-activation-green-02.log: 667.062 seconds, four legitimate activation regressions failed with invalid authorization. Preserved as failure evidence.
- task3ay-manifest-red.log: persisted raw digest differed while canonical digest matched; legitimate activation still failed before the normalization repair (39.917 seconds).
- task3ay-members-red.log and task3ay-members-red-02.log: passed rejection tests while the earlier manifest refusal masked the member omission; these are not valid RED evidence for the omission.
- task3ay-members-red-03.log: after normalization, normal activation passed with one full validation (27.11 seconds); actual omitted-member activation incorrectly succeeded, giving the intended RED (29.42 seconds).
- task3ay-wire-green.log: source Unicode/large integer and invalid-wire checks passed (6.097 seconds).
- task3ay-activation-green-04.log: five affected top-level tests passed, including three stored-conflict subcases (248.595 seconds). Covers normal activation, one full check, omitted members, stale head, replay and persisted scope/manifest/member conflicts.

Frozen independent review 01 found the omitted-member blocker. Frozen review 02 found zero blockers (manifest 7dc74006a8346ecc5e373b4e9c12a642f1c131500e2e889769b0138f8c8bcc9c; report /private/tmp/g3-task3ay-independent-review-02.md SHA b3ac6aa8dd3064fdbbdaaddec64f2fb5664bfff351319e397775f2eb399532cf). Deployment remains pending. In-memory SQLite fixtures and counted fake source-verifier calls demonstrate code boundaries, not real service performance. No provider calls or business records were used for these tests.

The existing published 投保年龄 page was also inspected through the browser. It shows 待补充 / live_chunk_quote_not_unique and omits the verified citation button. This is a concrete distinction from deleted original material: the page lacks a validated locator. The design still allows multiple immutable Evidence records per field. G3 acceptance must separately demonstrate verified original-page access and a clear route to retained failed/raw extraction records; this observation is not evidence of a completed fix for that presentation gap.

After tests and independent review pass: build and deploy only the existing APP, keep Task3ax Harness/config/services/databases, recover the failed task through the webpage, then verify actual publication, retrieval and evidence. Fresh product three-file webpage acceptance remains required afterward. Do not count local diagnostic/test scripts as platform processing.

Deployment: source ede52c6e9d4ba7e27bde5f98c04198d72498f610, image sha256:fad365cb7af16c43e67093d4f8436e57ae53e6c35fae4161e661971612ba6c5a. Build receipt and smoke passed; existing APP replacement completed 2026-09-15T14:55:54.032993Z, new container76ab9c33e67b17f585b5b83ba9162f3a53ea9116fb3d42bdc52c9bad8a32f32e, rollback weknora-g3-830-app-before-task3ay. Configuration changes0, active jobs0 before deployment. Harness remains d9d30adac. Deployment is not business acceptance.

Actual webpage recovery 15d287e4-d317-587e-87d7-22081517c590 started 2026-09-15T15:08:27.123Z, finished15:12:20.150596Z (233.027596s) needs_confirmation/CHECKPOINT_INVALID before publish. Task3ay activation behavior therefore NOT RUN on this recovery. No new model calls, model reuse counts not yet accepted by checkpoint. D/task3ay-web-recovery.json now FAILED_ACCEPTANCE. Readonly diagnosis conclusively found checkpoint delta comparison ignores the saved effective field_validation view; Task3ba narrows that consumer repair. Original82 fields and9 raw responses remain unchanged.
