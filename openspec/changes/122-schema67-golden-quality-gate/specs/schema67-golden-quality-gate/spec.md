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

All 67 fields SHALL receive two independent named-human decisions. Disagreements SHALL
produce a conflict and require named adjudication. A whole-batch Golden receipt SHALL bind
the exact source receipts, ordered field decisions, normalization/risk/metric policies and
Golden hash. A correction SHALL create a new Golden version/hash.

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

A future `Schema67GoldenQualityGateReceiptV1` SHALL bind the concrete Candidate hash,
Evidence-companion hash, Golden version/hash, ordered 67 field-decision hashes, evaluator
hash, metric-policy hash, all metric numerators/denominators and final PASS status.

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
