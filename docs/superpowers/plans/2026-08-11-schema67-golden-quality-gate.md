# Schema67 Golden Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze and later implement one fail-closed, canonical Golden Set quality gate for the Ping An eShengBao medical-insurance product version `596-1`, evaluated after a sealed `Schema67CandidateV2` exists and before any Schema Wiki Draft can be created.

**Architecture:** A protected, independently human-reviewed 67-field Golden artifact is the only semantic answer authority. A deterministic offline evaluator compares one concrete Candidate and its Evidence companion to that Golden, emits a candidate-bound quality receipt, and permits the existing Candidate → Draft → named-human Review → publish authorization → Active DAG to continue only when every structural and semantic threshold passes. This is a single-product vertical gate, not a general evaluation platform.

**Tech Stack:** Python 3.12, Pydantic v2 closed DTOs, canonical JSON/SHA-256, existing Schema67 Candidate/Evidence/057 contracts, existing named-human receipt verification, pytest, Ruff, strict mypy, OpenSpec.

**Spec:** `openspec/changes/122-schema67-golden-quality-gate/specs/schema67-golden-quality-gate/spec.md`

---

## 1. Current truth boundary

- Semantic quality for the current official DeepSeek path is `INCONCLUSIVE`.
- The provider-zero fixture distribution `45 present / 1 absent_explicitly / 21 unknown`
  proves contract behavior only. It is not a measured model result and MUST NOT be reported
  as quality evidence.
- The previous official exact8 run terminated with a typed failure and produced no
  Candidate. It remains immutable history and MUST NOT be rerun or admitted under its old
  identity.
- The exact latest 71-row source has completed human Review. Its model annotator is retained
  as provenance, not treated as proof of zero human review. A mechanical Schema67 successor
  resolves 51 direct fields and retains 16 real residuals. Reviewer identity/time and the
  cryptographic whole-batch approval receipt remain absent and MUST NOT be invented.
- No evaluator-authoritative canonical Golden, evaluation receipt, Schema Wiki Draft,
  named-human release review or activation is produced until those residual and authority
  gaps close.
- The existing 46 generic Material Wiki pages are not Golden, Candidate or Schema facts.

## 2. Exact scope and owner paths

This plan/OpenSpec delta owns exactly six paths:

1. `docs/superpowers/plans/2026-08-11-schema67-golden-quality-gate.md`
2. `openspec/changes/README.md`
3. `openspec/changes/122-schema67-golden-quality-gate/proposal.md`
4. `openspec/changes/122-schema67-golden-quality-gate/specs/schema67-golden-quality-gate/spec.md`
5. `openspec/changes/122-schema67-golden-quality-gate/tasks.md`
6. `openspec/changes/122-schema67-golden-quality-gate/validation-report.md`

Future production/test paths require a separate implementation authorization. This plan
does not authorize edits to CandidateV2, the provider runner, the Schema Wiki release
compiler, the Wiki Release service, DB migrations or frontend code.

## 3. Canonical Golden artifact

The future `Schema67GoldenSet5961V1` is closed-world canonical JSON with:

- contract/version, Golden ID/version and canonical `golden_set_sha256`;
- exact product/entity/version and `medical-schema67.v1` identity/hash;
- exact ordered 67 field IDs, with no missing, extra, duplicate or reordering;
- exact three source-document roles and committed source revision receipts;
- exactly 67 `Schema67GoldenFieldV1` records in SchemaPack order;
- a two-person named-human annotation manifest, disagreement/adjudication receipts and a
  whole-batch Golden approval receipt;
- the normalization policy hash, risk policy hash and metric policy hash.

Each `Schema67GoldenFieldV1` contains:

- `field_id` and `state ∈ {present, absent_explicitly, unknown}`;
- value schema (`scalar | ordered_list | unordered_set | range | structured`), canonical
  value, accepted equivalent values/atoms and an exact per-field normalization rule ID;
- exact source-document role and `LiveRevisionSourceReceiptV1`/committed-revision identity;
- one or more exact evidence targets for known states: knowledge ID, Evidence parse
  attempt, WeKnora parse attempt, revision source ID, file SHA-256, parsed-document SHA-256,
  parse-manifest SHA-256, WeKnora chunk-manifest digest/count, chunk, page, locator, quote
  hash and content hash;
- optional bbox only when the Golden reviewer can establish its coordinate authority;
  bbox records include coordinate-space version, page width/height and rotation;
- `bbox_evaluation = required | not_evaluable`, never an inferred full-page box;
- `risk_level = critical | high | standard`, conflict status, two named annotator decision
  hashes and an adjudication hash when they disagree.

State invariants are exact: `present` and `absent_explicitly` require a nonblank canonical
value plus at least one revision-bound evidence target; `unknown` requires null value,
empty accepted values and no Evidence. Missing page is invalid Golden custody. Missing
optional bbox is `not_evaluable`, not page 1 or a full-page fallback.

### Exact ordered 67 fields

```text
product_code
product_short_name
product_name
sales_start_date
sales_end_date
product_type
insurance_category
sales_channels
external_publication_status
sales_status
policy_role
product_summary
official_product_features
target_customer_profile
marketing_tagline
product_overview
entry_age_range
insured_eligibility
health_declaration_requirements
geographic_eligibility_requirements
social_insurance_requirement
eligible_occupation_classes
underwriting_method
premium_payment_term
premium_payment_frequency
cooling_off_period
waiting_period
premium_grace_period
coverage_period
coverage_term_category
surrender_and_cancellation_terms
coverage_and_renewal_terms
guaranteed_renewal_status
guaranteed_renewal_period
product_conversion_rules
premium_adjustment_rules
post_discontinuation_renewal_arrangement
covered_risk_categories
coverage_responsibilities
coverage_summary
cancer_medical_coverage
age_segment_tags
coverage_limit_category
special_coverage_and_exclusion_tags
exclusions
pre_existing_condition_rules
out_of_hospital_special_drug_coverage
indemnity_principle
zero_deductible_flag
deductible_rules
outpatient_inpatient_scope
reimbursable_expense_scope
reimbursement_rate_rules
eligible_hospital_scope
premium_medical_facility_coverage
direct_billing_and_advance_payment_rules
claim_application_deadline_and_documents
policyholder_rights
eligible_service_packages
medical_service_benefits
tax_qualified_status
tax_benefit_rules
product_bundle_rules
objection_handling_scripts
product_faq
four_step_sales_script
sales_pitch_script
```

## 4. Metric contracts and denominators

Every output number carries `metric_id`, numerator, denominator, scope, Candidate hash,
Golden hash, evaluator identity/version and admission status. No naked percentage is legal.

| Metric ID | Exact definition |
|---|---|
| `sgq.state.micro_accuracy.v1` | Correct state count / exactly 67. |
| `sgq.state.macro_recall.v1` | Unweighted mean of present, absent and unknown recall; each class denominator is its Golden support. An empty class is `NOT_EVALUABLE`, never silently dropped. |
| `sgq.value.present.micro_precision.v1` | Sum of accepted predicted atoms / all predicted atoms on Golden-present fields. Scalar values are singleton atom sets. |
| `sgq.value.present.micro_recall.v1` | Sum of accepted predicted atoms / all Golden atoms on Golden-present fields. |
| `sgq.value.present.macro_f1.v1` | Unweighted mean of per-field atom F1 across Golden-present fields; an empty prediction scores zero. |
| `sgq.state.absent_to_unknown.v1` | Golden absent predicted unknown / Golden absent support. |
| `sgq.state.unknown_to_absent.v1` | Golden unknown predicted absent / Golden unknown support. |
| `sgq.value.wrong_fill_rate.v1` | Golden-present fields predicted present with a non-accepted value / candidate-present ∩ Golden-present fields. |
| `sgq.value.hallucinated_fill_rate.v1` | Golden absent-or-unknown fields predicted present / Golden absent-or-unknown support. |
| `sgq.evidence.document_revision_page_precision.v1` | Candidate evidence fragments matching an allowed Golden document + committed revision + page / all candidate evidence fragments. |
| `sgq.evidence.field_support_recall.v1` | Golden known fields with at least one exact document/revision/page/locator/quote match / all Golden known fields. |
| `sgq.evidence.bbox_iou.v1` | Per matched, bbox-required fragment, intersection-over-union in the exact same coordinate space. Coordinate mismatch is failure, not conversion. |
| `sgq.evidence.highlight_accuracy.v1` | Required fragments with exact quote/content hashes and bbox IoU at threshold / bbox-required fragments. |
| `sgq.human.high_risk_pass.v1` | Critical/high fields passing state, value and Evidence checks / all critical/high fields. |
| `sgq.human.conflict_resolution_pass.v1` | Conflicted fields with a valid named adjudication receipt / all conflicted fields. |

Micro metrics aggregate exact atoms/fragments; macro metrics weight each field equally.
The evaluator reports supports and confusion counts beside every rate. Wilson 95% intervals
are reported for binomial proportions. Macro metrics report the raw per-field distribution;
they do not manufacture a normal-theory interval. A denominator below 20 is marked
`SMALL_SAMPLE`, and no aggregate percentage may erase a zero-support or small-support
class. This single-product result authorizes only product version `596-1`, never a general
model admission claim.

## 5. Frozen release thresholds and STOP rules

All structural/custody checks are exact PASS/FAIL and cannot be averaged away.

| Gate | Required threshold |
|---|---|
| Exact Golden/Candidate/Evidence custody | 100%; any hash, order, schema, revision or receipt drift is STOP. |
| State micro accuracy | At least 65/67, with all critical/high fields exact. |
| State macro recall | At least 0.95 for every evaluable class; report the macro mean but gate each class independently. |
| Absent ↔ unknown confusion | Zero in both directions. |
| Present value | Micro precision ≥ 0.95, micro recall ≥ 0.95, macro F1 ≥ 0.90; critical/high value checks 100%. |
| Wrong fill / hallucinated fill | Zero hallucinated fills; wrong-fill rate ≤ 0.02 and zero on critical/high fields. |
| Evidence document/revision/page | Precision 1.00 and field-support recall 1.00; any foreign or missing revision/page is STOP. |
| Required bbox/highlight | Every required fragment IoU ≥ 0.80, critical/high IoU ≥ 0.90, highlight accuracy 1.00. |
| Human high-risk/conflict | 1.00; no unresolved conflict or unsigned high-risk field. |

Any missing denominator, `NOT_EVALUABLE` result on a required metric, invalid Golden
receipt, model-generated self-Golden, stale Candidate/Golden/evaluator identity, typed page
or bbox failure on a required target, or threshold failure produces
`SCHEMA67_GOLDEN_QUALITY_GATE_FAILED`. No Schema Wiki review dossier, Draft, review or
activation may be created. Optional bbox marked `not_evaluable` is excluded only from bbox
metrics and remains explicitly visible; it cannot become page 1/full-page output.

## 6. Named-human Golden workflow and custody

The latest reviewed source is the starting authority; the workflow does not restart all 67
fields. It replays the 51 direct mappings, reviews only the 16 residual conflict/merge/
missing targets, and supplements only evidence-supported reviewer metadata.

1. Two deployment-verifiable named humans approve the exact completed Schema67 successor
   against the exact committed three-document revisions.
2. They cannot see or copy the evaluated Candidate while producing their first decisions.
3. A disagreement creates a conflict record; a named adjudicator resolves it from source
   custody. Unresolved conflicts block Golden freeze.
4. Finalization replays all exact quotes/pages/locators, then signs one whole-batch Golden
   manifest using the existing named-human receipt framing. It does not invent a new
   signing protocol.
5. The immutable Golden version binds source receipts, ordered fields, decisions,
   normalization/risk/metric policies and receipt hashes. A correction creates a new
   Golden version/hash; it never mutates the evaluated version.
6. The model being evaluated MUST NOT generate or adjudicate its own Golden. Any optional
   model assistance is non-authoritative provenance and requires independent human
   replacement before canonical freeze.

## 7. Candidate → evaluation → release DAG

```text
new authorized provider run
  → concrete sealed Schema67CandidateV2 + Evidence companion
  → deterministic 596-1 Golden evaluation
  → PASS-only Schema67GoldenEvaluationReviewBundleV1
      = signed quality receipt + redacted aggregate + private ordered67 dossier
  → SchemaWikiReviewBundleV1 binds the same concrete receipt
  → schema-wiki-preparation-custody.v1 embeds the full evaluation bundle
  → CreateSchemaDraft
  → named-human ReviewDraft
  → separate PublishAuthorization
  → ActivateReviewed / sole Active Head
```

The quality receipt binds Candidate hash, Evidence-companion hash, Golden hash/version,
ordered 67 field-decision hashes, metric-policy hash, evaluator hash, every metric
numerator/denominator and the final gate status. It is evaluated after Candidate creation
and before any Draft write. FAIL/PENDING receipts are not reviewable and cannot be
overridden by a release reviewer.

### Preparation custody equation

`Schema67GoldenEvaluationReviewBundleV1` is the only persisted evaluation form. Its
`evaluation_id` equals the canonical signed quality receipt SHA-256, and its own
`evaluation_bundle_sha256` hashes the full receipt + aggregate + dossier content. The
quality receipt binds the private dossier and public aggregate hashes; the dossier binds
ordered67 decision hashes; both private/public objects bind the same Candidate, Golden
and metric identities. The same receipt is already nested in `SchemaWikiReviewBundleV1`.

The existing `schema-wiki-preparation-custody.v1` JSONB manifest embeds the full release,
the exact review bundle, the full evaluation bundle and one closed
`Schema67GoldenReviewSuccessorMetadataV1`. Its storage `ManifestDigest`
hashes canonical custody bytes. The release manifest digest, review-bundle hash and
evaluation-bundle hash stay separate; none aliases another authority. Existing immutable
75 member snapshots and `PreparationDigest` close the row. JSONB read accepts equivalent
database key order/whitespace only after strict closed decode, canonical re-marshal and
full nested replay. It never treats raw JSONB text as authority.

Only a signed PASS bundle with a formal review successor reaches `CreateSchemaDraft`.
The successor is exact67 with residual count zero, separates annotation model
`claude-fable-5` from named reviewer `linyao`, requires a known `reviewed_at` and a
`VERIFIED` whole-batch receipt joined to the evaluation, and binds every Candidate
Evidence ID to the stored Candidate-Evidence authority. The current source Review is
`COMPLETED` by `linyao`; independently, its Schema67 mapping is
`PARTIAL_51_CLOSED_16_RESIDUAL` and its Golden admission is
`BLOCKED_RESIDUALS_AND_RECEIPT_UNVERIFIED`. Its `reviewed_at=null` and whole-batch receipt
is `READY_TO_SIGN/UNVERIFIED`; therefore it
remains offline and creates zero Draft rows. `FAIL`, `FIXTURE_ONLY`,
`INCONCLUSIVE`, missing and stale outcomes produce safe offline receipts/aggregates only;
they never enter a preparation. Creating the Draft still does not review or publish it.

### Exact read-only review surface

The scoped prefix remains:

`/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/schema`

The new closed route set is exactly:

- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/summary`
- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/dossier`
- `GET .../preparations/:preparation_id/golden-quality/evaluations/:evaluation_id/fields/:field_id/evidence/:evidence_id/preview`

All are preparation-derived, human JWT Admin/Owner, API-key denied and protected by Wiki
ACL/evidence → RAW ACL/evidence → existing release seal. The dossier and Evidence preview
also require a nonblank authenticated human principal ID as the named reviewer for that
read; caller body/query/path data cannot provide it. This plan chooses Admin/Owner for the
aggregate summary because it is still a pre-activation preparation; `public` means
redacted DTO, not Viewer access. A later Active-release public summary route is outside
this 596-1 slice.

The summary wraps the exact frozen `Schema67GoldenPublicAggregateV1`; the private response
is `SchemaWikiGoldenQualityDossierV2`, retaining the exact private dossier and adding one
closed review-successor projection. Its annotation and human layers are distinct; ordered67
rows exact-join decision/state/value presentation, risk/conflict status and Evidence
changes. Candidate Evidence IDs must be the exact stored JoinReceipt IDs accepted by the
existing preview route; a Golden-only digest has no preview. Evidence preview selects that
exact stored Candidate Evidence target and
returns a preparation-bound authority that reuses the existing immutable revision source
plus third-ring opaque token; the existing token-only bytes route performs the fetch. No
response contains raw PDF bytes, paths, secrets or key material. There is no caller
revision/page/bbox/hash authority and no current/latest/presigned/material/page-1 fallback.

These routes are display-only. They neither expose nor call named-human approval,
`ReviewDraft`, publish authorization or activation APIs.

## 8. Future implementation sequence

### Task 1: Freeze closed Golden DTO and canonical vector

- [ ] Write RED for missing/extra/reordered 67 fields, tri-state violations, revision/page
  drift, bbox coordinate drift, unknown/trailing JSON and self-rehash.
- [ ] Implement only the 596-1 Golden DTO and canonical hashing.
- [ ] Run focused pytest, Ruff and strict mypy.

### Task 2: Produce independent human Golden

- [ ] Freeze exact source receipts without provider calls.
- [x] Preserve the already-reviewed latest71 source and mechanically resolve 51 direct
  Schema67 mappings.
- [ ] Resolve the exact 16 residuals; do not re-annotate the other 51 fields.
- [ ] Backfill only evidence-supported review metadata and obtain two cryptographic
  named-human approvals.
- [ ] Replay quotes/pages/locators and freeze the whole-batch Golden identity.

### Task 3: Implement deterministic evaluator and quality receipt

- [ ] RED every metric denominator, tri-state confusion, hallucination, evidence, bbox,
  small-sample and threshold boundary.
- [ ] Implement deterministic metrics and Wilson intervals without a generic experiment
  registry or online service.
- [ ] Prove provider-zero fixtures are labelled `FIXTURE_ONLY`, never quality results.

### Task 4: Insert the PASS-only gate before Draft

- [ ] RED Candidate PASS/FAIL/PENDING and Golden/evaluator/receipt drift with Draft writes
  fixed at zero.
- [ ] Bind the PASS receipt into the review dossier/bundle before `CreateSchemaDraft`.
- [ ] Preserve existing named-human ReviewDraft and independent publish authorization.

### Task 5: Separately authorize one new real execution

- [ ] Do not rerun the old exact8 identity.
- [ ] After Golden and evaluator independent review, obtain explicit provider authorization
  for one new Candidate identity, evaluate it once, and STOP on any failed gate.

### Task 6: Implement the review surface in a separately authorized delta

- [ ] RED the exact PASS bundle/custody equation, JSONB canonical replay, nested
  substitution and every non-PASS Draft write at zero.
- [ ] RED the exact three GET routes, immutable preparation/evaluation pin, Admin/Owner +
  Wiki/RAW dual ACL, named-reviewer private access and fixed safe errors.
- [ ] RED aggregate privacy, ordered67 dossier invariants and server-derived Evidence
  preview/token-only bytes with typed unavailable behavior.
- [ ] GREEN only the existing preparation-manifest adapter and bounded backend/frontend
  read surface; add no table, Head, CAS, approval action or generic evaluation service.

## 9. Non-goals

- No provider/model call, Golden answer generation, DB/WeKnora write, migration, Draft,
  review, activation, deployment or existing Candidate mutation.
- No generic benchmarking service, model leaderboard, experiment database, online judge,
  auto-tuning loop or multi-product platform.
- No use of generic Material Wiki pages or provider-zero fixtures as Golden truth.
- No default page 1, synthetic bbox, current/latest revision fallback or missing-Evidence
  waiver.
- No change to CandidateV2 wire or reuse of the failed old exact8 identity.
- No Viewer/anonymous/API-key access to pre-activation evaluation data, no review or
  activation control in the evaluation UI, and no generic multi-product evaluation API.
