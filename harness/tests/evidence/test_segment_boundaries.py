"""S4i acceptance: bullets, glued headings and the length cap end segments at real boundaries.

Protected file: written by Claude (Spec §3.1). Three defects reached the published 1828 page: a
bullet list ran into one 340-character segment, the cap cut it mid-sentence, and a heading the
PDF extractor glued onto the previous line ("效力中止。 责任免除") merged two provisions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.evidence.segments import MAX_CHARS, SegmentedSource

REPO = Path(__file__).resolve().parents[3]
SYMBOL_FONT_BULLET = chr(0xF06C)  # what a Wingdings bullet becomes in extracted PDF text
IDEOGRAPHIC_SPACE = chr(0x3000)


class Page:
    def __init__(self, document: str, page: int, text: str, sha: str = "a" * 64) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, page, text


def texts(*pages: Page) -> list[str]:
    return [segment.text for segment in SegmentedSource(list(pages)).segments]


@pytest.mark.parametrize("bullet", [SYMBOL_FONT_BULLET, "●", "①"])
def test_a_bullet_line_opens_a_segment(bullet: str) -> None:
    page = Page(
        "产品说明书.pdf",
        1,
        f"产品特色\n{bullet} 甲种保障\n提供甲种保障，以一次为限\n{bullet} 乙种保障\n乙种保险金\n",
    )
    assert texts(page) == [
        "产品特色",
        f"{bullet} 甲种保障\n提供甲种保障，以一次为限",
        f"{bullet} 乙种保障\n乙种保险金",
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
    page = Page("保险条款.pdf", 2, "甲规定。 乙规定。 2.1 丙条款 内容\n续写完毕。\n")
    assert texts(page) == ["甲规定。", "乙规定。", "2.1 丙条款 内容\n续写完毕。"]


def test_a_terminator_without_following_space_does_not_split() -> None:
    page = Page("保险条款.pdf", 2, "效力中止。责任免除的内容\n继续写完。\n")
    assert texts(page) == ["效力中止。责任免除的内容\n继续写完。"]


def test_the_cap_cuts_after_the_last_terminator_and_carries_the_rest_forward() -> None:
    plain = ["甲" * 49] * 3
    mixed = "乙" * 20 + "。" + "丙" * 28
    tail = ["丁" * 49] * 3
    page = Page("产品说明书.pdf", 1, "\n".join([*plain, mixed, *tail]) + "\n")
    assert sum(len(line) for line in [*plain, mixed, *tail]) >= MAX_CHARS
    assert texts(page) == [
        "\n".join(plain) + "\n" + "乙" * 20 + "。",
        "丙" * 28 + "\n" + "\n".join(tail),
    ]


def test_without_any_terminator_the_cap_still_cuts_at_a_line_end() -> None:
    lines = [f"{age} 岁 1000 元 2000 元 3000 元" for age in range(60)]
    page = Page("附表.pdf", 1, "\n".join(lines))
    segments = SegmentedSource([page]).segments
    assert len(segments) > 1
    for segment in segments:
        assert page.text[segment.end : segment.end + 1] in {"", "\n"}


def test_every_segment_is_still_an_exact_slice_of_its_page() -> None:
    page = Page(
        "产品说明书.pdf",
        1,
        f"标题\r\n引言。 产品特色\r\n{SYMBOL_FONT_BULLET} 甲\r\n"
        f"说明。{IDEOGRAPHIC_SPACE}乙\r\n" + "戊" * 400,
    )
    for segment in SegmentedSource([page]).segments:
        assert page.text[segment.start : segment.end] == segment.text == segment.text.strip()


def test_a_leading_bullet_is_ignored_when_comparing_copies() -> None:
    # The bulleted passage is the shorter one, so its bullet would otherwise break containment.
    sentence = "犹豫期内您可以要求全额退还保险费，我们将退还已收取的全部保险费，"
    source = SegmentedSource(
        [
            Page("产品说明书.pdf", 1, f"{SYMBOL_FONT_BULLET} {sentence}\n"),
            Page("保险条款.pdf", 3, f"6.1 {sentence}犹豫期后解除合同会有损失。\n", "b" * 64),
        ]
    )
    brochure, terms = source.segments
    assert source.copies(brochure.id) == {terms.id}


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
