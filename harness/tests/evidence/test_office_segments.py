"""S11c acceptance: Office pages are split block by block, and evidence never crosses a block
(Spec §2.2, §2.3).

Protected file: written by Claude. Each block of an Office page is split on its own with the PDF
rules; segment ids stay D<n>P<p>S<k>. Evidence slices merge adjacent segments only inside one
block, and `locator(span)` gives each slice the block's Office locator with page-text offsets.
PDF pages split, merge and locate exactly as before. S11d lets the platform verify Office locators,
so the bundle carries evidence on an Office page with its block locator (S11d Spec §4).
"""

from __future__ import annotations

import hashlib

import pytest

from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.contracts import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficeBlock, OfficePageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

SHA = hashlib.sha256(b"office").hexdigest()
PDF_SHA = hashlib.sha256(b"pdf").hexdigest()


def office_page(document: str, number: int, *blocks: tuple[str, Locator]) -> OfficePageText:
    text, located, offset = "", [], 0
    for index, (block_text, locator) in enumerate(blocks):
        if index:
            text, offset = text + "\n\n", offset + 2
        located.append(OfficeBlock(start=offset, end=offset + len(block_text), locator=locator))
        text, offset = text + block_text, offset + len(block_text)
    return OfficePageText(document, SHA, number, text, tuple(located))


def slide(number: int) -> Locator:
    return Locator(kind="PPTX_SHAPE", slide=number)


TITLE, BODY, LIST = "产品亮点", "保障全面", "开场话术。\n需求挖掘。"
DECK = office_page("产品培训.pptx", 1, (TITLE, slide(1)), (BODY, slide(1)), (LIST, slide(1)))
# The same text read as a PDF page: lines without a terminator run on into one segment.
AS_PDF = PageText("产品培训.pdf", PDF_SHA, 1, DECK.text)


def test_each_block_is_split_on_its_own() -> None:
    source = SegmentedSource([DECK])
    assert [(s.id, s.start, s.end, s.text) for s in source.segments] == [
        ("D1P1S1", 0, 4, TITLE),
        ("D1P1S2", 6, 10, BODY),
        ("D1P1S3", 12, 17, "开场话术。"),
        ("D1P1S4", 18, 23, "需求挖掘。"),
    ]
    assert [s.text for s in SegmentedSource([AS_PDF]).segments] == [
        "产品亮点\n\n保障全面\n\n开场话术。",
        "需求挖掘。",
    ], "PDF pages keep the S4d/S4i rules"


def test_evidence_merges_inside_a_block_but_never_across_blocks() -> None:
    source = SegmentedSource([DECK])
    assert [(s.start, s.end, s.quote) for s in source.spans(["D1P1S1", "D1P1S2"])] == [
        (0, 4, TITLE),
        (6, 10, BODY),
    ]
    assert [(s.start, s.end, s.quote) for s in source.spans(["D1P1S3", "D1P1S4"])] == [
        (12, 23, LIST),
    ]
    ids, dropped = source.resolve(["D1P1S2-D1P1S4"])
    assert dropped == [] and [q.quote for q in source.evidence(ids)] == [BODY, LIST]


def test_each_slice_carries_its_block_locator_with_page_offsets() -> None:
    source = SegmentedSource([DECK])
    [span] = source.spans(["D1P1S3", "D1P1S4"])
    assert source.locator(span) == Locator(kind="PPTX_SHAPE", slide=1, page=1, start=12, end=23)
    assert source.locator(span).shape_id is None


def test_document_and_workbook_slices_carry_their_locators() -> None:
    doc = office_page(
        "销售话术.docx",
        1,
        ("话术标题", Locator(kind="DOCX_BLOCK", block_index=0)),
        ("问：保费贵吗？", Locator(kind="DOCX_BLOCK", block_index=3)),
    )
    sheet = office_page(
        "常见问题.xlsx",
        2,
        ("犹豫期多长\t15日", Locator(kind="XLSX_CELL_RANGE", sheet="问答", cell_range="A4:XFD4")),
    )
    source = SegmentedSource([doc, sheet])
    located = [source.locator(span) for span in source.spans([s.id for s in source.segments])]
    assert located == [
        Locator(kind="DOCX_BLOCK", block_index=0, page=1, start=0, end=4),
        Locator(kind="DOCX_BLOCK", block_index=3, page=1, start=6, end=13),
        Locator(
            kind="XLSX_CELL_RANGE", sheet="问答", cell_range="A4:XFD4", page=2, start=0, end=9
        ),
    ]
    assert [s.id for s in source.segments] == ["D1P1S1", "D1P1S2", "D2P2S1"]


def test_pdf_slices_keep_their_text_span_locator() -> None:
    source = SegmentedSource([AS_PDF])
    [span] = source.spans(["D1P1S1", "D1P1S2"])
    assert source.locator(span) == Locator(kind="PDF_TEXT_SPAN", page=1, start=0, end=23)


def test_an_empty_office_page_has_no_segments() -> None:
    empty = OfficePageText("产品培训.pptx", SHA, 2, "", ())
    source = SegmentedSource([DECK, empty])
    assert {s.page for s in source.segments} == {1}
    assert len(source.pages) == 2


def test_one_document_cannot_mix_office_and_plain_pages() -> None:
    plain = PageText("产品培训.pptx", SHA, 2, "第二页")
    with pytest.raises(ValueError):
        SegmentedSource([DECK, plain])


def test_an_office_header_is_clipped_block_by_block() -> None:
    def row(number: int) -> Locator:
        return Locator(kind="XLSX_CELL_RANGE", sheet="费率", cell_range=f"A{number}:XFD{number}")

    rates = office_page(
        "费率表.xlsx",
        1,
        ("交费期间 投保年龄", row(1)),
        ("10年交 20年交", row(2)),
        ("0 408 275", row(3)),
    )
    source = SegmentedSource([], table_headers={"rate_table": [rates]})
    assert [s.text for s in source.segments] == ["交费期间 投保年龄", "10年交 20年交"]


def test_a_pptx_shape_locator_no_longer_needs_a_shape_id() -> None:
    assert Locator(kind="PPTX_SHAPE", slide=2).model_dump(exclude_none=True) == {
        "kind": "PPTX_SHAPE",
        "slide": 2,
    }
    with pytest.raises(ValueError):
        Locator(kind="PPTX_SHAPE")


def test_the_bundle_carries_office_evidence_with_its_block_locator() -> None:
    brochure = office_page(
        "产品说明书.docx", 1, ("产品说明书", Locator(kind="DOCX_BLOCK", block_index=0)),
        ("本产品保障期间为终身。", Locator(kind="DOCX_BLOCK", block_index=1)),
    )
    source = SegmentedSource([brochure])
    field = FieldResult(
        field_key="coverage_period",
        state="present",
        value="终身",
        evidence=source.evidence(["D1P1S2"]),
        segment_ids=["D1P1S2"],
    )
    output = CompileOutput(
        pack_id="pack", entity_id="p1", model="m", fields=[field], cards_version="cards-x"
    )
    claims = claims_from(output, source, {"产品说明书.docx": SourceRevision("k-1", 1)})
    (evidence,) = claims[0].evidence
    assert evidence.locator == Locator(kind="DOCX_BLOCK", block_index=1, page=1, start=7, end=18)
    assert evidence.quote == "本产品保障期间为终身。"
    assert (evidence.source_ref, evidence.file_sha256) == (f"source:v1:k-1:1:{SHA}", SHA)
