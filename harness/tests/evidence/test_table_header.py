"""S4j acceptance: a table page offers only its header block, never its rows (Spec §3.1, §3.3).

Protected file: written by Claude. A data row is a line of at least two tokens that are all numbers;
the header block runs from the page start to the last line before the first data row. A source read
with table headers numbers those documents after the evidence documents, so every existing id stays
the same, and cuts them only inside their header blocks, so no id can point at a rate.
"""

from __future__ import annotations

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource, header_block

ONE_ROW = (
    "《某某重大疾病保险》年交费率表\n（每万元基本保险金额）\n男性\n单位：人民币元\n"
    "　交费期间\n投保年龄\n10年交 15年交 20年交 30年交\n0 408 275 222 157\n1 416 280 226 160\n"
)
TWO_ROWS = (
    "《某某意外伤害保险》基本部分年交费率表\n（每万元基本保险金额）\n女性\n单位：人民币元\n"
    "保险期间 保10年 保15年\n 交费期间\n投保年龄\n10年交 10年交 15年交\n0 7.30 9.64 6.69\n"
)


def block(text: str) -> str | None:
    found = header_block(text)
    return None if found is None else text[found[0] : found[1]]


@pytest.mark.parametrize(
    ("text", "header"),
    [
        (ONE_ROW, ONE_ROW[: ONE_ROW.index("\n0 408")]),
        (TWO_ROWS, TWO_ROWS[: TWO_ROWS.index("\n0 7.30")]),
        ("年交费率表\n12\n0 408 275\n", "年交费率表\n12"),  # a lone number is not a row
        (
            "\n\n  标题\n-1.5 2,000 30%\n注：以上为年交保费。\n",
            "标题",
        ),  # notes after rows are not header
        ("标题\n- 10年 20年\n1 人 100%\n5 6\n", "标题\n- 10年 20年\n1 人 100%"),
    ],
    ids=["one header row", "two header rows", "page number", "signs and notes", "mixed lines"],
)
def test_the_header_block_ends_before_the_first_row_of_numbers(text: str, header: str) -> None:
    assert block(text) == header


@pytest.mark.parametrize(
    "text",
    [
        "60 1000 900\n61 1010 910\n",  # a continuation page starts with rows
        "费率计算公式\n保险费=单位费率×家庭费率因子\n1 人 100%\n",  # no row of numbers at all
        "",
    ],
    ids=["continuation", "no rows", "empty"],
)
def test_a_page_without_a_header_before_its_rows_has_no_block(text: str) -> None:
    assert header_block(text) is None


SHA_T, SHA_B, SHA_R = "a" * 64, "b" * 64, "c" * 64
TERMS = PageText(
    "保险条款.pdf", SHA_T, 1, "阅读指引\n1.4 等待期\n自本合同生效之日起90日内为等待期。\n"
)
BROCHURE = PageText("产品说明书.pdf", SHA_B, 1, "产品说明书\n交费方式由您与我们约定。\n")
RATE_PAGES = [
    PageText("费率表.pdf", SHA_R, 1, ONE_ROW),
    PageText("费率表.pdf", SHA_R, 2, ONE_ROW.replace("男性", "女性")),
    PageText("费率表.pdf", SHA_R, 3, "60 1000 900\n61 1010 910\n"),
]


def test_header_documents_are_numbered_last_and_cut_only_inside_their_blocks() -> None:
    plain = SegmentedSource([TERMS, BROCHURE])
    source = SegmentedSource([TERMS, BROCHURE], table_headers={"rate_table": RATE_PAGES})

    def kept(s: SegmentedSource) -> list[tuple[str, str, int, int]]:
        return [
            (x.id, x.document, x.start, x.end) for x in s.segments if x.document != "费率表.pdf"
        ]

    assert kept(source) == kept(plain)
    header = [x for x in source.segments if x.document == "费率表.pdf"]
    assert header and {x.id[:3] for x in header} == {"D3P"}
    assert {x.page for x in header} == {1, 2}
    for segment in header:
        page = RATE_PAGES[segment.page - 1]
        start, end = header_block(page.text) or (0, 0)
        assert start <= segment.start < segment.end <= end
        assert page.text[segment.start : segment.end] == segment.text
    joined = "".join(x.text for x in header if x.page == 1)
    assert "10年交 15年交 20年交 30年交" in joined
    listing = source.listing()
    assert "0 408" not in listing and "60 1000" not in listing and "1 416" not in listing
    assert source.header_role("费率表.pdf") == "rate_table"
    assert source.header_role("保险条款.pdf") is None
    assert source.header_role("没有这份.pdf") is None


def test_without_table_headers_nothing_changes() -> None:
    assert [x.id for x in SegmentedSource([TERMS, BROCHURE], table_headers=None).segments] == [
        x.id for x in SegmentedSource([TERMS, BROCHURE]).segments
    ]
    assert SegmentedSource([TERMS]).header_role("保险条款.pdf") is None


def test_a_header_document_cannot_also_be_an_evidence_document() -> None:
    with pytest.raises(ValueError):
        SegmentedSource([TERMS, RATE_PAGES[0]], table_headers={"rate_table": RATE_PAGES[1:]})
