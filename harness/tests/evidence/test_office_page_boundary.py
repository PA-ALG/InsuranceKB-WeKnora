"""S11c review R1/R2 on #479: the source-pages boundary decides Office by the presence of the
`blocks` key and refuses locator fields that do not belong to the block's kind (Spec §2.1).

R1: one page that declares `blocks`, even an empty list, makes the whole document Office, so a page
with text but no blocks is refused instead of being read as PDF text. A response without the key
on every page is a PDF page set as before. R2: an explicit null, or a key of another kind, is
refused before anything is normalised; a field that is genuinely omitted is not a violation.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx
import pytest

from insurance_harness.contracts import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficePageText
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages

DOC_SHA = hashlib.sha256(b"office bytes").hexdigest()
Body = dict[str, Any]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page(number: int, text: str, blocks: list[Body] | None) -> Body:
    body: Body = {"page_number": number, "text": text, "page_text_sha256": sha(text)}
    if blocks is not None:
        body["blocks"] = blocks
    return body


def block(text: str, locator: Body, start: int = 0) -> Body:
    return {"block_id": "b0", "start": start, "end": start + len(text), "locator": locator}


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


def read(body: Body) -> list[PageText]:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    return WeKnoraSourcePages("https://weknora.example", "key", transport=transport).pages(
        "space-1", "k-1", 2
    )


def refused(body: Body) -> None:
    with pytest.raises(SourcePagesError) as stopped:
        read(body)
    assert stopped.value.code == "PARSE_ARTIFACT_INTEGRITY"


TEXT = "产品说明书\n等待期为90日。"


# R1 -----------------------------------------------------------------------------------------------


def test_text_with_an_empty_blocks_list_is_refused_not_read_as_pdf() -> None:
    refused(page_set("产品说明书.docx", page(1, TEXT, [])))


def test_any_page_declaring_blocks_makes_every_page_office() -> None:
    first = "标题"
    deck = page_set(
        "产品培训.pptx",
        page(1, first, [block(first, {"kind": "PPTX_SHAPE", "slide": 1})]),
        page(2, "第二页文字", []),  # an explicitly empty list with text
    )
    refused(deck)
    deck["pages"][1] = page(2, "第二页文字", None)  # the key omitted, text kept
    refused(deck)


def test_a_document_of_explicitly_empty_pages_stays_office() -> None:
    pages = read(page_set("空白.pptx", page(1, "", []), page(2, "", [])))
    assert [type(p) for p in pages] == [OfficePageText, OfficePageText]
    assert all(p.blocks == () for p in pages if isinstance(p, OfficePageText))


def test_pages_without_the_key_are_a_pdf_page_set_as_before() -> None:
    [only] = read(page_set("产品说明书.pdf", page(1, TEXT, None)))
    assert type(only) is PageText and only.text == TEXT


# R2 -----------------------------------------------------------------------------------------------

DOCX = {"kind": "DOCX_BLOCK", "block_index": 0}
PPTX = {"kind": "PPTX_SHAPE", "slide": 1}
XLSX = {"kind": "XLSX_CELL_RANGE", "sheet": "问答", "cell_range": "A1:XFD1"}


def one_block(name: str, locator: Body) -> Body:
    return page_set(name, page(1, "等待期为90日。", [block("等待期为90日。", locator)]))


@pytest.mark.parametrize(
    ("name", "locator"),
    [
        ("a.docx", {**DOCX, "slide": None}),
        ("a.docx", {**DOCX, "sheet": None}),
        ("a.docx", {**DOCX, "cell_range": None}),
        ("a.docx", {**DOCX, "shape_id": None}),
        ("a.docx", {**DOCX, "slide": 1}),
        ("a.docx", {**DOCX, "block_index": None}),
        ("a.pptx", {**PPTX, "block_index": None}),
        ("a.pptx", {**PPTX, "shape_id": None}),
        ("a.pptx", {**PPTX, "sheet": "问答"}),
        ("a.pptx", {**PPTX, "slide": None}),
        ("a.xlsx", {**XLSX, "slide": None}),
        ("a.xlsx", {**XLSX, "block_index": 0}),
        ("a.xlsx", {**XLSX, "sheet": None}),
        ("a.xlsx", {"kind": None, "sheet": "问答", "cell_range": "A1:XFD1"}),
    ],
)
def test_explicit_nulls_and_keys_of_another_kind_are_refused(name: str, locator: Body) -> None:
    refused(one_block(name, locator))


@pytest.mark.parametrize(
    ("name", "locator", "expected"),
    [
        ("a.docx", DOCX, Locator(kind="DOCX_BLOCK", block_index=0)),
        ("a.pptx", PPTX, Locator(kind="PPTX_SHAPE", slide=1)),  # shape_id genuinely omitted
        ("a.xlsx", XLSX, Locator(kind="XLSX_CELL_RANGE", sheet="问答", cell_range="A1:XFD1")),
    ],
)
def test_each_kind_with_only_its_own_fields_is_read(
    name: str, locator: Body, expected: Locator
) -> None:
    [only] = read(one_block(name, locator))
    assert isinstance(only, OfficePageText)
    assert [b.locator for b in only.blocks] == [expected]
    assert only.blocks[0].locator.model_dump(exclude_unset=True) == expected.model_dump(
        exclude_unset=True
    )
