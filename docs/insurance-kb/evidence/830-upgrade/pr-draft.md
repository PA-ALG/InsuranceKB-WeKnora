# Upgrade WeKnora to v0.8.2 while preserving Harness boundaries

Adopts fixed upstream `3e8b0bfc80b845b2d4b2ed683994748741450a97` on product baseline `8ccc2ac942df7572499ac7b25e14587c594918db` while preserving the Harness REST/lifecycle boundary, immutable sources, current ACL and sole Release authority. Model dispatch journaling uses the native transport; source mutation and worker writes use generation fences and exact-batch cleanup. BrowserSkill's verified pnpm executable is exposed on child-process PATH so its extension lifecycle can run correctly.

OpenSpec 130, UPG-01—09. Unique integration Owner=root. Approved design SHA256 `8392a3a7420b09bc2beda82dcfcb82c385e61f4a857f98ec568eba6fbcd771bd`. Initial upgraded source `8a0863fa095bc27b901db90c5f744d1db84063b2`; current App software source `e71c72f7dd885e228c4f447c68902450fed7ae26`. Later evidence-only commits do not change the App artifact identity.

**Keep Draft: the upgrade is not ready to merge or deploy.** The b64923 CI snapshot has seven independently diagnosed blocker groups: license fixture, frontend style guard, Nginx route fixture, stale historical Go DTO, CLI lint, client lint and the pinned upstream dsh rc8 HMR activation race. See `ci-failures-b64923.json`; suggested repairs have not been implemented or verified. Some checks were still running in that snapshot, so this is not a final all-checks report.

## Validation and App artifact

Affected Go/source-contract checks, Harness/Ruff/mypy, frontend tests/type-check/build and OpenSpec checks have recorded local passes. Frozen implementation reviews report zero BLOCKER for core43 plus the router fixture, frontend80, build18, migration13 and the DocReader base pin. The pnpm child-shell regression is RED→GREEN; its related suite is 130 PASS, full Ruff PASS and mypy 736 files PASS. These bounded results do not claim full CI or service/model namespace coverage.

The download path was repaired by selecting an existing verified Singapore proxy route and removing failed registry mirrors from live and persistent configuration. Six fixed-layer transfers and five locked dependencies passed checksum checks. The next real App attempt passed all compilation and runtime assembly, including AnyDoc, BrowserSkill and Go, then failed during local image unpack with ENOSPC after 3139.799075386 seconds. Its original exit1/INCOMPLETE receipt is retained.

The complete OCI image had already been exported. After available space recovered without manual cleanup, all 22 layer hashes were verified and expanded tar size was checked against free capacity. Independent review found zero BLOCKER for one isolated verification. The existing selector, with a hard build budget of **zero**, returned REUSE PASS; the existing exact-image artifact smoke then passed and cleaned up its own temporary container. No sixth build or additional pull occurred.

- App artifact: `sha256:12d583e5de9f3ad36cad01490250962a18c4d5197b9da0494fa874747c5a1da4`.
- Recovered image: `sha256:442701a3bde3de5ff8aee7dfc9f7f461df1819b050c417f38ecd4ff226e33775`.
- Total App attempts: **5**; this window **1/1 used**, remaining **0**. Separate REUSE/smoke: build0/pull0.
- Smoke scope: executable artifacts, dynamic libraries, AnyDoc license and BrowserSkill extension. It overrides the application entrypoint and does not prove HTTP/business health.
- Original eight services retain their IDs/start times/PIDs. No manual image/container/volume/cache cleanup, daemon/service restart, migration, deployment or provider call occurred in this window. Post-smoke Colima free space: **1583464 KiB**.

Exact failure, export-integrity checks, independent recovery review, REUSE/smoke receipts and service snapshots are in `delivery-attempt-05.json`. Earlier failures remain in attempts01—04; none was rewritten as success.

## Remaining delivery

UI/DocReader upgraded images, database backup/restore/migration, upgraded service health, provider probes, Candidate/Draft/review/publish/activation and upgraded local live acceptance are **NOT RUN**. Existing epoch27 is prior evidence, not upgrade acceptance. Database target remains official110/enterprise5 and pg_search0.22.6; rollback requires a matching old database backup and old App. Ordinary-KB enrichment/finalizer and exact-index-cleanup retry limitations remain documented BACKLOG. No upgraded-runtime screenshots exist because the upgraded services have not been deployed.

## Mechanical evidence exemption for this update

UPG-08/D0: this update only records authorized execution, immutable receipts, existing-source CI diagnosis and current delivery status. It changes no product behavior, build inputs or acceptance criteria, so repository AGENTS.md permits exemption from RED; no application build is triggered for documentation. The root is the only writer. Independent reviewer `migration_review` reviews the frozen hashes and explicitly confirms this exemption before integration. Exact eight paths:

- `HANDOFF.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/tasks.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/delivery-impact.md`
- `openspec/changes/130-weknora-082-harness-plugin-boundary/validation-report.md`
- `docs/insurance-kb/evidence/830-upgrade/recovery-authorization.md`
- `docs/insurance-kb/evidence/830-upgrade/delivery-attempt-05.json`
- `docs/insurance-kb/evidence/830-upgrade/ci-failures-b64923.json`
- `docs/insurance-kb/evidence/830-upgrade/pr-draft.md`

Previous mechanical-evidence exemptions and their exact reviewed paths remain in prior commits. The pnpm implementation itself has a real behavioral RED→GREEN and is not exempt. The user explicitly authorized pushing this source/evidence payload and maintaining this Draft in `PA-ALG/InsuranceKB-WeKnora`; no merge is authorized.
