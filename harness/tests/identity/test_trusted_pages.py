"""S4j acceptance: pages are read as whole evidence or for their table header only (Spec §3.2).

Protected file: written by Claude. `trusted_pages` keeps the S4i split for evidence and adds the
pages of roles the TrustPolicy reads for their table header; an unrecognised material still stops
the product. The WeKnora reader keeps those documents' revisions so their citations can open the
file, and the real 1828 rate table offers its header block without a single rate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.catalog.trust_policy import trusted_pages
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.product_sources import source_directory, trusted_source_pages
from insurance_harness.evidence.segments import SegmentedSource, header_block
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.material_roles import MaterialRoleError
from insurance_harness.ingest.source_map import SourceEntry, load_trusted_pages

REPO = Path(__file__).resolve().parents[3]
TERMS_HEAD = "某某终身寿险\n阅读指引\n为了帮助您更好地了解产品"
BROCHURE_HEAD = "某某终身寿险产品说\n明书\n在本说明书中，“您”指投保人"
RATES_HEAD = (
    "《某某终身寿险》年交费率表\n（每万元基本保险金额）\n单位：人民币元\n交费期间\n趸交 3年\n"
    "0 11389 3943"
)


def pages_of(document: str, *texts: str, sha: str = "c" * 64) -> list[PageText]:
    return [PageText(document, sha, number, text) for number, text in enumerate(texts, start=1)]


def test_rate_table_pages_are_kept_apart_for_their_header_only() -> None:
    pages = [
        *pages_of("保险条款.pdf", TERMS_HEAD, "第二页"),
        *pages_of("费率表.pdf", RATES_HEAD, "1 11390 3943", sha="d" * 64),
        *pages_of("产品说明书.pdf", BROCHURE_HEAD, sha="e" * 64),
    ]
    trusted = trusted_pages(pages)
    assert [(p.document, p.page) for p in trusted.evidence] == [
        ("保险条款.pdf", 1),
        ("保险条款.pdf", 2),
        ("产品说明书.pdf", 1),
    ]
    assert list(trusted.table_headers) == ["rate_table"]
    assert [(p.document, p.page) for p in trusted.table_headers["rate_table"]] == [
        ("费率表.pdf", 1),
        ("费率表.pdf", 2),
    ]


def test_an_unrecognised_material_still_stops_the_product() -> None:
    pages = [*pages_of("保险条款.pdf", TERMS_HEAD), *pages_of("附件.pdf", "说明", sha="d" * 64)]
    with pytest.raises(MaterialRoleError) as stopped:
        trusted_pages(pages)
    assert stopped.value.code == "MATERIAL_ROLE_UNRESOLVED"


class Reader:
    def __init__(self, documents: dict[str, tuple[str, str, str]]) -> None:
        self.documents = documents

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        name, head, sha = self.documents[knowledge_id]
        return pages_of(name, head, sha=sha)


def test_the_weknora_reader_keeps_the_header_documents_revision() -> None:
    reader = Reader(
        {
            "k-1": ("保险条款.pdf", TERMS_HEAD, "1" * 64),
            "k-2": ("费率表.pdf", RATES_HEAD, "2" * 64),
            "k-3": ("产品说明书.pdf", BROCHURE_HEAD, "3" * 64),
        }
    )
    entries = [
        SourceEntry(knowledge_id=k, parse_attempt=n) for n, k in enumerate(("k-1", "k-2", "k-3"), 1)
    ]
    trusted, sources = load_trusted_pages(reader, "space-1", entries)
    assert [p.document for p in trusted.evidence] == ["保险条款.pdf", "产品说明书.pdf"]
    assert [p.document for p in trusted.table_headers["rate_table"]] == ["费率表.pdf"]
    assert sources == {
        "保险条款.pdf": SourceRevision("k-1", 1),
        "费率表.pdf": SourceRevision("k-2", 2),
        "产品说明书.pdf": SourceRevision("k-3", 3),
    }
    source = SegmentedSource(trusted.evidence, table_headers=trusted.table_headers)
    assert {s.document: s.id[:2] for s in source.segments} == {
        "保险条款.pdf": "D1",
        "产品说明书.pdf": "D2",
        "费率表.pdf": "D3",
    }


def test_the_real_1828_rate_table_offers_its_header_and_no_rate() -> None:
    trusted = trusted_source_pages(source_directory(REPO, "1828"))
    assert {p.document for p in trusted.evidence} == {"产品说明书.pdf", "保险条款.pdf"}
    headers = trusted.table_headers["rate_table"]
    assert {p.document for p in headers} == {"费率表.pdf"}
    blocks = [header_block(page.text) for page in headers]
    assert all(found is not None for found in blocks)
    for page, found in zip(headers, blocks, strict=True):
        assert found is not None
        text = page.text[found[0] : found[1]]
        assert "10年交 15年交 20年交 30年交" in text
        assert "408" not in text and "397" not in text
