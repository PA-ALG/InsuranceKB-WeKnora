# G3 D backend seams — read-only pre-review

Status: `READ_ONLY`; no product/runtime effects. Inputs: frozen D v2 `lane-d-consolidated-contract-v2.md` SHA `75c81f582b2ace94efba6d016f0d24c00eb3e10a836f6673612bb7aaa3bfb94d` and `d-ui-seams-readonly-01.md`. Active D Python/Go was not read.

## Minimal production paths and exact dispatch points

1. **Create only**
   - `internal/handler/schema_wiki.go`: `schemaWikiCreateDraftRequest`, `decodeSchemaWikiCreateDraftRequest`, and `SchemaWikiHandler.CreateDraft`.
   - Add exact `preparation_id + batch_concept_candidate_bundle`; dispatch to `SchemaWikiService.CreateBatchConceptDraft830G3` in planned `internal/application/service/concept_free_wiki_830_g3.go`.
   - The service validates outer bytes, reopens current Head/base release/preparation/members, projects snapshots, then calls existing `WikiReleaseService.createDraftAtExpectedHead`. No repository schema or generic route change.

2. **Review and activation**
   - In `internal/application/service/wiki_release.go`, add G3 contract dispatch to `WikiReleaseService.reviewDraft`, `ActivateReviewed`, and private `activate`; every branch reparses the frozen preparation and recomputes G3 manifest/member/base/alignment closure.
   - `ReviewSchemaDraft` in `internal/application/service/schema_wiki.go` already delegates to `reviewDraft`; no second review API.
   - Existing `SchemaWikiHandler.ReviewDraft`, `WikiReleaseHandler.Activate`, review route, and `/activations` route remain.

3. **RegisteredSource and legacy G1/C5 authority**
   - Extend only top-level contract dispatch of `ConceptSourceAuthorityService830G2.VerifyConceptSources830G2` in `internal/application/service/concept_source_authority_830_g2.go`.
   - G3 must compare all 14 `knowledge-revision-source.v1` fields with live `GetKnowledgeByID`, `GetRevision`, and `GetRevisionSource`: scope/KB, attempt, source ID, file/object hash, size, MIME, page count, manifest algorithm/digest, chunk count, binding digest, and pinned retention.
   - Then reuse `verifyEvidence`, which recomputes chunk manifest and checks exact SourceBlock text, Unicode-code-point quote offsets, fixed PDF, and native bbox. The receipt alone is not authority.
   - For actual G2 base, load/validate its exact bundle and reuse `verifyLegacyCarryover830G2`; it already follows the immutable chain to G1 and replays `loadLegacySchemaCustody830G2` plus C5 citation authority. Transfer proof only to byte-identical carry; new/changed evidence uses `verifyEvidence`.
   - Review and Activate call this same branch from stored manifest. Active citation keeps the sealed route; service loader dispatches G3 before signing the existing release/epoch/candidate-bound token.

4. **Preparation DRAFT/READY read**
   - Add `SchemaWikiService.LoadBatchConceptPreparation830G3` in the new G3 service. Call `GetDraftPreparation`, fall back only on `ErrWikiReleaseNotFound` to `GetReadyPreparation`, preserve status, and fully validate frozen manifest/members.
   - Add one handler/interface entry in `internal/handler/schema_wiki.go` and one route in `internal/router/routes_schema_wiki.go`: `GET .../schema/preparations/:preparation_id/batch-concept`.
   - Reuse `humanPreparationGuards` and `RequirePreparationScopeParams`; never replace expected base with current Head.

5. **Pinned Active reads and single Head**
   - Add G3 dispatch to `WikiReleaseService.readMembers`, preserving existing `Current`, exact pin, search, and pinned payload routes.
   - Add bounded G3 dispatch in `internal/application/service/concept_free_wiki_830_g2.go` for current concept-page/citation routes. Keep handler/routes if the frozen compatible page envelope is retained.
   - Do not edit `internal/application/repository/wiki_release.go`: `CreateDraft` checks expected Head twice, `ReviewDraft` CASes immutable Draft→Ready, and `Activate` atomically writes release/members/receipt and CASes the sole Head.

## Minimal test seams

- Handler/router: exact G3 create accepted; mixed/extra keys rejected; preparation GET enforces Admin + dual-KB seal and reopens DRAFT/READY.
- G3 service: stored manifest/member tamper, stale base Head, incomplete base MATCH, alignment drift, and candidate drift fail before Draft.
- Wiki release: review/activation both revalidate sources; drift leaves Draft/Ready and Head unchanged; stale Head fails CAS; nonce retry remains exact/idempotent.
- Source authority: each receipt-field drift, revoked source, manifest/chunk/text/Unicode/native drift fail; unchanged G1/C5 carry succeeds and changed carry cannot borrow proof.
- Active read: preparation stays out of current/search; pinned G3 survives later Head changes; citation token binds outer candidate, release, epoch, member, citation.

Conclusion: no new table, source service, review authority, route family, or Head is required. Before changing the active-page handler interface, freeze whether `concept-page-read.830.g2.v1` is intentionally reused for G3 members; otherwise freeze one G3 response envelope.
