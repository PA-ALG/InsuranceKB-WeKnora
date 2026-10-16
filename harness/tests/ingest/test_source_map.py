"""The source map names fixed WeKnora revisions; pages are read from exactly those."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.source_map import load_pages, load_source_map, page_source

SHA = "ab" * 32


class Reader:
    def __init__(self, documents: dict[tuple[str, int], str]) -> None:
        self.documents = documents
        self.calls: list[tuple[str, str, int]] = []

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        self.calls.append((space_id, knowledge_id, attempt))
        name = self.documents[(knowledge_id, attempt)]
        return [PageText(name, SHA, 1, "第一页"), PageText(name, SHA, 2, "第二页")]


def write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "map.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


MAP = {
    "space_id": "space-1",
    "products": {
        "1828": [
            {"knowledge_id": "k-1", "parse_attempt": 2},
            {"knowledge_id": "k-2", "parse_attempt": 1},
        ]
    },
}


def test_pages_and_revisions_come_from_the_named_attempts(tmp_path: Path) -> None:
    source_map = load_source_map(write(tmp_path, MAP))
    reader = Reader({("k-1", 2): "保险条款.pdf", ("k-2", 1): "产品说明书.pdf"})
    pages, sources = load_pages(reader, source_map.space_id, source_map.entries("1828"))
    assert [(p.document, p.page) for p in pages] == [
        ("保险条款.pdf", 1),
        ("保险条款.pdf", 2),
        ("产品说明书.pdf", 1),
        ("产品说明书.pdf", 2),
    ]
    assert sources == {
        "保险条款.pdf": SourceRevision("k-1", 2),
        "产品说明书.pdf": SourceRevision("k-2", 1),
    }
    assert reader.calls == [("space-1", "k-1", 2), ("space-1", "k-2", 1)]
    assert len(page_source(source_map, reader)("1828")) == 4


def test_two_revisions_with_one_document_name_are_refused(tmp_path: Path) -> None:
    source_map = load_source_map(write(tmp_path, MAP))
    reader = Reader({("k-1", 2): "保险条款.pdf", ("k-2", 1): "保险条款.pdf"})
    with pytest.raises(ValueError):
        load_pages(reader, source_map.space_id, source_map.entries("1828"))


@pytest.mark.parametrize(
    "document",
    [
        {"space_id": "space-1", "products": {"1828": []}},
        {
            "space_id": "space-1",
            "products": {"1828": [{"knowledge_id": "../x", "parse_attempt": 1}]},
        },
        {"space_id": "space-1", "products": {"1828": [{"knowledge_id": "k", "parse_attempt": 0}]}},
        {"space_id": "space-1", "products": {}, "extra": 1},
    ],
)
def test_malformed_maps_are_refused(tmp_path: Path, document: object) -> None:
    with pytest.raises(ValueError):
        source_map = load_source_map(write(tmp_path, document))
        source_map.entries("1828")
