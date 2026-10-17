"""S4i acceptance: list markers, glued headings and the length cap end segments at real boundaries.

Protected file: written by Claude (Spec §3.1, revised after review R1/R2 on #200). Three defects
reached the published 1828 page: a bullet list ran into one 340-character segment, the cap cut it
mid-sentence, and a heading the PDF extractor glued onto the previous line ("效力中止。 责任免除")
merged two provisions. Segments stay a partition of the page's non-blank text in page coordinates.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.evidence.segments import MAX_CHARS, Segment, SegmentedSource

REPO = Path(__file__).resolve().parents[3]
SYMBOL_FONT_BULLET = chr(0xF06C)  # what a Wingdings bullet becomes in extracted PDF text
GLUED_SYMBOL = chr(0xF043)  # a symbol-font glyph written straight against its text
IDEOGRAPHIC_SPACE = chr(0x3000)


class Page:
    def __init__(self, document: str, page: int, text: str, sha: str = "a" * 64) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, page, text


def texts(*pages: Page) -> list[str]:
    return [segment.text for segment in SegmentedSource(list(pages)).segments]


def assert_partition(text: str, segments: Sequence[Segment]) -> None:
    """Non-empty, ordered, disjoint slices whose gaps are blank and that cover all other text."""
    previous = 0
    for segment in segments:
        assert previous <= segment.start < segment.end <= len(text)
        assert text[segment.start : segment.end] == segment.text
        assert not text[segment.start].isspace() and not text[segment.end - 1].isspace()
        assert not text[previous : segment.start].strip()
        previous = segment.end
    assert not text[previous:].strip()


@pytest.mark.parametrize("marker", [SYMBOL_FONT_BULLET, "●", "①"])
def test_a_list_marker_line_opens_a_segment(marker: str) -> None:
    page = Page(
        "产品说明书.pdf",
        1,
        f"产品特色\n{marker} 甲种保障\n提供甲种保障，以一次为限\n{marker} 乙种保障\n乙种保险金\n",
    )
    assert texts(page) == [
        "产品特色",
        f"{marker} 甲种保障\n提供甲种保障，以一次为限",
        f"{marker} 乙种保障\n乙种保险金",
    ]


def test_symbols_that_are_not_separated_list_markers_do_not_open_a_segment() -> None:
    page = Page(
        "保险条款.pdf",
        1,
        f"前文内容\n{GLUED_SYMBOL}您拥有的重要权益\n选项如下\n√ 是\n□ 否\n甲 ● 乙\n"
        f"{SYMBOL_FONT_BULLET} 犹豫期为20日。\n",
    )
    assert texts(page) == [
        f"前文内容\n{GLUED_SYMBOL}您拥有的重要权益\n选项如下\n√ 是\n□ 否\n甲 ● 乙",
        f"{SYMBOL_FONT_BULLET} 犹豫期为20日。",
    ]


@pytest.mark.parametrize("gap", [" ", "\t", IDEOGRAPHIC_SPACE, "  "])
def test_a_terminator_followed_by_space_and_text_ends_the_segment(gap: str) -> None:
    page = Page(
        "产品说明书.pdf",
        4,
        f"未还款项达到现金价值时，合同的\n效力中止。{gap}责任免除\n因下列情形之一导致的，我们不承担责任。\n",
    )
    assert texts(page) == [
        "未还款项达到现金价值时，合同的\n效力中止。",
        "责任免除\n因下列情形之一导致的，我们不承担责任。",
    ]


def test_a_line_can_split_more_than_once_and_each_piece_follows_the_line_rules() -> None:
    page = Page("保险条款.pdf", 2, "甲规定。 乙规定！？ 2.1 丙条款 内容\n续写完毕。\n")
    assert texts(page) == ["甲规定。", "乙规定！？", "2.1 丙条款 内容\n续写完毕。"]


def test_a_terminator_without_following_space_does_not_split() -> None:
    page = Page("保险条款.pdf", 2, "效力中止。责任免除的内容\n继续写完。\n")
    assert texts(page) == ["效力中止。责任免除的内容\n继续写完。"]


def capped_page(size: int) -> Page:
    """A run of `size` counted characters, one terminator in its first line, none at a line end."""
    first = "甲" * 9 + "。" + "乙" * 40
    rest = "丙" * (size - len(first))
    lines = [first, *(rest[i : i + 50] for i in range(0, len(rest), 50))]
    return Page("产品说明书.pdf", 1, "\n".join(lines))  # no trailing line break


@pytest.mark.parametrize("size", [MAX_CHARS - 1, MAX_CHARS, MAX_CHARS + 1])
def test_the_cap_is_reached_at_max_chars_and_cuts_after_the_last_terminator(size: int) -> None:
    page = capped_page(size)
    found = texts(page)
    if size < MAX_CHARS:
        assert found == [page.text]
    else:
        assert found == ["甲" * 9 + "。", page.text[10:]]
    assert_partition(page.text, SegmentedSource([page]).segments)


def test_a_rest_that_still_reaches_the_cap_is_cut_where_the_piece_ends() -> None:
    page = Page("产品说明书.pdf", 1, "甲" * 9 + "。" + "乙" * 40 + "\n" + "丙" * 300 + "\n丁丁丁。")
    assert texts(page) == ["甲" * 9 + "。", "乙" * 40 + "\n" + "丙" * 300, "丁丁丁。"]


def test_a_long_piece_without_terminators_is_not_cut_inside() -> None:
    page = Page("附表.pdf", 1, "戊" * 400 + "\n己己。")
    assert texts(page) == ["戊" * 400, "己己。"]


def test_without_any_terminator_the_cap_still_cuts_at_a_line_end() -> None:
    lines = [f"{age} 岁 1000 元 2000 元 3000 元" for age in range(60)]
    page = Page("附表.pdf", 1, "\n".join(lines))
    segments = SegmentedSource([page]).segments
    assert len(segments) > 1
    for segment in segments:
        assert page.text[segment.end : segment.end + 1] in {"", "\n"}


SYNTHETIC = [
    f"标题\r\n引言。 产品特色\r\n{SYMBOL_FONT_BULLET} 甲\r\n说明。{IDEOGRAPHIC_SPACE}乙\r\n"
    + "戊" * 400,
    "  \n\n首行。  \t次行内容\n\n\n① 列表项。 ② 次项\n" + "庚。" * 200,
    "无终止符" * 120,
    "",
]


@pytest.mark.parametrize("text", SYNTHETIC)
def test_segments_partition_a_synthetic_page(text: str) -> None:
    page = Page("产品说明书.pdf", 1, text)
    assert_partition(text, SegmentedSource([page]).segments)


@pytest.mark.parametrize("product", ["1828", "1824"])
def test_segments_partition_every_real_page(product: str) -> None:
    source = SegmentedSource(source_pages(source_directory(REPO, product)))
    for page in source.pages:
        on_page = [s for s in source.segments if (s.document, s.page) == (page.document, page.page)]
        assert_partition(page.text, on_page)


def test_a_leading_list_marker_is_ignored_when_comparing_copies() -> None:
    # The marked passage is the shorter one, so its marker would otherwise break containment.
    sentence = "犹豫期内您可以要求全额退还保险费，我们将退还已收取的全部保险费，"
    source = SegmentedSource(
        [
            Page("产品说明书.pdf", 1, f"{SYMBOL_FONT_BULLET} {sentence}\n"),
            Page("保险条款.pdf", 3, f"6.1 {sentence}犹豫期后解除合同会有损失。\n", "b" * 64),
        ]
    )
    brochure, terms = source.segments
    assert brochure.text.startswith(SYMBOL_FONT_BULLET)  # the quote itself keeps the marker
    assert source.copies(brochure.id) == {terms.id}


@pytest.mark.parametrize("prefix", ["√", "√ ", SYMBOL_FONT_BULLET])
def test_a_symbol_that_is_not_a_separated_marker_is_not_stripped(prefix: str) -> None:
    sentence = "犹豫期内您可以要求全额退还保险费，我们将退还已收取的全部保险费，"
    source = SegmentedSource(
        [
            Page("产品说明书.pdf", 1, f"{prefix}{sentence}\n"),
            Page("保险条款.pdf", 3, f"6.1 {sentence}犹豫期后解除合同会有损失。\n", "b" * 64),
        ]
    )
    brochure, terms = source.segments
    assert source.copies(brochure.id) == frozenset()


# Regression on the reported pages, and the same rule on a second product of another type.
def segment_with(product: str, document: str, page: int, needle: str) -> str:
    source = SegmentedSource(source_pages(source_directory(REPO, product)))
    found = [
        s.text
        for s in source.segments
        if (s.document, s.page) == (document, page) and needle in s.text
    ]
    assert len(found) == 1, (product, needle)
    return found[0]


def test_the_1828_feature_bullet_is_its_own_complete_segment() -> None:
    text = segment_with("1828", "产品说明书.pdf", 1, "0-17 周岁投保享加护")
    assert "外给付" in text
    assert "产品特色" not in text and "120 种重大疾病保障" not in text


@pytest.mark.parametrize(("product", "page"), [("1828", 4), ("1824", 2)])
def test_the_exclusions_heading_no_longer_carries_the_loan_sentence(
    product: str, page: int
) -> None:
    assert "责任免除" not in segment_with(product, "产品说明书.pdf", page, "效力中止。")
    exclusions = segment_with(product, "产品说明书.pdf", page, "因下列情形之一导致")
    assert exclusions.startswith("责任免除")
