"""Which fixed WeKnora source revisions a product's pages come from (S4g Spec §2.4).

Compiling and publishing must read the same page text, or segment ids and offsets would not
match the platform's captured parse artifact. Both read it through the S4c-1 page reader, from
the revisions a source map names; the map also gives the bundle its ``source:v1`` references.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from insurance_harness.catalog.trust_policy import TrustedPages, trusted_pages
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.evidence.weknora_pages import WeKnoraSourcePages
from insurance_harness.identity.material_roles import MaterialRoleError, evidence_pages


class PageReader(Protocol):
    """Reads every page of one fixed source revision (S4c-1's WeKnoraSourcePages)."""

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]: ...


BASE_URL_ENV = "HARNESS_WEKNORA_BASE_URL"
API_KEY_ENV = "HARNESS_WEKNORA_API_KEY"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


class SourceMapError(ValueError):
    """A caller-safe code; never the file path or its content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    # The registry-recorded material role (S5b-6); absent in hand-written maps, then inferred.
    role: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*$")] | None = None


class SourceMap(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    space_id: _Identifier
    products: dict[_Identifier, list[SourceEntry]]

    def entries(self, product: str) -> list[SourceEntry]:
        entries = self.products.get(product)
        if not entries:
            raise SourceMapError("SOURCE_MAP_INVALID")
        return entries


def load_source_map(path: Path) -> SourceMap:
    try:
        return SourceMap.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        raise SourceMapError("SOURCE_MAP_INVALID") from None


def reader_from_env() -> WeKnoraSourcePages:
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        raise SourceMapError("CONFIGURATION_MISSING")
    return WeKnoraSourcePages(base_url, api_key)


def load_pages(
    reader: PageReader, space_id: str, entries: list[SourceEntry]
) -> tuple[list[PageText], dict[str, SourceRevision]]:
    """Pages of the named revisions that may be evidence, plus each kept document's revision.

    One document name twice is refused first; then materials are judged by role (S4i): a
    non-evidence material is dropped with its revision, and an unresolved one stops the read.
    The documents kept keep their revisions, fingerprints, pages and text unchanged.
    """
    pages, sources, recorded = _read_sources(reader, space_id, entries)
    try:
        kept = evidence_pages(pages, recorded)
    except MaterialRoleError as error:
        raise SourceMapError(error.code) from None
    documents = {page.document for page in kept}
    return kept, {name: revision for name, revision in sources.items() if name in documents}


def _read_sources(
    reader: PageReader, space_id: str, entries: list[SourceEntry]
) -> tuple[list[PageText], dict[str, SourceRevision], dict[str, str]]:
    pages: list[PageText] = []
    sources: dict[str, SourceRevision] = {}
    recorded: dict[str, str] = {}
    for entry in entries:
        read = reader.pages(space_id, entry.knowledge_id, entry.parse_attempt)
        document = read[0].document
        if document in sources:
            raise SourceMapError("SOURCE_DOCUMENTS_AMBIGUOUS")
        sources[document] = SourceRevision(entry.knowledge_id, entry.parse_attempt)
        if entry.role is not None:
            recorded[document] = entry.role
        pages.extend(read)
    return pages, sources, recorded


def load_trusted_pages(
    reader: PageReader, space_id: str, entries: list[SourceEntry]
) -> tuple[TrustedPages[PageText], dict[str, SourceRevision]]:
    """Whole evidence and header inputs, with fixed revisions for every included document."""
    pages, sources, recorded = _read_sources(reader, space_id, entries)
    try:
        trusted = trusted_pages(pages, recorded)
    except MaterialRoleError as error:
        raise SourceMapError(error.code) from None
    documents = {
        page.document
        for group in [trusted.evidence, *trusted.table_headers.values()]
        for page in group
    }
    return trusted, {name: revision for name, revision in sources.items() if name in documents}


def trusted_page_source(
    source_map: SourceMap, reader: PageReader
) -> Callable[[str], TrustedPages[PageText]]:
    def pages_of(product: str) -> TrustedPages[PageText]:
        return load_trusted_pages(reader, source_map.space_id, source_map.entries(product))[0]

    return pages_of


def page_source(source_map: SourceMap, reader: PageReader) -> Callable[[str], list[PageText]]:
    """Pages of one product for the compiler, read from the revisions the map names."""

    def pages_of(product: str) -> list[PageText]:
        return load_pages(reader, source_map.space_id, source_map.entries(product))[0]

    return pages_of
