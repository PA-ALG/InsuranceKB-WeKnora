# G3 C native hash and page/quote join — read-only review 01

Date: 2026-09-07

Scope: local saved evidence only. No HTTP, parser, database, provider, upload, container mutation, or product/design change was performed.

## Result

`native_capture_sha256` in the G3 C `CorpusEntryV1` should use the canonical sanitized native projection digest recorded as `native_sha256` in `native-capture-inventory-v2.json`, not the gzip file digest, decompressed capture-wrapper digest, or Markdown digest.

This follows the already-written G3 semantic in `c-source-wiring-inventory-01.md` and the serving verifier in `resolveConceptNativeQuote830G2`: the verifier canonicalizes the decoded sanitized projection and requires that digest to equal `NativeStructure.SanitizedSHA256`; it separately binds `MarkdownSHA256`, source SHA, and parser identity.

The saved hash layers remain distinct:

- `capture_file_sha256` / historical `gzip_sha256`: exact persisted `.json.gz` bytes and capture-set membership.
- `raw_capture_sha256`: exact decompressed wrapper JSON bytes where recorded. Existing 01 and 03 historical receipts bound it; 04 did not historically bind it. Preservation evidence now verifies the stored decompressed bytes without retroactively changing historical authority.
- `native_sha256` / historical `canonical_native_sha256` / `native_artifact_sha256`: SHA-256 of canonical JSON for `metadata.sanitized_json`. This is the C `native_capture_sha256` value.
- `markdown_sha256`: SHA-256 of exact UTF-8 Markdown; the projection carries this value and the verifier recomputes it.
- `parser_identity_sha256`: SHA-256 of canonical parser identity; it remains `CorpusEntry.parser_identity_sha256` and each `SourceBlock.parser_identity`.

An acquisition receipt should bind all locally available custody layers by their explicit names. It must not substitute the gzip/raw-wrapper digest into the C native projection field.

## SourceBlock page semantics

`SourceBlock.text` and `block_id` must be the exact current W1 row. `Evidence.start/end` are Unicode-code-point offsets into that unchanged W1 text. `SourceBlock.page_number` is the page on which the selected evidence quote must resolve; it does not assert that the entire W1 chunk belongs to that page.

The existing serving verifier proves the required construction order:

1. Read the exact W1 block and select a non-empty `[start,end)` quote from its text.
2. Find the exact quote in one saved native page, requiring exactly one occurrence on that page.
3. Assign that page to the one `SourceBlock` for `(revision_id,block_id)`.
4. Keep the W1 block ID, full text, and offsets unchanged. Later verification first checks the W1 substring, then resolves the same quote uniquely inside the assigned native page and checks char-box completeness.

Native global offsets are only join evidence. They are not copied into C `Evidence.start/end`. A quote crossing a native page boundary is not usable. A chunk spanning several pages may be used for one assigned page only; its cited range must lie wholly inside that page and uniquely match there.

The construction may select blocks/pages mechanically from already frozen model-returned evidence quotes and reject unresolved/ambiguous joins. It must not create labels or Evidence facts from native regex observations, and it must not alter a block to make it page-local.

## Mechanical local checks

For the eleven offline splitter outputs, every one of the 204 recorded `[start,end)` ranges reproduced its `content_sha256` from the exact saved native Markdown. The page-overlap counts were:

| material | chunks | wholly one page | cross-page | max pages in one chunk |
|---|---:|---:|---:|---:|
| 07 | 34 | 33 | 1 | 2 |
| 08 | 40 | 35 | 5 | 3 |
| 09 | 9 | 8 | 1 | 2 |
| 11 | 9 | 9 | 0 | 1 |
| 12 | 41 | 38 | 3 | 2 |
| 13 | 11 | 10 | 1 | 2 |
| 14 | 8 | 7 | 1 | 2 |
| 17 | 42 | 41 | 1 | 2 |
| 18 | 6 | 1 | 5 | 2 |
| 19 | 2 | 2 | 0 | 1 |
| 21 | 2 | 0 | 2 | 3 |

Every offline chunk had at least one page-local non-whitespace span of eight or more code points, so one page-valid quote is mechanically possible per chunk. Existing observations for 07, 08, 11, 12, 13, 14, and 17 placed both observed code/filing quotes in offline chunk 0 and native page 1, with exactly one occurrence on that page. These observations are feasibility checks, not C labels or Evidence.

The four old documents require actual saved W1 block text rather than offline Markdown slicing. Existing G2 vectors already demonstrate successful quote-driven joins for 01, 03, and 04. Material 02 has saved current chunks and native capture, but its eventual C source blocks still require the same exact W1-substring/native-page unique-match procedure after target readback; old C5 locator values must not be reused.

## BLOCKER

There is no general structural blocker for a single page-valid citation from any of the eleven offline documents. Offline outputs are predictions, so actual target W1 IDs/text and manifest must still be reread before constructing real `SourceBlock` values.

There is one reproducible coverage blocker for `g3-material-21` if C must produce native-resolvable evidence for product rows across its full five-page list. The document has only two W1 chunks; both cross pages, while C permits only one `SourceBlock` per `(revision_id,block_id)` and each block has one `page_number`. At most two native pages can therefore be represented without duplicating a block key. Saved native content shows substantive product rows on all five pages. No choice of two page numbers can make rows on the other three pages verifiable under the existing serving check.

This does not prevent a partial C entry citing at most two selected pages. It does prevent claiming complete page-level evidence coverage of the five-page multi-product list. The blocker must be assessed against the intended material-21 coverage after actual W1 readback; it cannot be repaired by copying blocks, changing IDs/text/offsets, inventing Evidence, or assigning a cross-page quote.

## Reproducible references

- `docs/insurance-kb/evidence/830-g3/native-capture-inventory-v2.json`
- `docs/insurance-kb/evidence/830-g3/native_runtime_assets_independent_verify.py:27-53`
- `docs/insurance-kb/evidence/830-g3/existing-native-preservation.json`
- `docs/insurance-kb/evidence/830-g3/c-source-wiring-inventory-01.md:25-31,47-54`
- `docs/insurance-kb/evidence/830-g3/offline_embedding_inputs.go:105-142`
- `/private/tmp/g3-embedding-prepared-v1/embedding-whitelist.json`
- `harness/src/insurance_harness/knowledge_compiler/concept_free_wiki_830_g2.py:123-188`
- `internal/application/service/concept_source_authority_830_g2.go:238-311,403-505`

Status: `READ_ONLY_REVIEW_COMPLETE_WITH_CONDITIONAL_MATERIAL_21_BLOCKER`
