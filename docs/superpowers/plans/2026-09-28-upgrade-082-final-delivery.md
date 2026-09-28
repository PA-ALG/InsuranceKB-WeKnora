# WeKnora 0.8.2 final delivery plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Root is the sole integration/build/deployment executor; continuation_review is read-only.

**Goal:** Deploy the reviewed 0.8.2 software to the user's existing local environment, preserve its data and rollback pair, and verify the existing reading and upload/parsing workflows.

**Architecture:** Keep the existing single Release authority and Harness REST boundary. Preserve the old database/files/configuration as a coherent rollback set; never migrate its volume in place and reconnect the old App to schema110.

**Tech Stack:** Colima linux/arm64, Docker, PostgreSQL17/pg_search0.22.6, Go App, Vue UI, DocReader, existing Python Harness.

## Authority and frozen scope

The user accepted merge → final artifacts/validation → backed-up cutover with “可以，就这么执行吧”. This supersedes previous no-merge/no-deployment and exhausted historical build windows for this specific final delivery. It does not authorize another product Goal, unrelated cleanup, or a new Release activation.

Root owns the paths in OpenSpec130 current-slice-paths.json and the private execution directory `/private/tmp/upg-final-delivery-20260928`. The component preparer writes only its declared private input/script files; it does not build or deploy. Private credentials/configuration stay in mode0700 directories/mode0600 files and never enter Git or tool output.

- Merged PR131: `c5beb1afc779a1a42d3658b4da62badd62f94b28`, preserving upstream and reviewed history.
- Tested PR source: `444ab56c1fccebcaf872862867b8564610ef4259`; merge tree is identical.
- Trusted software/build source: `d5be03b3b2da18d9bdcfb8f32d66e0bc31843a83`; later changes are evidence/source-lock metadata. Build input equality is checked per component.
- CI:21 successful/5 conditional skips; exact-head receipt and independent review are recorded on PR131.

## D2: final artifacts (execute before D3)

- [x] Merge the exact checked head, preserving the source ancestry. Verify main tree equals the checked tree.
- [x] Root runs existing `scripts/app_artifact.py select-or-build --repo-root . --context colima --build-source-head d5be03b3b2da18d9bdcfb8f32d66e0bc31843a83 --evidence-out /private/tmp/upg-final-delivery-20260928/app-d2-receipt.json` once, behind an exclusive execution receipt. Standard runtime recipe, no runtime-rebase exception. Frozen identity is `sha256:ffd27ee68069a1a81249f4ba0fcf9e7b3fb46625791e233e8e09e951ad13d42c`; lookup-before-build, miss permits at most one invocation. Preserve all caches and old images. Require at least16GiB guest free before invocation.
- [x] UI: preserve the reviewed872-path canonical definition and target field; use d5be source archive and commit build arg. Hash only canonical bytes, excluding the two already-reviewed non-input files. Do not reuse the previous mislabeled image or re-label it. Lookup exact identity; miss permits one cached Dockerfile build. Require at least8GiB guest free.
- [x] DocReader: preserve the existing112-path canonical definition. Its copied package-test input changed, so strict canonical comparison is a miss even though effective runtime behavior may be unchanged. Lookup new exact identity; at most one cached runner-stage build. Require at least14GiB guest free. This bound uses the previous measured growth of7,749,092KiB (7.3901GiB), leaving6.6099GiB reserve at the threshold; it is a planning estimate, not a peak guarantee. Run DocReader before UI and recheck UI capacity independently.
- [x] Harness: existing runtime image is unchanged in its runtime source/dependency inputs. Preserve its image; any later container recreation changes only reviewed deployment configuration.
- [x] Verify each resulting immutable image ID, source label, canonical identity and linux/arm64 platform. Run existing isolated artifact health/Markdown/static UI checks against these images with no external network or application data. Do not count these as business acceptance.

D2 builds run sequentially. No automatic retry, cache pruning, global network changes or extra image build. A build failure preserves the exact attempt/log and returns to diagnosis. Do not bypass identity guards or fabricate a REUSE result.

## D3: exact preparation and cutover gate

D3 remains unexecuted until a concrete private script/plan has independently closed the following observed risks. The user has authorized the work; no redundant permission question is required for routine implementation of these steps.

- [x] Inventory current container IDs, networks, mounts, ports, application/configuration identities and queues. Preserve all eight original services until the maintenance window. Record source DB official75/enterprise5 and existing Release epoch27.
- [x] First validate final App and DocReader on isolated resources, with distributed empty Redis and housekeeping disabled. Preserve the known21 pending tuples/216 spans and three soft-deleted records; do not invoke Lite fallback or old queues. Verify ordinary login, knowledge/ACL reading, source locator and exact PDF bytes using normal authentication, never extracting auth tokens from DB.
- [x] Validate one dedicated upload/parsing sample using native KB switches and parser configuration. Freeze sample, optional-processing flags and actual model-call budget before sending. Prefer provider-zero parsing where supported; do not pretend an unindexed parsing test is full semantic retrieval acceptance. No Candidate/review/publish/activation is needed for this approved scope.
- [x] Choose fresh consistent backup/restore by default. Existing restored copy can be reused only after all writers are quiesced and complete database/file/configuration comparison proves freshness; epoch/row counts alone are insufficient.
- [x] Enter maintenance: block new user writes; drain actual queued/in-flight work; stop old App and Harness API/worker writers. Preserve old containers, old unmodified DB volume, file/config/C5 archives and queue state. Back up all databases with adequate PG memory (previous1GiB dump OOM requires a temporary reviewed4GiB limit, restored afterward).
- [x] Restore current coherent backups to a separate target DB/files/config set. Use the already-pulled exact PG0.22.6 image, the final App's native migration entrypoint and one bounded migration attempt. Check110/false, enterprise5/false, extension0.22.6, original-column data continuity and the reviewed migration-only differences. Unknown or unexpected results stop before routing users to the target.
- [x] Switch all dependent configuration together: UI targets App by container name; Harness DB URLs currently hardcode the old PG name, and its REST/catalog targets also require exact verification. Preserve model/C5/ACL configuration; avoid duplicate workers or competing queue consumers. Start only exact D2 image IDs, never rebuild/pull during D3.
- [x] Verify the existing host entrypoint, normal login, Harness authentication/health, knowledge read/ACL and source/PDF bytes on the new live environment. Reuse the separate exact-final-image isolated PDF upload/parsing proof; no additional live upload or provider dispatch at cutover. Confirm epoch27 remains unchanged and no new Release authority was introduced. Open normal user writes only after these checks pass.

## Rollback and STOP

Before reopening writes, failure returns the routing and stopped services to the untouched old App/UI/DocReader/PG/files/config/Harness pair. The old App must never connect to schema110. If users have written to the new environment, stop new writes and preserve the new DB/files first; do not silently revert to an older snapshot and lose their changes.

STOP on unknown migration state, any dirty ledger, unexpected business/data/ACL changes, unknown in-flight work, artifact mismatch, failed authentication/continuity, low capacity or a failed bounded build. Evidence must distinguish software, image health, provisioning, provider activity, local live and GitHub CI. Final user report must state what actually runs and any acceptance limits.

## Closeout

- [x] Independently review the frozen execution receipts.
- [x] Update HANDOFF/OpenSpec130 and `final-delivery-20260928.json` with exact final identities, counts, side effects and rollback location; no private contents.
- [ ] Report the actual user entrypoint and version after successful cutover. Do not claim deployment from CI alone.

## Diagnosed UI network recovery amendment

The first final UI build failed only while `npm ci` downloaded dependencies: ECONNRESET/network aborted after137s; no compiler or capacity failure. Preserve the failed receipt and complete log. Four exact lockfile tarballs covering registry.npmjs.org, mirrors.tencent.com, registry.npmmirror.com and cdn.sheetjs.com were subsequently downloaded once from Colima and each matched its locked SHA512. The precise failing URL is unavailable; these probes support one bounded transport recovery and do not guarantee all later transfers.

Within the user-authorized network recovery and final delivery, root permits one additional independently reviewed UI build (UI total maximum2, App1/DocReader1/Harness0 unchanged). Keep all872 inputs, Dockerfile, pinned bases, registry/build args, source d5be and canonical identity unchanged. Recheck8GiB capacity. Change only output receipt/log/iid paths; archive the first failure byte-for-byte before the second invocation. On success publish the canonical D2 receipt referencing the retained first failure. On another failure stop for diagnosis; no automatic loop or configuration bypass.

The archive preparer retained0664 transport modes while the prior successful context used0644; a read-only manifest records the difference. Current BuildKit inventory has312 records and only the newly failed COPY/WORKDIR entries for this frontend; no prior successful npm ci layer remains available. Therefore this recovery does not normalize modes merely to chase an absent cache: preserve the original context bytes and permissions unchanged. No build recipe, registry, dependency version or integrity check changes.

## UI transport diagnosis and proxy-wired recovery

The second attempt also failed in npm ci with ECONNRESET after77s, so further unchanged retries stopped. Exact BuildKit history records only the three canonical recipe arguments and no proxy arguments. Colima itself uses the already-configured HTTP/HTTPS proxy at192.168.5.2:7897 with localhost-only bypass. Thus earlier VM curl probes used a different network route from the failing build. No precise first/second failing npm URL survived in BuildKit storage; do not invent one.

An isolated Docker-bridge curl probe explicitly using the existing proxy verified all four origin samples with HTTP200 and their locked SHA512. A separate one-shot diagnostic uses the same pinned Node24 base, npm11.19.0 and exact package/lock bytes, explicit existing proxy, npm ci with verbose logs and no image build. Its detailed logs and exit status must pass and be archived before recovery. A Python-client403 probe remains separate failed evidence; it is not treated as a successful transport proof.

After independent review and full-lock diagnostic PASS, allow one corrected UI build (UI total maximum3; no automatic loop). Preserve every canonical source byte/mode, declared recipe argument, platform, base digest and identity. Add only Docker's standard predefined HTTP_PROXY/HTTPS_PROXY/NO_PROXY transport arguments for this invocation. [Docker documents](https://docs.docker.com/build/building/variables/#proxy-arguments) that these need no Dockerfile declaration and are excluded from cache/history by default. They are not product inputs or runtime ENV; the receipt records them separately and verifies no proxy ENV persists in the final UI image. Do not modify global proxy settings, registries, integrity checks, source or Dockerfile.

Both failed attempts remain immutable evidence. On a further failure, stop and diagnose rather than retry. After successful npm diagnostic and archived debug logs, its exact owned stopped temporary container may be removed to reclaim its disposable dependency layer; preserve all old environments/images/caches and the diagnostic receipt/logs. Recheck8GiB before the final build and recheck the separate measured cutover capacity budget afterward.

## Isolated upload preflight correction

The first isolated upload invocation stopped before login, upload, or provider-egress attachment. Its duplicate guard passed PostgreSQL's raw boolean `f` to `json.loads`; an unused later model guard had the same defect. Encode both EXISTS expressions with native `to_json`, retaining their assertions. Preserve the original failure/once/cleanup records; the exact validation App was stopped successfully. No product code or image changes.

A separately reviewed one-shot recovery wrapper may start that same owned stopped validation App once after checking image, dependency, network, original-service and protected-data identities. Write ordinary recovery evidence to a new private directory, but preserve the root-level exclusive upload lock across invocations. Actual upload budget remains one; no automatic resend or model retry is added. On success publish the canonical receipt with original-failure and recovery-receipt hashes. Any failure stops the owned validation App and retains evidence; do not loop.

## Correct the acceptance sample to the existing PDF contract

The single Markdown upload parsed and embedded successfully (one journaled HTTP200, zero retries) but failed revision sealing because the pre-upgrade repository already requires application/pdf. This is a sample-design failure, not evidence of an upgrade regression. Preserve the failed source and its one terminal archived postprocess task. No runnable/retry work remains; a closed-set read-only guard may permit exactly this frozen archived task while rejecting all others. Do not delete the task, edit MIME, or loosen product validation.

Use one genuine one-page ASCII PDF and first verify final DocReader builtin parsing with native PDF structure capture and no external provider. Freeze exact text, file hash, image and parser proof. Reuse the existing isolated upload verification with only explicit sample-format parameters. Permit one manual PDF upload. The successful expectation is one embedding call; the observed result is Markdown1 + PDF1 = two actual calls, with zero observed embedding-worker or model-transport retries. Native task MaxRetry3 remains and can allow up to four PDF dispatches in a failure case; the observer stops on unexpected calls/retries but is not a hard exactly-once guarantee. Do not describe the successful expectation as a removed native retry capability. Preserve executed scripts verbatim before the private verification module is parameterized. Independent review must pass before parser-proof execution and before the one PDF upload. Successful PDF source revision, manifest, source bytes and journal are required before cutover.

## Backup memory window correction

The first final backup was interrupted before any dump by a source PostgreSQL backend OOM at its existing1GiB limit during the full product_ingestion_artifacts hash. Native recovery and automatic rollback restored the old services; no target database or migration was created. Keep the original failure and rollback evidence. Extend the already planned temporary4GiB setting over both full snapshots and all backup work, with unconditional restoration. Permit one separately reviewed recovery invocation after exact rollback-state and empty-output-directory verification; preserve the historical running baseline and bind the new authorized restart baseline separately. No product/image changes or repeated upload are needed.

## Container mount comparison correction

The backup recovery stopped during preflight, before stopping writers or creating any dump. Docker returned the same Mounts entries in a different order, so an order-sensitive hash and rollback comparison falsely reported drift. All original services remain running with exact images and complete mount attributes equal after sorting by destination. Preserve this invocation and STOP evidence. Correct only the set ordering, retain all attribute checks and original running identities, and allow one separately reviewed recovery2 invocation against the same empty backup directory. Later stage rollback receipts must be exclusive and uniquely named; preflight failure must not consume old maintenance intents. No new product change, upload, image build, or migration attempt is added.

## Native Redis stdout correction and fresh backup

The second actual backup completed five dumps and four archives, but redis-cli treated /dev/stdout as a regular file and failed fsync on a pipe after successful transfer. The second source snapshot did not run, so the partial set is not declared coherent. Original service rollback PASS and original source memory restored. Preserve the entire prior backup directory and failure evidence. Official Redis CLI supports --rdb - for stdout; a controlled export and native redis-check-rdb both exited0, with only an owned temporary checker file removed. Use that exact native option.

One separately reviewed recovery3 uses a fresh sibling directory tmp/upg-final-backup-20260928-recovery3, a separately frozen current uptime baseline tied to unchanged original identities/configuration, and the same backup/restore/native migration procedure. Preserve both earlier attempts and the preflight-only failure; do not retrofit coherence into older dumps or erase once guards. Temporary4GiB covers both snapshots and all backup work. No extra application build, provider call, original database migration, or new business activation.

## Final execution outcome

D2 exact artifacts, isolated PDF acceptance, coherent five-database backup, separate-volume restore, one native migration, dependent rewiring and actual public endpoint checks all PASS. Historical failed attempts remain in the evidence; the closeout JSON distinguishes actual provider calls and acceptance limits. Private recovery material is durable. No new Candidate or Release activation.
