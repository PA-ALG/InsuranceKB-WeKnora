"""S11c acceptance: Harness reads Office source pages with their located blocks (Spec §2.1).

Protected file: written by Claude. S11b serves an Office capture's pages with blocks; each block
is a code-point range of the page text and carries its Office locator (PPTX_SHAPE{slide},
DOCX_BLOCK{block_index}, XLSX_CELL_RANGE{sheet, row range}). The reader returns OfficePageText,
a PageText that also carries the blocks, and refuses any page set whose blocks do not cut its text
exactly as the platform builds it. PDF page sets are returned exactly as before.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from insurance_harness.contracts import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficeBlock, OfficePageText
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages

BASE = "https://weknora.example"
DOC_SHA = hashlib.sha256(b"office bytes").hexdigest()
Body = dict[str, Any]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page(number: int, *blocks: tuple[str, Body]) -> Body:
    """A page as the platform builds it: block texts joined by a blank line."""
    text, located, offset = "", [], 0
    for index, (block_text, locator) in enumerate(blocks):
        if index:
            text += "\n\n"
            offset += 2
        located.append(
            {
                "block_id": f"b{index}",
                "end": offset + len(block_text),
                "locator": locator,
                "start": offset,
            }
        )
        text += block_text
        offset += len(block_text)
    body: Body = {"page_number": number, "text": text, "page_text_sha256": sha(text)}
    if located:
        body["blocks"] = located
    return body


def slide(number: int) -> Body:
    return {"kind": "PPTX_SHAPE", "slide": number}


def block(index: int) -> Body:
    return {"kind": "DOCX_BLOCK", "block_index": index}


def rows(sheet: str, row: int) -> Body:
    return {"kind": "XLSX_CELL_RANGE", "sheet": sheet, "cell_range": f"A{row}:XFD{row}"}


def page_set(name: str, *pages: Body) -> Body:
    return {
        "knowledge_id": "k-1",
        "parse_attempt": 2,
        "document": name,
        "document_sha256": DOC_SHA,
        "parser_identity_sha256": sha("ooxml"),
        "native_sha256": sha("native"),
        "pages": list(pages),
    }


def deck() -> Body:
    return page_set(
        "产品培训.pptx",
        page(1, ("产品亮点", slide(1)), ("保障𠮷全面，交费灵活。", slide(1))),
        page(2),  # a slide without text: the platform omits its blocks
        page(3, ("一、开场话术。\n二、需求挖掘。", slide(3))),
    )


def document() -> Body:
    return page_set(
        "销售话术.docx",
        page(1, ("话术标题", block(0)), ("问：保费贵吗？\n答：可以按年交。", block(2))),
    )


def workbook() -> Body:
    return page_set(
        "常见问题.xlsx",
        page(1, ("问题\t回答", rows("问答", 1)), ("犹豫期多长\t15日", rows("问答", 3))),
        page(2, ("话术\t场景", rows("话术", 2))),
    )


def read(body: object) -> list[PageText]:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    return WeKnoraSourcePages(BASE, "key-123", transport=transport).pages("space-1", "k-1", 2)


def office(body: object) -> list[OfficePageText]:
    pages = read(body)
    assert all(type(p) is OfficePageText for p in pages)
    return [p for p in pages if isinstance(p, OfficePageText)]


# 1. What the reader returns ----------------------------------------------------------------------


def test_deck_pages_carry_their_blocks_and_slide_locators() -> None:
    pages = office(deck())
    assert all(isinstance(p, PageText) for p in pages), "every compiler page reader accepts them"
    first, empty, third = pages
    assert (first.document, first.document_sha256, first.page) == ("产品培训.pptx", DOC_SHA, 1)
    assert first.text == "产品亮点\n\n保障𠮷全面，交费灵活。"
    assert first.blocks == (
        OfficeBlock(start=0, end=4, locator=Locator(kind="PPTX_SHAPE", slide=1)),
        OfficeBlock(start=6, end=17, locator=Locator(kind="PPTX_SHAPE", slide=1)),
    )
    assert first.text[first.blocks[1].start : first.blocks[1].end] == "保障𠮷全面，交费灵活。"
    assert (empty.page, empty.text, empty.blocks) == (2, "", ())
    assert third.blocks[0].locator.slide == 3 and third.blocks[0].locator.shape_id is None


def test_document_and_workbook_locators() -> None:
    [only] = office(document())
    assert [b.locator for b in only.blocks] == [
        Locator(kind="DOCX_BLOCK", block_index=0),
        Locator(kind="DOCX_BLOCK", block_index=2),
    ]
    sheets = office(workbook())
    assert [(b.locator.sheet, b.locator.cell_range) for p in sheets for b in p.blocks] == [
        ("问答", "A1:XFD1"),
        ("问答", "A3:XFD3"),
        ("话术", "A2:XFD2"),
    ]


def test_an_empty_blocks_list_means_the_same_as_none() -> None:
    body = deck()
    body["pages"][1]["blocks"] = []
    assert office(body)[1].blocks == ()


def test_pdf_page_sets_still_become_plain_page_text() -> None:
    text = "第一条 本合同。"
    body = page_set("保险条款.pdf", {"page_number": 1, "text": text, "page_text_sha256": sha(text)})
    [only] = read(body)
    assert type(only) is PageText
    assert only == PageText("保险条款.pdf", DOC_SHA, 1, text)


def test_office_page_text_checks_its_own_blocks() -> None:
    locator = Locator(kind="PPTX_SHAPE", slide=1)
    first, second = (OfficeBlock(start=0, end=1, locator=locator),
                     OfficeBlock(start=3, end=4, locator=locator))
    assert OfficePageText("a.pptx", DOC_SHA, 1, "甲\n\n乙", (first, second)).blocks[1] == second
    with pytest.raises(ValueError):  # not joined by a blank line
        OfficePageText("a.pptx", DOC_SHA, 1, "甲\n乙", (first, OfficeBlock(2, 3, locator)))
    with pytest.raises(ValueError):  # text without blocks
        OfficePageText("a.pptx", DOC_SHA, 1, "甲", ())
    with pytest.raises(ValueError):  # a locator that is not an Office block
        OfficePageText("a.pptx", DOC_SHA, 1, "甲", (
            OfficeBlock(0, 1, Locator(kind="PDF_TEXT_SPAN", page=1, start=0, end=1)),
        ))


# 2. Integrity: any page set the platform could not have built is refused -------------------------

Change = Callable[[Body], None]


def mutate(build: Callable[[], Body], change: Change) -> Callable[[], Body]:
    def body() -> Body:
        result = copy.deepcopy(build())
        change(result)
        return result

    return body


def set_text(number: int, text: str) -> Change:
    def change(body: Body) -> None:
        body["pages"][number - 1].update(text=text, page_text_sha256=sha(text))

    return change


def edit_block(number: int, index: int, **fields: object) -> Change:
    def change(body: Body) -> None:
        body["pages"][number - 1]["blocks"][index].update(fields)

    return change


def edit_locator(number: int, index: int, **fields: object) -> Change:
    def change(body: Body) -> None:
        body["pages"][number - 1]["blocks"][index]["locator"].update(fields)

    return change


def drop_locator_key(number: int, index: int, key: str) -> Change:
    def change(body: Body) -> None:
        del body["pages"][number - 1]["blocks"][index]["locator"][key]

    return change


def unchanged(body: Body) -> None:
    return None


def white_space_block() -> Body:
    return page_set("a.pptx", page(1, ("标题", slide(1)), ("  ", slide(1))))


REFUSED: dict[str, Callable[[], Body]] = {
    "block beyond the page text": mutate(deck, edit_block(1, 1, end=40)),
    "blocks overlap": mutate(deck, edit_block(1, 1, start=3)),
    "blocks out of order": mutate(deck, lambda b: b["pages"][0]["blocks"].reverse()),
    "an empty block": mutate(deck, edit_block(1, 0, end=0)),
    "a negative start": mutate(deck, edit_block(1, 0, start=-1)),
    "a boolean offset": mutate(deck, edit_block(1, 0, start=False)),
    "a duplicate block id": mutate(deck, edit_block(1, 1, block_id="b0")),
    "a blank block id": mutate(deck, edit_block(1, 1, block_id=" ")),
    "an undeclared block field": mutate(deck, edit_block(1, 0, shape="title")),
    "page text is not the blocks joined by a blank line": mutate(
        deck, set_text(1, "产品亮点\n保障𠮷全面，交费灵活。")
    ),
    "text after the last block": mutate(deck, set_text(1, "产品亮点\n\n保障𠮷全面，交费灵活。尾")),
    "a white-space block": mutate(white_space_block, unchanged),
    "an Office page with text but no blocks": mutate(deck, set_text(2, "无块文字")),
    "a null blocks list": mutate(deck, lambda b: b["pages"][1].update(blocks=None)),
    "a slide locator on another page": mutate(deck, edit_locator(3, 0, slide=2)),
    "a slide locator with a shape id": mutate(deck, edit_locator(1, 0, shape_id="title")),
    "a slide locator with a block index": mutate(deck, edit_locator(1, 0, block_index=0)),
    "a slide locator without its slide": mutate(deck, drop_locator_key(1, 0, "slide")),
    "a text-span locator": mutate(
        deck,
        edit_locator(1, 0, kind="PDF_TEXT_SPAN", slide=None, page=1, start=0, end=4),
    ),
    "an undeclared locator kind": mutate(deck, edit_locator(1, 0, kind="SLIDE")),
    "two locator kinds in one document": mutate(
        deck, lambda b: b["pages"][2]["blocks"][0].update(locator=block(0))
    ),
    "a document over two pages": mutate(
        document, lambda b: b["pages"].append(page(2, ("尾", block(3))))
    ),
    "block indexes that do not increase": mutate(document, edit_locator(1, 1, block_index=0)),
    "a cell range that is not one whole row": mutate(
        workbook, edit_locator(1, 0, cell_range="A1:C1")
    ),
    "a row range over two rows": mutate(workbook, edit_locator(1, 0, cell_range="A1:XFD2")),
    "rows that do not increase": mutate(workbook, edit_locator(1, 1, cell_range="A1:XFD1")),
    "two sheets on one page": mutate(workbook, edit_locator(1, 1, sheet="话术")),
    "one sheet on two pages": mutate(workbook, edit_locator(2, 0, sheet="问答")),
    "a blank sheet": mutate(workbook, edit_locator(2, 0, sheet=" ")),
}


@pytest.mark.parametrize("build", REFUSED.values(), ids=REFUSED.keys())
def test_inconsistent_office_pages_are_refused(build: Callable[[], Body]) -> None:
    with pytest.raises(SourcePagesError) as refused:
        read(build())
    assert refused.value.code == "PARSE_ARTIFACT_INTEGRITY"
    assert "产品" not in str(refused.value) and "话术" not in str(refused.value)
