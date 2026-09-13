from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3DSourceSelectionV1,
    _resolve_g3_d_evidence,
)

PRODUCT_NAME = "平安福满分（2026）养老年金保险"


def _source(text: str, *, block_id: str = "block-a") -> SourceBlock:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceBlock(
        tenant_id=10003,
        space_id="space-a",
        raw_kb_id="raw-a",
        knowledge_id="knowledge-a",
        parse_attempt=1,
        revision_id="revision-a",
        source_hash=digest,
        parse_hash="a" * 64,
        parser_identity="parser-a",
        block_id=block_id,
        page_number=1,
        text=text,
        source_type="DOCUMENT",
    )


def _selection(source_ref: str = "source-a", quote: str = PRODUCT_NAME):
    return G3DSourceSelectionV1(source_ref=source_ref, quote=quote)


def _offered(source_ref: str, source: SourceBlock, *ranges: tuple[int, int]):
    return [
        {
            "source_ref": source_ref,
            "source": source.model_dump(exclude={"text"}),
            "spans": [
                {
                    "start": start,
                    "end": end,
                    "quote": source.text[start:end],
                    "heading": "",
                }
                for start, end in ranges
            ],
        }
    ]


def test_window_keeps_both_exact_occurrences_inside_one_offered_span() -> None:
    source = _source(f"甲{PRODUCT_NAME}乙{PRODUCT_NAME}丙")

    evidence = _resolve_g3_d_evidence(
        (_selection(),),
        {"source-a": source},
        allowed={"source-a"},
        offered_sources=_offered("source-a", source, (0, len(source.text))),
    )

    starts = tuple(
        index
        for index in range(len(source.text))
        if source.text.startswith(PRODUCT_NAME, index)
    )
    assert tuple(row.start for row in evidence) == starts
    assert all(row.quote == PRODUCT_NAME for row in evidence)
    assert all(row.end == row.start + len(PRODUCT_NAME) for row in evidence)


def test_window_filters_exact_occurrence_outside_offered_span() -> None:
    source = _source(f"甲{PRODUCT_NAME}乙{PRODUCT_NAME}丙")
    second = source.text.rindex(PRODUCT_NAME)

    evidence = _resolve_g3_d_evidence(
        (_selection(),),
        {"source-a": source},
        offered_sources=_offered(
            "source-a", source, (second, second + len(PRODUCT_NAME))
        ),
    )

    assert tuple(row.start for row in evidence) == (second,)


def test_window_deduplicates_one_occurrence_from_overlapping_spans() -> None:
    source = _source(f"甲乙{PRODUCT_NAME}丙丁")
    start = source.text.index(PRODUCT_NAME)

    evidence = _resolve_g3_d_evidence(
        (_selection(),),
        {"source-a": source},
        offered_sources=_offered(
            "source-a",
            source,
            (0, start + len(PRODUCT_NAME)),
            (start, len(source.text)),
        ),
    )

    assert tuple(row.start for row in evidence) == (start,)


def test_window_rejects_quote_with_no_complete_offered_match() -> None:
    source = _source(f"甲{PRODUCT_NAME}乙")
    start = source.text.index(PRODUCT_NAME)

    with pytest.raises(ValueError, match="outside offered source spans"):
        _resolve_g3_d_evidence(
            (_selection(),),
            {"source-a": source},
            offered_sources=_offered(
                "source-a", source, (start, start + len(PRODUCT_NAME) - 1)
            ),
        )


def test_window_rejects_foreign_source_and_empty_quote() -> None:
    source = _source(PRODUCT_NAME)
    offered = _offered("source-a", source, (0, len(source.text)))

    with pytest.raises(ValueError, match="foreign D source reference"):
        _resolve_g3_d_evidence(
            (_selection("source-b"),),
            {"source-a": source},
            offered_sources=offered,
        )
    with pytest.raises(ValueError, match="empty"):
        _resolve_g3_d_evidence(
            (SimpleNamespace(source_ref="source-a", quote=""),),
            {"source-a": source},
            offered_sources=offered,
        )


def test_legacy_mode_preserves_unique_occurrence_requirement() -> None:
    unique = _source(f"甲{PRODUCT_NAME}乙")
    evidence = _resolve_g3_d_evidence((_selection(),), {"source-a": unique})
    assert len(evidence) == 1
    assert evidence[0].start == unique.text.index(PRODUCT_NAME)

    repeated = _source(f"甲{PRODUCT_NAME}乙{PRODUCT_NAME}丙")
    with pytest.raises(ValueError, match="must occur exactly once"):
        _resolve_g3_d_evidence((_selection(),), {"source-a": repeated})
