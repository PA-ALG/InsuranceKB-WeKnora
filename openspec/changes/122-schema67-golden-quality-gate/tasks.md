# 122 · Implementation Tasks

## Task 0 · Governance and contract freeze

- [x] Bind current quality status as `INCONCLUSIVE` and provider-zero `45/1/21` as
  `FIXTURE_ONLY`.
- [x] Record that the previous exact8 run failed, Candidate is absent and the old identity
  must not be rerun.
- [x] Freeze the exact ordered 67-field Golden schema, metrics, denominators, confidence/
  small-sample reporting, thresholds and STOP rules.
- [x] Freeze the independent named-human annotation/adjudication and immutable Golden
  version/hash custody.
- [x] Place the PASS-only quality receipt after Candidate and before Draft.
- [x] Restrict this change to plan/OpenSpec paths and zero provider/DB/WeKnora action.

## Task 1 · Canonical 596-1 Golden DTO

- [x] Obtain a separate implementation Mission Card and exact owner paths.
- [x] RED missing/extra/reordered 67 fields, tri-state/value/Evidence violations, committed
  revision/page/locator/bbox drift, unknown/trailing JSON and fully rehashed mutation.
- [x] GREEN one closed canonical DTO and deterministic hash; do not modify CandidateV2.

## Task 2 · Independent human Golden freeze

- [ ] Freeze exact three-document revision receipts without provider calls.
- [ ] Complete two independent named-human annotations for every field.
- [ ] Adjudicate every disagreement and assign per-field risk/normalization policies.
- [ ] Replay Evidence and freeze one immutable whole-batch Golden receipt/version/hash.

## Task 3 · Deterministic evaluator

- [x] RED all metric definitions, supports, macro/micro boundaries, Wilson intervals,
  `SMALL_SAMPLE`, required `NOT_EVALUABLE` and threshold edges.
- [x] RED provider-zero fixture misuse, self-Golden and stale identity.
- [x] GREEN the product-specific evaluator and Candidate-bound quality receipt.
- [x] Require two distinct, deployment-trusted, domain-separated named-human Golden
  approvals before evaluation; nil/unconfigured or self-signed authority fails closed.
- [x] Remove per-call verifier/signer injection; compose one sealed evaluator authority
  from deployment public-key settings plus an external signing credential source, reject
  duplicate approver key material, and inject the evaluator receipt public ring in Go.
- [x] Compute present precision/recall/F1 from frozen normalized atoms and report actual
  per-fragment bbox IoU aggregate separately from threshold pass counts.

## Task 4 · Candidate-to-Draft integration

- [x] RED FAIL/PENDING/missing/stale quality receipts with review dossier/Draft/review/
  activation call counts all zero.
- [x] Bind PASS receipt into the review dossier/bundle before `CreateSchemaDraft`.
- [x] Sign the full canonical PASS receipt with a dedicated evaluator key and verify it
  against an injected frozen public-key ring at the Go boundary before repository access;
  the receipt self-hash remains integrity-only.
- [x] Preserve existing named-human review, publish authorization and sole Active Head.

## Task 5 · Real acceptance

- [ ] Independently review the Golden and evaluator identities.
- [ ] Obtain explicit authorization for one new official DeepSeek run identity; never rerun
  the old exact8 identity.
- [ ] Evaluate the resulting Candidate once and STOP on any failed gate.
- [ ] Only after PASS, continue the existing Draft → Review → Publish → Activate runbook.

## Global STOP conditions

- Evaluated model participates in its own Golden authority.
- Golden does not contain exactly 67 ordered fields or exact committed revisions.
- Any metric lacks numerator/denominator/support or hides a small/empty class.
- Any threshold, high-risk field, Evidence or human conflict gate fails.
- Any page/current/latest/bbox fallback is proposed.
- Any provider-zero fixture or old failed execution is presented as semantic acceptance.
- Any general evaluation platform, DB/migration or second release authority is required.
