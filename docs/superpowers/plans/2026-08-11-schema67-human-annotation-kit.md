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

The successor is not yet an evaluator-authoritative Golden because its whole-batch
cryptographic approval remains fail-closed. Generic Material Wiki content is never an
answer source.

The frozen statuses are three independent authorities and MUST NOT be collapsed:

- `source_review_status=COMPLETED`: the latest 71-row source was reviewed by `linyao`;
  `annotator_model_id=claude-fable-5` remains separate provenance and `reviewed_at=null`.
- `schema67_mapping_status=COMPLETE_67`: the 51 direct rows remain byte-identical and the
  other 16 reviewed fields are normal `unknown` because the current three source materials
  do not cover them.
- `golden_admission_status=BLOCKED_RECEIPT_UNVERIFIED`: formal Golden admission is blocked
  by the unverified whole-batch receipt, not by a field-review residual.

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
- Current-material coverage authority input: closed list SHA-256
  `e58d0ffdc7e0c16d98df13f1be51b5d747bf81102f0e35f01612a969c2164506`,
  external manifest SHA-256
  `2e98c5e45f9c4447b61e9b0055f12774062a8ce2e96e6f48ed59156d4a11acf2`, and
  manifest self-hash
  `9071fe763efd18aea7afca22d3dfe2d7911067237c118999744e72cfeceda70d`.
  It is generation input and informational coverage authority, not a Golden or receipt.
- Target topology is the code-owned `medical-schema67.v1` exact ordered67.

## Deterministic migration

Both source mappings remain explicit and use only `reuse/rename/split/merge/new/N-A`.
The latest reviewed source mechanically resolves 51 one-to-one `reuse/rename` targets.
The following 16 targets are closed as `REVIEWED/unknown`, with null value, empty Evidence,
no page and typed reason `NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS`:

`product_type`, `marketing_tagline`, `product_overview`,
`health_declaration_requirements`, `eligible_occupation_classes`,
`premium_grace_period`, `guaranteed_renewal_status`, `premium_adjustment_rules`,
`direct_billing_and_advance_payment_rules`, `eligible_service_packages`,
`tax_qualified_status`, `tax_benefit_rules`, `objection_handling_scripts`,
`product_faq`, `four_step_sales_script`, `sales_pitch_script`.

Historical conflict/merge/missing mapping notes do not reopen these reviewed fields. The 51
direct rows are exact projections of the latest reviewed record; the 16 coverage-gap rows
carry no value, Evidence, page, citation or bbox. Rate pages 12/27 remain out of range.

## TDD and freeze

1. RED exact input identity, complete67 closure, explicit mappings, tri-state/Evidence rules,
   missing metadata, unsigned receipt, closed wire and fully rehashed mutations.
2. GREEN one closed Pydantic successor, canonical field/evidence/package hashes and exact
   eight-file artifact set, including an unsigned review-attestation event. Its
   `attested_at=2026-08-11T11:21:07Z` records this fact-capture event and is not the unknown
   original `reviewed_at`.
3. Freeze an unsigned ready-to-sign payload. Signing requires deployment-owned key material,
   the new whole-batch review time and formal receipt authority; the payload is already bound
   to `linyao`. The historical `reviewed_at` remains unknown and is not backfilled.
4. Run one bounded focused pytest, relevant SchemaPack compatibility, Ruff, strict mypy,
   OpenSpec 122 strict validation, diff and privacy checks; commit and freeze a read-only
   index without push.

## STOP rules

- No provider, live, DB, WeKnora, Candidate, Draft, review, publish or activation action.
- No invented review time/key/signature/approval receipt and no substitution of the
  attestor for reviewer `linyao`.
- No evaluated model or Material Wiki as Golden authority.
- No guessed value, fabricated Evidence, `absent_explicitly` coercion or page-1 fallback for
  the 16 current-material coverage gaps; they are informational, not a decision queue.
- No formal evaluator conclusion until the Schema67 canonical successor and required
  cryptographic approvals are complete.
