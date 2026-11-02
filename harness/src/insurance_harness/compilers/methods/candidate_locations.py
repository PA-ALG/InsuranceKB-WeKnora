"""Candidate-only display folding and unique RAW locations (SK-2d §2–3).

This is not quote verification. A match proposes a recorded RAW segment; downstream methods
still extract and verify every Evidence from the original fixed revision without this folding.
Copy chunks have no Office locator: only the RAW side's validated block bounds are asserted.
"""

import html
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from insurance_harness.compilers.methods.copies import CopiesError
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import OfficePageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest.method_registry import block_order

LOCATE_MIN_CHARS = 8
OVERLAP_MIN_CHARS = 40
_TAG = re.compile(
    r"</?(?:table|thead|tbody|tfoot|tr|td|th|p|div|span|br|b|strong|i|em|u)"
    r"(?:\s+[^<>]*?)?\s*/?>", re.IGNORECASE,
)
_CELL_SEPARATOR = re.compile(r"(?<!\\)\|")
_ALIGNMENT = re.compile(r":?-{3,}:?$")
_PUNCTUATION = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "「": '"', "」": '"',
    "『": '"', "』": '"', "【": "[", "】": "]", "〔": "[", "〕": "]",
    "–": "-", "—": "-", "−": "-",
})


def normalized_text(text: str) -> str:
    """Fold display differences only; keep content characters and mathematical symbols."""
    text = unicodedata.normalize("NFKC", html.unescape(_TAG.sub("", text)))
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and not stripped.endswith(r"\|"):
            cells = _CELL_SEPARATOR.split(stripped)[1:-1]
            if cells and all(_ALIGNMENT.fullmatch(cell.strip()) for cell in cells):
                continue
            line = "".join(cells).replace(r"\|", "|")
        lines.append(line)
    return "".join("".join(lines).translate(_PUNCTUATION).split())


def _overlap(raw: str, chunk: str) -> str | None:
    """One longest suffix/prefix overlap, not an internal common phrase or edit alignment."""
    for size in range(min(len(raw), len(chunk)) - 1, OVERLAP_MIN_CHARS - 1, -1):
        choices = set()
        if raw.endswith(chunk[:size]):
            choices.add(chunk[:size])
        if raw.startswith(chunk[-size:]):
            choices.add(chunk[-size:])
        if choices:
            return next(iter(choices)) if len(choices) == 1 else None
    return None


def _token_char(char: str) -> bool:
    return char.isdigit() or char.isascii() and (char.isalpha() or char in ".%+-/<>=") or (
        char in "≤≥≠"
    )


def _uncut(text: str, needle: str) -> bool:
    """Containment is not permission to change 12.5% into 12.5, or A15 into A1."""
    at = text.find(needle)
    while at >= 0:
        end = at + len(needle)
        left = at > 0 and _token_char(text[at - 1]) and _token_char(text[at])
        right = end < len(text) and _token_char(text[end - 1]) and _token_char(text[end])
        if not left and not right:
            return True
        at = text.find(needle, at + 1)
    return False


@dataclass(frozen=True)
class _Block:
    id: str
    text: str
    office: bool


class RecordedLocations:
    """One fixed revision: signal blocks plus all RAW units needed to reject ambiguity."""

    def __init__(self, pages: Sequence[PageText], block_ids: Sequence[str]) -> None:
        source = SegmentedSource(pages)
        if len(source.document_ids) != 1:
            raise CopiesError("RECORDED_BLOCKS_MISSING")
        prefix = next(iter(source.document_ids.values()))
        self._units = [
            normalized_text(page.text[block.start:block.end] if block is not None else page.text)
            for page in pages
            for block in (page.blocks if isinstance(page, OfficePageText) else (None,))
        ]
        by_page = {(page.document, page.page): page for page in pages}
        self._blocks = []
        wanted = set(block_ids)
        for segment in source.segments:
            block_id = segment.id.removeprefix(prefix)
            if block_id not in wanted:
                continue
            page = by_page[(segment.document, segment.page)]
            office = isinstance(page, OfficePageText)
            if isinstance(page, OfficePageText):
                page.block_at(segment.start, segment.end)  # cannot span two RAW Office locations
            self._blocks.append(_Block(block_id, normalized_text(segment.text), office))
        if {b.id for b in self._blocks} != wanted:
            raise CopiesError("RECORDED_BLOCKS_MISSING")
        self._unique: dict[str, bool] = {}

    @property
    def eligible(self) -> frozenset[str]:
        return frozenset(b.id for b in self._blocks if len(b.text) >= LOCATE_MIN_CHARS)

    @property
    def short_count(self) -> int:
        return len(self._blocks) - len(self.eligible)

    def _unique_position(self, needle: str) -> bool:
        if needle not in self._unique:
            count = 0
            for unit in self._units:
                at = unit.find(needle)
                if at < 0:
                    continue
                count += 1
                if count > 1 or unit.find(needle, at + 1) >= 0:
                    count = 2
                    break
            self._unique[needle] = count == 1
        return self._unique[needle]

    def located(self, chunks: Sequence[str]) -> tuple[str, ...]:
        found = set()
        for block in self._blocks:
            for chunk in chunks:
                if min(len(block.text), len(chunk)) < LOCATE_MIN_CHARS:
                    continue
                needle: str | None
                if block.text in chunk:
                    needle = block.text
                elif chunk in block.text:
                    needle = chunk
                else:
                    needle = _overlap(block.text, chunk) if block.office else None
                if (needle and _uncut(block.text, needle) and _uncut(chunk, needle)
                        and self._unique_position(needle)):
                    found.add(block.id)
        return tuple(sorted(found, key=block_order))
