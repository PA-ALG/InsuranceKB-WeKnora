"""Method candidates from the discovery base's native Wiki pages (SK-2b Spec §4; SK-0 §5.1).

Native discover/cite proposes which methods there are and near which blocks; nothing it wrote
goes further. Each entity or concept page becomes one candidate per material it cites: the cited
chunks name their copy, the copy mapping names the original revision, and the chunks' text is
located among the blocks the original's method-use record holds, on the original pages. The
candidate file carries names and block IDs only; SK-2a admission checks it again from the start.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from insurance_harness.compilers.methods.admission import Candidate, CandidateFile, CopyEntry
from insurance_harness.compilers.methods.candidate_locations import (
    RecordedLocations,
    normalized_text,
)
from insurance_harness.compilers.methods.copies import CopyBook, MethodCopy, check_discovery_kb
from insurance_harness.compilers.wiki_pages.members import NativePage
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import RawListing, RawSource, material_pages
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.source_map import PageReader

PAGE_TYPES = frozenset({"entity", "concept"})  # the pages S6c also takes as reading pages
RECALL_MINIMUM = 0.5  # SK-2d: candidate coverage only, not permission to run values or publish


@dataclass(frozen=True)
class CandidateRun:
    candidates: CandidateFile
    report: dict[str, Any]  # codes and counts only


class _Originals:
    """Each original's recorded blocks as folded text, read and segmented once."""

    def __init__(self, reader: PageReader, space_id: str) -> None:
        self.reader, self.space_id = reader, space_id
        self.blocks: dict[tuple[str, int, str], RecordedLocations] = {}

    def recorded(self, use: MethodUse) -> RecordedLocations:
        if use.triple not in self.blocks:
            raw = RawSource(
                knowledge_id=use.knowledge_id,
                parse_attempt=use.parse_attempt,
                file_name=use.file_name,
                sha256=use.sha256,
            )
            self.blocks[use.triple] = RecordedLocations(
                material_pages(self.reader, self.space_id, raw), use.block_ids
            )
        return self.blocks[use.triple]


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
    # Denominators include active signals without a copy or citation; never hide misses.
    for record in registry.method_uses:
        if record.state == "active":
            originals.recorded(record)
    covered: dict[tuple[str, int, str], set[str]] = {}
    counts: Counter[str] = Counter()
    candidates: list[Candidate] = []
    for page in pages:
        if page.page_type not in PAGE_TYPES:
            continue
        cited: dict[str, list[str]] = {}
        for chunk in page.chunks:
            cited.setdefault(chunk.knowledge_id, []).append(normalized_text(chunk.content))
        for copy_id, chunks in cited.items():
            copy = usable.get(copy_id)
            if copy is None:
                counts["CHUNK_UNMAPPED"] += 1  # no mapping, or the copy is still being parsed
                continue
            use = records.get(copy.triple)
            if use is None or use.state != "active":
                counts["METHOD_USE_NOT_ACTIVE"] += 1
                continue
            blocks = originals.recorded(use).located(chunks)
            if not blocks:
                counts["NO_RECORDED_BLOCKS"] += 1
                continue
            covered.setdefault(use.triple, set()).update(blocks)
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
    total = sum(len(locations.eligible) for locations in originals.blocks.values())
    recalled = sum(len(covered.get(triple, set()) & locations.eligible)
                   for triple, locations in originals.blocks.items())
    ratio = recalled / total if total else None
    report = {
        "candidates": len(unique), "counts": dict(sorted(counts.items())),
        "recall": {
            "eligible": {"total": total, "covered": recalled, "ratio": ratio},
            "short": {"total": sum(loc.short_count for loc in originals.blocks.values()),
                      "covered": 0},
            "gate": {"minimum": RECALL_MINIMUM,
                     "passed": ratio is not None and ratio >= RECALL_MINIMUM},
        },
    }
    return CandidateRun(file, report)
