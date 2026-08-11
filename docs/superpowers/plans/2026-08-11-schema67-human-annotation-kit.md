# Schema67 Reviewed Golden Successor Plan

> Fact correction, 2026-08-11: the exact latest 71-row source has already completed
> human Review. Its `annotator_model` provenance does not mean human review was absent.
> The earlier all-PENDING annotation kit is superseded as the current factual status.

## Goal and boundary

Build one deterministic, provider-zero 596-1 Schema67 successor from existing reviewed
data. This is not a request to re-annotate all 67 fields. It preserves the annotation
model provenance and separately records the human-review fact and user-attested reviewer
identity `linyao` while refusing to invent the missing review timestamp, approval receipt,
key or signature. `workspace-owner-houjing` is only the fact attestor, never the reviewer.

The successor is not yet an evaluator-authoritative Golden: its real Schema67 mapping
residuals and whole-batch cryptographic approval remain fail-closed. Generic Material Wiki
content is never an answer source.

The frozen statuses are three independent authorities and MUST NOT be collapsed:

- `source_review_status=COMPLETED`: the latest 71-row source was reviewed by `linyao`;
  `annotator_model_id=claude-fable-5` remains separate provenance and `reviewed_at=null`.
- `schema67_mapping_status=PARTIAL_51_CLOSED_16_RESIDUAL`: only the mechanical 71→67
  mapping has 16 unresolved targets; the 51 closed targets are not re-reviewed.
- `golden_admission_status=BLOCKED_RESIDUALS_AND_RECEIPT_UNVERIFIED`: formal Golden
  admission requires residual count zero and a verified whole-batch receipt.

## Exact input authority

- Old S0-Q migration input: exact 60-row `596.jsonl`, SHA-256
  `562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`, with the
  existing approval artifact SHA-256
  `484fdb78bdc73109bccd4d771e41089574b26f28c1992b67b2114524a515c868`.
  It remains a migration input only.
- Latest reviewed source: exact 71-row `annotations.jsonl`, SHA-256
  `25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4`;
  `annotator_model=claude-fable-5` is retained. The existing deterministic verification
  report SHA-256 is
  `4dde5c35e311af3ce4a0c01e2309ff65e872de77ee4cff0762dc951c42c00e73`.
- Review completion and `reviewed_by=linyao` are user-authority facts from 2026-08-11.
  No repository artifact supplies the original `reviewed_at`, signature material or a
  whole-batch approval receipt, so those fields remain explicitly null/unverified. The
  confirmation by `workspace-owner-houjing` is recorded only as an attestation source.
- Target topology is the code-owned `medical-schema67.v1` exact ordered67.

## Deterministic migration

Both source mappings remain explicit and use only `reuse/rename/split/merge/new/N-A`.
The latest reviewed source mechanically resolves 51 one-to-one `reuse/rename` targets.
Only the following 16 targets remain `PENDING_RESIDUAL`:

- tri-state conflicts: `product_type`, `premium_grace_period`,
  `guaranteed_renewal_status`, `premium_adjustment_rules`,
  `eligible_service_packages`;
- multi-source merge: `eligible_occupation_classes`;
- missing in the latest reviewed source: `marketing_tagline`, `product_overview`,
  `health_declaration_requirements`, `direct_billing_and_advance_payment_rules`,
  `tax_qualified_status`, `tax_benefit_rules`, `objection_handling_scripts`,
  `product_faq`, `four_step_sales_script`, `sales_pitch_script`.

High-risk or mandatory-review flags alone do not turn a reviewed row back into PENDING.
Each resolved row is an exact projection of the latest reviewed record; pending rows have
no state, value or Evidence. Bbox remains `PENDING_CAPTURE`, and rate pages 12/27 remain
out of range.

## TDD and freeze

1. RED exact input identity, 51/16 closure, explicit mappings, tri-state/Evidence rules,
   missing metadata, unsigned receipt, closed wire and fully rehashed mutations.
2. GREEN one closed Pydantic successor, canonical field/evidence/package hashes and exact
   eight-file artifact set, including an unsigned review-attestation event. Its
   `attested_at=2026-08-11T11:21:07Z` records this fact-capture event and is not the unknown
   original `reviewed_at`.
3. Freeze an unsigned ready-to-sign payload. Signing is permitted only after the 16
   residuals close and deployment-owned key material plus the missing review timestamp and
   formal receipt authority exist; the signing payload is already bound to `linyao`.
4. Run one bounded focused pytest, relevant SchemaPack compatibility, Ruff, strict mypy,
   OpenSpec 122 strict validation, diff and privacy checks; commit and freeze a read-only
   index without push.

## STOP rules

- No provider, live, DB, WeKnora, Candidate, Draft, review, publish or activation action.
- No invented review time/key/signature/approval receipt and no substitution of the
  attestor for reviewer `linyao`.
- No evaluated model or Material Wiki as Golden authority.
- No automatic resolution of the 16 true mapping residuals.
- No formal evaluator conclusion until the Schema67 canonical successor and required
  cryptographic approvals are complete.
