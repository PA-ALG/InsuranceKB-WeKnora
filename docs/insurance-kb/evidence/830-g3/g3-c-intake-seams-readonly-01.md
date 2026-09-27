# G3 C actual intake seams — read-only preparation 01
Date: 2026-09-07
Status: `READ_ONLY_PREPARATION_COMPLETE_WITH_REQUIRED_INPUT_GAPS`.
Scope: steps after an actual upload-v2 `SOURCE_PASS`; this report did not run HTTP, DB,
Docker, parser, provider, upload, model, or product/evidence writes.

## Frozen identities and existing authority
- C8 production module:
  `harness/src/insurance_harness/knowledge_compiler/batch_entity_resolution_830_g3.py`,
  frozen SHA-256 `050f5a0b65e8919142946e6f38a947220ec9181060b9d6ea89f3ed9778dfe2e5`.
- Upload v2 is the source-capture producer. Its final run receipt is a summary and index;
  the exact revision/chunk/backfill HTTP response bytes live in its artifact directory.
- Catalog input already has an exact parser/validator at
  `schema_pack_catalog_830_g3.py::validate_catalog`; the frozen full JSON is
  `internal/handler/schema_pack_catalog_830_g3.generated.json`.
- C is pure: `resolve_batch` consumes Catalog, Corpus, ProposalBatch,
  ExistingEntitySnapshot and BatchResolutionPolicy; it performs no model or source I/O.
- `validate_batch` validates only the resulting wire object. It does not prove external
  source, native-capture, policy, catalog-head or model-execution authority.

## Shortest post-SOURCE_PASS construction path
1. Freeze the upload run receipt bytes/SHA and its artifact-directory manifest. Require
   final `SOURCE_PASS`, counts 11 uploads / 11 provider attempts / 15 W1 revisions /
   15 source seals, exact tenant/RAW-KB, authorization, runner, provision and guard-ledger
   bindings. Do not consume only `materials[*].result`; it omits full W1 and 14-field data.
2. For every selected `g3-material-01..21` member (the exact 15 in
   `corpus-files-v4.json`), bind one actual knowledge ID and parse attempt from the saved
   completion/revision responses. Require 15 distinct source keys and the frozen old
   knowledge/source identities where defined; old 02 uses its new actual source ID.
3. Load every saved `revision-before-*` / `old-revision-before-*` response and every
   paginated `chunks-*` / `old-chunks-*` response. Preserve the full ordered W1 chunk rows,
   including exact `block_id`/chunk ID and `text`; offline 204 chunks are predictions only.
4. Recompute `weknora.chunk_manifest.v1` over the complete actual ordered rows with
   `source_upload_runner_v2.py::compute_manifest_digest`; reapply
   `validate_revision_capture` / `validate_existing_revision_capture`. Freeze both raw
   response bytes and the recomputed digest/count, rather than a derived text summary.
5. Extract `data` from each saved `backfill-<material>.json` and validate its exact
   14-field mirror with `RegisteredSourceReceipt830G3V1` and upload runner
   `validate_source_receipt`. Require object SHA = file SHA and retention `pinned`.
6. Build one acquisition record per material from actual saved facts: authenticated
   tenant/user/role hashes in the run receipt; RAW-KB/knowledge/version reads; the exact
   RegisteredSource receipt; complete W1 response set and recomputation; and the native
   custody identities below. Hash its exact frozen bytes into
   `SourceProvenanceV1.acquisition_receipt_sha256`; provenance declaration itself uses the
   existing `source-provenance.830.g3.v1` hash domain.
7. Bind native layers without substitution: persisted gzip is `capture_file_sha256`,
   decompressed wrapper is `raw_capture_sha256`, Markdown is `markdown_sha256`, canonical
   JSON of `metadata.sanitized_json` is `native_sha256`, and parser identity is separate.
   Set `CorpusEntry.native_capture_sha256 = native_sha256` and
   `CorpusEntry.parser_identity_sha256 = parser_identity_sha256`.
8. Before producing or sending any model request, freeze one `page_number` for each W1
   block exposed to the model. The page must be justified by an unchanged W1 substring
   that occurs exactly once on that saved native page. Keep full W1 `text`, original block
   ID and Unicode offsets; restrict later model Evidence to the already assigned page.
9. Construct sorted unique `SourceBlock` values with actual tenant/space/RAW-KB,
   knowledge ID, attempt, Registered revision source ID, file SHA, W1 manifest digest,
   parser identity, chosen page and exact full W1 text. Then construct hashed
   `CorpusEntryV1` values and sorted `BatchCorpusV1` using
   `batch_canonical_830_g3.py::batch_sha256_830_g3` and model validation.
10. Independently freeze the current `ExistingEntitySnapshotV1` from the actual serving
    head/receipt and the exact catalog instance. Neither source upload nor native capture
    supplies this existing-identity authority.
11. Freeze the real `BatchResolutionPolicyV1` instance (two thresholds, taxonomy,
    named queue/owner, trust rules) and the separate model-policy call identity. C accepts
    only purpose `g3-batch-resolution`, schema `830-g3-v1`, role `classify`.
12. Freeze the model-visible request bytes before transport. Sorted material bindings
    produce `input_sha256` under `batch-classifier-input.830.g3.v1`; actual request bytes,
    raw response bytes and execution receipt remain separately hashed in
    `ModelReceiptBindingV1`. Parse actual output into exact `ProposalBatchV1` without
    filling absent issuer/code/name/version/labels/Evidence.
13. Only after Catalog, Corpus, ProposalBatch, Existing snapshot and Policy are frozen,
    call `resolve_batch(...)`; retain all 15 material decisions and zero-valued disposition
    counts. A later serving/review stage must reopen source/native authority as designed.

## Reusable implementation seams
- W1 capture validation: `source_upload_runner_v2.py::{compute_manifest_digest,
  validate_revision_capture,validate_existing_revision_capture,validate_source_receipt}`.
- Source/corpus DTOs: C8 `RegisteredSourceReceipt830G3V1`, `SourceProvenanceV1`,
  `CorpusEntryV1`, `BatchCorpusV1`.
- Exact W1 Evidence: `concept_free_wiki_830_g2.py::{SourceBlock,Evidence,evidence_for,
  verify_evidence}`. These prove W1 substring/offset identity, not native-page uniqueness.
- Native serving reference: `internal/application/service/concept_source_authority_830_g2.go`
  quote resolver/custody checks. It validates a supplied quote/page; it is not a pre-model
  Python page-assignment builder.
- C model binding check: C8 `_valid_model_receipt`; shared policy/transport types are
  `model_policy.models::{ModelCallRequest,PolicyReceipt,ModelPermitView}` and the sealed
  public boundary `model_policy::{ProductionModelComposition,GuardedModelClient}`.

## Required gaps; do not manufacture values
- **Page-freeze gap:** no frozen helper, per-block page map, canonical artifact schema or
  selection rule exists for assigning cross-page actual W1 chunks before model output.
  The minimum missing input is an explicit pre-model block-to-page map based only on exact
  W1/native unique joins. Existing quote-driven verification cannot choose it for us.
- **Material 21 conditional blocker:** two W1 blocks cover five substantive native pages;
  one page per unique block can expose at most two pages. Partial evidence is constructible;
  complete five-page product-row coverage is not constructible under the current SourceBlock
  key/page contract without forbidden block duplication or text/ID changes.
- **Acquisition freeze gap:** amendment 8 requires the acquisition facts above, but no exact
  acquisition-record DTO/canonical byte layout or accepted instance is frozen. Therefore an
  authoritative `acquisition_receipt_sha256` cannot yet be selected merely from run-summary
  fields; the underlying exact artifacts are available after SOURCE_PASS.
- **Policy gap:** `BatchResolutionPolicyV1` defines shape only. No accepted threshold values,
  named queue/owner, trust-rule set, taxonomy instance or policy SHA exists. Draft values
  0.95/0.90 are explicitly unfrozen.
- **Seed gap:** no real Seed contract, accepted label file, expected-outcome file, or builder
  exists. `corpus-inventory-v3.json` dispositions/packs are `seed_only` suggestions and
  `corpus-files-v4.json` says Seed/policy freeze is pending. Provisioning's `SEED` name is a
  storage-volume helper and is unrelated. Seed must not be inferred from model output.
- **Model-run gap:** no C-specific prompt/template, serialized request schema, response
  parser, batching/window plan, chosen model identity, call authorization/receipt instance,
  or persistence runner was found. `existing-model-config-readonly.json` is runtime config;
  generic model-policy gateway code does not supply the C proposal protocol.
- **Existing-head gap:** no actual `ExistingEntitySnapshotV1` instance/head receipt for this
  batch is frozen. Tests contain fixtures only.
- **Five-disposition gap:** no actual ProposalBatch exists, and C explicitly permits any of
  MATCH/CREATE/MULTI/NEEDS_CONFIRM/QUARANTINE counts to be zero. Inventory suggestions and
  the old keyword-classifier RED are not outcomes. Material 21 is only a MULTI candidate;
  QUARANTINE must arise from real source/model/trust failure and cannot be added for coverage.

Conclusion: SOURCE_PASS closes source custody; the listed gaps remain, without admission triples or fabricated dispositions.
