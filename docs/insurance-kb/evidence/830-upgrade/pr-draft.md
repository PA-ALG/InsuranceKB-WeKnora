# Upgrade WeKnora to v0.8.2 while preserving Harness boundaries

Adopts fixed upstream `3e8b0bfc80b845b2d4b2ed683994748741450a97` on product baseline `8ccc2ac942df7572499ac7b25e14587c594918db`. Preserves the Harness REST/lifecycle boundary, immutable source revisions, current ACL and sole published Release authority. Model dispatch uses the native transport; source mutation and worker writes retain generation fences and exact-batch cleanup. BrowserSkill's verified pnpm entry point is available to lifecycle subprocesses.

OpenSpec 130, UPG-01 through UPG-09. The source checker accepts only the reviewed exact migration-077 preservation pair for the fixed upstream and the complete manually reviewed report digest. No migration drift or downgraded verdict is accepted.

**Keep Draft. No merge or original-runtime cutover is authorized. Code, CI, artifacts and isolated migration evidence are separate.**

## Validation

- Frontend: 1,283 tests passed, one existing skip; type-check and all 10 style guards passed without raising the baseline.
- License/Nginx fixtures and CLI/client tests/lint passed. Adoption/report checks, Ruff and mypy evidence are recorded against their exact source identities.
- Remote `5bd50ba78` finished with 21 successful, 3 failed and 5 skipped checks. Two failures shared a historical standalone-Go package collision, repaired in `0565517ce`; explicit-file builds and package enumeration passed. The dsh failure exposed an incompatible transitive HMR update; `3507e8fcb` pins HMR 1.0.16 for exact dsh rc8 and refreshes incompatible cached installs. Its 58 unit tests passed; real E2E requires final-head CI.
- Removing the Go typecheck blocker exposed 174 diff-scoped lint findings. The bounded correction preserves runtime strings and serialized fields, documents only the two required single-line compatibility exceptions, and retains all failed and incomplete checks. The final 96-path correction `18c5f74c3` passed two frozen code reviews and focused tests. An uncapped run reported 973 findings over 279 changed paths and timed out; all findings were confirmed within the product-base diff. The final nine corrections stayed inside the approved lane. Full lint remains **BLOCKED**; no rules were relaxed and the other 234 paths were not modified.
- Trusted source verification/report binding passed for final reviewed source `07d0e3e48` / tree `8eb1c1f2…`; the same `dfaf453e…` report matches the earlier 844/3507 report byte-for-byte. Existing images are not relabeled as artifacts of this later source.

## Artifacts and isolated recovery

Colima was expanded from 110 to 130 GiB. Original services/volumes are retained. Five private custom PostgreSQL dumps have now been restored into a new isolated server. The fifth restore initially failed because its owner role was absent; the transaction rolled back. After independent review, only that failed copy was recreated with its verified owner and restored once more successfully. The role password was not copied and Harness credential authentication remains untested. A PostGIS-created search-path difference is explicitly recorded.

The isolated recovery and migration of the existing e71 App image now pass. Five database backups and the exact live App configuration were restored; old-version published reads passed before the one target-PG pull and one formal native migration. The result is official110/false, enterprise5/false and pg_search0.22.6. All61 original-table projections satisfy the closed migration contract; only four declared storage timestamps changed. Protected21 knowledge rows/216 spans and epoch27/member/source/citation/PDF continuity are preserved. Both test Apps are stopped and the original eight services remain unchanged. Six legacy Wiki log entries are preserved; the zero legacy-log-page sample does not exercise nonempty page archival. Harness password authentication remains untested.

Two verification mismatches were resolved without restart or database edits: citation digests include expiry and validate independently before full authority comparison at a common expiry; storage timestamps require their actual SQL type for comparison. Initial failures and configuration preflight stops remain in the receipts. Configuration contents stay in local private storage.

Head `8b1215519` completed19 successful,2 failed and5 skipped checks. Pinned dsh real E2E and deterministic checks passed; Go tests and root lint failed. Bounded test-fixture and Linux-runner prerequisite repairs preserve the existing assertions. A distinct new regression exposed replacement files retaining the previous source SHA; the bounded source update/rollback correction in `07d0e3e48` passed19 tests and4 subtests, with14 fixture tests and the historical capture tests also passing. Its10-path diff passed independent review. This later software is not claimed to be inside the tested e71 image.

App source e71/image `442701a3…` was recovered from the fifth build's complete export after its original disk-unpack failure; zero additional builds. Total App attempts remain five, extra budget zero. DocReader e71/image `d1777cd…` passed one build, no-network health and Markdown gRPC smoke. UI source `82ff324de`/image `1ca8b0c…` passed one build and no-network content smoke; its incorrectly generated identity label is retained, so canonical exact reuse remains blocked. No new trusted-publication image has been built.

## Remaining acceptance

Final-head CI, new-source artifact delivery, original-runtime deployment, provider probes and new business tracer acceptance remain pending gates. Isolated upgraded continuity passed only for the recorded e71 image and copied dataset. Existing epoch27 is not switched; no new Candidate/review/publish/activation is inferred from local checks. Ordinary-KB enrichment/finalizer and exact-index-cleanup retry limitations remain documented backlog.

Receipts are in `docs/insurance-kb/evidence/830-upgrade/`; HANDOFF and OpenSpec record exact current status. Documentation/receipt and mechanical metadata corrections use the UPG-08/09 exemption from new behavioral RED; existing lint failures provide the mechanical RED, while substantive checker changes retain real RED-to-GREEN tests. Root is the sole commit/push owner for this authorized fork and Draft PR.
