"""PB-A2: the actual read-only attribution entry keeps page and source boundaries."""

from collections.abc import Sequence

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import ProductEntry, ProductRegistry
from insurance_harness.ingest.uploads import attribute_uploads

NAME = "合成附加谨慎医疗保险"
SOURCE = RawSource(
    knowledge_id="synthetic-rate", parse_attempt=7, sha256="a" * 64, file_name="费率表.pdf"
)
ROWS = "投保年龄 男 女\n0 10 20\n" * 20


class Reader:
    def __init__(self, texts: Sequence[str], *, wrong_sha: bool = False) -> None:
        self.texts = texts
        self.wrong_sha = wrong_sha
        self.calls: list[tuple[str, str, int]] = []

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        self.calls.append((space_id, knowledge_id, attempt))
        return list(reversed([
            PageText(knowledge_id, "b" * 64 if self.wrong_sha else SOURCE.sha256, i + 1, text)
            for i, text in enumerate(self.texts)
        ]))


def registry() -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1", space_id="synthetic-space", raw_kb_id="synthetic-raw",
        products={"synthetic-product": ProductEntry(
            names=[NAME], clause_codes=[], schema_pack_id="schemapack_medical_insurance",
            origin="seeded", materials=[],
        )}, pending=[], decisions=[],
    )


@pytest.mark.parametrize("texts", [[ROWS + NAME + "年交费率表"], [ROWS, NAME + "年保障成本表"]])
def test_whole_title_on_first_or_second_page_records_the_exact_source(texts: list[str]) -> None:
    current = registry()
    before = current.model_dump()
    reader = Reader(texts)
    result = attribute_uploads(current, [SOURCE], reader)
    assert current.model_dump() == before
    assert reader.calls == [(current.space_id, SOURCE.knowledge_id, SOURCE.parse_attempt)]
    material = result.registry.products["synthetic-product"].materials
    assert len(material) == 1
    assert (material[0].knowledge_id, material[0].parse_attempt, material[0].sha256) == (
        SOURCE.knowledge_id, SOURCE.parse_attempt, SOURCE.sha256
    )
    assert material[0].role == "rate_table"
    assert len(result.registry.decisions) == 1
    assert result.registry.decisions[0].attribution.outcome == "SUPPLEMENT"
    assert result.registry.decisions[0].attribution.policy_ref == "attribution-policy@2026-11-14.1"


@pytest.mark.parametrize(
    "texts",
    [[ROWS, ROWS, NAME + "年交费率表"], [ROWS + NAME[:5], NAME[5:] + "年交费率表"]],
)
def test_third_page_and_cross_page_name_cannot_supply_a_title(texts: list[str]) -> None:
    result = attribute_uploads(registry(), [SOURCE], Reader(texts))
    assert result.registry.products["synthetic-product"].materials == []
    assert len(result.registry.pending) == 1
    assert result.registry.pending[0].attribution.outcome == "QUARANTINE"


def test_title_in_a_different_source_revision_is_unreadable() -> None:
    result = attribute_uploads(registry(), [SOURCE], Reader([NAME + "年交费率表"], wrong_sha=True))
    assert result.registry.products["synthetic-product"].materials == []
    assert result.registry.decisions == []
    assert len(result.report.unreadable) == 1
    assert result.report.unreadable == [SOURCE.knowledge_id]
    assert result.report.unreadable_reasons[0].code == "PARSE_ARTIFACT_INTEGRITY"
