"""S4i acceptance: material roles are recognised from data, and rate tables are not evidence.

Protected file: written by Claude (Spec §3.2). User ruling 2026-10-17 reverses S4e: a rate table is
not evidence. A role needs both its name signal and its opening-text signal; anything else stays
unrecognised and keeps today's behaviour. Both page readers drop non-evidence documents, so
compiling, publishing and scoring see the same pages.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.eval.pdf_text import PageText, read_pdf
from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.identity.material_roles import (
    document_roles,
    evidence_pages,
    load_material_roles,
    role_of,
)
from insurance_harness.ingest.source_map import SourceEntry, load_pages

REPO = Path(__file__).resolve().parents[3]
PRODUCTS = REPO / "dataset" / "shouxian_product"
SHA = "c" * 64
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
    ],
)
def test_a_role_needs_its_name_and_its_opening_text(document: str, head: str, role: str) -> None:
    assert role_of(document, head) == role


@pytest.mark.parametrize(
    ("document", "head"),
    [
        ("费率表.pdf", BROCHURE_HEAD),  # name and text disagree
        ("附件一.pdf", RATES_HEAD),  # text only
        ("费率表.pdf", "本页没有可识别的标题"),  # name only
        ("费率表.pdf", "甲" * 250 + "费率表"),  # the signal must be near the start
    ],
)
def test_anything_else_is_not_recognised(document: str, head: str) -> None:
    assert role_of(document, head) is None


def pages_of(document: str, *texts: str) -> list[PageText]:
    return [PageText(document, SHA, number, text) for number, text in enumerate(texts, start=1)]


def test_rate_table_pages_are_dropped_and_everything_else_keeps_its_order() -> None:
    pages = [
        *pages_of("保险条款.pdf", TERMS_HEAD, "第二页"),
        *pages_of("费率表.pdf", RATES_HEAD, "0 岁 408 元"),
        *pages_of("产品说明书.pdf", BROCHURE_HEAD),
        *pages_of("其他材料.pdf", "无法识别的材料"),
    ]
    kept = evidence_pages(pages)
    assert [(p.document, p.page) for p in kept] == [
        ("保险条款.pdf", 1),
        ("保险条款.pdf", 2),
        ("产品说明书.pdf", 1),
        ("其他材料.pdf", 1),
    ]
    assert document_roles(pages) == {
        "保险条款.pdf": "terms",
        "费率表.pdf": "rate_table",
        "产品说明书.pdf": "brochure",
        "其他材料.pdf": None,
    }


def test_the_opening_text_follows_page_order_and_skips_an_empty_first_page() -> None:
    pages = [PageText("费率表.pdf", SHA, 2, RATES_HEAD), PageText("费率表.pdf", SHA, 1, "  ")]
    assert document_roles(pages) == {"费率表.pdf": "rate_table"}
    assert evidence_pages(pages) == []


class Reader:
    def __init__(self, documents: dict[str, tuple[str, str]]) -> None:
        self.documents = documents

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        name, head = self.documents[knowledge_id]
        return pages_of(name, head, "下一页")


def test_reading_from_weknora_drops_rate_tables_and_their_revisions() -> None:
    reader = Reader({"k-1": ("保险条款.pdf", TERMS_HEAD), "k-2": ("费率表.pdf", RATES_HEAD)})
    entries = [SourceEntry(knowledge_id="k-1", parse_attempt=1)]
    entries.append(SourceEntry(knowledge_id="k-2", parse_attempt=1))
    pages, sources = load_pages(reader, "space-1", entries)
    assert {p.document for p in pages} == {"保险条款.pdf"}
    assert set(sources) == {"保险条款.pdf"}


def test_dataset_pages_no_longer_include_the_rate_table() -> None:
    documents = {p.document for p in source_pages(source_directory(REPO, "1828"))}
    assert documents == {"产品说明书.pdf", "保险条款.pdf"}


def test_every_dataset_material_is_recognised_and_each_product_drops_one_rate_table() -> None:
    directories = sorted(path.parent for path in PRODUCTS.glob("*/product_meta.json"))
    assert len(directories) >= 14
    for directory in directories:
        roles: dict[str, str | None] = {}
        for path in sorted(directory.glob("*.pdf")):
            roles.update(document_roles(read_pdf(path)))
        assert None not in roles.values(), directory.name
        assert list(roles.values()).count("rate_table") == 1, directory.name
        assert {"terms", "brochure"} <= set(roles.values()), directory.name
