# Task3as candidate persistence — code evidence

G3 remains incomplete. This change reuses the existing product jobs/artifacts, database and APP preparation interface. Workflow 2 commits candidate before preparation submission; recovery submits the same producer-run preparation identity and original candidate bytes. Workflow 1 retains combined compilation and original checkpoint serialization.

Base: `92460ac41d7ad7c27db5b3f505fb62cdb7f61211`. Frozen implementation review patch SHA256: `5a63474c0c7c2bad06670cbed9478cf0374ff244c1179061248f221655c22def`. Final test-only delta adds compilation to the expected reused stages and strengthens original candidate/no-recompilation assertions.

| Requirement | Implementation | Verification | Code |
|---|---|---|---|
| G3-AUTO-3: persist/reuse successful results | compilation/preparation split, producer identity, immutable refs | recovery rejected request + lost response; identical bytes/id; zero reassembly/model/source calls | PASS |
| G3-AUTO-4: explicit stages/terminal | workflow-specific progression and preparation barrier; UI phase | progression/contract/composition 28; UI 36 | PASS |
| G3-AUTO-5: existing deployment | additive workflow_version migration, old default 1, new explicit 2 | version/migration 7; rollback runbook reviewed | PASS |
| G3-AUTO-6: custody | original artifact digest/fence and candidate bytes retained | immutable original calls/fields and candidate in recovery tests | PASS |

RED receipts under `/private/tmp/g3-platform-independent-deploy-20260913/`: pipeline 1 failed in 137.30s (candidate not persisted); version 7 failed in 22.48s; contracts 3 failed/1 passed in 32.82s; UI 1 failed. Environment failures were not used as RED.

GREEN: version 7 in 30.10s; contracts/progression/composition 28 in 118.30s; full recovery 2 in 215.01s; UI 36 in 19.71s; vue-tsc and Ruff PASS. An intermediate full-recovery run reached successful verification in both cases but failed an outdated reused-stage list assertion; that run is retained as failed and is not counted as GREEN.

Independent code review: BLOCKER 0, BACKLOG 1 (small direct metadata fixture for completed legacy compilation recovery), REJECTED 0. No observed code defect in legacy selection. No added model calls or live business continuation in these tests.

Deployment script review found the old image requires migration head 0017 exactly. Fixed before execution: rollback stops services, requires zero active jobs, no workflow-2 rows and unchanged historical fingerprints, runs formal downgrade 0017, verifies fingerprints/head, then restores old image. No stamp or bypass. Final reviewed deployment-script SHA256: `e7ab2ac1071397a52bfc5c8df607cc4465f5cb3da258af1c9a9678df16aca061`; BLOCKER 0.

Delivery at code freeze: software PASS; container health NOT RUN for new artifact; provider probe NOT RUN (zero); provisioning NOT RUN; local live NOT RUN for new artifact; GitHub live NOT RUN. Real incremental publication and fresh-product three-file webpage acceptance remain NOT RUN for this change. Existing APP 92460 and all source/original outputs are retained.

Previous real run dcbc67b3-15a3-588b-b7e7-19df10591cc4 failed after 1146.683148s, 2 checkpoint lease recoveries, HTTP400 invalid wiki release authorization, 0 new/10 reused model calls, 21 verified/31 missing/30 failed fields. It is not an acceptance pass.

Idle scan issue remains backlog: pump scans historical runs and constructs snapshots twice. Finalized runs do return before checkpoint/source validation; the 151% idle CPU observation cannot be attributed to full checkpoint revalidation from current evidence. Read-only live query found zero unfinalized executable historical runs and zero active jobs. Original worker was stopped only within this zero-work upgrade window.
