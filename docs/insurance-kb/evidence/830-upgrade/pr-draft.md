# Upgrade WeKnora to v0.8.2 while preserving Harness boundaries

Adopts fixed upstream `3e8b0bfc80b845b2d4b2ed683994748741450a97` on product baseline `8ccc2ac942df7572499ac7b25e14587c594918db`, preserving the Harness REST/lifecycle boundary, immutable sources, current ACL and sole Release authority. Model dispatch journaling uses the native transport; source mutation and worker writes use generation fences and exact-batch cleanup. BrowserSkill's verified pnpm executable is available to lifecycle subprocesses.

OpenSpec 130, UPG-01 through UPG-09. The latest CI/source correction commit is `844f03c55c8d25cff2fbccc9eb639cc343d932ab`. Source locking now uses a checker that accepts only the reviewed, exact two-file migration-077 preservation for this fixed release and requires the complete report's reviewed digest. Extra report keys, wrong hashes, partial preservation and a downgraded PASS verdict are rejected.

**Keep Draft. Full CI and runtime upgrade acceptance remain incomplete; no merge is authorized.**

## Validation

- Frontend: 1,283 tests passed, one existing skip; type-check and all 10 style guards passed. Shared tokens retain existing visual values without raising the baseline.
- License and real Nginx fixtures passed; the historical transport fixture uses the current embedding API. CLI/client tests and exact golangci-lint v2.12.2 checks passed.
- Adoption/report checks: 152 targeted tests plus seven final negative cases passed; full Ruff and mypy over 737 files passed. Frozen UI9, root7 plus formatting correction, and remaining18 file reviews report zero code blockers.
- Local full Harness run was interrupted after 1,112.67 seconds with 125 passed and 65 deselected. It is incomplete, not a full-suite pass. Final-head remote CI remains required.
- Pinned dsh rc8 HMR startup fixture is repaired; build and 58 unit tests passed. Two bounded dependency-install attempts did not complete, so real dsh E2E remains **BLOCKED**.
- Root Go lint was stopped after 1,243.14 seconds without a completed result and remains **BLOCKED** locally. UI build and no-network static smoke passed; exact-label reuse remains blocked as documented below.

## Artifacts and recovery

Colima's data disk was expanded from 110 to 130 GiB, retaining original services and volumes. Five database archives were created and their archive tables checked; this is not a successful restore. PostgreSQL's memory limit was temporarily raised after a backup OOM and restored after successful backup. Private data and credentials remain local and are excluded from this PR.

App source remains `e71c72f7`, image `sha256:442701a3bde3de5ff8aee7dfc9f7f461df1819b050c417f38ecd4ff226e33775`. Its fifth build's unpack failure remains recorded; the complete export was recovered with zero new builds and passed artifact smoke. Total App attempts remain five, additional budget zero. It is not an exact artifact for the later trusted-publication source.

DocReader source remains e71: one build produced `sha256:d1777cdcd55d5478d9781e4e3db7be1042983940deda748622feb796b77c7feb`; no-network health and Markdown gRPC parsing passed, and the temporary container was removed. An earlier unsupported txt fixture failure is retained separately.

UI source is `82ff324de9c43ed3e80460d1c82a9930e6298139`. The build wrapper generated a label using the wrong canonical input ordering/hash payload. Its observed label is retained, the reviewed expected identity is `sha256:9feb81303bd45548589375466c352e350d58814f737b63dfdb171b61ef37afc3`, and canonical exact reuse remains **BLOCKED**. Build and no-network content smoke passed for immutable image `sha256:1ca8b0cce1903b59116c8ddee9cc5dc005deb6d302c260a83ba66a81cc245d56`: homepage, 14 assets, Nginx/runtime configuration and the 7-character source marker. Temporary containers were removed. No rebuild or label mutation conceals the mismatch.

## Remaining acceptance

Isolated restore/migration has not started: automatic approval rejected creating test resources and archiving possibly sensitive configuration, and explicit user confirmation is pending. Existing services and epoch27 are not switched. Upgraded database migration, provider probes, new tracer, Candidate/review/publish/activation and source-click acceptance remain **NOT RUN**. Historical business evidence is not upgrade acceptance. New trusted-publication images are also **NOT RUN**.

Receipts are in `docs/insurance-kb/evidence/830-upgrade/`; the latest handoff and OpenSpec matrix distinguish code, artifacts, provisioning and business status. Ordinary-KB enrichment/finalizer and exact-index-cleanup retry limitations remain documented backlog.

Documentation/receipt changes are mechanical evidence updates under UPG-08/D0 and require no new behavioral RED or application build. Substantive checker changes have real RED-to-GREEN tests. The user authorized source/evidence push to this existing fork and Draft PR; root remains the only integration owner.
