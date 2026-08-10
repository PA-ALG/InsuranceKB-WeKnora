# 120 · Validation Report

Status: `INTEGRATION-CODE-GREEN / LIVE-NO-GO`

## Identity and scope

- Coordination base: `db6fd60bbf9cf4529db43ded24934c7bbdd422f9`
- Plan commit: `db0e52320e461a13863d8c803cd80d255c25b815`
- OpenSpec Task 0 commit: `a865c1066c15d7bb67ace3ed261d0ee0875663c7`
- Lane A A1 payload/sorting authority: commits
  `d014dcd24ab882b7514554b37f46d958cbad18b3` and
  `585cb9dd6f369ca57825e4d63ab35805fb5b6f32`.
- Integration branch: `codex/schema-wiki-mvp-integration`
- Integration code identity before this documentation-only closeout:
  commit `3da54ff80b6106dea6e2b27ca105f3c5238a1864`, tree
  `c8fcc503bd4f1047bd105a95515646dcf2eb4f8a`.
- Scope: A1 contracts, Lane B medical pack/compiler and immutable vector, A2 existing-row
  lifecycle/read facade, and Lane C release-pinned UI. This report and checklist are
  mechanically synchronized without changing production bytes.
- Provider/model, Golden scoring, DB, WeKnora, migration, activation and live:
  `NOT RUN`.

## RED evidence

Before these files existed, strict validation was run as:

`openspec validate 120-schema-wiki-medical-596-1-mvp --strict`

It exited `1` with `Unknown item '120-schema-wiki-medical-596-1-mvp'`. Subsequent telemetry
DNS noise did not alter that load-bearing missing-change RED.

## GREEN gates

- Strict OpenSpec: `PASS` (`Change '120-schema-wiki-medical-596-1-mvp' is valid`).
- `git diff --check`: `PASS`.
- A1 corrective delta: Python control/C0/vector gates `36 PASS`; Go control/unknown/
  typed-roundtrip/vector gates `PASS`.
- Lane B payload-corrective candidate tree:
  `a168f35058cf10c0dfd00b57fd3a6c395eb6ade3`; exact three changed paths, real index empty.
- Lane B bounded pytest (`medical pack`, `release compiler`, existing Candidate report):
  `62 PASS`.
- Lane A representative payload/citation contract: Python `98 PASS`; Go Schema Wiki
  `PASS`.
- Lane B Ruff: `PASS`.
- Lane B strict mypy over two production modules and two focused tests: `PASS`.
- Immutable payload-bearing 75-member/111-citation release vector: `216,482` bytes;
  SHA-256 `d1de4362342584374c693776f07f3916edd3879a5dcf562252fdfed063ce22db`.
- Task 0 exact five-path scope and README status: `PASS`.
- Integrated repository evidence before the reachability delta: Python Schema
  contracts/compiler/release/report `160 PASS`; bounded Go types/repository/service/
  handler/router/container `PASS`; frontend pure contracts/navigation/current/session
  `30 PASS`; citation viewer `8 PASS`; global frontend typecheck/build, Ruff, strict mypy,
  Go vet, strict OpenSpec, diff and privacy gates `PASS`.
- UI reachability successor commit
  `21ece179e2cfb620975bcd5379fd941923baac41` changes exactly five approved paths.
  Its load-bearing gates are reachability/current-pin `2 PASS`, Schema contracts/
  navigation/citation `24 PASS`, citation viewer `8 PASS`, global typecheck/build and
  diff/privacy `PASS`.
- Backend mount delta: `NOT REQUIRED`. The real `NewRouter` dependency path in
  `internal/router/router.go` directly registers all 13 Schema Wiki routes; the exact
  route test passes. `internal/router/routes_knowledge.go` is intentionally unchanged to
  avoid duplicate registration and retrieve-policy drift.
- `frontend/src/components/schema-wiki/pdfJsPort.ts` and the six exact frontend hygiene
  paths listed in the owner matrix are integration support only. They do not replace an
  approved Schema Wiki path or claim release/citation authority.

## A2 owner and state-machine amendment

- Lane A is explicitly authorized to modify the existing
  `internal/types/wiki_release.go`, `internal/application/repository/wiki_release.go` and
  `internal/application/service/wiki_release.go` alongside its already listed A2 paths.
- The authorization is limited to the existing `wiki_release_preparations` row lifecycle:
  persisted Draft -> concrete named-human `ReviewDraft` -> Ready -> separate publish
  authorization -> existing `ActivateReviewed` CAS.
- The Schema entry must validate the exact Lane B release plus review bundle and persist
  the actual canonical typed member payloads. It must not accept a caller-built generic
  preparation.
- The existing preparation `Manifest` column is the no-migration custody boundary for
  strict canonical `schema-wiki-preparation-custody.v1` bytes containing the complete B
  release and exact review bundle. Its storage `ManifestDigest` is independent from the
  inner B `release.ManifestDigest`; tests must recompute both and reject substitution.
- Because preparation manifest/member storage is PostgreSQL JSONB, Create must hash the
  canonical concrete DTO bytes before write, while Read must strict closed-decode, reject
  unknown fields/trailing JSON, canonical re-marshal and recompute the digest before the
  snapshot join. JSONB-equivalent key order/whitespace is accepted; raw DB text is never
  authority, and value/type/self-hash drift fails closed. CAS preserves the logical JSONB
  values and compares the existing authority columns/digests; no migration is introduced.
- All 75 snapshots must equal the custody envelope's ordered release members byte-for-byte
  and digest-for-digest. Draft/Ready/Active reads follow `PreparationID`, replay the full
  envelope and scope, and derive citation authority only from stored logical slug plus
  citation ID. Foreign citation `SpaceID` fails before output.
- Draft remains non-serving; review preview is exact `preparation_id`/member revision only.
  Reject, partial, expired or invalid review leaves the Draft unchanged. CAS failure leaves
  the previous Active Head and pins unchanged.
- ReviewDraft transition CAS is bound to exact scope, `preparation_id`, Draft status and
  the old `PreparationDigest` plus Candidate, review-bundle, policy and custody-envelope
  manifest authority columns; concurrent drift is a typed conflict with no state change.
- ReviewDraft must replay the full custody envelope and ordered 75-snapshot bijection before
  named-human verification or transition; corrupted Draft custody never becomes Ready.
- Draft creation, exact Draft preview and ReviewDraft are now explicitly constrained to
  human JWT Admin+ with route order `DenyAPIKeyPrincipal -> g.Admin -> Wiki ACL/evidence ->
  scope resolution -> RAW ACL/evidence -> SealAccess -> handler`. The service must repeat
  API-key denial and trusted-context Admin+ authorization before any repository row lookup,
  verifier or preview-port access even when RBAC is disabled, so Draft preview cannot leak
  row existence. Active Viewer+/scoped API-key reads are
  unchanged.
- Lane C API identity is frozen to the closed five-field `SchemaWikiScopeV1` bootstrap and
  the single scoped base containing exact domains, taxonomy/current,
  entity-version/current, release root/section/field, preparation root/section/field and
  release field/citation preview reads. A second `/drafts` read namespace or body-supplied
  scope is not accepted.
- The current entity-version endpoint returns only the closed
  `schema-wiki-current-entity-version.v1` payload with exact entity/version,
  `active_release_id`, `activation_epoch` and typed root. That release/epoch pair is the
  sole trusted pin for release reads. Scope contains no release ID; entity/version/release/
  epoch drift and guessed current/latest fallback must fail before content output.
- Active scope comes only from the sole Head; preparation review/preview scope comes only
  from the immutable preparation. Initial none/e0 CreateDraft is the sole exception: the
  exact path scope may bootstrap the first row only after human JWT Admin+, Wiki then RAW
  ACL/evidence, seal, no-conflicting-space and complete-custody checks. Once Head exists,
  path scope must match it exactly. This is not caller self-authorization.
- No new table, migration, Head, CAS or approval model is authorized. A2 repository code
  and provider-free tests are GREEN and frozen; this does not claim live serving or
  deployment acceptance.

## Live NO-GO boundary

- No successful sealed production `Schema67CandidateV2` is available for publication.
- The production Evidence-to-WeKnora exact revision/page/bbox authority join and concrete
  preview adapter are not frozen; the UI therefore reports typed unavailable and never
  falls back to current/latest bytes or page 1.
- Live `wiki_release_*` deployment/migration custody was not established in this Mission;
  no Draft, named-human review, publish authorization or activation was executed.
- Provider/model, Golden scoring, DB/WeKnora writes, migration, deployment and activation
  remain `NOT RUN`. Existing 46 generic material Wiki pages are not migrated or converted.

Lane B fixture acceptance uses a real public-factory-sealed Candidate and a synthetic trusted
citation-authority port. It does not claim that a real Candidate, the production exact-revision
join, preparation, activation, release tables, deployment or the end-to-end MVP exists.
