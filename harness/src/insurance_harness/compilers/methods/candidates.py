"""Method candidates from the discovery base's native Wiki pages (SK-2b Spec §4; SK-0 §5.1).

Native discover/cite proposes which methods there are and near which blocks; nothing it wrote
goes further. Each entity or concept page becomes one candidate per material it cites: the cited
chunks name their copy, the copy mapping names the original revision, and the chunks' text is
located among the blocks the original's method-use record holds, on the original pages. The
candidate file carries names and block IDs only; SK-2a admission checks it again from the start.
"""

import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from insurance_harness.compilers.methods.admission import Candidate, CandidateFile, CopyEntry
from insurance_harness.compilers.methods.copies import CopyBook, MethodCopy, check_discovery_kb
from insurance_harness.compilers.wiki_pages.members import NativePage
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest.method_registry import block_order
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import RawListing, RawSource, material_pages
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.source_map import PageReader

PAGE_TYPES = frozenset({"entity", "concept"})  # the pages S6c also takes as reading pages
# A shorter text is too generic to tie a page to a place in the source (as S6c).
LOCATE_MIN_CHARS = 8


@dataclass(frozen=True)
class CandidateRun:
    candidates: CandidateFile
    report: dict[str, Any]  # codes and counts only


def _squeeze(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


class _Originals:
    """Each original's recorded blocks as folded text, read and segmented once."""

    def __init__(self, reader: PageReader, space_id: str) -> None:
        self.reader, self.space_id = reader, space_id
        self.blocks: dict[tuple[str, int, str], list[tuple[str, str]]] = {}

    def recorded(self, use: MethodUse) -> list[tuple[str, str]]:
        if use.triple not in self.blocks:
            raw = RawSource(
                knowledge_id=use.knowledge_id,
                parse_attempt=use.parse_attempt,
                file_name=use.file_name,
                sha256=use.sha256,
            )
            source = SegmentedSource(material_pages(self.reader, self.space_id, raw))
            prefix = next(iter(source.document_ids.values()))
            hits = set(use.block_ids)
            self.blocks[use.triple] = [
                (block, _squeeze(segment.text))
                for segment in source.segments
                if (block := segment.id.removeprefix(prefix)) in hits
            ]
        return self.blocks[use.triple]


def _located(blocks: Sequence[tuple[str, str]], chunks: Sequence[str]) -> tuple[str, ...]:
    """The recorded blocks a page's chunks of one material cite (Spec §4)."""
    found = {
        block
        for block, text in blocks
        for chunk in chunks
        if min(len(text), len(chunk)) >= LOCATE_MIN_CHARS and (text in chunk or chunk in text)
    }
    return tuple(sorted(found, key=block_order))


def method_candidates(
    registry: ProductRegistry,
    book: CopyBook,
    listing: RawListing,
    pages: Sequence[NativePage],
    reader: PageReader,
) -> CandidateRun:
    check_discovery_kb(registry, book)
    digests = {source.knowledge_id: source.sha256 for source in listing.completed}
    usable: dict[str, MethodCopy] = {
        copy.copy_knowledge_id: copy for copy in book.copies if copy.copy_knowledge_id in digests
    }
    records = {use.triple: use for use in registry.method_uses}
    originals = _Originals(reader, registry.space_id)
    counts: Counter[str] = Counter()
    candidates: list[Candidate] = []
    for page in pages:
        if page.page_type not in PAGE_TYPES:
            continue
        cited: dict[str, list[str]] = {}
        for chunk in page.chunks:
            cited.setdefault(chunk.knowledge_id, []).append(_squeeze(chunk.content))
        for copy_id, chunks in cited.items():
            copy = usable.get(copy_id)
            if copy is None:
                counts["CHUNK_UNMAPPED"] += 1  # no mapping, or the copy is still being parsed
                continue
            use = records.get(copy.triple)
            if use is None or use.state != "active":
                counts["METHOD_USE_NOT_ACTIVE"] += 1
                continue
            blocks = _located(originals.recorded(use), chunks)
            if not blocks:
                counts["NO_RECORDED_BLOCKS"] += 1
                continue
            candidates.append(
                Candidate(
                    name=page.title,
                    aliases=tuple(alias for alias in page.aliases if alias.strip()),
                    copy_knowledge_id=copy_id,
                    block_ids=blocks,
                )
            )
    entries = tuple(
        CopyEntry(
            copy_knowledge_id=copy.copy_knowledge_id,
            copy_sha256=digests[copy.copy_knowledge_id],
            knowledge_id=copy.knowledge_id,
            parse_attempt=copy.parse_attempt,
            sha256=copy.sha256,
        )
        for copy in usable.values()
    )
    unique = tuple(dict.fromkeys(candidates))  # the same page and material once
    file = CandidateFile(
        contract="method-candidates.v1",
        discovery_kb_id=book.discovery_kb_id,
        copies=entries,
        candidates=unique,
    )
    report = {"candidates": len(unique), "counts": dict(sorted(counts.items()))}
    return CandidateRun(file, report)
