# Schema67 Golden Quality Gate Specification

## ADDED Requirements

### Requirement: SGQ1 exact ordered 67-field Golden custody

The system SHALL accept only a closed canonical `Schema67GoldenSet5961V1` bound to product
version `596-1`, the exact `medical-schema67.v1` identity/hash, the exact three committed
source revisions and exactly 67 field records in the frozen SchemaPack order documented in
the approved implementation plan. Missing, extra, duplicate, reordered, unknown or
trailing fields and any self-hash drift SHALL fail closed.

Each field SHALL bind its state, per-field value schema and normalization rule, canonical
and accepted values, source document/revision authority, page, locator, quote/content
hashes, optional bbox/coordinate authority, risk level and named-human decision custody.
`present` and `absent_explicitly` SHALL have nonblank canonical values and Evidence;
`unknown` SHALL have null value and no Evidence.

#### Scenario: Golden field topology drifts

- **WHEN** any one of the 67 field IDs is missing, duplicated, added or reordered, even if
  the outer Golden hash is recomputed
- **THEN** Golden validation fails before Candidate evaluation

#### Scenario: missing page or optional bbox

- **WHEN** required Evidence has no exact page
- **THEN** Golden validation fails and page 1 is not substituted
- **WHEN** bbox is legitimately unavailable and declared `not_evaluable`
- **THEN** it is excluded only from bbox denominators and remains explicitly unavailable;
  no synthetic/full-page bbox is produced

### Requirement: SGQ2 Golden truth is independently human-owned

The system SHALL treat the exact latest 71-row source as an already-human-reviewed
migration source and preserve its annotator-model provenance separately from the human-review layer and
SHALL NOT describe it as zero human annotation or require a from-scratch 67-field review.
Mechanical one-to-one mappings MAY enter the Schema67 successor as reviewed; only actual
conflict, split/merge or missing targets remain pending. The user-attested reviewer
identity SHALL be exactly `linyao` and SHALL remain distinct from annotator model
`claude-fable-5` and confirming attestor `workspace-owner-houjing`. Missing `reviewed_at`,
approval receipt or signature SHALL remain explicit missing authority and SHALL NOT be
fabricated from the annotator model or the review-completion assertion.

The successor SHALL encode three non-substitutable statuses:
`source_review_status=COMPLETED`,
`schema67_mapping_status=COMPLETE_67`, and
`golden_admission_status=BLOCKED_RECEIPT_UNVERIFIED`. The source Review
status SHALL NOT be downgraded because mapping or admission remains incomplete, and the
mapping status SHALL NOT be treated as a Golden admission.

All 67 fields SHALL receive two independent named-human decisions. Disagreements SHALL
produce a conflict and require named adjudication. A whole-batch Golden receipt SHALL bind
the exact source receipts, ordered field decisions, normalization/risk/metric policies and
Golden hash. A correction SHALL create a new Golden version/hash.

Evaluation SHALL additionally require two distinct, unexpired, domain-separated signatures
from a deployment-owned named-human approval key ring. Each approval SHALL bind the exact
Golden bytes/version, ordered67 digest, SchemaPack/entity/product scope, source-revision
authority digest and all normalization/risk/metric policies. A caller-selected key ring,
self-signature, duplicate principal/key, duplicate public-key material under different IDs
or unconfigured verifier SHALL fail before scoring. The public evaluation boundary SHALL be
a sealed evaluator authority composed once from deployment-owned public-key configuration
and an external evaluator signing credential source; no per-evaluation verifier, key ring or
signer argument is permitted. Missing production composition SHALL block evaluation.

The evaluated model SHALL NOT create, replace or adjudicate its own Golden. Model-assisted
suggestions, if any, SHALL remain non-authoritative until replaced by independent human
decisions.

#### Scenario: model output is presented as Golden

- **WHEN** an evaluated Candidate/model output is used as a field decision or adjudication
  authority
- **THEN** Golden freeze fails regardless of self-consistent hashes

#### Scenario: one reviewer or unresolved conflict

- **WHEN** any field lacks two named decisions or any disagreement lacks named adjudication
- **THEN** the Golden remains pending and cannot evaluate a release Candidate

#### Scenario: reviewed source lacks cryptographic metadata

- **WHEN** the reviewed source is present but its reviewer identity, review timestamp,
  whole-batch receipt or required signatures are absent
- **THEN** the reviewed data remains valid migration input, but formal Golden evaluation
  and Draft creation remain blocked; the system does not relabel all fields as unreviewed

### Requirement: SGQ3 metrics have fixed definitions and denominators

The evaluator SHALL emit the following metric IDs with exact numerator, denominator,
Candidate hash, Golden hash, evaluator identity/version and admission status:

- `sgq.state.micro_accuracy.v1`: correct states / 67;
- `sgq.state.macro_recall.v1`: unweighted recall across each nonempty Golden state class,
  while any empty class is explicitly `NOT_EVALUABLE`;
- `sgq.value.present.micro_precision.v1`,
  `sgq.value.present.micro_recall.v1` and `sgq.value.present.macro_f1.v1`, using each
  field's frozen normalized atom semantics;
- `sgq.state.absent_to_unknown.v1` and `sgq.state.unknown_to_absent.v1`;
- `sgq.value.wrong_fill_rate.v1` and `sgq.value.hallucinated_fill_rate.v1`;
- `sgq.evidence.document_revision_page_precision.v1` and
  `sgq.evidence.field_support_recall.v1`;
- `sgq.evidence.bbox_iou.v1` and `sgq.evidence.highlight_accuracy.v1`;
- `sgq.human.high_risk_pass.v1` and `sgq.human.conflict_resolution_pass.v1`.

Micro metrics SHALL aggregate exact atoms/fragments. Macro metrics SHALL weight fields
equally. Binomial metrics SHALL report Wilson 95% intervals. Every metric SHALL report
support; support below 20 SHALL be marked `SMALL_SAMPLE`. A single-product result SHALL
authorize only `596-1` and SHALL NOT be generalized into model-wide quality.

For Golden-present fields, present precision SHALL be `TP/(TP+FP)` and recall SHALL be
`TP/(TP+FN)` over the frozen normalized atoms; macro F1 SHALL average each present field's
atom F1. Predicted present values on Golden absent/unknown fields SHALL be counted only in
the separately named hallucination metric. Bbox IoU SHALL report the actual per-fragment
IoU values and their `sum/(fragment_count × 1,000,000)` aggregate; the threshold pass count
SHALL remain only in the separately named highlight metric.

#### Scenario: denominator is absent or hidden

- **WHEN** a score omits its numerator, denominator, class support or evaluability state
- **THEN** the metric and whole quality receipt fail closed

#### Scenario: provider-zero fixture is scored as model quality

- **WHEN** the synthetic `45/1/21` fixture is submitted as a real Candidate measurement
- **THEN** the evaluator returns `FIXTURE_ONLY` and cannot issue a PASS receipt

### Requirement: SGQ4 release thresholds are deterministic STOP gates

The 596-1 quality gate SHALL require:

- exact custody 100%; state accuracy at least 65/67 and all critical/high states exact;
- per-class state recall at least 0.95 and zero absent↔unknown confusion;
- present-value micro precision and recall each at least 0.95, macro F1 at least 0.90,
  and critical/high values exact;
- hallucinated fills zero, wrong-fill rate at most 0.02 and zero critical/high wrong fills;
- Evidence document/revision/page precision and field-support recall each 1.00;
- every bbox-required fragment IoU at least 0.80, critical/high IoU at least 0.90, and
  highlight accuracy 1.00;
- high-risk and conflict human pass rates each 1.00.

Any required `NOT_EVALUABLE`, stale identity, missing custody, unresolved conflict or
threshold failure SHALL return `SCHEMA67_GOLDEN_QUALITY_GATE_FAILED`. No reviewer override
may convert FAIL/PENDING to PASS.

#### Scenario: aggregate score hides a critical error

- **WHEN** aggregate thresholds pass but any critical/high state, value, Evidence or human
  decision check fails
- **THEN** the whole gate fails

#### Scenario: citation page or bbox is guessed

- **WHEN** evaluation would require page 1, current/latest revision or a synthetic bbox
  fallback
- **THEN** the gate fails before review or Draft creation

### Requirement: SGQ5 the quality receipt is Candidate-bound and pre-Draft

The `Schema67GoldenQualityGateReceiptV1` SHALL bind the concrete Candidate hash,
Evidence-companion hash, Golden version/hash, ordered 67 field-decision hashes, evaluator
hash, metric-policy hash, all metric numerators/denominators and final PASS status.
The receipt SHALL also bind the two Golden-approval hashes and carry a domain-separated
signature/key ID over its full canonical content. Its self-hash is integrity-only. The Go
Draft boundary SHALL verify that signature against a deployment-owned public-key ring
injected by the production container before repository access; missing/unknown/foreign
signatures or a nil key ring fail closed. Public configuration carries identities and public
keys only; evaluator private signing bytes remain behind the credential-source boundary.

Evaluation SHALL occur after Candidate creation and before the review dossier and
`CreateSchemaDraft`. Only a PASS receipt may be bound into the Schema Wiki review bundle.
The existing named-human `ReviewDraft`, independent publish authorization and sole Active
Head activation SHALL remain mandatory and separate.

#### Scenario: semantic gate fails

- **WHEN** quality status is FAIL, PENDING, stale or missing
- **THEN** review-dossier, Draft, review and activation calls are all zero

#### Scenario: quality receipt is replayed for another Candidate

- **WHEN** any Candidate, Evidence companion, Golden, policy or evaluator identity differs
  even after outer hashes are recomputed
- **THEN** the receipt is rejected before Draft creation

### Requirement: SGQ6 current quality status remains truthful

The previous official exact8 failure SHALL remain immutable history and SHALL NOT be
rerun under its old identity. Candidate remains absent. No provider-zero fixture, historical
Golden score, generic Wiki page or synthetic release vector SHALL be represented as the
new official DeepSeek quality result.

#### Scenario: old exact8 result is reused

- **WHEN** the failed old execution or its absent Candidate is offered as the new quality
  input
- **THEN** evaluation stops with no Draft or provider call

### Requirement: SGQ7 implementation remains a bounded vertical slice

The future implementation SHALL be limited to the 596-1 Golden DTO, deterministic
evaluator, quality receipt and one pre-Draft gate. It SHALL NOT add a generic evaluation
platform, online judge, model leaderboard, experiment DB, auto-tuning loop, new serving
Head, migration or generic Material Wiki fallback.

#### Scenario: implementation requires a general platform

- **WHEN** the gate cannot be delivered without a generic experiment/serving subsystem
- **THEN** implementation stops for a new Mission Card rather than expanding this change

### Requirement: SGQ8 a PASS evaluation bundle is immutable preparation custody

Only a closed canonical `Schema67GoldenEvaluationReviewBundleV1` SHALL cross the Schema
Wiki Draft boundary. It SHALL contain exactly:

- `contract = schema67-golden-evaluation-review-bundle.v1`;
- one server-derived `evaluation_id` equal to the embedded signed quality receipt's
  `receipt_sha256`;
- the concrete signed PASS `Schema67GoldenQualityGateReceiptV1`;
- the exact `Schema67GoldenPublicAggregateV1`;
- the exact `Schema67GoldenPrivateDossierV1`; and
- `evaluation_bundle_sha256` over the preceding canonical content.

The bundle validator SHALL require status `PASS` in the receipt, public aggregate and
private dossier; exact equality of every repeated Candidate, Golden and evaluator identity;
the receipt's Evidence-companion hash equal to the dossier's; exact receipt-to-dossier
ordered 67 decision hashes; exact receipt-to-public/private hashes; and an exact common
ordered metric-hash sequence bound to the receipt's metric-policy identity. A fully
rehashed substitution, missing object, unknown/trailing field or noncanonical value SHALL
fail before `CreateSchemaDraft`.

The existing `SchemaWikiReviewBundleV1` SHALL continue to embed the same concrete quality
receipt. The existing canonical `schema-wiki-preparation-custody.v1` JSONB envelope SHALL
embed the full evaluation review bundle alongside the full release and review bundle.
Its storage `ManifestDigest` SHALL cover the canonical custody envelope, while the inner
release manifest, review-bundle hash and evaluation-bundle hash remain distinct digest
domains. Existing preparation/member snapshots, `PreparationDigest`, Draft-to-Ready CAS,
publish authorization and sole Active Head remain unchanged; no table, migration, Head or
CAS is added.

On a JSONB read the server SHALL closed-decode with EOF, canonicalize the concrete nested
DTOs, revalidate every digest/signature/join and exact-compare the preparation's immutable
scope and snapshots. Database key order or whitespace is not authority. The validated
canonical bundle, not database text, is the only response source and remains pinned to the
same preparation if the Active Head later changes.

#### Scenario: non-PASS evaluation is offered to Draft

- **WHEN** status is `FAIL`, `FIXTURE_ONLY`, `INCONCLUSIVE`, missing or stale
- **THEN** only a safe offline evaluation result may exist and Draft/review/activation/
  repository calls are zero; no evaluation bundle is persisted

#### Scenario: public or private result is replaced

- **WHEN** the public aggregate, private ordered-67 dossier, signed receipt or any nested
  identity is removed or replaced and outer hashes are recomputed
- **THEN** preparation validation fails before a Draft row is created

### Requirement: SGQ9 the review surface is read-only, scoped and privacy-separated

All review URLs SHALL use the existing exact scoped prefix
`/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema`.
The only added routes are:

- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/summary`;
- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/dossier`;
- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/fields/:field_id/evidence/:evidence_id/preview`.

The server SHALL derive tenant/Wiki/RAW/space and the evaluation identity from the
immutable preparation before output, exact-compare all path IDs and then apply the
existing Wiki ACL/evidence -> RAW ACL/evidence -> release-seal chain. All three routes
SHALL deny API keys and require human JWT Admin/Owner. The private dossier and Evidence
preview SHALL additionally require a nonblank authenticated human principal ID, which is
the named reviewer identity for that read; it is never copied from body/query/path data.
Missing or foreign authenticated identity is typed unavailable. No Viewer route is added
for a pre-activation preparation. `public` describes redaction, not authorization.

`SchemaWikiGoldenQualitySummaryV1` SHALL be a closed wrapper with exactly `version`,
`preparation_id`, `evaluation_id`, `quality_gate_receipt_sha256`, `public_aggregate`,
`evaluation_bundle_sha256`, `wiki_admission_allowed` and `serving_effect`.
`public_aggregate` SHALL be the exact validated `Schema67GoldenPublicAggregateV1` already
bound by the receipt; its status is `PASS`, its reason codes are empty, and its Candidate,
Golden, evaluator, metrics and aggregate hash exact-join the bundle. The wrapper SHALL set
`wiki_admission_allowed=false` and `serving_effect=NONE`: quality PASS is not release
review or publication authority. It SHALL expose no field decisions, Candidate/Golden
values, quotes, locator text, bbox, raw PDF bytes, local/object-store paths, opaque token,
key material or private signing values.

`SchemaWikiGoldenQualityDossierV2` SHALL be a closed wrapper with exactly `version`,
`preparation_id`, `evaluation_id`, `quality_gate_receipt_sha256`, `private_dossier`,
`review_successor`, `evaluation_bundle_sha256` and `serving_effect`. `private_dossier` SHALL be the exact
validated `Schema67GoldenPrivateDossierV1` already bound by the receipt, including exactly
the SchemaPack-ordered 67 decision rows and the same ordered metric rows.
`review_successor` SHALL be a closed `schema67-golden-review-successor-metadata.v1` object
whose annotation layer retains `claude-fable-5`, whose distinct human layer names
`linyao`, and whose formal form requires nonempty `reviewed_at`, `VERIFIED` receipt status,
and a review receipt exact-joined to the signed evaluation. It SHALL contain exactly the
ordered67 rows and no `PENDING_RESIDUAL`: each row binds the existing decision hash,
Candidate/Golden states, literal/digest/none value presentation, risk/conflict status and
hashed Evidence changes. Every non-null Candidate Evidence ID SHALL be an exact stored
JoinReceipt ID for the same field and every stored JoinReceipt SHALL occur exactly once.
Golden-only digests SHALL have no preview. The current complete67 receipt-unverified
successor SHALL fail before repository access. The wrapper SHALL set `serving_effect=NONE`.

Evidence preview SHALL accept only the four immutable path IDs. The server SHALL require
the field to exist in the ordered private dossier and select the unique exact Evidence/
citation authority from the validated release and Candidate-Evidence preparation custody,
then reuse the existing attempt-bound immutable revision reader and third-ring,
server-derived opaque-token flow. A preparation-bound preview authority SHALL bind the
preparation/evaluation/field/evidence IDs, full `LiveRevisionSourceReceiptV1`, page, bbox,
coordinate space/page dimensions/rotation, quote/content/Evidence-receipt hashes,
expiry/key ID and authority hash. PDF bytes SHALL be fetched only by that opaque token.
Caller revision/page/bbox/hash/token authority, current/latest/presigned/material fallback,
page 1 fallback and raw redirect URLs are forbidden. Missing page, bbox or immutable bytes
is typed unavailable.

The routes SHALL have no POST/PATCH/approve/review/publish/activate operation and SHALL NOT
call any such authority. Existing named-human `ReviewDraft`, separate publish
authorization and `ActivateReviewed` remain the only state-changing DAG.

#### Scenario: summary leaks private content

- **WHEN** a summary contains any field row/value, quote, locator, bbox, PDF/path/token or
  signing-key material, even with a recomputed wrapper or bundle hash
- **THEN** the closed response validator rejects it before transport

#### Scenario: caller substitutes a preparation or Evidence target

- **WHEN** any scoped path, evaluation, field or Evidence identity differs from immutable
  preparation custody
- **THEN** the read returns a fixed typed error with no dossier, token, bytes or release
  state change and no fallback is attempted

### Requirement: SGQ10 current reviewed-source status is separate from formal PASS custody

The private Schema review surface SHALL add exactly one independent read-only route:

- `GET .../golden-quality/successor-status`.

The route SHALL return a closed `SchemaWikiGoldenSuccessorStatusV1`. It SHALL bind the
exact tenant, space, RAW KB, Wiki KB, product version and SchemaPack identities; the
Golden-set, Schema67 mapping, successor-file and review-attestation hashes; the source
Review state `COMPLETED` with `reviewed_by=linyao`, `annotator_model_id=claude-fable-5`
and nullable `reviewed_at`; the distinct attestor and attestation creation time; the
mapping state `COMPLETE_67` with counts `67/0` and an empty residual field list; and Golden
admission `BLOCKED_RECEIPT_UNVERIFIED` with receipt state `UNVERIFIED` and
`READY_TO_SIGN`. A status self-hash SHALL cover every preceding field.

The corresponding canonical successor SHALL preserve the 51 direct reviewed field rows
byte-for-byte. The exact 16 fields not covered by the current three materials SHALL be
`REVIEWED`, `state=unknown`, null-valued and Evidence-free, with closed
`unknown_reason=NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS`. Every `residual_reason` SHALL be
null. These fields SHALL generate ordinary unknown Schema field pages and participate in the
exact75 release; they SHALL NOT block Candidate, Draft, whole-batch review or publication,
and SHALL NOT acquire an inferred value, absent state, citation, bbox or page-1 fallback.

The status SHALL contain no field value, Evidence, metric or PASS assertion, signature,
opaque token, path, key material, approval action, Draft identity, release Head or serving
effect. It SHALL NOT satisfy or weaken `SchemaWikiGoldenQualityDossierV2`, whose formal
67/0, known-review-time and VERIFIED-receipt requirements remain unchanged.

The sole production authority SHALL be deployment-owned canonical JSON plus its exact
SHA-256. Startup/injection SHALL closed-decode with EOF, reject unknown/trailing or
noncanonical bytes, verify the external artifact SHA and status self-hash, and freeze an
immutable provider. Nil, empty or unconfigured authority SHALL return the fixed typed
`NO_GOLDEN_SUCCESSOR_STATUS`; request body/query/path data SHALL NOT provide or override
status or hashes and the server SHALL NOT read a caller filesystem path.

The route SHALL deny API keys and require a human JWT Admin/Owner, then traverse the
existing Wiki ACL/evidence -> RAW ACL/evidence -> release-seal chain. The service SHALL
independently require trusted Admin/Owner context and exact-compare the provider's tenant,
space, RAW and Wiki scope before output. It SHALL perform no preparation, Draft, Head,
repository, database or release-state write.

#### Scenario: current complete67 receipt-blocked status is requested

- **WHEN** a human Admin/Owner presents the exact sealed Wiki/RAW scope and deployment
  authority is configured
- **THEN** the closed status is returned without a PASS dossier or any state change

#### Scenario: status authority is absent or substituted

- **WHEN** deployment authority is nil, or any hash/status/count/residual/scope byte is
  changed, removed, reordered, extended or self-rehashed outside the frozen authority
- **THEN** the route returns a fixed typed unavailable/invalid response with no status,
  repository call, Draft, Head or release write

#### Scenario: untrusted principal requests current status

- **WHEN** an API key, Viewer, Contributor or foreign scope requests the status
- **THEN** authorization or exact-scope validation fails closed and no private status is
  returned
