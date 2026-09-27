# G3 C pre-model block-to-page freeze — bounded read-only review 01

Date: 2026-09-07
Status: `DESIGN_PREPARATION_PASS_WITH_ENTRY_GATE_AND_MATERIAL_21_BACKLOG`
Effect: local saved-byte reads only; no HTTP, parser, DB, provider, model, upload, policy permit, product write, or business Evidence/label was created.

## Result

The saved native layout is sufficient to propose and independently verify one page assignment for an exact W1 block. Each inspected native projection binds exact Markdown page intervals and page hashes, and supplies boxes that cover every non-whitespace code point exactly once. The existing serving verifier can therefore recheck a frozen W1 quote against its assigned native page without changing the W1 block ID, full text, or Unicode offsets.

The map instance cannot be finalized for materials 17 or 21 from the offline splitter output. Those ranges are feasibility predictions, not actual target source rows. Final rows require SOURCE_PASS plus actual revision/chunk readback and its W1 manifest.

## Minimum freeze

Freeze one canonical manifest only after actual W1 readback. Its header binds the actual space/RAW-KB, knowledge ID, parse attempt, Registered Source revision ID, W1 manifest digest, native projection SHA, Markdown SHA, and parser-identity SHA. Each row binds:

- the unique `(revision_id, block_id)` key, chunk index, full unchanged W1 text SHA, and the selected `page_number`;
- one nonempty page-local proof anchor as W1 Unicode `[start,end)`, quote SHA, selected page-text SHA, native global range, and aggregate bbox;
- validation facts that the W1 slice equals the quote, the quote occurs exactly once in the selected native page, all visible quote code points have boxes, and the row's input identities match the header.

Reject absent proof anchors, duplicate `(revision_id,block_id)` rows, a second page for the same key, changed W1 text/ID, cross-page anchors, ambiguous page matches, or input-identity drift. Candidate anchors can be enumerated mechanically from exact page-local W1 substrings. The selected candidate is reviewed and frozen before any model call; it is not inferred from a later model answer.

Construct each later C `SourceBlock` directly from its single frozen row. The model may return Evidence only for that block's already-selected page. Post-model validation must still require the proposed Unicode slice to equal the unchanged W1 text and resolve uniquely, with complete boxes, inside that same page. A different page is rejection; the preparation step must never copy the block under another key or rewrite its text.

This manifest is an input/custody artifact. It does not add a second source authority, Evidence DTO, source seal, or business label.

## Bounded sample evidence

- Old material 01: all four actual saved W1 rows had at least one globally unique, page-local exact-line anchor with complete bbox coverage. The deterministic probe's first candidates assigned chunk indices 0/2/8/10 to native pages 3/1/21/26. These are mechanical feasibility candidates, not approved business selections.
- Material 17: saved offline prediction 0 is wholly on page 1 and has a unique boxed candidate there. The sole inspected cross-page prediction, sequence 40 over pages 41–42, also has a unique page-local candidate (page 42). All 42 predicted ranges reproduced their exact Markdown hashes and had a candidate, but none supplies an actual W1 block ID.
- Material 21: both predicted ranges reproduce their hashes and cross pages (1–3 and 4–5). Each has a unique boxed candidate, on pages 2 and 5 in the mechanical probe. With two eventual unique block keys, at most two pages can be selected.

## Findings

- `BLOCKER: 0` for freezing the pre-model rule and manifest shape.
- `ENTRY GATE`: do not produce authoritative rows for the eleven new sources until actual W1 revision/chunks and manifest are read back. Offline predictions remain explicitly non-authoritative.
- `BACKLOG`: material 21 full five-page product-list coverage remains impossible with two unique W1 blocks and one page per block. Partial coverage of at most two selected pages is valid; it must not be described as full coverage or repaired by key duplication.
- `REJECTED`: using offline chunk IDs/ranges as source facts, delaying page choice until model output, assigning a cross-page quote, or duplicating/rewriting a block to cover more pages.

## Evidence identity

- Probe script: `/private/tmp/g3-c-premodel-page-freeze-probe-01.py`, SHA-256 `00f2207de0a62cfc8f0ce62c4530e98df96da036dec8821e31f86329d096b8c2`
- Probe output: `/private/tmp/g3-c-premodel-page-freeze-probe-01.json`, SHA-256 `45d46d4f30271b81b4cdf6593be3f1ccc4f9d29a506660d135cd3046354165ab`
- Inputs are named and hashed in the probe output. Native integrity checks passed for material 01, 17, and 21.
