"""S3f-2a acceptance: the navigation names the Space and its product overview fields (Spec §2.1).

Protected file: written by Claude. Both are data kept by the Harness, so the page hard-codes no
field key and no Space name; older releases without them keep working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.contracts import NavigationProfile
from insurance_harness.contracts.export import export

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / SCHEMA_PACK_CATALOG

DOMAIN = {"domain_key": "product", "display_name": "产品库", "entity_types": ["insurance_product"]}


def test_the_shipped_navigation_names_the_space_and_its_overview_fields() -> None:
    navigation = load_navigation()
    assert navigation.display_name and navigation.display_name.strip()
    assert navigation.overview_fields and len(navigation.overview_fields) <= 5
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    product_fields = {
        field["field_key"]
        for entry in catalog["entries"]
        if entry["pack"]["entity_type"] == "insurance_product"
        for field in entry["pack"]["fields"]
    }
    assert set(navigation.overview_fields) <= product_fields


def test_both_fields_are_optional_and_checked() -> None:
    plain = NavigationProfile.model_validate(
        {"navigation_id": "n", "navigation_version": "1", "domains": [DOMAIN]}
    )
    assert plain.display_name is None and plain.overview_fields == []
    for bad in (
        {"display_name": " "},
        {"overview_fields": ["a", "a"]},
        {"overview_fields": [" "]},
        {"overview_fields": None},  # may be left out, never null (review R1 on PR #233)
    ):
        with pytest.raises(ValidationError):
            NavigationProfile.model_validate(
                {"navigation_id": "n", "navigation_version": "1", "domains": [DOMAIN], **bad}
            )


def test_the_exported_schema_carries_both_fields(tmp_path: Path) -> None:
    export(tmp_path)
    schema = json.loads((tmp_path / "navigation_profile.schema.json").read_text(encoding="utf-8"))
    assert {"display_name", "overview_fields"} <= set(schema["properties"])
