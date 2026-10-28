"""S5b-6 acceptance (protected, written by Claude): a material role recorded in the registry is
authoritative when compiling and publishing; page inference only applies without a record.

Spec docs/design/slices/S5b-6-已确认材料角色用于编译.md §4. Offline: a fake page reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.source_map import (
    SourceEntry,
    SourceMapError,
    load_pages,
    load_source_map,
    load_trusted_pages,
)
from tests.ingest.upload_helpers import entry, knowledge_id, registry

SHA = "ab" * 32
SPACE = "space-1"

# A conversion table named like a rate table whose opening text carries no rate-table signal:
# the S4i inference cannot resolve its role (the 2026-10-28 recompile failure).
DOCUMENTS = {
    "k-terms": ("保险条款.pdf", "阅读指引 本条款"),
    "k-table": ("费率表.pdf", "转换标准表 每万元保单账户价值转换的领取金额"),
    "k-brochure": ("产品说明书.pdf", "产品说明书 本产品"),
}


class Reader:
    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        name, head = DOCUMENTS[knowledge_id]
        return [PageText(name, SHA, 1, f"{head}第一页"), PageText(name, SHA, 2, "第二页")]


def entries(**roles: str | None) -> list[SourceEntry]:
    return [
        SourceEntry(knowledge_id=kid, parse_attempt=1, role=role) for kid, role in roles.items()
    ]


def test_a_recorded_role_resolves_a_material_pages_cannot() -> None:
    trusted, sources = load_trusted_pages(
        Reader(), SPACE, entries(**{"k-terms": "terms", "k-table": "rate_table"})
    )
    assert {page.document for page in trusted.evidence} == {"保险条款.pdf"}, (
        "a rate table is not evidence"
    )
    assert [page.document for page in trusted.table_headers["rate_table"]] == [
        "费率表.pdf",
        "费率表.pdf",
    ], "it is the header input the trust policy names for rate tables"
    assert sources == {
        "保险条款.pdf": SourceRevision("k-terms", 1),
        "费率表.pdf": SourceRevision("k-table", 1),
    }


def test_without_a_record_an_unresolvable_material_still_stops_the_read() -> None:
    with pytest.raises(SourceMapError) as caught:
        load_trusted_pages(Reader(), SPACE, entries(**{"k-terms": None, "k-table": None}))
    assert caught.value.code == "MATERIAL_ROLE_UNRESOLVED"


def test_a_recorded_role_wins_over_a_contradicting_inference() -> None:
    # The pages look like a brochure; the record says terms. Terms and brochures are both
    # evidence, so the difference shows in the trusted headers and the role map the read uses.
    trusted, _ = load_trusted_pages(
        Reader(), SPACE, entries(**{"k-brochure": "rate_table", "k-terms": "terms"})
    )
    assert {page.document for page in trusted.evidence} == {"保险条款.pdf"}, (
        "the recorded rate_table role keeps the brochure-looking file out of evidence"
    )
    assert {page.document for page in trusted.table_headers["rate_table"]} == {"产品说明书.pdf"}


def test_an_unknown_recorded_role_stops_the_read() -> None:
    with pytest.raises(SourceMapError) as caught:
        load_trusted_pages(Reader(), SPACE, entries(**{"k-terms": "manual"}))
    assert caught.value.code == "MATERIAL_ROLE_UNKNOWN"


def test_the_evidence_only_read_uses_recorded_roles_too() -> None:
    pages, sources = load_pages(
        Reader(), SPACE, entries(**{"k-terms": "terms", "k-table": "rate_table"})
    )
    assert {page.document for page in pages} == {"保险条款.pdf"}
    assert sources == {"保险条款.pdf": SourceRevision("k-terms", 1)}

    with pytest.raises(SourceMapError) as caught:
        load_pages(Reader(), SPACE, entries(**{"k-terms": "terms", "k-table": None}))
    assert caught.value.code == "MATERIAL_ROLE_UNRESOLVED"


def test_the_registry_source_map_carries_the_recorded_roles() -> None:
    value: ProductRegistry = registry(p1828=entry("1828", "rate_table", "terms"))
    assert value.source_map().products["1828"] == [
        SourceEntry(
            knowledge_id=knowledge_id("1828", "rate_table"), parse_attempt=1, role="rate_table"
        ),
        SourceEntry(knowledge_id=knowledge_id("1828", "terms"), parse_attempt=1, role="terms"),
    ]


def test_a_source_map_file_without_roles_loads_and_infers_as_before(tmp_path: Path) -> None:
    path = tmp_path / "map.json"
    path.write_text(
        json.dumps(
            {
                "space_id": SPACE,
                "products": {
                    "1828": [
                        {"knowledge_id": "k-terms", "parse_attempt": 1},
                        {"knowledge_id": "k-brochure", "parse_attempt": 1},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    source_map = load_source_map(path)
    assert all(e.role is None for e in source_map.entries("1828"))
    trusted, _ = load_trusted_pages(Reader(), SPACE, source_map.entries("1828"))
    assert {page.document for page in trusted.evidence} == {"保险条款.pdf", "产品说明书.pdf"}
