"""Service definitions are reusable structure, never published service facts."""

from __future__ import annotations

import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from insurance_harness.knowledge_compiler.entity_page_graph_830_g1 import PresentationProfileV1

MODULE = "insurance_harness.knowledge_compiler.service_schema_catalog_830_g3"
ASSET = Path(__file__).parents[2] / "docs/insurance-kb/assets/service-schema-830-g3.json"


def _module() -> ModuleType:
    assert importlib.util.find_spec(MODULE) is not None, "service schema loader is missing"
    return importlib.import_module(MODULE)


def _raw() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(ASSET.read_text())
    return result


def test_load_three_original_service_definitions_with_g1_profiles() -> None:
    module = _module()
    catalog = module.load_service_schema_catalog(ASSET.read_bytes())
    assert catalog.content_status == "STRUCTURE_ONLY_NOT_PUBLISHED"
    assert [(entry.entity_type, len(entry.fields)) for entry in catalog.entries] == [
        ("service_line", 5),
        ("service_line_version", 16),
        ("service_item", 21),
    ]
    for entry in catalog.entries:
        profile = module.presentation_profile(entry)
        assert isinstance(profile, PresentationProfileV1)
        assert set(profile.ordered_field_keys) == {field.field_key for field in entry.fields}
        assert len(profile.ordered_field_keys) == len(entry.fields)
        assert profile.schema_pack_sha256 == entry.schema_sha256
        assert all(field.source_field_name == field.field_key for field in entry.fields)
    version = catalog.entries[1]
    assert version.identity_fields == ("line_name", "version_name")
    assert catalog.entries[2].identity_fields == ("line_name", "version_name", "item_name")
    assert version.fields[0].description == "如：臻享家医、安有医、居家养老。"
    assert "service_series" in catalog.deferred_entity_types
    assert "service_item_concept" in catalog.deferred_entity_types
    assert "workbook_sha256" not in ASSET.read_text()


@pytest.mark.parametrize(
    "mutation",
    [
        "type",
        "duplicate_schema",
        "duplicate_field",
        "source_hash",
        "source_path",
        "field_source_name",
        "field_description",
        "missing_mapping",
        "duplicate_mapping",
        "unknown_mapping",
        "mapping_label",
        "unknown_key",
        "business_fact",
        "identity",
    ],
)
def test_reject_invalid_or_misattributed_structure(mutation: str) -> None:
    module = _module()
    raw = deepcopy(_raw())
    entry = raw["entries"][0]
    if mutation == "type":
        entry["entity_type"] = "insurance_product"
    elif mutation == "duplicate_schema":
        raw["entries"][1] = deepcopy(entry)
    elif mutation == "duplicate_field":
        entry["fields"][1] = deepcopy(entry["fields"][0])
    elif mutation == "source_hash":
        raw["source"]["sha256"] = "0" * 64
    elif mutation == "source_path":
        raw["source"]["path"] = "/not-the-source.ts"
    elif mutation == "field_source_name":
        entry["fields"][0]["source_field_name"] = "made_up"
    elif mutation == "field_description":
        entry["fields"][0]["description"] = "changed source meaning"
    elif mutation == "missing_mapping":
        entry["sections"][0]["fields"].pop()
    elif mutation == "duplicate_mapping":
        entry["sections"][0]["fields"].append(deepcopy(entry["sections"][0]["fields"][0]))
    elif mutation == "unknown_mapping":
        entry["sections"][0]["fields"][0]["field_key"] = "not_defined"
    elif mutation == "mapping_label":
        entry["sections"][0]["fields"][0]["short_title"] = "wrong label"
    elif mutation == "unknown_key":
        entry["fields"][0]["source_row"] = 6
    elif mutation == "business_fact":
        raw["content_status"] = "PUBLISHED"
    elif mutation == "identity":
        entry["identity_fields"] = ["line_summary"]
    # Recompute ordinary content hashes: semantic/source/topology guards must still reject.
    for row in raw["entries"]:
        row["schema_sha256"] = module.schema_wiki_sha256(
            row["contract"], {key: value for key, value in row.items() if key != "schema_sha256"}
        )
    raw["catalog_sha256"] = module.schema_wiki_sha256(
        raw["contract"], {key: value for key, value in raw.items() if key != "catalog_sha256"}
    )
    with pytest.raises(ValueError):
        module.load_service_schema_catalog(json.dumps(raw).encode())


def test_reject_source_bytes_and_stale_content_hashes() -> None:
    module = _module()
    with pytest.raises(ValueError, match="source"):
        module.load_service_schema_catalog(ASSET.read_bytes(), source_bytes=b"unrelated code")
    raw = _raw()
    raw["entries"][0]["sections"][0]["display_name"] = "changed navigation"
    with pytest.raises(ValueError):
        module.load_service_schema_catalog(json.dumps(raw))


def test_loading_has_no_dependency_on_original_absolute_source_path() -> None:
    # Deployed consumers use the reviewed source hash; original source bytes are optional.
    catalog = _module().load_service_schema_catalog(ASSET.read_bytes())
    assert catalog.source.kind == "legacy_code_definition"
    assert (
        catalog.source.sha256 == "7c20729b0dcb6aaa4672a51d2f9158846da1ebe7ee21b0bde5891aed1c869f82"
    )
