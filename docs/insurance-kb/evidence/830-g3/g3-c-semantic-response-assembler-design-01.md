# G3 C model semantic response and local assembler — design candidate 01

Date: 2026-09-07

Status: `LOCAL_DESIGN_ONLY; NOT_FROZEN; NO_CALL_AUTHORITY`.

This is a provider-independent, parser-local response shape. It neither changes C8 nor
defines admission, transport, authorization, PolicyReceipt, candidate, or release authority.
It contains no final request hash, receipt, permit, source identity, page identity, proposal
hash or disposition.

## Recommended shape

Use one closed JSON object with exact keys. Null fields are explicit; extra or omitted keys,
duplicate JSON keys, floats, non-NFC text and forbidden controls are invalid.

| Object | Exact model-visible keys | Required semantic meaning |
|---|---|---|
| root | `contract`, `materials` | `contract=g3-batch-resolution-semantic-response.local.v1`; `materials` is a unique subset of the exact request window. Omission means no proposal for that requested material. |
| material | `material_id`, `material_role`, `material_role_evidence_refs`, `entities`, `evidence` | ID must copy a requested ID. Role is a real evidence-backed model proposal from the frozen policy role allowlist. A listed material has at least one entity/evidence/role-evidence ref. |
| entity | `entity_ref`, `issuer`, `name`, `product_code`, `version_label`, `filing_or_registration`, `identity_confidence`, `identity_evidence_refs`, `labels`, `primary_label`, `valid_from`, `valid_through` | `entity_ref` is a response-local unique handle. Identity strings are observed source text or explicit `null`; confidence is the model's exact six-decimal proposal. Dates are exact ISO dates or null. |
| filing/registration | `kind`, `value` | `kind` is `filing_number` or `registration_number`; both object fields are present, or the parent value is null. |
| label | `taxonomy_label`, `confidence`, `evidence_refs` | Label must come from the exact frozen taxonomy allowlist, confidence matches `0.[0-9]{6}` or `1.000000`, and evidence refs are nonempty. The primary label names exactly one listed label. |
| evidence | `evidence_ref`, `entity_ref`, `purpose`, `field_key`, `locator` | The model selects the factual purpose and exact source span. `purpose` is one of issuer/product_code/name/version/classification/material_role/field. Material-role has null entity/field; field has both; every other purpose has entity and null field. |
| locator | `block_ref`, `start`, `end`, `quote` | `block_ref` is an opaque handle from the request, not a source ID. `start/end` are strict integer Unicode-code-point offsets into that exact exposed block text. `quote` is an exact echo used as a cross-check, never trusted as source bytes. |

`identity_evidence_refs` may be empty only when identity facts are absent; every non-null
issuer/name/product code/version label/filing or registration value must be supported by a
matching-purpose ref whose derived quote contains that observed value under C8 normalization.
Each stated validity date also needs version evidence containing the exact date. Every label
needs classification evidence. These mirror C8 evidence checks
(`batch_entity_resolution_830_g3.py:1235-1352`).

The model does **not** return `corpus_entry_sha256`, `model_request_sha256`, final
`proposal_ref`/`evidence_id`, `proposal_sha256`, `ProposalBatchV1`, `ModelReceiptBindingV1`,
`PolicyReceipt`, permit data, source scope/receipt fields, page number, quote hash, pack ID,
matched entity, candidate ID, reason code, queue, disposition or any aggregate count.

## Synthetic example

Synthetic request context only:

```text
material_id = synthetic-material-01
block_ref = b1
block text = 保险条款。示例保险公司推出示例安康医疗保险，产品代码EX-MED-001，2026版，登记编号示例登记号-001，属于医疗保险。
```

```json
{
  "contract": "g3-batch-resolution-semantic-response.local.v1",
  "materials": [
    {
      "material_id": "synthetic-material-01",
      "material_role": "terms",
      "material_role_evidence_refs": ["role-1"],
      "entities": [
        {
          "entity_ref": "entity-1",
          "issuer": "示例保险公司",
          "name": "示例安康医疗保险",
          "product_code": "EX-MED-001",
          "version_label": "2026版",
          "filing_or_registration": {
            "kind": "registration_number",
            "value": "示例登记号-001"
          },
          "identity_confidence": "0.970000",
          "identity_evidence_refs": ["code-1", "issuer-1", "name-1", "registration-1", "version-1"],
          "labels": [
            {
              "taxonomy_label": "medical_insurance",
              "confidence": "0.960000",
              "evidence_refs": ["classification-1"]
            }
          ],
          "primary_label": "medical_insurance",
          "valid_from": null,
          "valid_through": null
        }
      ],
      "evidence": [
        {"evidence_ref":"role-1","entity_ref":null,"purpose":"material_role","field_key":null,"locator":{"block_ref":"b1","start":0,"end":4,"quote":"保险条款"}},
        {"evidence_ref":"issuer-1","entity_ref":"entity-1","purpose":"issuer","field_key":null,"locator":{"block_ref":"b1","start":5,"end":11,"quote":"示例保险公司"}},
        {"evidence_ref":"name-1","entity_ref":"entity-1","purpose":"name","field_key":null,"locator":{"block_ref":"b1","start":13,"end":21,"quote":"示例安康医疗保险"}},
        {"evidence_ref":"code-1","entity_ref":"entity-1","purpose":"product_code","field_key":null,"locator":{"block_ref":"b1","start":26,"end":36,"quote":"EX-MED-001"}},
        {"evidence_ref":"version-1","entity_ref":"entity-1","purpose":"version","field_key":null,"locator":{"block_ref":"b1","start":37,"end":42,"quote":"2026版"}},
        {"evidence_ref":"registration-1","entity_ref":"entity-1","purpose":"version","field_key":null,"locator":{"block_ref":"b1","start":43,"end":56,"quote":"登记编号示例登记号-001"}},
        {"evidence_ref":"classification-1","entity_ref":"entity-1","purpose":"classification","field_key":null,"locator":{"block_ref":"b1","start":57,"end":63,"quote":"属于医疗保险"}}
      ]
    }
  ]
}
```

All names and identifiers above are synthetic. The offsets are Python/Unicode code-point
indices into the shown string, not UTF-8 byte offsets.

## Local assembler duties

1. Parse the exact JSON bytes once with duplicate-key rejection and size/depth/count bounds.
   Preserve raw bytes separately. Validate that material IDs are a subset of one exact
   request window; unknown/duplicate material, entity or evidence refs fail the whole window.
2. Map each opaque `block_ref` through the pre-frozen request map to exactly one block in that
   material's `CorpusEntryV1`. Never accept an actual knowledge/revision/block/page/hash value
   from model output.
3. Treat `start/end` as code-point offsets. Require `0 <= start < end <= len(block.text)`,
   derive `quote = block.text[start:end]`, and require byte-for-byte equality with the echo.
   Require the quote to occur exactly once in that block. Reopen the frozen native page named
   by the pre-model page map and require the exact quote once on that canonical native-page
   projection. A duplicate or absent occurrence is rejected; no trimming, normalization,
   fuzzy search, page switching or wider-span repair is allowed.
4. Construct final C8 `Evidence` mechanically from the matched `SourceBlock`: tenant/Space,
   RAW KB, knowledge, attempt, revision, source/parse/parser identities, source type, actual
   block ID and frozen page; set offset unit to `UNICODE_CODE_POINT`; use derived quote and its
   UTF-8 SHA-256. Run existing `verify_evidence` (`concept_free_wiki_830_g2.py:152-188`).
5. Convert local refs to globally unique structural IDs using domain-separated canonical
   hashes of `(material_id, entity_ref)` and `(material_id, evidence_ref)`. These are navigation
   handles, not serving entity IDs or authority. Rewrite all internal refs and reject dangling,
   wrong-purpose, cross-entity or cross-material references.
6. Preserve observed identity strings exactly. Do not copy identity from filenames, Existing
   Snapshot, catalog titles or another material; do not normalize or fill nulls. Validate
   confidence/date/enums and evidence membership, then construct `EntityProposalV1`.
7. Inject `material_id` and `corpus_entry_sha256` from the exact bound corpus entry and
   `model_request_sha256` from the exact serialized HTTP request bytes. Construct sorted
   `MaterialProposalV1` rows and compute each `material-proposal.830.g3.v1` hash using the C8
   canonical helper (`batch_entity_resolution_830_g3.py:197-236,432-473`).
8. Outside semantic parsing, build `ModelReceiptBindingV1` only from the real guard-emitted
   PolicyReceipt, exact sorted material bindings, C8 classifier input hash, request bytes,
   exact returned content and a durable execution receipt (`:355-372,1075-1104`). The model
   cannot supply or influence those values.
9. Avoid both hash cycles: request bytes exclude the eventual request SHA; semantic output
   excludes it. Compute request SHA before send, material proposal hashes after response,
   execution receipt next, then `ModelReceiptBindingV1`, and finally ProposalBatch hash. The
   execution receipt may bind material-proposal hashes but must not contain the final
   ProposalBatch hash that contains its own SHA.
10. Call pure `resolve_batch` only after the complete ProposalBatch validates. It alone derives
    normalized anchors, pack assignment, matching/candidate identities, reasons, queues,
    dispositions and counts (`batch_entity_resolution_830_g3.py:1186-1222,1743-2070`).

## Missing, ambiguous and multi-product behavior

- A requested material omitted from an otherwise valid response gets no MaterialProposal;
  the real receipt still records it as attempted, and C8 deterministically yields
  `MODEL_OUTPUT_MISSING` / `NEEDS_CONFIRM` (`:1802-1806,1981-1994`). Do not invent null rows.
- A listed material must have at least one entity and label. Unsupported identity values are
  explicit null. Low confidence is preserved; the assembler never raises it. If no
  evidence-backed allowed label can be proposed, omit the material rather than create a
  sentinel classification outside the frozen taxonomy.
- Multiple entities are allowed only when the document independently supports each. Each
  entity needs its own name and product-code evidence occurrence; those occurrences must be
  disjoint across identity clusters. Shared issuer text is allowed. C8, not the assembler,
  decides whether this becomes MULTI (`:821-866`). Uncertainty about whether two mentions are
  separate products is represented by missing/null/low-confidence semantics, not invented
  children.
- Malformed JSON, extra fields, invalid refs, wrong offsets/quotes/pages, or any source/hash
  drift invalidates the whole window. Preserve raw output and the failure record, make no
  ProposalBatch from that window, perform no retry or repair, and stop later windows.
- Never construct a deliberately invalid receipt/evidence binding to obtain QUARANTINE.
  QUARANTINE may only result from real source/receipt/evidence facts evaluated by C8
  (`:1623-1637,1697-1719`). The desired five dispositions do not authorize fabricated source
  defects, anchors, labels, Seed values or proposals.

## Review alternatives

The recommended opaque-block-ref schema prevents model-authored source authority while still
requiring exact semantic spans. A less safe alternative would let the model echo full C8
Evidence and then compare every field; it is larger, invites forged custody fields and still
needs the same mechanical reconstruction. A quote-only alternative cannot resolve repeated
text or code-point offsets deterministically. Neither alternative improves this batch.

