from __future__ import annotations

import hashlib
import importlib
import typing
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    SourceBlock,
    verify_evidence,
)
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1


def module() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.routing")
    except ModuleNotFoundError as error:
        if error.name not in {
            "insurance_harness.product_ingestion",
            "insurance_harness.product_ingestion.routing",
        }:
            raise
        pytest.fail("platform first-page product routing is not implemented")


@pytest.fixture(scope="module")
def catalog() -> typing.Any:
    path = Path(__file__).parents[3] / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
    return SchemaPackCatalogV1.model_validate_json(path.read_bytes())


def source(
    mid: typing.Any, text: typing.Any, page: typing.Any = 1, tenant: typing.Any = 10003
) -> SourceBlock:
    return SourceBlock(
        tenant_id=tenant,
        space_id="space",
        raw_kb_id="raw",
        knowledge_id=mid,
        parse_attempt=1,
        revision_id=f"revision-{mid}",
        source_hash="a" * 64,
        parse_hash="b" * 64,
        parser_identity="native-v1",
        block_id=f"{mid}-p{page}",
        page_number=page,
        text=text,
        source_type="DOCUMENT",
    )


def materials(title: typing.Any = "平安测试（2026）两全保险") -> typing.Any:
    return [
        {
            "material_id": role,
            "file_name": filename,
            "blocks": (source(role, title + "\n" + label),),
        }
        for role, filename, label in (
            ("terms", "保险条款.pdf", "保险条款"),
            ("brochure", "产品说明书.pdf", "产品说明书"),
            ("rates", "费率表.pdf", "费率表"),
        )
    ]


def test_platform_groups_first_page_title_preserving_each_material_role(
    catalog: typing.Any,
) -> None:
    result = module().route_product_materials(materials(), catalog=catalog)
    assert result.status == "matched"
    assert result.product_name == "平安测试（2026）两全保险"
    assert result.route.primary_label == "endowment_insurance"
    assert [row.material_type for row in result.materials] == ["terms", "brochure", "rate_table"]
    assert len({row.material_id for row in result.materials}) == 3
    for row, original in zip(result.materials, materials(), strict=True):
        assert row.title_evidence
        for evidence in row.title_evidence:
            verify_evidence(evidence, original["blocks"])


def test_wrapped_name_normalizes_identity_without_changing_original_quote(
    catalog: typing.Any,
) -> None:
    rows = materials()
    rows[1]["blocks"] = (source("brochure", "平安测试(2026)\r\n两全保险产品说明书"),)
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "matched"
    evidence = result.materials[1].title_evidence[0]
    assert evidence.quote == "平安测试(2026)\r\n两全保险"
    assert evidence.quote_hash == hashlib.sha256(evidence.quote.encode()).hexdigest()


@pytest.mark.parametrize("other", ["平安测试（2025）两全保险", "平安其他（2026）两全保险"])
def test_conflicting_identity_or_version_is_a_platform_terminal(
    catalog: typing.Any, other: typing.Any
) -> None:
    rows = materials()
    rows[2]["blocks"] = (source("rates", other + "\n费率表"),)
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "needs_confirmation"
    assert result.reason == "PRODUCT_IDENTITY_OR_VERSION_CONFLICT"
    assert result.product_name is None


def test_filename_and_later_page_cannot_supply_missing_first_page_identity(
    catalog: typing.Any,
) -> None:
    rows = materials()
    rows[2]["file_name"] = "平安测试（2026）两全保险费率表.pdf"
    rows[2]["blocks"] = (
        source("rates", "投保年龄与交费方式\n费率表"),
        source("rates", "平安测试（2026）两全保险", page=2),
    )
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "needs_confirmation"
    assert result.reason == "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"


def test_material_role_conflict_is_explicit(catalog: typing.Any) -> None:
    rows = materials()
    rows[2]["file_name"] = "保险条款.pdf"
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "needs_confirmation"
    assert result.reason == "MATERIAL_TYPE_CONFLICT"


def test_sources_from_another_tenant_are_rejected_before_grouping(catalog: typing.Any) -> None:
    rows = materials()
    rows[2]["blocks"] = (source("rates", "平安测试（2026）两全保险\n费率表", tenant=7),)
    with pytest.raises(ValueError, match="SOURCE_SCOPE_MISMATCH"):
        module().route_product_materials(rows, catalog=catalog)


def test_product_name_selects_annuity_and_not_body_critical_illness(catalog: typing.Any) -> None:
    rows = materials("平安测试（2026）养老年金保险")
    rows[0]["blocks"] += (source("terms", "重大疾病保险为其他产品", page=2),)
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "matched"
    assert result.route.primary_label == "annuity_insurance"


def test_same_title_with_conflicting_filing_anchors_is_not_merged(catalog: typing.Any) -> None:
    rows = materials()
    rows[0]["blocks"] = (
        source("terms", "平安测试（2026）两全保险\n平安人寿〔2025〕两全保险140号\n保险条款"),
    )
    rows[1]["blocks"] = (
        source("brochure", "平安测试（2026）两全保险\n平安人寿〔2025〕两全保险141号\n产品说明书"),
    )
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "needs_confirmation"
    assert result.reason == "PRODUCT_IDENTITY_OR_VERSION_CONFLICT"


def test_brochure_reference_to_terms_is_not_a_role_heading(catalog: typing.Any) -> None:
    rows = materials()
    rows[1]["blocks"] = (
        source("brochure", "平安测试（2026）两全保险\n产品说明书\n详细保险责任请参阅保险条款"),
    )
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "matched"
    assert result.materials[1].material_type == "brochure"


def test_cross_page_block_cannot_route_from_its_second_page(catalog: typing.Any) -> None:
    rows = materials()
    first = "投保年龄与交费方式\n费率表\n"
    block = source("rates", first + "平安测试（2026）两全保险")
    rows[2]["blocks"] = (block,)
    rows[2]["first_page_ranges"] = {block.block_id: [(0, len(first))]}
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.reason == "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"


def test_first_page_range_keeps_original_block_offsets(catalog: typing.Any) -> None:
    rows = materials()
    text = "封面备注\n平安测试（2026）两全保险\n费率表\n"
    block = source("rates", text + "平安其他（2025）两全保险\n")
    rows[2]["blocks"] = (block,)
    rows[2]["first_page_ranges"] = {block.block_id: [(0, len(text))]}
    result = module().route_product_materials(rows, catalog=catalog)
    assert result.status == "matched"
    evidence = result.materials[2].title_evidence[0]
    assert evidence.start == len("封面备注\n")
    verify_evidence(evidence, (block,))
