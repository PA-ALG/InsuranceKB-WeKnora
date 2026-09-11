from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1
from tests.test_batch_entity_resolution_830_g3 import (
    _corpus,
    _entry,
    _existing,
    _material_proposal,
    _model_binding,
    _policy,
    _proposal_batch,
)


def _module():
    name = "insurance_harness.knowledge_compiler.g3_title_routing"
    assert importlib.util.find_spec(name) is not None, "no deterministic G3 title routing overlay"
    return importlib.import_module(name)


@pytest.fixture(scope="module")
def catalog():
    path = Path(__file__).parents[2] / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
    return SchemaPackCatalogV1.model_validate_json(path.read_bytes())


@pytest.mark.parametrize(
    "title,label",
    (
        ("平安福满分（2026）养老年金保险产品说明书", "annuity_insurance"),
        ("平安爱满分（2026）两全保险", "endowment_insurance"),
    ),
)
def test_formal_title_selects_catalog_without_model(title, label, catalog):
    info = _module().route_formal_title(title, catalog=catalog)
    assert info.classification_status == "KNOWN"
    assert info.primary_label == label
    assert info.schema_pack_id == "schemapack_" + label
    assert info.title_year == "2026"


def _capture(version=None, filing="REG001"):
    name = "平安测试（2026）两全保险"
    entry = _entry(
        material_id="m-001",
        text=(
            f"平安保险\n{name}\n产品代码 TEST001 登记编号 REG001 历史资料2025\n"
            "重大疾病保险为另一险种\n官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "product",
                "name": name,
                "product_code": "TEST001",
                "version_label": version,
                "filing": filing,
                "label": "endowment_insurance",
            },
        ),
    )
    return corpus, _proposal_batch(corpus, (receipt,), (proposal,))


def test_title_year_overlay_preserves_captured_model_and_enters_existing_resolver(catalog):
    module = _module()
    corpus, captured = _capture()
    original = batch_json_bytes_830_g3(captured)
    overlay, derived = module.build_title_routing_overlay(
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        material_ids=("m-001",),
    )
    assert batch_json_bytes_830_g3(captured) == original
    assert derived.model_receipts == captured.model_receipts
    assert captured.proposals[0].entities[0].version_label is None
    assert derived.proposals[0].entities[0].version_label == "2026"
    assert overlay.observations[0].classification_status == "KNOWN"
    assert overlay.observations[0].version_action == "FILLED_FROM_TITLE"
    assert (
        module.apply_title_routing_overlay(
            overlay,
            corpus=corpus,
            catalog=catalog,
            source_proposals=captured,
        )
        == derived
    )
    resolution = module.resolve_with_title_overlay(
        overlay,
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert resolution.decisions[0].disposition == "CREATE"
    assert resolution.decisions[0].children[0].classification.primary_label == "endowment_insurance"


def test_known_classification_does_not_invent_missing_filing(catalog):
    module = _module()
    corpus, captured = _capture(filing=None)
    overlay, derived = module.build_title_routing_overlay(
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        material_ids=("m-001",),
    )
    assert overlay.observations[0].classification_status == "KNOWN"
    assert derived.proposals[0].entities[0].filing_or_registration is None
    result = module.resolve_with_title_overlay(
        overlay,
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert result.decisions[0].disposition == "NEEDS_CONFIRM"
    assert "VERSION_UNRESOLVED" in result.decisions[0].children[0].reason_codes


def test_tampered_overlay_is_rejected(catalog):
    module = _module()
    corpus, captured = _capture()
    overlay, _ = module.build_title_routing_overlay(
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        material_ids=("m-001",),
    )
    tampered = overlay.model_copy(update={"effective_proposals_sha256": "f" * 64})
    with pytest.raises(ValueError):
        module.apply_title_routing_overlay(
            tampered,
            corpus=corpus,
            catalog=catalog,
            source_proposals=captured,
        )


def test_existing_conflicting_version_is_preserved_and_cannot_auto_resolve(catalog):
    module = _module()
    corpus, captured = _capture(version="2025")
    overlay, derived = module.build_title_routing_overlay(
        corpus=corpus,
        catalog=catalog,
        source_proposals=captured,
        material_ids=("m-001",),
    )
    assert overlay.observations[0].version_action == "VERSION_CONFLICT"
    assert derived.proposals[0].entities[0].version_label == "2025"
    with pytest.raises(ValueError, match="title rule conflict"):
        module.resolve_with_title_overlay(
            overlay,
            corpus=corpus,
            catalog=catalog,
            source_proposals=captured,
            existing_entities=_existing(),
            policy=_policy(),
        )


def test_known_title_without_explicit_year_keeps_version_separate(catalog):
    route = _module().route_formal_title("平安测试年金保险", catalog=catalog)
    assert route.classification_status == "KNOWN"
    assert route.title_year is None
    assert route.title_year_status == "NOT_PRESENT"


@pytest.mark.parametrize(
    "title",
    (
        "甲年金保险、乙两全保险",
        "甲年金保险与乙年金保险",
        "甲（2026）年金保险+乙（2026）两全保险",
    ),
)
def test_obvious_multiple_product_titles_do_not_select_first_keyword(catalog, title):
    route = _module().route_formal_title(title, catalog=catalog)
    assert route.classification_status == "AMBIGUOUS_TITLE"
    assert route.primary_label is None
    assert route.schema_pack_id is None


def test_existing_specific_keyword_overlap_keeps_one_catalog_line(catalog):
    module = _module()
    for title, label in (
        ("甲医疗意外保险", "accident_medical_insurance"),
        ("甲意外医疗保险", "accident_medical_insurance"),
        ("甲补充养老年金保险", "supplementary_pension_insurance"),
    ):
        route = module.route_formal_title(title, catalog=catalog)
        assert route.classification_status == "KNOWN"
        assert route.primary_label == label


def test_title_line_mapping_matches_all_eleven_actual_catalog_entries(catalog):
    module = _module()
    titles = (
        "甲医疗保险",
        "甲意外医疗保险",
        "甲意外伤害保险",
        "甲重大疾病保险",
        "甲定期寿险",
        "甲终身寿险",
        "甲两全保险",
        "甲年金保险",
        "甲护理保险",
        "甲补充养老保险",
        "甲失能收入损失保险",
    )
    routes = [module.route_formal_title(title, catalog=catalog) for title in titles]
    assert all(row.classification_status == "KNOWN" for row in routes)
    assert {row.primary_label for row in routes} == {
        label for entry in catalog.entries for label in entry.pack.applicable_classifications
    }
    assert len({row.schema_pack_id for row in routes}) == 11
