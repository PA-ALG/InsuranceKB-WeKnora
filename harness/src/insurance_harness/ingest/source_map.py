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

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.evidence.weknora_pages import WeKnoraSourcePages


class PageReader(Protocol):
    """Reads every page of one fixed source revision (S4c-1's WeKnoraSourcePages)."""

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]: ...


BASE_URL_ENV = "HARNESS_WEKNORA_BASE_URL"
API_KEY_ENV = "HARNESS_WEKNORA_API_KEY"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


class SourceEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)


class SourceMap(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    space_id: _Identifier
    products: dict[_Identifier, list[SourceEntry]]

    def entries(self, product: str) -> list[SourceEntry]:
        entries = self.products.get(product)
        if not entries:
            raise ValueError(f"source map names no documents for {product}")
        return entries


def load_source_map(path: Path) -> SourceMap:
    try:
        return SourceMap.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as error:
        raise ValueError(f"invalid source map {path.name}: {error}") from None


def reader_from_env() -> WeKnoraSourcePages:
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        raise ValueError(f"{BASE_URL_ENV} and {API_KEY_ENV} must be set")
    return WeKnoraSourcePages(base_url, api_key)


def load_pages(
    reader: PageReader, space_id: str, entries: list[SourceEntry]
) -> tuple[list[PageText], dict[str, SourceRevision]]:
    """Every page of the named revisions, plus each document's revision for the bundle."""
    pages: list[PageText] = []
    sources: dict[str, SourceRevision] = {}
    for entry in entries:
        read = reader.pages(space_id, entry.knowledge_id, entry.parse_attempt)
        document = read[0].document
        if document in sources:
            raise ValueError(f"two source revisions are named {document}")
        sources[document] = SourceRevision(entry.knowledge_id, entry.parse_attempt)
        pages.extend(read)
    return pages, sources


def page_source(source_map: SourceMap, reader: PageReader) -> Callable[[str], list[PageText]]:
    """Pages of one product for the compiler, read from the revisions the map names."""

    def pages_of(product: str) -> list[PageText]:
        return load_pages(reader, source_map.space_id, source_map.entries(product))[0]

    return pages_of
