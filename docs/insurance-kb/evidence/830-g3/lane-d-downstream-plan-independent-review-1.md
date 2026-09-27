# G3 D downstream execution plan — independent read-only review 01

Date: 2026-09-07
Reviewed identities:

- `lane-d-downstream-execution-plan-1.md` SHA-256 `c991a8fe8de69ac843e509cc91933fd36cfa6543a71bc15b7d2814aa0e93d759`
- `d-preparation-alignment-display-clarification-1.md` SHA-256 `13468d31e6e070988ed4ab6baf68495cd7cf430531efbaf46a172e39238122ad`
- baseline commit inspected through `git show`: `e85fa570dc7b3d86c77a7fcc8682523f67b9db0d`

Effect: design/source inspection only. Active uncommitted Go files were not read. No test, HTTP, DB, provider, model, build, install, product write, or commit was run.

## Conclusion

`BLOCKER: 2`; downstream production dispatch should remain closed. Task ordering, declared ownership, 8 MiB gate, DRAFT/READY immutable reopen, Active pinned-read envelope, dual-KB guards, human review, and sole-Head activation/CAS otherwise follow the frozen D contracts and existing seams.

## BLOCKER 1 — create-time live source reopening is not an explicit executable step

D consolidated v2 §7.3 requires the service to revalidate `source custody` before writing the Draft. The current plan's Task1 implementation sequence ends with `createDraftAtExpectedHead` after outer/base/carry/alignment checks (plan line 52). Task2 defines the G3 source dispatcher and calls from `reviewDraft`, `ActivateReviewed`, and private `activate` (lines 59–62), but never explicitly connects that verifier back to `CreateBatchConceptDraft830G3` before repository `CreateDraft`.

This matters because the existing baseline `CreateConceptFreeWikiDraft830G2` validates bundle/base and calls `createDraftAtExpectedHead`; it does not invoke `VerifyConceptSources830G2`. An implementation following Task1 literally can persist a Draft whose RegisteredSource receipt or live revision has drifted, contrary to the frozen D path. The Task2 phrase “Never reuse create-time source conclusions” implies such a check but does not create a testable implementation dependency.

Minimum plan correction: Task2 must, before Task3 exposes the handler, call the G3 source verifier from `CreateBatchConceptDraft830G3` after strict/base validation and before `createDraftAtExpectedHead`. Its focused tests must prove every registered-receipt field drift, revoked source, wrong scope/attempt, bad manifest/text/Unicode/native join, and changed carry cause zero repository `CreateDraft` calls. Review and activation still reopen independently.

## BLOCKER 2 — the proposed client-static alignment projection bypasses KB ACL

The clarification's only runtime source is a six-field projection copied into `batchConcept830G3.ts` from the repository fixture (clarification lines 11–15). That places exact tenant release topology — entity/version and old/new member IDs — into the downloadable JavaScript bundle before authentication. It repeats the already-rejected Catalog static-asset boundary: protected KB metadata must be obtained through existing dual-KB ACL and seal checks. The docs fixture is also unavailable as a runtime asset unless copied or hardcoded, neither of which is declared as a protected backend input.

The response DTO need not change. After the authenticated preparation-scope bootstrap and immutable preparation GET pass, use `expected_base_release_id` to call the existing sealed generic GET:

`/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/releases/:expected_base_release_id/search?q=`

That route already enforces Viewer, Wiki KB read, RAW KB read, and the access seal. Strictly parse the result with the existing G2 parser using the response's exact expected base release/epoch; locate exactly one singular-key field for each of the two frozen entity/version pairs. Resolve `new_member_id` only from the current preparation manifest's plural-key field. Reject missing/duplicate/wrong owner/version/key and never substitute `/current`. This uses existing transport and fits the new `batchConcept830G3.ts`; it adds no DTO, table, service, static asset, or second authority. Task4's “bypasses Active directory fetch” test should mean no `/current` or active-G3 directory load; this exact historical base pinned read is permitted only for the alignment preview.

## Confirmed compatible seams

- The declared backend paths cover the needed new G3 service plus bounded dispatch in the existing G2 source, Wiki release, handler, and router files. The handler's current closed create decoder and 8 MiB limit support a new exact two-key variant.
- Existing `humanPreparationGuards` already provide Admin, dual-KB reads, preparation-scope resolution, and access sealing for the one new GET.
- `GetDraftPreparation`, NotFound-only Ready fallback, stored expected base identity, and no CurrentHead lookup match immutable refresh semantics.
- Task1 → Task2 → Task3 is runnable after BLOCKER 1 is made explicit: service/storage first, source/review/activation next, then the HTTP surface. Task4 can consume the frozen response contract and existing authenticated transports after backend freeze.
- Generic `/current`, exact pinned `/releases/:release_id/search`, existing `/activations`, and repository CAS remain the single serving path. Preparation does not enter current/search or receive Active citation tokens.

## BACKLOG / REJECTED

- `BACKLOG: 0` within this plan review.
- `REJECTED`: widening the preparation response solely to carry alignment rows, adding a new metadata endpoint/static JSON, reading current Head for the historical link, or weakening G2 parsers. The existing authenticated pinned search closes the display-source need.
