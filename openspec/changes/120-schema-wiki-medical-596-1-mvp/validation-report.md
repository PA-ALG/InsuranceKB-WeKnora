# 120 · Validation Report

Status: `MERGED-CODE-GREEN / DELIVERY-BLOCKED / LIVE-NOT-RUN`

## Identity and scope

- Merged authority: `main@bee91696131efa3a3aa5ea1339557eaa68e63f0a`
  (PR #121); merged main CI: `PASS`.
- Packaged migration heads: official `75`, enterprise `5`; migration-tree evidence
  `e8446dff`; route-manifest evidence `ffa548b9`.

- Coordination base: `db6fd60bbf9cf4529db43ded24934c7bbdd422f9`
- Plan commit: `db0e52320e461a13863d8c803cd80d255c25b815`
- OpenSpec Task 0 commit: `a865c1066c15d7bb67ace3ed261d0ee0875663c7`
- Lane A A1 payload/sorting authority: commits
  `d014dcd24ab882b7514554b37f46d958cbad18b3` and
  `585cb9dd6f369ca57825e4d63ab35805fb5b6f32`.
- Integration branch: `codex/schema-wiki-mvp-integration`
- Final3 integration identity before the production-readiness delta: commit
  `0f6a958a203d6813bee057c7d87eb2ad9bc86a49`, tree
  `2aa839523e559d2612b9433cdcb3901828f0fd53`.
- Reviewed production-readiness source: tree
  `db07de2e737a209a1cc8edf59c63914260bc810a`, exact eight paths, frozen index SHA-256
  `8da2663f054891265b58962e1dde0eb2ed8b95759018d217aaa3b3f10d778a63`.
- Immutable-citation integration sources: commits
  `82e3b1b1c3aa80962b11b981019a60dfc1b462b1`,
  `6e5502bfb844753d3f709f1491e881180ec60907`,
  `8d6fdb89996fb458c093f87e809b0c777d9e7290`,
  `881edffadff5edf1c6b3ac01773880b4e09ced47` and
  `bbe67a1e1c65ef2706da3e7fa5a60e97437601ae`, applied in that order.
- Scope: A1 contracts, Lane B medical pack/compiler and immutable vector, A2 existing-row
  lifecycle/read facade, and Lane C release-pinned UI. This report and checklist are
  mechanically synchronized without changing production bytes.
- Provider/model, real Candidate, Golden scoring, DB/WeKnora migration/backfill, clone
  rehearsal, Draft, review, publish, activation and live: `NOT RUN`.

## RED evidence

Before these files existed, strict validation was run as:

`openspec validate 120-schema-wiki-medical-596-1-mvp --strict`

It exited `1` with `Unknown item '120-schema-wiki-medical-596-1-mvp'`. Subsequent telemetry
DNS noise did not alter that load-bearing missing-change RED.

## GREEN gates

- Strict OpenSpec: `PASS` (`Change '120-schema-wiki-medical-596-1-mvp' is valid`).
- Merged `bee91696` GitHub CI: `PASS`.
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
- Production-readiness delta gates: focused application-service citation tests `PASS`;
  focused config signer/redaction tests `PASS`; focused container verifier/DI tests `PASS`;
  bounded Go vet over service/config/container `PASS`; strict OpenSpec, diff-check,
  exact owner/support `56/56`, frozen exact8 blob replay and privacy scans `PASS`.
- Immutable-citation source checkpoints independently reported focused provider-free GO;
  their complete-stack verification is recorded only after the single integration matrix
  is run. Release vector SHA-256 is
  `6783e3312199378a51065872278961f10c0e0f6510648e2ff1ce18823f10e6be`.
- Migration packaging: official head `75`, enterprise head `5`; `000004` creates the
  attempt-bound source row and `000005` closes resource/object/manifest/binding custody.
- Pinned-source destructive guards: direct/batch reparse, move-reparse and single/batch
  delete reject before mutation; previous source/chunk/manifest custody is retained.

## Production-readiness delta

- Lane A now injects a non-nil native citation replay adapter. It validates server-derived
  tenant/scope plus exact knowledge, source revision/parse attempt, file/document identity,
  chunk membership and the recomputed revision manifest. It never opens current/latest or
  presigned bytes and never substitutes page 1.
- The adapter deliberately returns typed unavailable and zero bytes after native replay.
  WeKnora still supplies no immutable attempt-bound blob or canonical coordinate-space/
  page/bbox authority, so this delta is not real citation-preview acceptance.
- Deployment configuration now supplies distinct public Ed25519 key rings to the existing
  named-human and publish-authorization verifiers. Empty and malformed configurations fail
  closed; duplicate key IDs or key bytes across the rings are rejected.
- No private-key configuration field exists. The signing configuration and public-key bytes
  are excluded from JSON serialization, preventing response/log serialization through the
  application config object.
- The production-readiness owner amendment adds five paths to the previous closed 51-path
  integration set: the native adapter and test, config and signing test, and container
  production-readiness test. The resulting closed owner/support union is 56 paths.

## Immutable citation and Candidate-companion delta

- `LiveRevisionSourceReceiptV1` and the narrow source migration bind exact knowledge,
  attempt, resource, file SHA/size/page count, document and manifest identities; deletion
  cannot silently detach a serving revision.
- Lane B keeps CandidateV2 wire unchanged and adds a factory-provenance-sealed companion
  containing all Evidence-to-live-source/chunk/page/bbox receipts. MinerU top-left
  `0..1000` coordinates normalize deterministically to `normalized_0_1e6`; copied,
  reparsed, mutated or self-rehashed companions fail closed.
- A third Ed25519 ring signs only five-minute citation tokens and cannot reuse either
  named-human or publish-authorization key IDs/material. The public authority contains no
  source text or private key. The bytes route accepts only the opaque token and replays
  exact source size/SHA before returning bytes.
- Lane C requests authority with exact Active release/epoch/field/citation only, verifies
  returned bytes by SHA-256 before PDF open, renders terms page 12 and brochure page 27,
  and rejects rate page 12/27 before token/bytes/PDF access. Current/latest/presigned/
  material/page-1 fallback remains absent.
- The closed owner/support union is now 74 paths. These are code and provider-free fixture
  facts, not a record of live model, DB, preparation or activation execution.

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
- Exact3 dry-run reads all three database authorities and existing source rows in one
  `REPEATABLE READ READ ONLY` snapshot, returns only redacted source/result/snapshot
  digests and `WOULD_INSERT|NOOP|CONFLICT_STOP` counts, and always reports `writes=0`.
  `NOOP` is a full sealed-row equality check. Actual remains ordered serial execution:
  a later failure preserves an earlier pin and skips later seals; it is not a three-row
  atomic transaction.
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

- Immutable image/SBOM/OCI proof for `bee91696`: `BLOCKED / NOT RUN`.
- Three deployment public-key ID rings: `BLOCKED / UNCONFIGURED`.
- Colima is stopped; therefore live current state is `UNKNOWN / NOT RUN`, not an
  application failure.

- No successful sealed production `Schema67CandidateV2` is available for publication.
- The previous official DeepSeek exact8 run ended in a typed failure and produced no
  Candidate. No new real model run has been executed with the immutable-citation Candidate
  companion identity, so the new code and fixtures cannot be used as a publication input.
- Immutable attempt-bound source custody, canonical coordinate-space/page/bbox receipts,
  token-only bytes and UI verification are implemented, but their migrations and live
  source rows have not been deployed/replayed in this Mission. No live citation byte was
  requested or rendered.
- Live `wiki_release_*` deployment/migration custody was not established in this Mission;
  no Draft, named-human review, publish authorization or activation was executed.
- Provider/model, Golden scoring, DB/WeKnora writes, migration, deployment and activation
  remain `NOT RUN`. Existing 46 generic material Wiki pages are not migrated or converted.

Lane B fixture acceptance uses a public-factory-sealed synthetic Candidate and the exact
companion/source receipt contracts. It does not claim that a new real Candidate, deployed
revision rows, preparation, activation, live release tables or the end-to-end MVP exists.

## Requirement-to-evidence matrix

| Requirement | Implementation | Representative test | Commit | Status |
|---|---|---|---|---|
| SWM1–SWM3 | Python/Go contracts, medical pack, sealed compiler and tri-state pages | `test_compile_requires_concrete_freshly_replayed_schema67_candidate`, `test_unknown_field_page_has_no_value_receipt_or_citation`, `TestSchemaFieldUnknownReasonTriStateAndFullyRehashedDrift` | `2cbe7991`, `a97c63a0` | PASS |
| SWM4–SWM6 | full typed 75-member/111-citation release, Evidence companion and canonical preparation custody | `test_factory_provenance_is_not_stored_as_private_model_state`, `TestSchemaWikiDraftPersistsExactMembersWithoutServingOrActivationState` | `bbe67a1e`, `5d4e7e01` | PASS |
| SWM7–SWM8 | existing Draft→Ready→Activate authority, no-Head preparation scope/token, Active Head/pin and dual ACL routes | `TestSchemaWikiReviewDraftVerifiesBeforeAtomicDraftToReady`, `TestSchemaWikiRoutesDeclareExactScopedPrefixAndRetrievePolicy`, `TestSchemaWikiCitationContentNoHeadStillReachesSealedDualACLHandler` | `5d4e7e01` | PASS |
| SWM9 | `000004`/`000005` immutable source/binding, token-only bytes, page bounds and pinned reparse/move/delete guards | `TestImmutablePDFPageCounterAcceptsExact5961EncryptedMaterials`, `TestPinnedRevisionSourceBlocksDirectReparseBeforeAnyMutation`, `TestMoveReparseRejectsPinnedRevisionSourceBeforeMutation`, `TestKnowledgeDeletePathsAtomicallyRejectPinnedRevisionSources` | `fac63173`, `0791abf1` | PASS |
| SWM9A | one RR/RO exact3 snapshot; `WOULD_INSERT/NOOP/CONFLICT_STOP`; actual serial partial-stop | `TestExact3AuthorityReadsAllRowsInsideOneReadOnlySnapshot`, `TestExact3DryRunClassifiesExactExistingRowsAndStopsOnConflict`, `TestExact3BackfillPreflightsAllSourcesBeforeStrictSerialSeal` | `4b7795fa` | PASS |
| SWM10 | merged code/CI identity and explicit external STOP gates | this report; PR #121 CI | `bee91696` | BLOCKED |
| SWM11 | closed owner/integration plan and docs-only reconciliation | exact-path/diff/docs-only checks | this docs commit | PASS |

`BLOCKED` in SWM10 means the immutable image/SBOM/OCI proof and key rings are absent.
Migration/backfill/provider/Candidate/Draft/review/publish/activation/live remain `NOT RUN`.
