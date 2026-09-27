# C source receipt contract correction — read-only finding

## Existing-path fact

No general existing WeKnora W1/native-capture to `ParsedDocumentV1` admission path was found.

- `harness/src/insurance_harness/compiler/parsed_documents.py` supplies general `ParsedDocumentV1`/manifest/quality models, not a WeKnora revision/native adapter.
- `harness/src/insurance_harness/compiler/native_pdfplumber.py` builds those models only after reading PDF bytes and binding a `MaterialProfileResolution`; its native selection role is `terms|brochure|rate_table`.
- `harness/src/insurance_harness/knowledge_compiler/bounded_capture_to_admission_596_1.py` is explicitly one-shot 596-1 MinerU, fixed to three roles and three approved source hashes.
- `harness/src/insurance_harness/knowledge_compiler/vertical_falsification.py::AdmittedParseArtifactV1` and `admit_596_1_vertical_falsification` are likewise 596-1/three-role quality admission.
- `harness/src/insurance_harness/s0q_047.py::admit_frozen_w1_bundle` admits a different `FrozenW1Bundle`; it does not emit `ParsedDocumentV1`, `ParseManifestV1`, or `AdmittedParseArtifactV1`.
- Repository-wide search found no `WeKnora/native -> ParsedDocumentV1` bridge and no Python model for the actual HTTP `knowledge-revision-source.v1` safe receipt.

## C actual use

`batch_entity_resolution_830_g3.py::_entry_source_reasons` consumes only receipt scope, knowledge ID, WeKnora attempt, revision source ID, file SHA, W1 manifest digest, page count, plus entry parser identity. The fields `evidence_parse_attempt_id`, `parsed_document_sha256`, and `parse_manifest_sha256` occur nowhere else in C; today they only satisfy imported `LiveRevisionSourceReceiptV1` shape/self-hash and four-domain-distinct validation.

Therefore requiring these 596-1 admission fields for all 15 G3 materials adds an unused second-level prerequisite and invites placeholder hashes. The earlier 03/04 “missing admission triple” is a real incompatibility of the current C DTO, but it should be corrected in C design rather than filled by a new admission platform. It does not block the source-only uploader from producing actual W1 revisions/source seals/native identities.

## Minimal direction (existing authority only)

Revise C `CorpusEntryV1.receipt` to mirror the already existing handler response `knowledge-revision-source.v1` from `internal/handler/knowledge_revision_source.go`: knowledge ID, parse attempt, actual server source ID, file/object SHA, size/mime/page count, W1 manifest algorithm/digest/chunk count, binding digest, retention state. Pair it with the existing `BatchCorpusV1` scope and current entry fields `native_capture_sha256`, `parser_identity_sha256`, `blocks`, and `provenance`; do not add another source protocol or table.

C should validate only claims present in that receipt and the actual block join: pinned source, file=object where required by current source contract, source ID/attempt/file/W1/page/count exact, block scope/identity/text/Unicode evidence, native/parser/provenance hashes. The existing server source authority remains responsible for reopening the source row/resource at review/activation. The HTTP receipt has no `resource_id`; C does not consume it, so it must not invent one merely to retain the 596-1 DTO.

Freeze this DTO correction before actual C corpus and before D incorporates C input hashes. Preserve the upload runner boundary unchanged.
