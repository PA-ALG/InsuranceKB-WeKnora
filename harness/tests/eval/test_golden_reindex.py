"""S12d round 2 (#424 review R4; Spec §3 and §6): L3223's Golden moved to new document numbers by
position, not by text. Only the document ordinal changes; page and sentence position stay, and the
text at the new id is checked. Two same-page sentences with equal text each keep their own place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.eval.golden_reindex import reindex_documents
from insurance_harness.eval.golden_remap import RemapError
from insurance_harness.eval.product_sources import source_directory, trusted_source_pages
from insurance_harness.eval.segment_score import GoldenV2, GoldenV2Evidence, load_golden_v2
from insurance_harness.evidence.segments import SegmentedSource, same_text

REPO = Path(__file__).resolve().parents[3]
TERMS = "保险条款.pdf"
SAME_TEXT = {"D1P6S7", "D1P6S14"}  # each has an equal-text twin on the same page
CLAIM_DOCUMENTS = "claim_application_deadline_and_documents"


def current_source() -> SegmentedSource:
    trusted = trusted_source_pages(source_directory(REPO, "L3223"))
    return SegmentedSource(trusted.evidence, table_headers=trusted.table_headers)


def stored() -> GoldenV2:
    return load_golden_v2(REPO / "dataset/golden/v2/L3223.json")


def with_ids(golden: GoldenV2, change: dict[str, str]) -> GoldenV2:
    """The same Golden with each quote's id prefix replaced (old ordinal -> new or vice versa)."""

    def moved(quote: GoldenV2Evidence) -> GoldenV2Evidence:
        sid = quote.segment_id or ""
        for old, new in change.items():
            if sid.startswith(old + "P"):
                return quote.model_copy(update={"segment_id": new + sid[len(old) :]})
        return quote

    fields = tuple(
        f.model_copy(update={"evidence": tuple(moved(q) for q in f.evidence)})
        for f in golden.fields
    )
    return golden.model_copy(update={"fields": fields})


def ids(golden: GoldenV2) -> list[str]:
    return [q.segment_id or "" for f in golden.fields for q in f.evidence]


def test_the_stored_l3223_golden_is_its_annotation_moved_from_d2_to_d1() -> None:
    golden = stored()
    annotated = with_ids(golden, {"D1": "D2"})  # the ids the judge saw, with the brochure as D1
    assert all(sid.startswith("D2P") for sid in ids(annotated))
    assert reindex_documents(annotated, current_source()) == golden


def test_equal_text_on_one_page_keeps_each_quotes_own_position() -> None:
    source = current_source()
    by_id = {s.id: s for s in source.segments}
    for sid in SAME_TEXT:
        twins = [
            s.id
            for s in source.segments
            if s.document == TERMS and s.page == 6 and same_text(s.text, by_id[sid].text)
        ]
        assert len(twins) == 2 and sid in twins, (sid, twins)  # looking up by text is ambiguous
    reindexed = reindex_documents(with_ids(stored(), {"D1": "D2"}), source)
    field = next(f for f in reindexed.fields if f.field_key == CLAIM_DOCUMENTS)
    assert SAME_TEXT <= {q.segment_id for q in field.evidence}


@pytest.mark.parametrize("damage", ["text", "fingerprint", "page"])
def test_a_quote_that_does_not_match_its_new_position_stops(damage: str) -> None:
    golden = with_ids(stored(), {"D1": "D2"})
    field = next(f for f in golden.fields if f.evidence)
    quote = field.evidence[0]
    updates: dict[str, dict[str, object]] = {
        "text": {"quote": quote.quote + "（改）"},
        "fingerprint": {"document_sha256": "0" * 64},
        "page": {"page": quote.page + 1},
    }
    update = updates[damage]
    broken = field.model_copy(
        update={"evidence": (quote.model_copy(update=update), *field.evidence[1:])}
    )
    golden = golden.model_copy(
        update={"fields": tuple(broken if f is field else f for f in golden.fields)}
    )
    with pytest.raises(RemapError) as stopped:
        reindex_documents(golden, current_source())
    assert stopped.value.code == "REINDEX_MISMATCH"
