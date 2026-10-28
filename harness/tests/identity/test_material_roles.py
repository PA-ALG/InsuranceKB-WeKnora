"""S4i acceptance: material roles are recognised from data, and rate tables are not evidence.

Protected file: written by Claude (Spec §3.2, revised after review R3/R4 on #200). User ruling
2026-10-17 reverses S4e: a rate table is not evidence. A role needs both of its signals and no
other role may show any; a material that is not recognised stops the product (blueprint §7.3:
quarantine), never passes through. Both page readers apply the same rule, and the documents kept
keep their source identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.eval.pdf_text import PageText, read_pdf
from insurance_harness.eval.product_sources import (
    source_directory,
    source_pages,
    trusted_source_pages,
)
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.material_roles import (
    MaterialRoleError,
    document_roles,
    evidence_pages,
    load_material_roles,
    role_of,
)
from insurance_harness.ingest.source_map import SourceEntry, SourceMapError, load_pages

REPO = Path(__file__).resolve().parents[3]
PRODUCTS = REPO / "dataset" / "shouxian_product"
TERMS_HEAD = "某某终身寿险\n阅读指引\n为了帮助您更好地了解产品"
BROCHURE_HEAD = "某某终身寿险产品说\n明书\n在本说明书中，“您”指投保人"
RATES_HEAD = "《某某终身寿险》年交费率表\n（每万元基本保险金额）\n单位：人民币元"


def test_the_shipped_roles_are_versioned_and_only_rate_tables_are_not_evidence() -> None:
    roles = load_material_roles()
    assert roles.version
    assert {r.role: r.evidence for r in roles.roles} == {
        "terms": True,
        "brochure": True,
        "rate_table": False,
    }


@pytest.mark.parametrize(
    ("document", "head", "role"),
    [
        ("保险条款.pdf", TERMS_HEAD, "terms"),
        ("产品说明书.pdf", BROCHURE_HEAD, "brochure"),  # the keyword wraps across a line
        ("费率表.pdf", RATES_HEAD, "rate_table"),
        ("费率表.pdf", "《某某年金保险》基本保险金额表\n单位：人民币元", "rate_table"),
        ("费率表.PDF", RATES_HEAD, "rate_table"),
        ("E保险条款.pdf", TERMS_HEAD, "terms"),
    ],
)
def test_a_role_needs_both_of_its_signals(document: str, head: str, role: str) -> None:
    assert role_of(document, head) == role


@pytest.mark.parametrize(
    ("document", "head"),
    [
        ("费率表.pdf", BROCHURE_HEAD),  # name and text point at different roles
        ("附件一.pdf", RATES_HEAD),  # text only
        ("费率表.pdf", "本页没有可识别的标题"),  # name only
        ("费率表.pdf", "甲" * 250 + "费率表"),  # the signal must be near the start
        ("产品说明书.pdf", BROCHURE_HEAD + "费率表"),  # a brochure carrying a rate-table title
        ("条款与说明书.pdf", TERMS_HEAD + "说明书"),  # two roles with both signals
        ("目录.pdf", "目录\n第一章……1\n第二章……5"),  # a contents page
        ("保险条款.pdf", ""),  # no readable text
    ],
)
def test_anything_else_is_not_recognised(document: str, head: str) -> None:
    assert role_of(document, head) is None


def pages_of(document: str, *texts: str, sha: str = "c" * 64) -> list[PageText]:
    return [PageText(document, sha, number, text) for number, text in enumerate(texts, start=1)]


def test_rate_table_pages_are_dropped_and_everything_else_keeps_its_order() -> None:
    pages = [
        *pages_of("保险条款.pdf", TERMS_HEAD, "第二页"),
        *pages_of("费率表.pdf", RATES_HEAD, "0 岁 408 元"),
        *pages_of("产品说明书.pdf", BROCHURE_HEAD),
    ]
    assert [(p.document, p.page) for p in evidence_pages(pages)] == [
        ("保险条款.pdf", 1),
        ("保险条款.pdf", 2),
        ("产品说明书.pdf", 1),
    ]
    assert document_roles(pages) == {
        "保险条款.pdf": "terms",
        "费率表.pdf": "rate_table",
        "产品说明书.pdf": "brochure",
    }


@pytest.mark.parametrize(
    ("document", "texts"),
    [
        ("其他材料.pdf", ("无法识别的材料",)),
        ("产品说明书.pdf", (BROCHURE_HEAD + "年交费率表",)),
        ("E保险条款.pdf", ("", "  ")),  # a terms name but no readable text
    ],
)
def test_one_unrecognised_material_stops_the_whole_product(
    document: str, texts: tuple[str, ...]
) -> None:
    pages = [*pages_of("保险条款.pdf", TERMS_HEAD), *pages_of(document, *texts, sha="d" * 64)]
    with pytest.raises(MaterialRoleError) as stopped:
        evidence_pages(pages)
    assert stopped.value.code == "MATERIAL_ROLE_UNRESOLVED"
    assert isinstance(stopped.value, ValueError)


def test_the_opening_text_follows_page_order_and_skips_an_empty_first_page() -> None:
    sha = "c" * 64
    pages = [PageText("费率表.pdf", sha, 2, RATES_HEAD), PageText("费率表.pdf", sha, 1, " ")]
    assert document_roles(pages) == {"费率表.pdf": "rate_table"}
    assert evidence_pages(pages) == []


class Reader:
    def __init__(self, documents: dict[str, tuple[str, str, str]]) -> None:
        self.documents = documents

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        name, head, sha = self.documents[knowledge_id]
        return pages_of(name, head, "下一页", sha=sha)


def entries(*knowledge_ids: str) -> list[SourceEntry]:
    return [SourceEntry(knowledge_id=k, parse_attempt=n) for n, k in enumerate(knowledge_ids, 1)]


def test_dropping_a_middle_rate_table_keeps_the_other_sources_identity() -> None:
    reader = Reader(
        {
            "k-1": ("保险条款.pdf", TERMS_HEAD, "1" * 64),
            "k-2": ("费率表.pdf", RATES_HEAD, "2" * 64),
            "k-3": ("产品说明书.pdf", BROCHURE_HEAD, "3" * 64),
        }
    )
    pages, sources = load_pages(reader, "space-1", entries("k-1", "k-2", "k-3"))
    assert [(p.document, p.document_sha256, p.page) for p in pages] == [
        ("保险条款.pdf", "1" * 64, 1),
        ("保险条款.pdf", "1" * 64, 2),
        ("产品说明书.pdf", "3" * 64, 1),
        ("产品说明书.pdf", "3" * 64, 2),
    ]
    assert sources == {
        "保险条款.pdf": SourceRevision("k-1", 1),
        "产品说明书.pdf": SourceRevision("k-3", 3),
    }
    # Ordinals count the documents kept, in read order; every consumer re-verifies ids by quote.
    assert {s.document: s.id[:2] for s in SegmentedSource(pages).segments} == {
        "保险条款.pdf": "D1",
        "产品说明书.pdf": "D2",
    }


def test_one_name_twice_is_refused_before_roles_are_judged() -> None:
    reader = Reader(
        {"k-1": ("费率表.pdf", RATES_HEAD, "1" * 64), "k-2": ("费率表.pdf", RATES_HEAD, "2" * 64)}
    )
    with pytest.raises(SourceMapError) as refused:
        load_pages(reader, "space-1", entries("k-1", "k-2"))
    assert refused.value.code == "SOURCE_DOCUMENTS_AMBIGUOUS"


def test_an_unrecognised_weknora_material_stops_with_a_code() -> None:
    reader = Reader(
        {"k-1": ("保险条款.pdf", TERMS_HEAD, "1" * 64), "k-2": ("附件.pdf", "说明", "2" * 64)}
    )
    with pytest.raises(SourceMapError) as stopped:
        load_pages(reader, "space-1", entries("k-1", "k-2"))
    assert stopped.value.code == "MATERIAL_ROLE_UNRESOLVED"


def test_dataset_pages_no_longer_include_the_rate_table() -> None:
    documents = {p.document for p in source_pages(source_directory(REPO, "1828"))}
    assert documents == {"产品说明书.pdf", "保险条款.pdf"}


def test_every_dataset_material_is_recognised_and_each_product_drops_one_rate_table() -> None:
    # Every material folder, including one that ships no product_meta.json.
    directories = sorted(path for path in PRODUCTS.iterdir() if path.is_dir())
    assert len(directories) >= 14
    for directory in directories:
        roles: dict[str, str | None] = {}
        for path in sorted(directory.glob("*.pdf")):
            roles.update(document_roles(read_pdf(path)))
        if (directory / "material_roles.json").exists():
            check_recorded_folder(directory, roles)
            continue
        assert None not in roles.values(), directory.name
        assert list(roles.values()).count("rate_table") == 1, directory.name
        assert {"terms", "brochure"} <= set(roles.values()), directory.name


def check_recorded_folder(directory: Path, inferred: dict[str, str | None]) -> None:
    """S12d §2.3: a folder with a complete, byte-bound role record. Its record decides roles the
    reader cannot infer and may leave out the brochure; it still has exactly one terms document
    and at most one rate table, and it never contradicts a role inference does resolve."""
    effective = trusted_source_pages(directory).roles  # validates completeness and bytes
    assert set(effective) == set(inferred), directory.name
    for document, role in inferred.items():
        assert role in (None, effective[document]), (directory.name, document)
    values = list(effective.values())
    assert values.count("terms") == 1, directory.name
    assert values.count("rate_table") <= 1, directory.name
