# G3 batch preparation and pinned pages implementation plan

> **For agentic workers:** Use superpowers:executing-plans in the existing exclusive lanes. Root owns integration and commits. This plan does not open a write domain until its entry gate passes.

**Goal:** Allow the reviewed complete batch to enter the existing human Draft/Ready/Activate flow and display its products, fields and sources from one pinned release.

**Architecture:** Extend the existing G2 services and UI through exact G3 contract dispatch. Reuse repository transactions, human decision verification, source authority and the sole serving Head. Python/C/common and their reviewed fixtures stay frozen.

**Tech stack:** Go service/handler/router; Vue 3/TypeScript; existing in-memory repository test doubles and Vitest. No dependency installation, migration, provider call or image build.

## Status and entry gate

`DESIGN_CANDIDATE_NOT_DISPATCHED`. Applicable requirements: G3-R3/R4/R5 and D consolidated v2 sections5–9; amendments7v2/8, source-coverage2, and d-active-page-transport-clarification-1.md. This plan specifies execution order, not a new wire contract.

- [x] Python source/test/342-field fixture independently PASS, commit e85fa570d.
- [x] Complete canonical preparation request:2,254,490 bytes, three separate raw executions, actual134-row base preserved with only the two frozen unknown-key alignments.
- [ ] Go mirror frozen and independently PASS for complete fixture, C replay and all nested authority/hash checks.
- [ ] Python-Go canonical/snapshot equality independently PASS.
- [ ] Root freezes exact Go source/test SHA and accepts this downstream plan review.
- [ ] Preparation UI alignment-lineage display clarification receives independent PASS (d-preparation-alignment-display-clarification-1.md); exact response DTO stays unchanged.

Until all unchecked entry gates pass, every production path below remains closed. Source provider approval is separate and still pending. Actual C model inputs and execution window are not supplied by this plan.

## Exclusive owner matrix after dispatch

Backend owner: g3_catalog_impl. Exact production paths:

- Create internal/application/service/concept_free_wiki_830_g3.go.
- Modify internal/application/service/concept_free_wiki_830_g2.go only at G3 base/read/citation dispatch.
- Modify internal/application/service/concept_source_authority_830_g2.go only for G3 source dispatch and necessary private helpers.
- Modify internal/application/service/wiki_release.go only at G3 preparation validation, review/activation and read-members dispatch.
- Modify internal/handler/schema_wiki.go for exact create variant, narrow optional service interfaces and preparation GET.
- Modify internal/router/routes_schema_wiki.go for the single human preparation GET.
- Create internal/application/service/concept_free_wiki_830_g3_test.go and internal/handler/concept_free_wiki_830_g3_test.go.
- Create internal/router/routes_batch_concept_830_g3_test.go.
- Modify internal/application/service/concept_source_authority_830_g2_test.go and internal/application/service/wiki_release_test.go only for G3 authority/CAS regressions.

UI owner: g3_catalog_ui. Exact production/test paths:

- Create frontend/src/api/schema-wiki/batchConcept830G3.ts and batchConcept830G3.spec.ts.
- Modify frontend/src/views/knowledge/schema-wiki/SchemaWikiCatalogEntry830G2.vue and .spec.ts.
- Modify frontend/src/views/knowledge/schema-wiki/ConceptDirectory830G2.vue and .spec.ts.
- Modify frontend/src/views/knowledge/schema-wiki/ConceptFreeWiki830G2.vue and .spec.ts.
- A narrow contract dispatcher in frontend/src/api/schema-wiki/conceptFreeWiki830G2.ts and .spec.ts is permitted only if the existing shared page loader requires it; preserve the G2 parser branch exactly.

No repository/interface-table migration, router-name change, KnowledgeBase.vue change, source service, generic adapter, second Head, Python rewrite or fixture rewrite. Any additional file needed returns to root before writing it. Root alone updates this evidence, OpenSpec, HANDOFF and commits reviewed slices.

## Task1 — Backend preparation construction and immutable reopen

- [ ] Add service tests using the frozen full candidate and actual saved G2 base. Assert a valid Draft stores the G3 outer candidate digest and exact snapshots while Head stays unchanged. Assert missing/changed base field, stale base epoch, missing base MATCH, alignment drift, changed canonical manifest and wrong scope fail before repository CreateDraft.
- [ ] Run `go test -p 2 ./internal/application/service -run 'Test.*BatchConcept.*830G3' -count=1`; preserve effective old-implementation failure separately from compile/environment errors.
- [ ] Implement CreateBatchConceptDraft830G3: existing Admin/scope checks, strict outer parse, current exact G2 base reopening, actual base/carry/alignment comparisons, then a fail-closed source-verifier call through the existing verifier interface, and only after success existing createDraftAtExpectedHead. Use the explicitly G3-only create-draft operation described in Task2; do not label a pre-storage check as review or fabricate a stored preparation digest. Task1 tests inject the existing fake verifier to prove both call order and denial causing zero repository CreateDraft calls; Task2 closes the real source implementation before any HTTP dispatch. CandidateDigest is outer candidate_hash; reviewer raw hash and existing policy hash feed existing preparation fields.
- [ ] Implement LoadBatchConceptPreparation830G3: GetDraftPreparation first; only repository NotFound permits GetReadyPreparation fallback. Validate canonical manifest and exact members again. Return the frozen preparation read DTO and read hash using its stored expected base, not a new CurrentHead lookup.
- [ ] Add DRAFT/READY reopen, wrong principal/seal, missing preparation, storage error (no fallback), stored member/manifest tamper and current-Head movement tests. Both valid statuses reopen the same candidate; preparation does not appear in current/search.
- [ ] Run the bounded tests to PASS, freeze source/test identities and request review before claiming service completion.

## Task2 — Source authority and review/activation

- [ ] Before dispatch changes, add tests for each registered receipt field drift, revoked source, wrong scope/attempt, chunk manifest/text/Unicode offsets/native bbox and changed old carry. A complete unchanged G1/C5 chain remains the positive legacy case.
- [ ] At the source verifier entry, dispatch by exact manifest contract before operation validation. Preserve G2 operations review/activate only. G3 accepts exactly create-draft/review/activate; reject all others. For create-draft, require nonempty requested preparation_id, exact scope, candidate hash, canonical outer Manifest and its real digest. PreparationDigest must be empty because nothing is stored yet, and it is explicitly not authority; reject nonempty forged stored digest in this branch. For review/activate, retain the real stored preparation digest and re-open that immutable preparation. No interface/DTO expansion. Add negative G2+create-draft and G3+unknown-operation checks.
- [ ] In G3 source dispatch, reopen live Knowledge, Revision and RevisionSource and compare the exact14 fields. Verify identity/classification and field/free-page Evidence with existing source checks. Reopen actual base and follow its existing G1/C5 chain; only exact byte-identical carry may inherit old proof.
- [ ] Complete the real create-time source branch already invoked by Task1; prove every14-field receipt drift, revoked source, wrong scope/attempt, bad manifest/text/Unicode/native join and changed carry rejects before repository CreateDraft (call count zero). The real source branch is mandatory before Task3 exposes create.
- [ ] Add G3 dispatch in reviewDraft, ActivateReviewed and private activate. Reparse preparation each time, recompute composition/alignment and call the same source authority verification. Never reuse create-time source conclusions.
- [ ] Test source drift before review leaves Draft and Head unchanged; drift after Ready leaves Ready, Head and activation receipt unchanged. Test stale Head CAS and exact nonce retry. Existing repository transaction semantics remain authoritative.
- [ ] Run `go test -p 2 ./internal/application/service -run 'Test.*(BatchConcept|ConceptSource|WikiRelease)' -count=1`; record bounded results and existing G2 regressions. Do not use a real DB or provider.

## Task3 — HTTP create/read and pinned source transport

- [ ] Add exact two-key create positive and missing/mixed/extra/null/duplicate-key negatives. Add human Admin/dual-KB sealed preparation route tests and DRAFT/READY status readback.
- [ ] Extend only the create variant `preparation_id + batch_concept_candidate_bundle`; retain 8 MiB limit and old variants. Add one GET at the frozen batch-concept preparation path with existing humanPreparationGuards and RequirePreparationScopeParams.
- [ ] Dispatch G3 Active concept reads after loading and validating the whole stored G3 preparation. Reuse the exact13-key concept-page-read.830.g2.v1 response; outer candidate hash and exact release/epoch pin bind all members and citations.
- [ ] For G3 overview, resolve related members from unique sections[].fields[].member_id within the same owner and manifest, return manifest order. Never look for a nonexistent overview.member_ids field. Overview citations are empty; existing concept/field/free-page citation projection remains.
- [ ] Reject repeated/empty G3 release_id and mixed preparation/release queries. Preserve old G2 query behavior. Issue Active source tokens only after full G3 authority reopening; preparation only exposes saved quote/page.
- [ ] Run `go test -p 2 ./internal/handler ./internal/router -run 'Test.*(BatchConcept|ConceptFreeWiki|SchemaWiki)' -count=1` and relevant service pinned-read tests. Preserve actual outputs and freeze the backend slice for independent review.

## Task4 — UI parser and preparation/Active modes

- [ ] Add parser tests against the exact frozen manifest and serializers. Cover all required/extra/null/duplicate/non-NFC/hash/scope/member-owner/Profile-coverage drift and preparation/release query exclusivity. Do not accept a partial object by casting it to G2.
- [ ] New batchConcept830G3.ts consumes the already validated Catalog. Preparation mode bootstraps human preparation scope and fetches the one immutable manifest response; Active mode pins current, searches the exact returned release and reads the exact pinned page transport.
- [ ] Add entry tests proving preparation query makes no /current or active-G3 directory load (the exact authenticated historical-base search needed for alignment is permitted), preserves the same candidate across refresh, and displays DRAFT as 待审核 and READY as 已审核但未发布. Normal G1/G2 modes remain unchanged.
- [ ] Add directory tests: five fixture products grouped by classification/formal name; exact Profile section order; each medical67, total342; no historical extra field; quality stays REGISTERED_NOT_QUALITY_ADMITTED. Alignment preview follows the separately confirmed bounded lineage display source.
- [ ] Add field tests that value/unknown, conditions, exceptions, valid_time and Evidence render from the same member. Preparation shows quote/page plus 激活后可打开原件 and makes zero Active token/content requests. Active follows the existing citation viewer with the outer candidate/release pin.
- [ ] Run existing Vitest command for the new API spec and the three changed Vue specs, plus relevant G2 page/citation specs and vue-tsc using the existing ignored G1 node_modules symlink. Do not install packages. Freeze changed UI identities for independent review.

## Task5 — Root integration and separate delivery

- [ ] Independent reviews must address exact frozen identities; owners fix only their domains within the repository repair budget. New foundational contract questions return to design.
- [ ] Root verifies backend+UI changes consume the same Go/Python frozen fixture, runs the appropriate combined bounded regression and strict OpenSpec validation, and checks the diff. Root commits only independently reviewed files.
- [ ] Software PASS does not authorize provider, DB writes, build, image deployment, Draft, review, activation or live browser actions. Those remain separately budgeted and receipt-backed. Preserve SOURCE approval and actual C execution dependencies.

Expected software result: local fixtures can traverse preparation/Ready/activation test doubles and pinned API/UI projections under existing authority. Real batch classifications, model quality, source upload, runtime health and actual serving activation remain NOT RUN until their own execution evidence exists.
