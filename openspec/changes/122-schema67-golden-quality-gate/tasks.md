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
- [x] Record the exact latest 71-row human-reviewed source and retain its model-annotator
  provenance separately from human-review status.
- [x] Mechanically map 51 direct fields byte-identically and close the exact 16 uncovered
  targets as reviewed `unknown` with null value, empty Evidence and
  `NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS`; do not restart all 67 fields.
- [x] Freeze independent source Review, Schema67 mapping and Golden admission statuses;
  record `linyao` separately from `claude-fable-5`, keep `reviewed_at=null`, and emit only
  an unsigned fact-attestation event rather than a forged review receipt.
- [x] Record the 16 source-coverage gaps as informational and non-blocking; never use them as
  a decision queue or invent the historical review time.
- [ ] Obtain the required two deployment-verifiable named-human approvals and adjudicate
  remaining disagreements under the existing quality-gate policy.
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

## Task 6 · Preparation-pinned evaluation review surface

- [x] Freeze one canonical PASS evaluation bundle containing the signed quality receipt,
  redacted public aggregate and private ordered-67 dossier.
- [x] Freeze storage inside the existing `schema-wiki-preparation-custody.v1` manifest,
  with distinct digest domains and JSONB canonical replay; add no table, Head or CAS.
- [x] Freeze the exact three preparation/evaluation-pinned GET routes and closed public/
  private DTOs. Public means aggregate-only; pre-activation summary remains human JWT
  Admin/Owner, while dossier/Evidence also bind the named reviewer and all use Wiki/RAW
  dual ACL plus the existing release seal.
- [x] Freeze Evidence preview as server-selected, attempt-bound fixed-revision authority
  followed by token-only bytes; forbid caller revision/page/bbox/hash authority and every
  current/latest/presigned/material/page-1 fallback.
- [x] RED/GREEN the backend custody replay, fixed safe errors, read-only authorization and
  exact routes in separately authorized production paths.
- [x] RED/GREEN the same-route Dossier V2 review-successor projection, exact67 joins and
  zero-Draft rejection of residual, metadata-incomplete or unsigned successors.
- [ ] RED/GREEN the closed frontend parsers and preparation review UI. The UI SHALL have no
  approval, review, publish or activation capability.

## Task 7 · Current Golden successor status

- [x] Freeze a separate closed status DTO for the completed latest71 source Review, the
  complete67 Schema67 mapping and receipt-unverified Golden admission state.
- [x] Freeze one deployment-owned canonical provider contract: exact bytes and SHA are
  revalidated at startup; nil/unconfigured is typed `NO_GOLDEN_SUCCESSOR_STATUS`.
- [x] RED/GREEN one read-only private GET under the existing scoped Schema Wiki surface,
  with human JWT Admin/Owner, API-key denial, Wiki/RAW ACL evidence and the existing seal.
- [x] Keep field values, Evidence, quality PASS, signatures and every Draft/review/publish/
  activate authority out of this status response; do not relax Dossier V2.
- [x] Reuse the existing concrete `HumanBatchDecisionReceiptV1` and deployment-owned
  human public-key ring to verify one domain-separated Golden-Dossier subject before
  registering formal review-successor or Dossier V2 provenance. Reject nil/unknown keys,
  reparsed/self-built objects, cross-pairs and nested Evidence-change drift.
- [x] Register the verifier capability only during deployment composition. Remove the
  obtainable construction token/public class export and reject direct/forged authority
  identities with evaluation, receipt and successor registry calls fixed at zero.
- [ ] `WAITING_FOR_REAL_CONCRETE_WHOLE_BATCH_RECEIPT`: no business receipt has been signed
  or supplied. The current complete67 authority stays `UNVERIFIED`, evaluator/Draft calls
  remain zero, and receipt issuance time SHALL NOT backfill historical `reviewed_at`.

## Global STOP conditions

- Evaluated model participates in its own Golden authority.
- Golden does not contain exactly 67 ordered fields or exact committed revisions.
- Any metric lacks numerator/denominator/support or hides a small/empty class.
- Any threshold, high-risk field, Evidence or human conflict gate fails.
- Any page/current/latest/bbox fallback is proposed.
- Any provider-zero fixture or old failed execution is presented as semantic acceptance.
- Any general evaluation platform, DB/migration or second release authority is required.
- Any evaluation surface exposes private field values in the summary, accepts caller
  revision authority, bypasses preparation scope/dual ACL, or changes release state.
