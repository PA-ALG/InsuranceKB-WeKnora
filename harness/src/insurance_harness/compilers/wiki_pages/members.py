"""Turn one native Wiki page into a wiki_page member payload (S6c Spec §3.2).

A page is model-written reading material. Its links are rewritten to member slugs of the same
product; its evidence is a segment of the product's own source pages that lies whole inside a
chunk the page cited, so the platform can verify it word for word. Nothing is guessed: a chunk
that contains no such segment yields no evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.bundle.assemble import ACCESS_SCOPE
from insurance_harness.contracts.enums import EvidenceMatch, LocatorKind
from insurance_harness.contracts.knowledge import Evidence, Locator, WikiPage
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

GENERATOR = "weknora-native-wiki"
MAX_EVIDENCE = 3
# A segment shorter than this is too generic to tie a page to a place in the source.
MIN_SEGMENT_CHARS = 8
_KEPT_TYPES = frozenset({"concept", "entity"})
_LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")


class NativeChunk(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    content: str = ""
    knowledge_id: str = ""  # the knowledge item the chunk belongs to (SK-2b); "" when not given


class NativePage(BaseModel):
    """A read-only snapshot of one discovery-KB page and the chunks it cites, in order."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    slug: str
    title: str
    page_type: str
    summary: str = ""
    content: str = ""
    aliases: list[str] = Field(default_factory=list)
    chunks: list[NativeChunk] = Field(default_factory=list)


def member_slug(entity_id: str, page_key: str) -> str:
    return f"wiki/{entity_id}/{page_key}"


def link_titles(pages: Iterable[NativePage]) -> dict[str, str]:
    """Titles of the pages that become members: the only targets a rewritten link may name."""
    return {page.slug: page.title for page in pages if page.page_type in _KEPT_TYPES}


def wiki_page(
    page: NativePage,
    *,
    entity_id: str,
    titles: Mapping[str, str],
    source: SegmentedSource,
    sources: Mapping[str, SourceRevision],
    model: str,
) -> WikiPage | None:
    """The member for a concept or entity page; None for summary, index and other pages."""
    if page.page_type not in _KEPT_TYPES:
        return None
    return WikiPage(
        page_key=page.slug,
        entity_refs=[entity_id],
        title=page.title,
        page_type=page.page_type,  # type: ignore[arg-type]  # narrowed by _KEPT_TYPES
        summary=page.summary,
        content=_links(page.content, entity_id, titles),
        aliases=[alias for alias in page.aliases if alias.strip()],
        evidence=_evidence([chunk.content for chunk in page.chunks], source, sources),
        origin="MODEL_GENERATED",
        generator=GENERATOR,
        model=model,
    )


def _links(content: str, entity_id: str, titles: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key, label = match.group(1).strip(), (match.group(2) or "").strip()
        if key in titles:
            return f"[[{member_slug(entity_id, key)}|{label or titles[key]}]]"
        return label or key.rsplit("/", 1)[-1]

    return _LINK.sub(replace, content)


def _squeeze(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _evidence(
    chunks: list[str], source: SegmentedSource, sources: Mapping[str, SourceRevision]
) -> list[Evidence]:
    used: set[str] = set()
    out: list[Evidence] = []
    segments = [(segment, _squeeze(segment.text)) for segment in source.segments]
    for chunk in chunks:
        if len(out) == MAX_EVIDENCE:
            break
        haystack = _squeeze(chunk)
        for segment, needle in segments:
            if segment.id in used or len(needle) < MIN_SEGMENT_CHARS or needle not in haystack:
                continue
            revision = sources.get(segment.document)
            if revision is None:
                continue
            (span,) = source.spans([segment.id])
            used.add(segment.id)
            out.append(
                Evidence(
                    source_ref=revision.ref(span.document_sha256.lower()),
                    file_sha256=span.document_sha256.lower(),
                    locator=Locator(
                        kind=LocatorKind.PDF_TEXT_SPAN,
                        page=span.page,
                        start=span.start,
                        end=span.end,
                    ),
                    quote=span.quote,
                    match=EvidenceMatch.EXACT,
                    access_scope=ACCESS_SCOPE,
                )
            )
            break
    return out
