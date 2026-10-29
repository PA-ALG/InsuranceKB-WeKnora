"""Move Golden evidence to new document numbers when only the set of documents changed (S12d §6).

When a material is added to or left out of a product, the other documents are split exactly as
before; only their ordinal in segment ids (D1, D2, ...) moves. A quote therefore keeps its page and
sentence position. It is not looked up by its text: one page can hold two sentences with the same
text, and each quote must stay with the one its annotator chose. The segment at the new id must
carry the quote's document, fingerprint, page and text, or nothing is returned. For segmentation
changes use golden_remap, which maps by page position.
"""

import re

from insurance_harness.eval.golden_remap import RemapError
from insurance_harness.eval.segment_score import GoldenV2, GoldenV2Evidence
from insurance_harness.evidence.segments import SegmentedSource, same_text

_ORDINAL = re.compile(r"D[0-9]+(?=P[0-9]+S[0-9]+$)")


def reindex_documents(golden: GoldenV2, source: SegmentedSource) -> GoldenV2:
    """The same Golden with every quote's segment id on its document's current ordinal."""
    ordinal: dict[str, str] = {}
    for segment in source.segments:
        match = _ORDINAL.match(segment.id)
        if match is None:
            raise RemapError("REINDEX_MISMATCH", golden.product_id)
        ordinal.setdefault(segment.document, match.group(0))
    by_id = {segment.id: segment for segment in source.segments}

    def moved(quote: GoldenV2Evidence) -> GoldenV2Evidence:
        old = _ORDINAL.match(quote.segment_id or "")
        if old is None or quote.document not in ordinal:
            raise RemapError("REINDEX_MISMATCH", golden.product_id)
        new_id = ordinal[quote.document] + (quote.segment_id or "")[old.end() :]
        segment = by_id.get(new_id)
        if (
            segment is None
            or segment.document != quote.document
            or segment.document_sha256 != quote.document_sha256
            or segment.page != quote.page
            or not same_text(segment.text, quote.quote)
        ):
            raise RemapError("REINDEX_MISMATCH", golden.product_id)
        return quote.model_copy(update={"segment_id": new_id, "quote": segment.text})

    fields = tuple(
        field.model_copy(update={"evidence": tuple(moved(q) for q in field.evidence)})
        for field in golden.fields
    )
    return golden.model_copy(update={"fields": fields})
