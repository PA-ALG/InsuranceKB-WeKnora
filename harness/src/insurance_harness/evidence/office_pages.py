"""Office source pages: page text plus the located blocks it is built from (S11c Spec §2.1).

The platform (S11b) builds each Office page from blocks: the page text is the block texts joined
by a blank line, and each block records its code-point range and its Office locator. A page here
re-checks exactly that, so a block range always cuts the text the locator names; anything the
platform could not have built is refused. Whole-document rules (one locator kind, one DOCX page,
one sheet per XLSX page) are checked by `check_office_document`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from insurance_harness.contracts.enums import LocatorKind
from insurance_harness.contracts.knowledge import Locator
from insurance_harness.eval.pdf_text import PageText

BLOCK_SEPARATOR = "\n\n"
# The fields each Office block locator carries, exactly: no shape or cell is located (S11b).
OFFICE_LOCATOR_FIELDS = {
    LocatorKind.PPTX_SHAPE: {"slide"},
    LocatorKind.DOCX_BLOCK: {"block_index"},
    LocatorKind.XLSX_CELL_RANGE: {"sheet", "cell_range"},
}
_ROW = re.compile(r"^A([1-9][0-9]*):XFD([1-9][0-9]*)$")


@dataclass(frozen=True)
class OfficeBlock:
    """One located text unit: page text [start, end) in code points, and where it sits."""

    start: int
    end: int
    locator: Locator


def row_of(locator: Locator) -> int | None:
    """The sheet row an XLSX block covers, or None when its range is not one whole row."""
    match = _ROW.fullmatch(locator.cell_range or "")
    return int(match[1]) if match and match[1] == match[2] else None


def _check_locator(locator: Locator, page: int) -> None:
    fields = OFFICE_LOCATOR_FIELDS.get(locator.kind)
    if fields is None or set(locator.model_dump(exclude_none=True)) != {"kind", *fields}:
        raise ValueError("not an Office block locator")
    if locator.kind == LocatorKind.PPTX_SHAPE and locator.slide != page:
        raise ValueError("a slide block on another page")
    if locator.kind == LocatorKind.XLSX_CELL_RANGE and (
        row_of(locator) is None or not (locator.sheet or "").strip()
    ):
        raise ValueError("a sheet block that is not one whole row")


@dataclass(frozen=True)
class OfficePageText(PageText):
    """A compiler page whose text is its blocks joined by a blank line (no blocks: no text)."""

    blocks: tuple[OfficeBlock, ...]

    def __post_init__(self) -> None:
        previous = 0
        for block in self.blocks:
            if not previous <= block.start < block.end <= len(self.text):
                raise ValueError("block ranges must be ordered, disjoint and inside the page")
            if not self.text[block.start : block.end].strip():
                raise ValueError("a block without text")
            _check_locator(block.locator, self.page)
            previous = block.end
        joined = BLOCK_SEPARATOR.join(self.text[b.start : b.end] for b in self.blocks)
        if joined != self.text:
            raise ValueError("page text is not its blocks joined by a blank line")

    def block_at(self, start: int, end: int) -> OfficeBlock:
        """The block that holds [start, end); evidence never crosses blocks."""
        for block in self.blocks:
            if block.start <= start and end <= block.end:
                return block
        raise ValueError("the range is not inside one block")


def check_office_document(pages: Sequence[OfficePageText]) -> None:
    """Rules across one document's pages, as the platform verifies its capture (S11b)."""
    located = [(page, block.locator) for page in pages for block in page.blocks]
    kinds = {locator.kind for _, locator in located}
    if len(kinds) > 1:
        raise ValueError("one document with two locator kinds")
    if kinds == {LocatorKind.DOCX_BLOCK}:
        indexes = [locator.block_index or 0 for _, locator in located]
        if len(pages) != 1 or any(b <= a for a, b in zip(indexes, indexes[1:], strict=False)):
            raise ValueError("a document is one page of increasing block indexes")
    if kinds == {LocatorKind.XLSX_CELL_RANGE}:
        sheets: list[str] = []
        for page in pages:
            names = {block.locator.sheet for block in page.blocks}
            rows = [row_of(block.locator) or 0 for block in page.blocks]
            if any(b <= a for a, b in zip(rows, rows[1:], strict=False)) or len(names) > 1:
                raise ValueError("a sheet page is one sheet of increasing rows")
            sheets.extend(name for name in names if name is not None)
        if len(set(sheets)) != len(sheets):
            raise ValueError("one sheet on two pages")
