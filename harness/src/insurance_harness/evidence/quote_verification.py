"""Page-local quote matching, ported from V5 source_evidence.py.

Legacy originals retire in S7. Only width, whitespace, line-leading list
glyphs and locally defined footnote references can be normalized. A claimed
source is authoritative: there is no search for a substitute page or revision.
"""

import re
import unicodedata
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]


class PageTextLike(Protocol):
    @property
    def document(self) -> str: ...
    @property
    def document_sha256(self) -> str: ...
    @property
    def page(self) -> int: ...
    @property
    def text(self) -> str: ...


class PageText(BaseModel):
    """Structural adapter for the caller's parsed page; no document I/O here."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", from_attributes=True)
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    text: str


class QuoteReference(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    quote: NonBlank


class QuoteMatch(StrEnum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    NOT_FOUND = "NOT_FOUND"


class VerifiedQuote(QuoteReference):
    match: Literal[QuoteMatch.EXACT, QuoteMatch.NORMALIZED]


def _normalized(value: str, source: str) -> str:
    # Require an explicit marker AND the same-page definition. Plain flattened
    # digits are ambiguous without geometry: they may be an amount, duration or
    # identifier, even when a matching footnote definition happens to exist.
    for number, term in re.findall(
        r"(?m)^\s*([0-9]{1,2})\s+([\u4e00-\u9fff]{2,20}?)(?:是指|指)",
        source,
    ):
        superscript = number.translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
        marker = r"(?:\s*[\[［]\s*" + number + r"\s*[\]］]|" + superscript + r"(?![⁰¹²³⁴⁵⁶⁷⁸⁹]))"
        value = re.sub(re.escape(term) + marker, term, value)
    value = re.sub(r"(?m)^[ \t]*[\uf06c•●▪][ \t]*", "", value)
    return "".join(char for char in unicodedata.normalize("NFKC", value) if not char.isspace())


def verify_quote(page_text: str, quote: str) -> QuoteMatch:
    """Classify a nonempty substring, never rewrite punctuation or meaning."""
    if not quote.strip():
        return QuoteMatch.NOT_FOUND
    if quote in page_text:
        return QuoteMatch.EXACT
    normalized = _normalized(quote, page_text)
    if normalized and normalized in _normalized(page_text, page_text):
        return QuoteMatch.NORMALIZED
    return QuoteMatch.NOT_FOUND


class QuoteVerifier:
    """Snapshot source pages once; reject ambiguous identities before extraction."""

    def __init__(self, pages: Sequence[PageTextLike]) -> None:
        self.pages = tuple(PageText.model_validate(page) for page in pages)
        self._index: dict[tuple[str, str, int], PageText] = {}
        for page in self.pages:
            key = (page.document, page.document_sha256.lower(), page.page)
            if key in self._index:
                raise ValueError("duplicate source page identity")
            self._index[key] = page

    def verify(self, reference: QuoteReference) -> VerifiedQuote | None:
        page = self._index.get(
            (
                reference.document,
                reference.document_sha256.lower(),
                reference.page,
            )
        )
        if page is None:
            return None
        match = verify_quote(page.text, reference.quote)
        if match is QuoteMatch.NOT_FOUND:
            return None
        return VerifiedQuote(**reference.model_dump(), match=match)
