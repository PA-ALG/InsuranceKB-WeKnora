"""Deterministic segmentation of page text into pointable segments (S4d Spec §3.1).

The extractor only names segment ids. Every quote the platform shows is cut from
page text here, so it matches the page it names by construction; there is nothing
for a model to copy wrongly. The split rules are the ones validated in the S4d
ablations (Issue #157): a segment ends at a line-final sentence terminator, and a line
that starts with a clause number opens a new segment. S4i Spec §3.1 adds: a line that
starts with a bullet opens a new segment too; a terminator followed by white space and
more text ends the segment inside the line (PDF extraction glues the next heading onto
the line); and a run that reaches MAX_CHARS is cut after its last terminator, the rest
carrying into the next segment, so only runs without any terminator (tables) are cut at
a line end.

S11c Spec §2.2: an Office page is split block by block with the same rules, so no segment or
evidence slice crosses a block, and `locator` gives a slice its block's Office locator. Which
restricted documents are clipped to their header block is the TrustPolicy's (catalog/): a scoped
role such as sales material is split whole.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.contracts.enums import LocatorKind
from insurance_harness.contracts.knowledge import Locator
from insurance_harness.evidence.office_pages import OfficeBlock, OfficePageText
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
_TERMINATORS = "。；;！!？?"
_TERMINATOR = re.compile(rf"[{_TERMINATORS}]\s*$")
_ANY_TERMINATOR = re.compile(rf"[{_TERMINATORS}]")
# A terminator, then spaces, tabs or ideographic spaces, then more text on the same line.
_INLINE_BREAK = re.compile(rf"(?<=[{_TERMINATORS}])[ \t\u3000]+(?=\S)")
_CLAUSE_START = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零\d]+[条章节]|\d+(?:\.\d+)+|\d+[、.．]|[（(][一二三四五六七八九十\d]+[）)])"
)
# A list marker opens a segment like a clause number: one marker character at the start of a
# line (or of a piece of one), then white space, then text. Marker characters are the private use
# area (symbol fonts such as Wingdings extract their bullets there), a few unambiguous bullet
# symbols and circled numbers. Symbols that also occur as content (√, □, ※ ...) are not markers,
# and a marker glued to its text does not count: only the separated form is a label.
_MARKER_CHARS = "●○■◆▪•◦►▶➢➤"
_MARKER_RANGES = ((0xE000, 0xF8FF), (0x2460, 0x2473), (0x2776, 0x277F), (0x24EB, 0x24F4))
_MARKER = re.compile(r"^[ \t\u3000]*(?P<mark>\S)[ \t\u3000]+\S")
_LINE_BREAK = re.compile(r"\s*\n\s*")
_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)*%?$")


def header_block(text: str) -> tuple[int, int] | None:
    """The exact nonempty block before the first all-numeric table row, if any."""
    start = len(text) - len(text.lstrip())
    position = end = 0
    for line in text.splitlines(keepends=True):
        tokens = line.split()
        if len(tokens) >= 2 and all(_NUMBER.fullmatch(token) for token in tokens):
            return (start, end) if start < end else None
        if tokens:
            end = position + len(line.rstrip())
        position += len(line)
    return None


def _marker_end(text: str) -> int | None:
    """Where a leading list marker ends in text, or None when text does not start with one."""
    match = _MARKER.match(text)
    if match is None:
        return None
    mark = match["mark"]
    if mark in _MARKER_CHARS or any(low <= ord(mark) <= high for low, high in _MARKER_RANGES):
        return match.end("mark")
    return None


def _opens_segment(content: str) -> bool:
    """A clause number or a list marker at the start of a line (or of a piece of one)."""
    return bool(_CLAUSE_START.match(content)) or _marker_end(content) is not None


def _pieces(line: str) -> list[tuple[int, str]]:
    """A line split after each terminator that white space separates from more text."""
    cuts = [0, *(match.end() for match in _INLINE_BREAK.finditer(line)), len(line)]
    return [(a, line[a:b]) for a, b in zip(cuts[:-1], cuts[1:], strict=True)]


def _size(text: str) -> int:
    """Characters counted towards MAX_CHARS: each line without its surrounding white space."""
    return sum(len(line.strip()) for line in text.splitlines())


class EvidenceSpan(BaseModel):
    """One evidence slice: quote == page text[start:end] of that page."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: NonBlank


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

    def flush(stop: int) -> None:
        nonlocal start
        if start is not None:
            raw = page.text[start:stop]
            first = start + len(raw) - len(raw.lstrip())
            last = stop - (len(raw) - len(raw.rstrip()))
            if first < last:
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
        start = None

    position = 0
    for line in page.text.splitlines(keepends=True):
        for offset, content in _pieces(line.rstrip("\r\n")):
            at = position + offset
            if start is not None and _opens_segment(content):
                flush(end)
            if content.strip():
                if start is None:
                    start = at
                end = at + len(content)
            if start is None:
                continue
            if _TERMINATOR.search(content):
                flush(end)
            elif _size(page.text[start:end]) >= MAX_CHARS:
                # A soft limit, checked where a piece ends: cut after the last terminator and
                # carry the rest into the next segment; a rest that still reaches the limit has
                # no terminator left and is cut at this piece's end, as a run without any is.
                cut = [m.end() for m in _ANY_TERMINATOR.finditer(page.text, start, end)]
                if cut and page.text[cut[-1] : end].strip():
                    flush(cut[-1])
                    start = cut[-1]
                if _size(page.text[start:end]) >= MAX_CHARS:
                    flush(end)
        position += len(line)
    flush(end)
    return out


def _split_ranges(
    page: PageText, document_number: int, ranges: Sequence[tuple[int, int]]
) -> list[tuple[int, Segment]]:
    """Each range of the page split on its own, with page offsets and ids running on across
    ranges; every segment is returned with the index of the range that holds it."""
    out: list[tuple[int, Segment]] = []
    for index, (start, end) in enumerate(ranges):
        clipped = page.model_copy(update={"text": page.text[start:end]})
        for segment in _split(clipped, document_number):
            update = {
                "id": f"D{document_number}P{page.page}S{len(out) + 1}",
                "start": segment.start + start,
                "end": segment.end + start,
            }
            out.append((index, segment.model_copy(update=update)))
    return out


def _clip(ranges: list[tuple[int, int]], text: str) -> list[tuple[int, int]]:
    """The parts of the ranges inside the page's header block (S4j), if it has one."""
    block = header_block(text)
    if block is None:
        return []
    clipped = [(max(a, block[0]), min(b, block[1])) for a, b in ranges]
    return [(a, b) for a, b in clipped if a < b]


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

    def __init__(
        self,
        pages: Sequence[PageTextLike],
        *,
        table_headers: Mapping[str, Sequence[PageTextLike]] | None = None,
    ) -> None:
        self._blocks: dict[tuple[str, int], tuple[OfficeBlock, ...]] = {}
        office: dict[str, bool] = {}

        def adapted(raw: PageTextLike) -> PageText:
            page = PageText.model_validate(raw)
            is_office = isinstance(raw, OfficePageText)
            if office.setdefault(page.document, is_office) != is_office:
                raise ValueError("one document with Office and plain pages")
            if isinstance(raw, OfficePageText):
                self._blocks[(page.document, page.page)] = raw.blocks
            return page

        ordinary = tuple(adapted(page) for page in pages)
        documents = {page.document for page in ordinary}
        headers: list[PageText] = []
        self._header_roles: dict[str, str] = {}
        for role, group in (table_headers or {}).items():
            if not isinstance(role, str) or not role.strip():
                raise ValueError("a header role must be a nonblank string")
            for raw in group:
                page = adapted(raw)
                if (
                    page.document in documents
                    or self._header_roles.get(page.document, role) != role
                ):
                    raise ValueError("one document with conflicting evidence roles")
                self._header_roles[page.document] = role
                headers.append(page)
        # Keep original pages for quote verification and offsets; only segmentation is clipped.
        self.pages = (*ordinary, *headers)
        numbers: dict[str, int] = {}
        digests: dict[str, str] = {}
        seen: set[tuple[str, int]] = set()
        segments: list[Segment] = []
        scoped = load_trust_policy().scoped_roles()
        self._block_of: dict[str, int] = {}  # an Office segment's block, by its index on the page
        for page in self.pages:
            if (page.document, page.page) in seen:
                raise ValueError("duplicate source page identity")
            if (
                digests.setdefault(page.document, page.document_sha256.lower())
                != page.document_sha256.lower()
            ):
                raise ValueError("one document name with two fingerprints")
            seen.add((page.document, page.page))
            number = numbers.setdefault(page.document, len(numbers) + 1)
            blocks = self._blocks.get((page.document, page.page))
            ranges = [(0, len(page.text))] if blocks is None else [(b.start, b.end) for b in blocks]
            restricted = self.header_role(page.document)
            if restricted is not None and restricted not in scoped:
                ranges = _clip(ranges, page.text)  # a header role serves its header block only
            for index, segment in _split_ranges(page, number, ranges):
                if blocks is not None:
                    self._block_of[segment.id] = index
                segments.append(segment)
        self.segments = tuple(segments)
        # The "D<n>" prefix of each document's segment ids, in reading order.
        self.document_ids = {document: f"D{number}" for document, number in numbers.items()}
        self._position = {segment.id: index for index, segment in enumerate(self.segments)}
        self._pages = {(page.document, page.page): page for page in self.pages}
        self._content: dict[str, str] = {}
        self._copies: dict[str, frozenset[str]] = {}

    def header_role(self, document: str) -> str | None:
        """The restricted role of a document (a header or a scoped role, read through
        table_headers), or None for ordinary/unknown documents."""
        return self._header_roles.get(document)

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
        return [
            VerifiedQuote(
                document=span.document,
                document_sha256=span.document_sha256,
                page=span.page,
                quote=span.quote,
                match=QuoteMatch.EXACT,
            )
            for span in self.spans(ids)
        ]

    def spans(self, ids: Sequence[str]) -> list[EvidenceSpan]:
        """The evidence slices with their page-text offsets (code points, half-open)."""
        out: list[EvidenceSpan] = []
        run: list[Segment] = []
        for segment in [*self.ordered(ids), None]:
            if run and (
                segment is None
                or (segment.document, segment.page) != (run[-1].document, run[-1].page)
                or self._position[segment.id] != self._position[run[-1].id] + 1
                or self._block_of.get(segment.id) != self._block_of.get(run[-1].id)
            ):
                page = self._pages[(run[0].document, run[0].page)]
                out.append(
                    EvidenceSpan(
                        document=page.document,
                        document_sha256=page.document_sha256,
                        page=page.page,
                        start=run[0].start,
                        end=run[-1].end,
                        quote=page.text[run[0].start : run[-1].end],
                    )
                )
                run = []
            if segment is not None:
                run.append(segment)
        return out

    def locator(self, span: EvidenceSpan) -> Locator:
        """Where a slice of this source sits: a PDF text span, or its Office block's locator with
        the page and the slice's page-text offsets (code points, half-open; S11c Spec §2.2)."""
        page = self._pages.get((span.document, span.page))
        if (
            page is None
            or page.document_sha256.lower() != span.document_sha256.lower()
            or page.text[span.start : span.end] != span.quote
        ):
            raise ValueError("not a slice of this source")
        blocks = self._blocks.get((span.document, span.page))
        if blocks is None:
            return Locator(
                kind=LocatorKind.PDF_TEXT_SPAN, page=span.page, start=span.start, end=span.end
            )
        block = next((b for b in blocks if b.start <= span.start and span.end <= b.end), None)
        if block is None:
            raise ValueError("a slice across blocks")
        located = block.locator.model_dump(exclude_none=True)
        return Locator(**located, page=span.page, start=span.start, end=span.end)

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
        number or list marker; two segments are copies when the shorter text, at least
        COPY_MIN_CHARS long, occurs inside the other. Repeats within one document are not
        copies: they are separate provisions that happen to share wording.
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

    def content(self, segment_id: str) -> str:
        """The text copies are compared on: no whitespace or width differences, and no leading
        clause number or list marker (S4e). Scoring rules fold it further (S12a)."""
        if segment_id not in self._position:
            raise ValueError(f"unknown segment id {segment_id}")
        return self._content_of(self.segments[self._position[segment_id]])

    def _content_of(self, segment: Segment) -> str:
        content = self._content.get(segment.id)
        if content is None:
            marker = _marker_end(segment.text)  # a list marker is a label too (S4i)
            squeezed, _ = _squeeze(segment.text if marker is None else segment.text[marker:])
            label = _CLAUSE_START.match(squeezed) if marker is None else None
            content = self._content[segment.id] = squeezed[label.end() :] if label else squeezed
        return content
