"""Header inputs fail closed on ambiguous roles and retain page-local raw offsets."""

from typing import cast

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource, header_block


@pytest.mark.parametrize("role", [None, 1, "", " \t"])
def test_a_missing_or_malformed_role_cannot_make_header_pages_whole_evidence(role: object) -> None:
    page = PageText("table.pdf", "a" * 64, 1, "Header\n10 years\n0 999\n")
    with pytest.raises(ValueError):
        SegmentedSource([], table_headers={cast(str, role): [page]})


def test_one_header_document_cannot_be_assigned_two_roles_even_on_different_pages() -> None:
    first = PageText("table.pdf", "a" * 64, 1, "Header\n0 999\n")
    second = PageText("table.pdf", "a" * 64, 2, "Header\n1 888\n")
    with pytest.raises(ValueError):
        SegmentedSource([], table_headers={"one": [first], "two": [second]})


def test_leading_whitespace_is_preserved_in_original_page_coordinates() -> None:
    page = PageText(
        "table.pdf", "a" * 64, 1, "\r\n \t标题。\r\n交费期间\r\n10年交\r\n0 999\r\n注释。"
    )
    source = SegmentedSource([], table_headers={"rate_table": [page]})
    block = header_block(page.text)
    assert block is not None and block[0] > 0
    assert len(source.segments) == 2
    span = source.spans([s.id for s in source.segments])[0]
    assert (span.start, span.end) == block
    assert span.quote == page.text[span.start : span.end]
    assert "999" not in span.quote and "注释" not in span.quote
