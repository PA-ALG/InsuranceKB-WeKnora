"""Deterministic segmentation of page text into pointable segments (S4d Spec §3.1).

The extractor only names segment ids. Every quote the platform shows is cut from
page text here, so it matches the page it names by construction; there is nothing
for a model to copy wrongly. The split rules are the ones validated in the S4d
ablations (Issue #157): a segment ends at a line-final sentence terminator, a line
that starts with a clause number opens a new segment, and runs without terminators
(tables) are cut once they reach MAX_CHARS.
"""

import re
import unicodedata
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.evidence.quote_verification import (
    Digest,
    NonBlank,
    PageText,
    PageTextLike,
    QuoteMatch,
    VerifiedQuote,
)

MAX_CHARS = 300
COPY_MIN_CHARS = 20  # shorter passages ("本合同终止。") repeat everywhere and prove nothing
_TERMINATOR = re.compile(r"[。；;！!？?]\s*$")
_CLAUSE_START = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零\d]+[条章节]|\d+(?:\.\d+)+|\d+[、.．]|[（(][一二三四五六七八九十\d]+[）)])"
)
_LINE_BREAK = re.compile(r"\s*\n\s*")


class Segment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    id: NonBlank
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: NonBlank


def _split(page: PageText, document_number: int) -> list[Segment]:
    out: list[Segment] = []
    start: int | None = None
    end = 0
    size = 0

    def flush() -> None:
        nonlocal start, size
        if start is not None:
            raw = page.text[start:end]
            first = start + len(raw) - len(raw.lstrip())
            last = end - (len(raw) - len(raw.rstrip()))
            out.append(
                Segment(
                    id=f"D{document_number}P{page.page}S{len(out) + 1}",
                    document=page.document,
                    document_sha256=page.document_sha256,
                    page=page.page,
                    start=first,
                    end=last,
                    text=page.text[first:last],
                )
            )
        start, size = None, 0

    position = 0
    for line in page.text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if start is not None and _CLAUSE_START.match(content):
            flush()
        if content.strip():
            if start is None:
                start = position
            end = position + len(content)
            size += len(content.strip())
        position += len(line)
        if start is not None and (_TERMINATOR.search(content) or size >= MAX_CHARS):
            flush()
    flush()
    return out


def _squeeze(text: str) -> tuple[str, list[int]]:
    """Width-folded text without whitespace, plus each kept character's original offset."""
    kept, offsets = [], []
    for index, char in enumerate(text):
        folded = unicodedata.normalize("NFKC", char)
        if folded.isspace() or not folded:
            continue
        kept.append(folded)
        offsets.extend([index] * len(folded))
    return "".join(kept), offsets


def same_text(a: str, b: str) -> bool:
    """Equal once whitespace and width are ignored: line endings and spacing are not content."""
    return _squeeze(a)[0] == _squeeze(b)[0]


class SegmentedSource:
    """One product's pages, split once; the only place segment ids are resolved."""

    def __init__(self, pages: Sequence[PageTextLike]) -> None:
        self.pages = tuple(PageText.model_validate(page) for page in pages)
        numbers: dict[str, int] = {}
        digests: dict[str, str] = {}
        seen: set[tuple[str, int]] = set()
        segments: list[Segment] = []
        for page in self.pages:
            if (page.document, page.page) in seen:
                raise ValueError("duplicate source page identity")
            if (
                digests.setdefault(page.document, page.document_sha256.lower())
                != page.document_sha256.lower()
            ):
                raise ValueError("one document name with two fingerprints")
            seen.add((page.document, page.page))
            segments.extend(_split(page, numbers.setdefault(page.document, len(numbers) + 1)))
        self.segments = tuple(segments)
        self._position = {segment.id: index for index, segment in enumerate(self.segments)}
        self._pages = {(page.document, page.page): page for page in self.pages}
        self._content: dict[str, str] = {}
        self._copies: dict[str, frozenset[str]] = {}

    def listing(self) -> str:
        """One line per segment: the id, a space, and the text with line breaks folded."""
        return "\n".join(f"{s.id} {_LINE_BREAK.sub(' ', s.text)}" for s in self.segments)

    def resolve(self, refs: Sequence[object]) -> tuple[list[str], list[object]]:
        """Ids or inclusive "first-last" ranges in reading order.

        Anything else is dropped and reported, never guessed.
        """
        ids: list[str] = []
        dropped: list[object] = []
        for ref in refs:
            found = self._expand(ref) if isinstance(ref, str) else None
            if found is None:
                dropped.append(ref)
                continue
            ids.extend(sid for sid in found if sid not in ids)
        return ids, dropped

    def _expand(self, ref: str) -> list[str] | None:
        if ref in self._position:
            return [ref]
        first, separator, last = ref.partition("-")
        if separator and first in self._position and last in self._position:
            a, b = self._position[first], self._position[last]
            if a <= b:
                return [s.id for s in self.segments[a : b + 1]]
        return None

    def ordered(self, ids: Sequence[str]) -> list[Segment]:
        """Known ids as segments in reading order (callers resolve refs first)."""
        return [self.segments[i] for i in sorted({self._position[sid] for sid in ids})]

    def evidence(self, ids: Sequence[str]) -> list[VerifiedQuote]:
        """Adjacent segments on one page merge into one exact slice of that page."""
        quotes: list[VerifiedQuote] = []
        run: list[Segment] = []
        for segment in [*self.ordered(ids), None]:
            if run and (
                segment is None
                or (segment.document, segment.page) != (run[-1].document, run[-1].page)
                or self._position[segment.id] != self._position[run[-1].id] + 1
            ):
                page = self._pages[(run[0].document, run[0].page)]
                quotes.append(
                    VerifiedQuote(
                        document=page.document,
                        document_sha256=page.document_sha256,
                        page=page.page,
                        quote=page.text[run[0].start : run[-1].end],
                        match=QuoteMatch.EXACT,
                    )
                )
                run = []
            if segment is not None:
                run.append(segment)
        return quotes

    def locate(
        self, document: str, page: int, quote: str, segment_id: str | None = None
    ) -> set[str]:
        """Segments overlapping a quote found on that page, ignoring whitespace and width.

        Used to score references written against an earlier segmentation. A segment_id
        recorded with the quote is taken when that segment, on that page, still holds
        exactly the quoted text; otherwise the quote is searched, and an empty set is
        returned when it is absent or occurs more than once on the page.
        """
        source = self._pages.get((document, page))
        needle, _ = _squeeze(quote)
        if source is None or not needle:
            return set()
        held = self.segments[self._position[segment_id]] if segment_id in self._position else None
        if held is not None and (held.document, held.page) == (document, page):
            if _squeeze(held.text)[0] == needle:
                return {held.id}
        haystack, offsets = _squeeze(source.text)
        at = haystack.find(needle)
        if at < 0 or haystack.find(needle, at + 1) >= 0:
            return set()
        first, last = offsets[at], offsets[at + len(needle) - 1] + 1
        return {
            s.id
            for s in self.segments
            if (s.document, s.page) == (document, page) and s.start < last and first < s.end
        }

    def copies(self, segment_id: str) -> frozenset[str]:
        """Segments of other documents that repeat this one word for word (S4e Spec §3.1).

        Text is compared without whitespace, width differences or one leading clause
        number; two segments are copies when the shorter text, at least COPY_MIN_CHARS
        long, occurs inside the other. Repeats within one document are not copies: they
        are separate provisions that happen to share wording.
        """
        if segment_id not in self._position:
            raise ValueError(f"unknown segment id {segment_id}")
        found = self._copies.get(segment_id)
        if found is None:
            segment = self.segments[self._position[segment_id]]
            mine = self._content_of(segment)
            matches = set()
            for other in self.segments:
                if other.document == segment.document:
                    continue
                short, long = sorted((mine, self._content_of(other)), key=len)
                if len(short) >= COPY_MIN_CHARS and short in long:
                    matches.add(other.id)
            found = self._copies[segment_id] = frozenset(matches)
        return found

    def _content_of(self, segment: Segment) -> str:
        content = self._content.get(segment.id)
        if content is None:
            squeezed, _ = _squeeze(segment.text)
            label = _CLAUSE_START.match(squeezed)
            content = self._content[segment.id] = squeezed[label.end() :] if label else squeezed
        return content
