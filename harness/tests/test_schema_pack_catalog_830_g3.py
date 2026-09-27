from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pydantic import ValidationError

from insurance_harness.knowledge_compiler.entity_page_graph_830_g1 import (
    PresentationProfileV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

_REPO = Path(__file__).parents[2]
_WORKBOOK = (
    _REPO
    / "docs/insurance-kb/evidence/830-b0/inputs"
    / "【汇总】11类保险产品知识Schema_全局一致性校验更新版_20260812-v5.xlsx"
)
_CONFIG = _REPO / "docs/insurance-kb/evidence/830-g3/profile-mapping-config.json"
_MODULE = "insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3"
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_EXPECTED_COUNTS = (67, 70, 62, 67, 66, 75, 79, 82, 74, 83, 76)
_WORKBOOK_SHA256 = "8feb33a1e7dc55fad1719a151737822e62bfac815f4b0969441e38744f0204ec"


@pytest.fixture(scope="module")
def catalog_module() -> ModuleType:
    return importlib.import_module(_MODULE)


@pytest.fixture(scope="module")
def workbook_bytes() -> bytes:
    return _WORKBOOK.read_bytes()


@pytest.fixture(scope="module")
def mapping_config() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_CONFIG.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def catalog(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> Any:
    return catalog_module.compile_catalog(workbook_bytes, mapping_config)


def _entry(catalog: Any, pack_id: str) -> Any:
    return next(item for item in catalog.entries if item.pack.schema_pack_id == pack_id)


def _config_for(workbook: bytes, config: dict[str, Any]) -> dict[str, Any]:
    changed = deepcopy(config)
    changed["workbook_sha256"] = hashlib.sha256(workbook).hexdigest()
    return changed


def _rewrite_medical_sheet(
    workbook: bytes,
    mutate: Callable[[ElementTree.Element], None],
) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(workbook)) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for info in original.infolist():
            payload = original.read(info.filename)
            if info.filename == "xl/worksheets/sheet2.xml":
                root = ElementTree.fromstring(payload)
                mutate(root)
                payload = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            changed.writestr(info, payload)
    return output.getvalue()


def _cell(root: ElementTree.Element, reference: str) -> ElementTree.Element:
    cell = root.find(f".//{{{_NS}}}c[@r='{reference}']")
    assert cell is not None
    return cell


def test_g3_r1_compiles_real_v5_workbook_without_metadata_loss(
    catalog: Any,
    mapping_config: dict[str, Any],
) -> None:
    assert catalog.contract == "schema-pack-catalog.830.g3.v1"
    assert catalog.workbook_sha256 == _WORKBOOK_SHA256
    assert catalog.mapping_config_sha256 == schema_wiki_sha256(
        mapping_config["contract"], mapping_config
    )
    assert tuple(len(item.pack.fields) for item in catalog.entries) == _EXPECTED_COUNTS
    assert catalog.field_name_union_count == 154
    assert catalog.field_name_intersection_count == 47

    medical = _entry(catalog, "schemapack_medical_insurance")
    first = medical.pack.fields[0]
    assert first.model_dump(mode="json") == {
        "field_key": "product_code",
        "short_title": "险种代码",
        "schema_category": "02 产品主数据",
        "value_spec": None,
        "description": (
            "产品在公司产品主数据中的唯一标识代码，用于关联产品元数据、条款、计划表及"
            "其他业务材料；优先从产品主数据获取，必要时可从条款首页核验。"
        ),
        "source_guidance": "产品元数据，该字段允许从产品条款PDF第一页获取",
        "formation_method": "外部映射",
        "knowledge_role": "事实 Fact",
        "common_field_marker": "是",
        "other_applicable_products": (
            "意外医疗保险、意外险、重疾险、定期寿险、终身寿险、两全保险、年金险、"
            "护理保险、补充养老保险、失能收入损失保险"
        ),
        "usage_frequency": 11,
        "source_row": 6,
        "semantic_sha256": first.semantic_sha256,
    }
    assert tuple(field.source_row for field in medical.pack.fields) == tuple(range(6, 73))
    assert medical.pack.applicable_classifications == ("medical_insurance",)
    assert all(
        "presentation_section" not in type(field).model_fields for field in medical.pack.fields
    )


def test_g3_r2_profiles_reuse_g1_contract_and_bind_every_field_once(catalog: Any) -> None:
    assert tuple(len(item.profile.sections) for item in catalog.entries) == (
        7,
        7,
        7,
        8,
        7,
        8,
        8,
        8,
        7,
        8,
        7,
    )
    for item in catalog.entries:
        assert isinstance(item.profile, PresentationProfileV1)
        assert item.profile.schema_pack_id == item.pack.schema_pack_id
        assert item.profile.schema_version == item.pack.schema_version
        assert item.profile.schema_pack_sha256 == item.pack.schema_pack_sha256
        assert item.profile.ordered_field_keys == tuple(
            field.field_key for field in item.pack.fields
        )
        assert item.profile_confirmation_status == "PENDING_PRODUCT_OWNER_CONFIRMATION"
        assert item.quality_status == "REGISTERED_NOT_QUALITY_ADMITTED"


def test_g3_r1_same_field_key_remains_pack_scoped_when_metadata_differs(catalog: Any) -> None:
    medical = _entry(catalog, "schemapack_medical_insurance").pack.fields[0]
    critical = _entry(catalog, "schemapack_critical_illness_insurance").pack.fields[0]
    assert medical.field_key == critical.field_key == "product_code"
    assert medical.description != critical.description
    assert medical.semantic_sha256 != critical.semantic_sha256


def test_g3_r1_is_byte_stable_and_json_round_trips(
    catalog_module: ModuleType,
    catalog: Any,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    second = catalog_module.compile_catalog(workbook_bytes, deepcopy(mapping_config))
    assert second == catalog
    wire = json.dumps(
        catalog.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert catalog_module.validate_catalog(wire) == catalog
    assert catalog_module.validate_catalog(wire).model_dump_json() == catalog.model_dump_json()


def test_g3_r2_display_reorder_does_not_change_pack_or_field_semantics(
    catalog_module: ModuleType,
    catalog: Any,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    changed = deepcopy(mapping_config)
    changed["packs"][0]["sections"] = list(reversed(changed["packs"][0]["sections"]))
    reordered = catalog_module.compile_catalog(workbook_bytes, changed)
    before = _entry(catalog, "schemapack_medical_insurance")
    after = _entry(reordered, "schemapack_medical_insurance")
    assert after.pack == before.pack
    assert tuple(field.semantic_sha256 for field in after.pack.fields) == tuple(
        field.semantic_sha256 for field in before.pack.fields
    )
    assert after.profile.profile_sha256 != before.profile.profile_sha256
    assert after.profile.sections[0].section_key == "sales-support"


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (
            lambda config: config["packs"][0]["sections"][1]["category_codes"].append("02"),
            "DUPLICATE_PROFILE_MAPPING",
        ),
        (
            lambda config: config["packs"][0]["sections"][0].update(category_codes=["99"]),
            "EMPTY_PROFILE_SECTION",
        ),
        (
            lambda config: config["packs"][0]["sections"].pop(),
            "ORPHAN_PROFILE_FIELD",
        ),
    ],
)
def test_g3_r2_rejects_invalid_profile_mappings(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
    reason_code: str,
) -> None:
    changed = deepcopy(mapping_config)
    mutate(changed)
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(workbook_bytes, changed)
    assert exc.value.reason_code == reason_code


def test_g3_r2_rejects_duplicate_section_keys_with_stable_error_boundary(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    changed = deepcopy(mapping_config)
    changed["packs"][0]["sections"][1]["section_key"] = changed["packs"][0]["sections"][0][
        "section_key"
    ]
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(workbook_bytes, changed)
    assert exc.value.reason_code == "MAPPING_CONFIG_INVALID"


def test_g3_r2_normalizes_unexpected_entry_validation_errors(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    changed = deepcopy(mapping_config)
    changed["packs"][0]["display_name"] = ""
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(workbook_bytes, changed)
    assert exc.value.reason_code == "COMPILED_CATALOG_INVALID"


def test_g3_r1_rejects_wrong_workbook_hash_and_count(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    wrong_hash = deepcopy(mapping_config)
    wrong_hash["workbook_sha256"] = "0" * 64
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(workbook_bytes, wrong_hash)
    assert exc.value.reason_code == "WORKBOOK_SHA256_MISMATCH"

    wrong_count = deepcopy(mapping_config)
    wrong_count["packs"][0]["expected_field_count"] += 1
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(workbook_bytes, wrong_count)
    assert exc.value.reason_code == "FIELD_COUNT_MISMATCH"


def test_g3_r1_rejects_missing_and_duplicate_field_keys_in_nonempty_rows(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    def remove_required_field(root: ElementTree.Element) -> None:
        cell = _cell(root, "D6")
        row = next(item for item in root.iter(f"{{{_NS}}}row") if cell in list(item))
        row.remove(cell)

    missing = _rewrite_medical_sheet(workbook_bytes, remove_required_field)
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(missing, _config_for(missing, mapping_config))
    assert exc.value.reason_code == "INCOMPLETE_WORKBOOK_ROW"

    def duplicate_field(root: ElementTree.Element) -> None:
        source = _cell(root, "D6").find(f"{{{_NS}}}v")
        target = _cell(root, "D7").find(f"{{{_NS}}}v")
        assert source is not None and target is not None
        target.text = source.text

    duplicate = _rewrite_medical_sheet(workbook_bytes, duplicate_field)
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(duplicate, _config_for(duplicate, mapping_config))
    assert exc.value.reason_code == "DUPLICATE_FIELD_KEY"


def test_g3_r1_requires_the_exact_header_on_row_five(
    catalog_module: ModuleType,
    workbook_bytes: bytes,
    mapping_config: dict[str, Any],
) -> None:
    def remove_header(root: ElementTree.Element) -> None:
        sheet_data = root.find(f".//{{{_NS}}}sheetData")
        assert sheet_data is not None
        header = next(row for row in sheet_data if row.attrib.get("r") == "5")
        sheet_data.remove(header)

    changed = _rewrite_medical_sheet(workbook_bytes, remove_header)
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.compile_catalog(changed, _config_for(changed, mapping_config))
    assert exc.value.reason_code == "WORKBOOK_HEADER_MISMATCH"


def test_g3_r1_validation_rejects_metadata_or_hash_drift(
    catalog_module: ModuleType,
    catalog: Any,
) -> None:
    changed = catalog.model_dump(mode="json")
    changed["entries"][0]["pack"]["fields"][0]["description"] += "篡改"
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.validate_catalog(json.dumps(changed, ensure_ascii=False))
    assert exc.value.reason_code == "CATALOG_VALIDATION_FAILED"

    changed = catalog.model_dump(mode="json")
    changed["catalog_sha256"] = "0" * 64
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.validate_catalog(json.dumps(changed, ensure_ascii=False))
    assert exc.value.reason_code == "CATALOG_VALIDATION_FAILED"


def test_g3_r2_validation_cannot_forge_confirmation_or_quality_upgrade(
    catalog_module: ModuleType,
    catalog: Any,
) -> None:
    for key, value in (
        ("profile_confirmation_status", "CONFIRMED"),
        ("quality_status", "QUALITY_ADMITTED"),
    ):
        changed = catalog.model_dump(mode="json")
        changed["entries"][0][key] = value
        with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
            catalog_module.validate_catalog(json.dumps(changed, ensure_ascii=False))
        assert exc.value.reason_code == "CATALOG_VALIDATION_FAILED"


def test_g3_r1_exact_catalog_lookup_requires_pack_id_and_version(
    catalog_module: ModuleType,
    catalog: Any,
) -> None:
    entry = catalog_module.get_catalog_entry(
        catalog,
        schema_pack_id="schemapack_medical_insurance",
        schema_version="2026-08-12-v5",
    )
    assert entry.pack.display_name == "医疗险"
    with pytest.raises(catalog_module.SchemaPackCatalogError) as exc:
        catalog_module.get_catalog_entry(
            catalog,
            schema_pack_id="schemapack_medical_insurance",
            schema_version="newer",
        )
    assert exc.value.reason_code == "CATALOG_ENTRY_NOT_FOUND"


def test_catalog_models_are_strict_frozen_and_forbid_extra(catalog_module: ModuleType) -> None:
    with pytest.raises(ValidationError):
        catalog_module.FieldDefinitionV1(
            field_key="field",
            short_title="字段",
            schema_category="02 分类",
            value_spec=None,
            description="说明",
            source_guidance="来源",
            formation_method="原文抽取",
            knowledge_role="事实 Fact",
            common_field_marker="否",
            other_applicable_products="无",
            usage_frequency="1",
            source_row="6",
            semantic_sha256="0" * 64,
            extra="forbidden",
        )
