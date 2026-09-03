# G1 Successor Source Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frozen 76-member G1 entity graph readable through its real successor Release identity, while preserving and replaying the exact historical 815 source identity for citations.

**Architecture:** The existing Wiki Release CAS remains the only publisher. The response envelope and opaque citation authority carry the successor serving identity; the immutable manifest members and source replay request retain the old 815 identity, joined only through the successor's existing `BaseReleaseID/BaseActivationEpoch`. Exact pinned successor reads and citation content replay do not consult Head, while current reads pin Head once and fail closed when Head is not a valid G1 successor.

**Tech Stack:** Go 1.26, GORM/SQLite service tests, Gin handler tests, Ed25519 opaque citation tokens, Vue 3/TypeScript/Vitest, Docker/BuildKit, OpenSpec evidence JSON.

---

## Frozen boundaries

- Implementation worktree: `/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g1-field-assertion-pages`
- Approved design: `docs/superpowers/specs/2026-09-02-g1-successor-release-source-bridge-design.md`
- Frozen manifest/vector: `harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json`
- Product-code write domain: the exact Go and frontend files listed below; no migrations, new routes, payload rewrites, frontend redesign, second Head, second publisher, production mutation, Provider/model calls, or G2 work.
- Build budget after all source tests pass: one replacement app image and one replacement frontend image. The original D2 images and receipts remain immutable.
- Controller alone executes every commit step below, builds, integrates, and writes evidence.
  Review windows are read-only.

## File map

- `internal/application/service/entity_page_graph_830_g1.go`: validate successor-to-source custody; construct current/pinned entity responses; derive exact historical citation requests from a route-selected successor.
- `internal/application/service/entity_page_graph_830_g1_test.go`: real CAS/read/source-bridge regressions and tamper/no-fallback tests.
- `internal/application/service/schema_wiki.go`: carry private serving/source request metadata, preserve generic Schema behavior, reconstruct active or exact-release citation reads.
- `internal/application/service/schema_wiki_citation_content.go`: sign and verify private route kind plus serving/source identities without changing the public authority contract.
- `internal/application/service/schema_wiki_citation_content_test.go`: token-kind, source-binding, tamper, and generic compatibility tests.
- `internal/handler/schema_wiki.go`: admit signed exact-release citation tokens through the existing dual-ACL route without consulting Head.
- `internal/handler/schema_wiki_test.go`: handler scope-gate regression for exact-release tokens.
- `internal/router/routes_schema_wiki_test.go`: prove the existing citation route and middleware order remain unchanged.
- `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts`: parse successor serving envelope separately from immutable source members.
- `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts`: new focused preparation/current/pinned dual-identity parser regressions.
- `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts`: current/pinned source-click regression using the unchanged route.
- `openspec/changes/126-830-g1-entity-field-assertion-pages/{tasks.md,validation-report.md}`: RED/GREEN/build/D3 custody.
- `docs/insurance-kb/evidence/830-g1/m3/`: append-only replacement-build and D3 receipts; never rewrite the original D2 receipts.

### Task 0: Freeze the expanded exact-path Owner matrix

**Files:**
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/proposal.md`
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/validation-report.md`

- [x] **Step 1: Add only the newly required exact paths**

Add these three paths to the G1-Win2 matrix before any product-code write:

```text
internal/application/service/schema_wiki_citation_content.go
internal/application/service/schema_wiki_citation_content_test.go
frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts
```

The first two are limited to private token claims/validation; the third is a
focused parser test. Governance/evidence remains controller-only.

- [x] **Step 2: Commit the matrix amendment**

The G1 controller alone runs:

```bash
git add openspec/changes/126-830-g1-entity-field-assertion-pages/proposal.md openspec/changes/126-830-g1-entity-field-assertion-pages/validation-report.md docs/superpowers/plans/2026-09-03-g1-successor-source-bridge.md
git commit -m "docs(G1): freeze successor bridge write paths"
```

- [x] **Step 3: Obtain read-only matrix/plan approval**

Dispatch the existing plan-document reviewer against the new exact commit/tree.
Do not start Task 1 until status is `Approved` with no blocking issue.

Approved at `63b4a11ddebdfdc310bff087d90919209eef3e58` /
`07796e78dca06286a10ace32f88383de0b28db19`; blocking issues: zero.

### Task 1: Prove and implement successor page identity

**Files:**
- Modify: `internal/application/service/entity_page_graph_830_g1.go`
- Modify: `internal/application/service/entity_page_graph_830_g1_test.go`

- [ ] **Step 1: Write the failing real-successor tests**

Add tests named:

```go
func TestEntityPageGraph830G1ReadsSuccessorServingIdentityWithoutRewritingSourceMembers(t *testing.T)
func TestEntityPageGraph830G1PinnedReadSurvivesNonG1HeadMove(t *testing.T)
func TestEntityPageGraph830G1RejectsSuccessorBaseIdentityDrift(t *testing.T)
```

The fixture must materialize a Ready G1 preparation whose expected tuple is the old manifest Release/epoch, activate one distinct `release-g1-successor` through the existing repository CAS, and assert:

```go
require.Equal(t, "release-g1-successor", read.ReleaseID)
require.Equal(t, manifest.ActivationEpoch+1, read.ActivationEpoch)
require.Equal(t, manifest.ReleaseID, read.Member.ReleaseID)
require.Equal(t, manifest.ReleaseID, field.Reference.SourceReleaseID)
require.Equal(t, rawManifestBefore, rawManifestAfter)
```

After a legal non-G1 control Release moves Head, current entity read must fail with `ErrEntityPageGraphIntegrity830G1`, while exact pinned `release-g1-successor` still returns the same bytes and original activation epoch. Base Release or epoch drift must fail with the same typed integrity error and perform no fallback read.

- [ ] **Step 2: Run the tests and capture RED**

Run:

```bash
go test ./internal/application/service -run 'TestEntityPageGraph830G1(ReadsSuccessorServingIdentityWithoutRewritingSourceMembers|PinnedReadSurvivesNonG1HeadMove|RejectsSuccessorBaseIdentityDrift)$' -count=1 -v
```

Expected: FAIL because the current loader requires `manifest.ReleaseID == release.ID` and `manifest.ActivationEpoch == serving epoch`.

- [ ] **Step 3: Add explicit source identity to the internal snapshot**

Extend the private snapshot only:

```go
type EntityPageGraphReleaseSnapshot830G1 struct {
    ReleaseID            string
    ActivationEpoch      uint64
    SourceReleaseID      string
    SourceActivationEpoch uint64
    Manifest             json.RawMessage
    Members              []types.WikiReleaseMemberSnapshot
}
```

Preparation snapshots set serving and source identities to the manifest tuple. Current/pinned successor snapshots set serving identity from the successor/Head and source identity from `WikiRelease.BaseReleaseID/BaseActivationEpoch`.

- [ ] **Step 4: Implement the closed successor loader**

In `loadEntityPageGraphRelease830G1`, require all of:

```go
release.ID == requestedReleaseID
release.ID != release.BaseReleaseID
release.BaseReleaseID == manifest.ReleaseID
release.BaseActivationEpoch == manifest.ActivationEpoch
release.BaseActivationEpoch+1 == servingActivationEpoch
release.PreparationID == preparation.ID
preparation.ExpectedReleaseID == manifest.ReleaseID
preparation.ExpectedActivationEpoch == manifest.ActivationEpoch
```

For an exact pinned read, derive `servingActivationEpoch` as `release.BaseActivationEpoch + 1`; do not query Head. In `readEntityPageGraphSnapshot830G1`, return `snapshot.ReleaseID` in the envelope but never mutate `manifest`, `member`, payload, digest, or source reference.

- [ ] **Step 5: Run GREEN and compatibility tests**

Run:

```bash
go test ./internal/application/service -run 'Test(EntityPageGraph|SchemaWikiServiceLoadEntityPageGraph)' -count=1 -v
```

Expected: PASS, including preparation behavior and existing custody-drift tests.

- [ ] **Step 6: Commit**

```bash
git add internal/application/service/entity_page_graph_830_g1.go internal/application/service/entity_page_graph_830_g1_test.go
git commit -m "fix(G1): separate successor and source identities"
```

### Task 2: Prove and implement the frontend dual-identity parser

**Files:**
- Modify: `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts`
- Create: `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts`
- Modify: `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts`

- [ ] **Step 1: Write failing parser tests**

Create response fixtures with:

```ts
data.read_mode = 'current' // repeat for pinned
data.release_id = 'release-g1-successor'
data.activation_epoch = 2
data.member.release_id = 'release-815-source'
data.member.payload.reference.source_release_id = 'release-815-source'
```

Assert current and pinned parse successfully, preparation still requires all three identities to be the same, and each of these fails with `ENTITY_PAGE_GRAPH_RESPONSE_INVALID`:

- source member rewritten to successor;
- reference differs from member source;
- current/pinned serving Release equals source Release;
- preparation envelope differs from source member.

Update the component test to prove both current and pinned pages continue to send the serving successor ID to the unchanged `/releases/:release_id/.../preview` route.

- [ ] **Step 2: Run RED**

Run:

```bash
cd frontend && npm run test:unit -- --run src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts
```

Expected: FAIL at the old equality checks against `data.release_id`.

- [ ] **Step 3: Implement the mode-dependent identity predicate**

Replace the two serving/source conflations with one explicit invariant:

```ts
const sourceReleaseID = member.release_id
const sourceIdentityValid = data.read_mode === 'preparation'
  ? sourceReleaseID === data.release_id
  : sourceReleaseID !== data.release_id

if (!text(sourceReleaseID) || !sourceIdentityValid) throw new Error()
// For field payloads:
if (reference.source_release_id !== sourceReleaseID) throw new Error()
```

Do not add keys, routes, fallback, or payload transformations.

- [ ] **Step 4: Run GREEN and commit**

Run the command from Step 2 and expect PASS, then:

```bash
git add frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts
git commit -m "fix(G1): parse serving and source release identities"
```

### Task 3: Bind opaque citation tokens to serving and source identities

**Files:**
- Modify: `internal/application/service/schema_wiki.go`
- Modify: `internal/application/service/schema_wiki_citation_content.go`
- Modify: `internal/application/service/schema_wiki_citation_content_test.go`

- [ ] **Step 1: Write failing token tests**

Add tests proving:

```go
// Generic Schema token remains active and same-identity.
route.Kind == "active"
route.ReleaseID == request.ReleaseID

// G1 exact successor token is release-scoped and dual-identity.
route.Kind == "release"
route.ReleaseID == "release-g1-successor"
public.ReleaseID == "release-g1-successor"
public.ActivationEpoch == sourceEpoch+1
```

Tampering route kind, serving Release/epoch, source Release/epoch, scope, or signature must return `ErrSchemaWikiCitationUnavailable` before blob access. Existing preparation token tests must remain unchanged.

- [ ] **Step 2: Run RED**

Run:

```bash
go test ./internal/application/service -run 'TestSchemaWikiCitationContent(RouteAuthorityDerivesSignedTokenKindAndScope|BindsSuccessorServingAndSourceIdentity|RejectsIdentityClaimDrift)$' -count=1 -v
```

Expected: FAIL because token claims currently imply every standard token is `active` and expose only one Release tuple.

- [ ] **Step 3: Add private request and token binding fields**

Add only unexported request fields:

```go
citationRouteAuthorityKind   string
citationServingReleaseID    string
citationServingActivationEpoch uint64
```

Add signed private claims:

```go
RouteAuthorityKind   string `json:"route_authority_kind"`
SourceReleaseID      string `json:"source_release_id"`
SourceActivationEpoch uint64 `json:"source_activation_epoch"`
```

Add `ReleaseID string` to `SchemaWikiCitationContentRouteAuthorityV1`. A normalization helper must default existing Schema requests to `active` with serving identity equal to the request's source identity; only `active` and `release` are valid.

- [ ] **Step 4: Make public authority use serving identity**

`schemaWikiCitationPublicAuthority` must populate `ReleaseID/ActivationEpoch` from the normalized serving tuple. `IssueExactRevision`, `verify`, `ResolveRouteAuthority`, and `ReadByOpaqueToken` must validate route kind, serving tuple, source tuple, public authority, scope, and exact reconstructed request together. The token remains quote-free and the public authority schema remains unchanged.

- [ ] **Step 5: Run GREEN and all citation-content tests**

Run:

```bash
go test ./internal/application/service -run 'TestSchemaWikiCitationContent' -count=1 -v
```

Expected: PASS; generic active and preparation behavior unchanged.

- [ ] **Step 6: Commit**

```bash
git add internal/application/service/schema_wiki.go internal/application/service/schema_wiki_citation_content.go internal/application/service/schema_wiki_citation_content_test.go
git commit -m "fix(G1): seal citation serving and source identity"
```

### Task 4: Implement the successor historical-source bridge

**Files:**
- Modify: `internal/application/service/entity_page_graph_830_g1.go`
- Modify: `internal/application/service/entity_page_graph_830_g1_test.go`
- Modify: `internal/application/service/schema_wiki.go`

- [ ] **Step 1: Write failing bridge tests**

Add real-custody tests for current and pinned successor citations. They must select the full G1 citation through the route's legacy short citation ID, validate the existing 17/17 join, and assert the issued public authority uses the successor tuple while the recorded content request uses the old source tuple.

After moving Head to a non-G1 control Release:

- current G1 entity/citation request fails closed;
- exact pinned successor authority issues `Kind=release` without a Head lookup;
- content read reconstructs from the exact successor and opens the same old 815 source bytes;
- revision/page/bbox/quote/join/base identity mutations each return `ErrSchemaWikiCitationUnavailable` with zero blob fallback.

- [ ] **Step 2: Run RED**

Run:

```bash
go test ./internal/application/service -run 'TestEntityPageGraph830G1(CurrentSuccessorCitationUsesHistoricalSource|PinnedCitationSurvivesNonG1HeadMove|CitationBridgeRejectsCustodyDrift)$' -count=1 -v
```

Expected: FAIL because only preparation citations currently traverse the G1 bridge and they require the old source to remain current.

- [ ] **Step 3: Extract one request constructor**

Implement a private helper in `entity_page_graph_830_g1.go` that:

1. loads and validates the route-selected successor with `loadEntityPageGraphRelease830G1`;
2. selects the field and exact full G1 citation by matching its 64-hex join to the legacy route ID;
3. creates a private `WikiReleasePinnedRead` for `BaseReleaseID/BaseActivationEpoch`;
4. replays `loadPinnedSchemaRelease` and `entityPageGraphManifestMatchesSchemaSource830G1`;
5. runs `entityPageGraphCitationMatchesSchemaSource830G1` against the exact join;
6. calls `schemaWikiCitationRequest` with the old source tuple;
7. binds C6 frozen native source when applicable;
8. annotates the request with the successor serving tuple and `active` or `release` route kind.

The helper accepts no caller-supplied source identity.

- [ ] **Step 4: Preserve generic Schema and add G1 dispatch**

In `IssueCurrentSchemaCitationAuthority`, keep the existing generic path when `release_id` is current and full Schema custody validates. If it is a G1 successor, use the helper; current successor gets `active`, historical exact successor gets `release`. Do not permit historical generic Schema preview as a side effect.

In `ReadSchemaCitationContent`, resolve both public and route authority. For `active`, pin current Head and require the token's serving tuple to match; for `release`, load the exact G1 successor without Head. Reconstruct the same old-source request and pass it to `ReadByOpaqueToken` so all signed identities are compared again before bytes open.

- [ ] **Step 5: Run GREEN and regression packages**

Run:

```bash
go test ./internal/application/service -run 'Test(EntityPageGraph830G1|SchemaWikiCitationContent|SchemaWiki.*Citation)' -count=1 -v
go test ./internal/application/service -count=1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/application/service/entity_page_graph_830_g1.go internal/application/service/entity_page_graph_830_g1_test.go internal/application/service/schema_wiki.go
git commit -m "fix(G1): bridge successor citations to historical source"
```

### Task 5: Admit exact-release tokens through the existing dual-ACL route

**Files:**
- Modify: `internal/handler/schema_wiki.go`
- Modify: `internal/handler/schema_wiki_test.go`
- Modify: `internal/router/routes_schema_wiki_test.go`

- [ ] **Step 1: Write failing middleware tests**

Add one `release` route-authority case whose signed scope matches the path. Assert it reaches the downstream RAW ACL without calling `GetHeadForWikiKB`. Add foreign scope, empty Release ID, and unknown kind cases that abort with 403 and leak no identity.

- [ ] **Step 2: Run RED**

Run:

```bash
go test ./internal/handler ./internal/router -run 'Test.*Citation.*(Release|Scope|Order)' -count=1 -v
```

Expected: FAIL because `RequireCitationContentScope` accepts only `active` and `preparation`.

- [ ] **Step 3: Add the exact-release branch**

For `authority.Kind == "release"`, require non-empty canonical `authority.ReleaseID` and the already-verified signed scope/path equality. Do not query or set Head. The service performs immutable successor custody validation before bytes open. Keep active and preparation branches byte-for-byte equivalent.

- [ ] **Step 4: Run GREEN and commit**

Run the command from Step 2 plus `go test ./internal/handler ./internal/router -count=1`; expect PASS, then:

```bash
git add internal/handler/schema_wiki.go internal/handler/schema_wiki_test.go internal/router/routes_schema_wiki_test.go
git commit -m "fix(G1): authorize exact release citation tokens"
```

### Task 6: Run full source verification and freeze the build commit

**Files:**
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/tasks.md`
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/validation-report.md`
- Create: `docs/insurance-kb/evidence/830-g1/m3/replacement-source-verification.json`

- [ ] **Step 1: Run formatting and focused suites**

```bash
gofmt -w internal/application/service/entity_page_graph_830_g1.go internal/application/service/entity_page_graph_830_g1_test.go internal/application/service/schema_wiki.go internal/application/service/schema_wiki_citation_content.go internal/application/service/schema_wiki_citation_content_test.go internal/handler/schema_wiki.go internal/handler/schema_wiki_test.go internal/router/routes_schema_wiki_test.go
go test ./internal/application/service ./internal/handler ./internal/router -count=1
cd frontend && npm run test:unit -- --run src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts src/api/schema-wiki/entityPageGraph830G1.spec.ts
```

Expected: PASS.

- [ ] **Step 2: Run the frozen Harness and applicable broad checks**

Use the existing repository commands recorded by the original G1 plan for Harness contract/vector tests, frontend type checking, and the full affected Go packages. No Docker yet. Every command, exit code, commit, tree, manifest hash, and clean/dirty state goes into the new append-only receipt.

- [ ] **Step 3: Update OpenSpec from RED to source GREEN**

Record actual commands and results only. Keep D3, production evidence, and business `G1=PASS` as NOT RUN. Change `NEXT_PHYSICAL_RESULT` to `FREEZE_REPLACEMENT_BUILD_INPUTS` only after all source checks pass.

- [ ] **Step 4: Commit and obtain read-only code review**

```bash
git add internal frontend/src openspec/changes/126-830-g1-entity-field-assertion-pages docs/insurance-kb/evidence/830-g1/m3/replacement-source-verification.json
git commit -m "test(G1): freeze successor source bridge verification"
```

Dispatch the mandatory independent read-only review against the exact commit/tree. Fix findings with TDD and repeat verification; do not build until `UNRESOLVED_COUNT=0`.

### Task 7: Consume the two replacement build budgets exactly once

**Files:**
- Create: `docs/insurance-kb/evidence/830-g1/m3/d2-replacement-image-build.json`
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/{tasks.md,validation-report.md}`

- [ ] **Step 1: Freeze inputs before invoking Docker**

Record literal final source commit/tree; SHA-256 of `go.mod`, `go.sum`,
`frontend/package-lock.json`, both Dockerfiles, `.dockerignore` files, the app
source subset, and frontend source subset. Confirm replacement counters are app
`0` and frontend `0`. Do not hash or admit the stale D2 `frontend/dist`.

- [ ] **Step 2: Build the app once**

Use `docker build --platform linux/arm64 -f docker/Dockerfile.app` with a unique immutable tag containing the literal final commit. Apply OCI revision plus frozen tree/source-subset/lock labels. Network/package retrieval is allowed only for the build; it must not touch production containers.

- [ ] **Step 3: Build frontend dist and image once**

Run the repository's pinned frontend dist build exactly once. Immediately after
it succeeds, freeze the completed dist's hash, file count and size; verify the
source/lock/Docker inputs still equal Step 1; then invoke exactly one
`docker build --platform linux/arm64 -f frontend/Dockerfile` with a unique
immutable tag and matching labels. Do not rebuild dist or image on failure;
record the actual result and stop G1 if either single budget is consumed
without an admissible image.

- [ ] **Step 4: Verify exact image identities**

Use `docker image inspect` to record image ID, repo digest, platform, created time, size, labels, and base digests. Set both replacement counters to `1` and `NEXT_PHYSICAL_RESULT=START_ISOLATED_D3_WITH_REPLACEMENT_IMAGE_IDS`. Commit only the new receipt and OpenSpec state; never edit `d2-image-build.json` or `d2-app-build-reconciliation.json`.

### Task 8: Execute isolated D3 and close G1

**Files:**
- Create: `docs/insurance-kb/evidence/830-g1/m3/d3-isolated-release.json`
- Modify: `openspec/changes/126-830-g1-entity-field-assertion-pages/{tasks.md,validation-report.md}`
- Modify/Create only the existing G1 closeout index files under `docs/insurance-kb/evidence/830-g1/`

- [ ] **Step 1: Reconfirm isolation and production before-state**

Run D3 only on the isolated clone/network with no egress and the two exact replacement image IDs. Record production container IDs/image IDs/Head counts read-only before D3. Do not restart, replace, or write production.

- [ ] **Step 2: Execute one real lifecycle**

Create G1 Draft from the frozen manifest, review to Ready, activate through the existing CAS, and record exactly one new successor Release, 76 members, one Head transition, and one receipt. Mark it `NOT_FOR_PRODUCTION` in evidence.

- [ ] **Step 3: Verify live current, pinned, and source behavior**

Assert all 76 pages use the successor serving envelope and immutable old-source members, current and exact pinned reads do not mix, all three known field source clicks return exact old-source bytes, and tampered/missing source cases fail closed. Move an isolated control Head only in the dedicated regression environment to prove pinned R1 survives while current G1 fails.

- [ ] **Step 4: Prove negative effects remain zero**

Record zero egress, Provider/model calls, second publisher/Head, G2 actions, and production writes/restarts/replacements. Re-read production identities and counts and compare to before-state.

- [ ] **Step 5: Final verification and independent acceptance**

Run focused tests, applicable CI, `git diff --check`, and `git status --short`. Commit the append-only D3/closeout evidence, then dispatch `830-G1-Review｜独立只读验收` against the exact final commit/tree/images/release/evidence. Only `UNRESOLVED_COUNT=0` may change the report to `G1=PASS`; otherwise G1 remains FAIL/STOPPED. Report G2 readiness only and do not start G2.
