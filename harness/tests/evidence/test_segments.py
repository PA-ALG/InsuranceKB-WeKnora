"""S4d acceptance: deterministic segmentation and code-built evidence (Spec §3.1).

Protected file: written by Claude. The model points at segment ids; everything the
platform later shows as a quote is cut from page text by this module, so every
quote must be an exact slice of the page it names.
"""

from __future__ import annotations

import pytest

from insurance_harness.evidence.quote_verification import QuoteMatch
from insurance_harness.evidence.segments import SegmentedSource

SHA_A, SHA_B = "a" * 64, "b" * 64


class Page:
    def __init__(self, document: str, page: int, text: str, sha: str = SHA_A) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, page, text


TERMS = Page(
    "保险条款.pdf",
    3,
    "1.4 等待期\n自本合同生效之日起90日内为等待期。\n因意外伤害发生保险事故的，\n无等待期。\n"
    "1.5 保险责任\n（一）身故保险金\n按基本保险金额给付。\n",
)
BROCHURE = Page("产品说明书.pdf", 1, "本产品保险期间为一年；\n可续保。\n", SHA_B)


def source() -> SegmentedSource:
    return SegmentedSource([TERMS, BROCHURE])


def test_ids_follow_document_order_page_and_sequence() -> None:
    ids = [s.id for s in source().segments]
    assert ids[0] == "D1P3S1" and ids[-1].startswith("D2P1S")
    assert [s.id for s in source().segments if s.document == "产品说明书.pdf"] == [
        "D2P1S1",
        "D2P1S2",
    ]


def test_terminators_and_clause_numbers_split_lines_into_segments() -> None:
    texts = [s.text for s in source().segments if s.document == "保险条款.pdf"]
    assert texts == [
        "1.4 等待期\n自本合同生效之日起90日内为等待期。",
        "因意外伤害发生保险事故的，\n无等待期。",
        "1.5 保险责任",
        "（一）身故保险金\n按基本保险金额给付。",
    ]


def test_long_text_without_terminators_is_cut_into_bounded_segments() -> None:
    table = Page(
        "费率表.pdf", 1, "\n".join(f"{age} 岁 1000 元 2000 元 3000 元" for age in range(60))
    )
    segments = SegmentedSource([table]).segments
    assert len(segments) > 1
    assert all(len(s.text) <= 300 + 40 for s in segments)


def test_every_segment_is_an_exact_slice_of_its_page() -> None:
    pages = {(p.document, p.page): p for p in (TERMS, BROCHURE)}
    for s in source().segments:
        page = pages[(s.document, s.page)]
        assert page.text[s.start : s.end] == s.text == s.text.strip()
        assert s.document_sha256 == page.document_sha256


def test_segmentation_is_deterministic() -> None:
    assert [s.model_dump() for s in source().segments] == [
        s.model_dump() for s in source().segments
    ]


def test_duplicate_page_identity_is_rejected() -> None:
    with pytest.raises(ValueError):
        SegmentedSource([TERMS, Page("保险条款.pdf", 3, "重复的页")])


def test_listing_shows_id_and_text_one_segment_per_line() -> None:
    lines = source().listing().split("\n")
    assert lines[0] == "D1P3S1 1.4 等待期 自本合同生效之日起90日内为等待期。"
    assert len(lines) == len(source().segments)


def test_resolve_expands_ranges_in_reading_order_and_reports_bad_refs() -> None:
    ids, dropped = source().resolve(["D1P3S2", "D1P3S1-D1P3S3", "D9P9S9", "D1P3S4-D1P3S1", 7])
    assert ids == ["D1P3S2", "D1P3S1", "D1P3S3"]
    assert dropped == ["D9P9S9", "D1P3S4-D1P3S1", 7]


def test_evidence_merges_adjacent_segments_on_one_page_into_exact_quotes() -> None:
    quotes = source().evidence(["D1P3S1", "D1P3S2", "D1P3S4", "D2P1S1"])
    assert [(q.document, q.page) for q in quotes] == [
        ("保险条款.pdf", 3),
        ("保险条款.pdf", 3),
        ("产品说明书.pdf", 1),
    ]
    assert (
        quotes[0].quote
        == "1.4 等待期\n自本合同生效之日起90日内为等待期。\n因意外伤害发生保险事故的，\n无等待期。"
    )
    assert quotes[1].quote == "（一）身故保险金\n按基本保险金额给付。"
    assert all(q.match is QuoteMatch.EXACT for q in quotes)
    assert quotes[2].document_sha256 == SHA_B


def test_evidence_follows_reading_order_whatever_order_ids_arrive_in() -> None:
    assert source().evidence(["D1P3S2", "D1P3S1"]) == source().evidence(["D1P3S1", "D1P3S2"])
