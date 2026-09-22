"""Schema-independent, bounded material coverage for open knowledge discovery.

Selection samples whole chapter spans without rewriting original text. Coverage
describes exactly what was offered and omitted; a sample is never a full reading.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from typing import Literal, TypedDict

from .concept_free_wiki_830_g2 import SourceBlock
from .g3_field_task_routing import RoutedSource, RoutedSourceIdentity, RoutedSourceSpan, _spans

ROUTING_VERSION = "g3-discovery-material-spread.830.v1"
Span = tuple[str, int, int, str]


class DiscoveryRange(TypedDict):
    start: int
    end: int


class DiscoverySourceCoverage(TypedDict):
    source_ref: str
    knowledge_id: str
    revision_id: str
    block_id: str
    page_number: int
    total_chars: int
    offered_chars: int
    omitted_chars: int
    offered_ranges: list[DiscoveryRange]
    omitted_ranges: list[DiscoveryRange]


class DiscoveryCoverage(TypedDict):
    routing_version: str
    offset_unit: Literal["UNICODE_CODE_POINT"]
    max_source_chars: int
    max_span_chars: int
    total_chars: int
    offered_chars: int
    omitted_chars: int
    complete: bool
    material_count: int
    represented_material_count: int
    total_span_count: int
    offered_span_count: int
    omitted_span_count: int
    sources: list[DiscoverySourceCoverage]


class DiscoverySourceSelection(TypedDict):
    source_options: list[RoutedSource]
    coverage: DiscoveryCoverage


class DiscoverySourceWindow(DiscoverySourceSelection):
    window_id: str
    window_index: int
    window_count: int


def _source_identity(source: SourceBlock) -> RoutedSourceIdentity:
    return RoutedSourceIdentity(
        tenant_id=source.tenant_id,
        space_id=source.space_id,
        raw_kb_id=source.raw_kb_id,
        knowledge_id=source.knowledge_id,
        parse_attempt=source.parse_attempt,
        revision_id=source.revision_id,
        source_hash=source.source_hash,
        parse_hash=source.parse_hash,
        parser_identity=source.parser_identity,
        block_id=source.block_id,
        page_number=source.page_number,
        source_type=source.source_type,
    )


def _spread(rows: Sequence[Span]) -> Iterator[Span]:
    """Offer both ends, then breadth-first midpoints of the ordered interior."""
    if not rows:
        return
    yield rows[0]
    if len(rows) == 1:
        return
    yield rows[-1]
    intervals = deque([(1, len(rows) - 2)])
    while intervals:
        start, end = intervals.popleft()
        if start > end:
            continue
        middle = (start + end) // 2
        yield rows[middle]
        intervals.extend(((start, middle - 1), (middle + 1, end)))


def route_discovery_sources(
    sources: Mapping[str, SourceBlock],
    *,
    max_source_chars: int = 24000,
    max_span_chars: int = 2000,
) -> DiscoverySourceSelection:
    """Round-robin materials, spreading whole spans across pages and chapters.

    Budgets count Unicode code points of offered quotes, excluding metadata.
    Entire spans that do not fit are omitted, never truncated to use the tail
    of a budget. If not all materials fit, coverage reports that explicitly.
    """
    if (
        type(max_source_chars) is not int
        or type(max_span_chars) is not int
        or max_span_chars <= 0
        or max_source_chars < max_span_chars
    ):
        raise ValueError("invalid discovery source budget")
    ordered = sorted(
        sources.items(),
        key=lambda pair: (
            pair[1].knowledge_id,
            pair[1].page_number,
            pair[1].revision_id,
            pair[1].block_id,
            pair[0],
        ),
    )
    material_rows: dict[str, list[Span]] = {}
    source_rows: dict[str, tuple[Span, ...]] = {}
    seen = set()
    for ref, source in ordered:
        identity = (source.knowledge_id, source.revision_id, source.block_id)
        if identity in seen:
            raise ValueError("duplicate source block alias in discovery routing")
        seen.add(identity)
        rows = tuple(
            (ref, start, end, heading)
            for start, end, heading in _spans(source.text, max_span_chars)
        )
        source_rows[ref] = rows
        material_rows.setdefault(source.knowledge_id, []).extend(rows)

    iterators = {material: _spread(rows) for material, rows in material_rows.items()}
    chosen: set[tuple[str, int, int]] = set()
    used = 0
    while iterators and used < max_source_chars:
        exhausted = []
        for material, iterator in iterators.items():
            for ref, start, end, _heading in iterator:
                if used + end - start <= max_source_chars:
                    chosen.add((ref, start, end))
                    used += end - start
                    break
            else:
                exhausted.append(material)
        for material in exhausted:
            del iterators[material]

    options: list[RoutedSource] = []
    coverage_sources: list[DiscoverySourceCoverage] = []
    represented = set()
    total_chars = 0
    total_spans = 0
    for ref, source in ordered:
        offered_ranges: list[DiscoveryRange] = []
        omitted_ranges: list[DiscoveryRange] = []
        offered_spans: list[RoutedSourceSpan] = []
        for _, start, end, heading in source_rows[ref]:
            span_range = DiscoveryRange(start=start, end=end)
            if (ref, start, end) in chosen:
                offered_ranges.append(span_range)
                offered_spans.append(
                    {
                        "start": start,
                        "end": end,
                        "quote": source.text[start:end],
                        "heading": heading,
                    }
                )
            else:
                omitted_ranges.append(span_range)
        offered_chars = sum(row["end"] - row["start"] for row in offered_ranges)
        total_chars += len(source.text)
        total_spans += len(source_rows[ref])
        coverage_sources.append(
            {
                "source_ref": ref,
                "knowledge_id": source.knowledge_id,
                "revision_id": source.revision_id,
                "block_id": source.block_id,
                "page_number": source.page_number,
                "total_chars": len(source.text),
                "offered_chars": offered_chars,
                "omitted_chars": len(source.text) - offered_chars,
                "offered_ranges": offered_ranges,
                "omitted_ranges": omitted_ranges,
            }
        )
        if offered_spans:
            represented.add(source.knowledge_id)
            options.append(
                {
                    "source_ref": ref,
                    "source": _source_identity(source),
                    "spans": offered_spans,
                }
            )
    return {
        "source_options": options,
        "coverage": {
            "routing_version": ROUTING_VERSION,
            "offset_unit": "UNICODE_CODE_POINT",
            "max_source_chars": max_source_chars,
            "max_span_chars": max_span_chars,
            "total_chars": total_chars,
            "offered_chars": used,
            "omitted_chars": total_chars - used,
            "complete": total_chars == used,
            "material_count": len(material_rows),
            "represented_material_count": len(represented),
            "total_span_count": total_spans,
            "offered_span_count": len(chosen),
            "omitted_span_count": total_spans - len(chosen),
            "sources": coverage_sources,
        },
    }


def route_discovery_source_windows(
    sources: Mapping[str, SourceBlock],
    *,
    max_source_chars: int = 24000,
    max_span_chars: int = 2000,
) -> tuple[DiscoverySourceWindow, ...]:
    """Cover each original span once using the existing chapter and material order.

    The detailed per-source coverage is a server-side audit record. Callers may
    project a smaller model view, but must retain these exact offsets and counts.
    """
    if (
        type(max_source_chars) is not int
        or type(max_span_chars) is not int
        or max_span_chars <= 0
        or max_source_chars < max_span_chars
    ):
        raise ValueError("invalid discovery source budget")
    ordered = sorted(
        sources.items(),
        key=lambda pair: (
            pair[1].knowledge_id,
            pair[1].page_number,
            pair[1].revision_id,
            pair[1].block_id,
            pair[0],
        ),
    )
    material_rows: dict[str, list[Span]] = {}
    source_rows: dict[str, tuple[Span, ...]] = {}
    seen = set()
    for ref, source in ordered:
        identity = (source.knowledge_id, source.revision_id, source.block_id)
        if identity in seen:
            raise ValueError("duplicate source block alias in discovery routing")
        seen.add(identity)
        rows = tuple(
            (ref, start, end, heading)
            for start, end, heading in _spans(source.text, max_span_chars)
        )
        source_rows[ref] = rows
        material_rows.setdefault(source.knowledge_id, []).extend(rows)
    iterators = {material: _spread(rows) for material, rows in material_rows.items()}
    spread: list[Span] = []
    while iterators:
        exhausted = []
        for material, iterator in iterators.items():
            row = next(iterator, None)
            if row is None:
                exhausted.append(material)
            else:
                spread.append(row)
        for material in exhausted:
            del iterators[material]
    partitions: list[list[Span]] = []
    current: list[Span] = []
    used = 0
    for row in spread:
        size = row[2] - row[1]
        if current and used + size > max_source_chars:
            partitions.append(current)
            current = []
            used = 0
        current.append(row)
        used += size
    if current:
        partitions.append(current)
    result: list[DiscoverySourceWindow] = []
    total_chars = sum(len(source.text) for _, source in ordered)
    total_spans = sum(len(rows) for rows in source_rows.values())
    for index, partition in enumerate(partitions):
        chosen = {(ref, start, end) for ref, start, end, _ in partition}
        options: list[RoutedSource] = []
        coverage_sources: list[DiscoverySourceCoverage] = []
        represented = set()
        offered_chars = 0
        for ref, source in ordered:
            offered_ranges: list[DiscoveryRange] = []
            omitted_ranges: list[DiscoveryRange] = []
            offered_spans: list[RoutedSourceSpan] = []
            for _, start, end, heading in source_rows[ref]:
                span_range = DiscoveryRange(start=start, end=end)
                if (ref, start, end) in chosen:
                    offered_ranges.append(span_range)
                    offered_spans.append(
                        {
                            "start": start,
                            "end": end,
                            "quote": source.text[start:end],
                            "heading": heading,
                        }
                    )
                else:
                    omitted_ranges.append(span_range)
            source_offered = sum(row["end"] - row["start"] for row in offered_ranges)
            offered_chars += source_offered
            coverage_sources.append(
                {
                    "source_ref": ref,
                    "knowledge_id": source.knowledge_id,
                    "revision_id": source.revision_id,
                    "block_id": source.block_id,
                    "page_number": source.page_number,
                    "total_chars": len(source.text),
                    "offered_chars": source_offered,
                    "omitted_chars": len(source.text) - source_offered,
                    "offered_ranges": offered_ranges,
                    "omitted_ranges": omitted_ranges,
                }
            )
            if offered_spans:
                represented.add(source.knowledge_id)
                options.append(
                    {
                        "source_ref": ref,
                        "source": _source_identity(source),
                        "spans": offered_spans,
                    }
                )
        window_identity = [(ref, start, end) for ref, start, end, _ in partition]
        window_id = hashlib.sha256(
            json.dumps(window_identity, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        result.append(
            {
                "window_id": window_id,
                "window_index": index,
                "window_count": len(partitions),
                "source_options": options,
                "coverage": {
                    "routing_version": ROUTING_VERSION,
                    "offset_unit": "UNICODE_CODE_POINT",
                    "max_source_chars": max_source_chars,
                    "max_span_chars": max_span_chars,
                    "total_chars": total_chars,
                    "offered_chars": offered_chars,
                    "omitted_chars": total_chars - offered_chars,
                    "complete": total_chars == offered_chars,
                    "material_count": len(material_rows),
                    "represented_material_count": len(represented),
                    "total_span_count": total_spans,
                    "offered_span_count": len(partition),
                    "omitted_span_count": total_spans - len(partition),
                    "sources": coverage_sources,
                },
            }
        )
    return tuple(result)
