"""A method's paragraphs: the linked blocks, read from the original revisions (Spec §4.1).

Each valid link's material is read through the fixed-revision page reader and split on its own with
the same segmentation SK-1 recorded its blocks with, so a block ID names the same text it named
then. Materials are numbered `M<n>` in (knowledge id, parse attempt) order and a paragraph is
`M<n>` + its block ID. Every quote is cut from these pages; a copy is never read.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from insurance_harness.evidence.segments import EvidenceSpan, Segment, SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.method_registry import MethodLink
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import RawSource, material_pages
from insurance_harness.ingest.source_map import PageReader

_LINE_BREAK = re.compile(r"\s*\n\s*")


class ParagraphsError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Material:
    number: int
    link: MethodLink
    revision: SourceRevision
    source: SegmentedSource


@dataclass(frozen=True)
class Paragraph:
    ref: str
    material: Material
    segment: Segment


class MaterialCache:
    """Each revision is read and segmented once per run, whichever methods link it."""

    def __init__(self, reader: PageReader, space_id: str, uses: Sequence[MethodUse]) -> None:
        self.reader, self.space_id = reader, space_id
        self.records = {use.triple: use for use in uses}
        self.sources: dict[tuple[str, int, str], SegmentedSource] = {}

    def source(self, link: MethodLink) -> SegmentedSource:
        if link.triple not in self.sources:
            record = self.records[link.triple]
            raw = RawSource(
                knowledge_id=record.knowledge_id,
                parse_attempt=record.parse_attempt,
                file_name=record.file_name,
                sha256=record.sha256,
            )
            self.sources[link.triple] = SegmentedSource(
                material_pages(self.reader, self.space_id, raw)
            )
        return self.sources[link.triple]


class MethodParagraphs:
    def __init__(self, links: Sequence[MethodLink], cache: MaterialCache) -> None:
        ordered = sorted(links, key=lambda link: (link.knowledge_id, link.parse_attempt))
        self.paragraphs: dict[str, Paragraph] = {}
        for number, link in enumerate(ordered, 1):
            source = cache.source(link)
            prefix = next(iter(source.document_ids.values()))
            blocks = {segment.id.removeprefix(prefix): segment for segment in source.segments}
            if not set(link.block_ids) <= set(blocks):
                raise ParagraphsError("PARAGRAPHS_MISMATCH")  # not the recorded segmentation
            material = Material(
                number, link, SourceRevision(link.knowledge_id, link.parse_attempt), source
            )
            for block in link.block_ids:
                ref = f"M{number}{block}"
                self.paragraphs[ref] = Paragraph(ref, material, blocks[block])

    def listing(self) -> str:
        return "\n".join(
            f"{p.ref} {_LINE_BREAK.sub(' ', p.segment.text)}" for p in self.paragraphs.values()
        )

    def resolve(self, refs: Sequence[str]) -> tuple[Material, list[EvidenceSpan]] | str:
        """The one material and its slices that `refs` name, or why they cannot be used."""
        found = [self.paragraphs.get(ref) for ref in refs]
        if any(paragraph is None for paragraph in found):
            return "REF_OUTSIDE_PARAGRAPHS"
        named = [paragraph for paragraph in found if paragraph is not None]
        if len({paragraph.material.number for paragraph in named}) != 1:
            return "REFS_ACROSS_MATERIALS"
        material = named[0].material
        return material, material.source.spans([paragraph.segment.id for paragraph in named])

    def known(self, refs: Sequence[str]) -> bool:
        return all(ref in self.paragraphs for ref in refs)
