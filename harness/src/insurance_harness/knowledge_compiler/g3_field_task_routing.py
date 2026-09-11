"""Bounded chapter routing shared by catalog and discovered field tasks.

The MVP chapter detector is reused; source text is never normalized or rewritten,
so every offered span retains original revision/block/character offsets.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from insurance_harness.compiler.sections import _is_heading

from .concept_free_wiki_830_g2 import SourceBlock
from .g3_field_tasks import FieldTaskV1

ROUTING_VERSION = "g3-field-task-chapter-routing.830.v1"


def _terms(task: FieldTaskV1) -> tuple[str, ...]:
    text = " ".join(filter(None, (task.short_title, task.source_guidance, task.description)))
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_]+|[\u3400-\u9fff]{2,}", text))
    # Chinese documents do not require a network tokenizer or another model call.
    words.update(
        text[index : index + 2]
        for index in range(len(text) - 1)
        if all("\u3400" <= c <= "\u9fff" for c in text[index : index + 2])
    )
    return tuple(sorted(words))


def _spans(text: str, limit: int) -> tuple[tuple[int, int, str], ...]:
    boundaries = [0]
    offset = 0
    title = ""
    titles: dict[int, str] = {}
    for line in text.splitlines(keepends=True):
        if _is_heading(line):
            if offset and offset != boundaries[-1]:
                boundaries.append(offset)
            title = line.strip()
        titles[offset] = title
        offset += len(line)
    boundaries.append(len(text))
    rows = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        while start < end:
            stop = min(start + limit, end)
            if stop < end:
                # Keep paragraph/sentence ends when possible without dropping text.
                cuts = [text.rfind(mark, start + limit // 2, stop) for mark in ("\n", "。", "；")]
                if max(cuts) >= 0:
                    stop = max(cuts) + 1
            heading = next((titles[key] for key in reversed(titles) if key <= start), "")
            rows.append((start, stop, heading))
            start = stop
    return tuple(rows)


def route_field_task_sources(
    tasks: Sequence[FieldTaskV1],
    sources: Mapping[str, SourceBlock],
    *,
    max_source_chars: int = 24000,
    max_span_chars: int = 2000,
) -> list[dict[str, object]]:
    """Select fair per-field chapter hits, then fill a strict shared text budget."""
    if max_span_chars <= 0 or max_source_chars < max_span_chars:
        raise ValueError("invalid field task source budget")
    candidates = [
        (ref, start, end, heading)
        for ref, source in sorted(sources.items())
        for start, end, heading in _spans(source.text, max_span_chars)
    ]
    ranked = []
    for task in tasks:
        terms = _terms(task)
        allowed_keys = {(s.revision_id, s.block_id) for s in task.allowed_sources}
        eligible = [
            row
            for row in candidates
            if not allowed_keys
            or (sources[row[0]].revision_id, sources[row[0]].block_id) in allowed_keys
        ]
        ranked.append(
            sorted(
                eligible,
                key=lambda row: (
                    -sum(
                        (4 if term in row[3] else 0)
                        + (1 if term in sources[row[0]].text[row[1] : row[2]] else 0)
                        for term in terms
                    ),
                    row[0],
                    row[1],
                ),
            )
        )
    if not ranked:
        ranked = [candidates]
    chosen: dict[tuple[str, int, int], tuple[str, int, int, str]] = {}
    size = 0
    # Round-robin avoids ten fields all spending their budget on the first field.
    for depth in range(max((len(rows) for rows in ranked), default=0)):
        for rows in ranked:
            if depth >= len(rows):
                continue
            row = rows[depth]
            key = row[:3]
            if key in chosen:
                continue
            if size + row[2] - row[1] <= max_source_chars:
                chosen[key] = row
                size += row[2] - row[1]
    result = []
    for ref, source in sorted(sources.items()):
        spans = [
            {"start": start, "end": end, "quote": source.text[start:end], "heading": heading}
            for r, start, end, heading in sorted(chosen.values())
            if r == ref
        ]
        if spans:
            result.append(
                {"source_ref": ref, "source": source.model_dump(exclude={"text"}), "spans": spans}
            )
    return result


def validate_routed_selections(selections, offered_sources) -> None:
    """Reject model quotes outside the exact bounded spans it was offered."""
    offered = {row["source_ref"]: row["spans"] for row in offered_sources}
    for source_ref, quote in selections:
        if not quote or not any(quote in span["quote"] for span in offered.get(source_ref, ())):
            raise ValueError("D source quote is outside offered source spans")
