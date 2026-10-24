"""S3d-2 acceptance: the product page published with the claims (Spec §3.1, §3.2).

Protected file: written by Claude. A compiled product becomes one Entity (filed name, entity
type, classification labels, product code) and its pack's PresentationProfile, both read from
the catalog as data and valid under the exported contracts. Every pack of the real catalog must
yield a page in its own section order; an inconsistent catalog stops the build with a reason code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.page import product_page

REPO = Path(__file__).resolve().parents[4]
CATALOG = REPO / SCHEMA_PACK_CATALOG
NAME = "演示重大疾病保险"


def schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((REPO / "contracts" / name).read_text(encoding="utf-8"))
    return loaded


def entry(pack_id: str = "pack_demo", label: str = "demo_class") -> dict[str, Any]:
    """One catalog entry shaped like the generated catalog, with three fields in two sections."""
    profile_id = f"profile_{pack_id}"
    return {
        "pack": {
            "schema_pack_id": pack_id,
            "display_name": "演示险",
            "entity_type": "insurance_product",
            "applicable_classifications": [label],
            "presentation_profile_ref": {"profile_id": profile_id, "profile_version": "1.0.0"},
            "fields": [
                {"field_key": "waiting_period", "short_title": "等待期", "description": "d"},
                {"field_key": "grace_period", "short_title": "宽限期", "description": "d"},
                {"field_key": "product_summary", "short_title": "产品简介", "description": "d"},
            ],
        },
        "profile": {
            "contract": "presentation-profile.v1",
            "profile_id": profile_id,
            "profile_version": "1.0.0",
            "profile_sha256": "cd" * 32,
            "schema_pack_id": pack_id,
            "sections": [
                {
                    "section_key": "overview",
                    "display_name": "产品概览",
                    "fields": [{"field_key": "product_summary", "short_title": "产品简介"}],
                },
                {
                    "section_key": "contract",
                    "display_name": "投保与合同",
                    "fields": [
                        {"field_key": "waiting_period", "short_title": "等待期"},
                        {"field_key": "grace_period", "short_title": "宽限期"},
                    ],
                },
            ],
        },
    }


def write(tmp_path: Path, *entries: dict[str, Any]) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"entries": list(entries)}, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_page_names_the_product_and_carries_its_packs_display_groups(tmp_path: Path) -> None:
    page = product_page(write(tmp_path, entry()), "pack_demo", entity_id="1828", name=NAME)
    entity = page.entity.model_dump(mode="json")
    profile = page.profile.model_dump(mode="json")
    assert entity == {
        "entity_id": "1828",
        "entity_type": "insurance_product",
        "names": [NAME],
        "aliases": [],
        "identifiers": {"product_code": "1828"},
        "classification_labels": ["demo_class"],
        "owner_module": "harness/schema_fields",
    }
    # S3e: the profile also names its pack and carries each field's schema definition and category.
    definitions = {field["field_key"]: field for field in entry()["pack"]["fields"]}
    sections = [
        {
            **section,
            "fields": [
                {
                    **field,
                    "description": definitions[field["field_key"]].get("description"),
                    "schema_category": definitions[field["field_key"]].get("schema_category"),
                }
                for field in section["fields"]
            ],
        }
        for section in entry()["profile"]["sections"]
    ]
    assert profile == {
        "profile_id": "profile_pack_demo",
        "profile_version": "1.0.0",
        "profile_sha256": "cd" * 32,
        "schema_pack_id": "pack_demo",
        "display_name": "演示险",
        "classification_labels": ["demo_class"],
        "sections": sections,
    }
    jsonschema.validate(entity, schema("entity.schema.json"))
    jsonschema.validate(profile, schema("presentation_profile.schema.json"))


def test_every_pack_of_the_catalog_yields_a_page_in_its_own_order() -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    contract = schema("presentation_profile.schema.json")
    assert len(document["entries"]) >= 2
    for item in document["entries"]:
        pack, expected = item["pack"], item["profile"]
        page = product_page(CATALOG, pack["schema_pack_id"], entity_id="P-1", name="产品")
        profile = page.profile.model_dump(mode="json")
        jsonschema.validate(profile, contract)
        assert profile["profile_id"] == pack["presentation_profile_ref"]["profile_id"]
        assert [
            (section["section_key"], [f["field_key"] for f in section["fields"]])
            for section in profile["sections"]
        ] == [
            (section["section_key"], [f["field_key"] for f in section["fields"]])
            for section in expected["sections"]
        ]
        assert page.entity.entity_type == pack["entity_type"]
        labels = pack["applicable_classifications"]
        assert page.entity.classification_labels == profile["classification_labels"] == labels


def _sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = document["profile"]["sections"]
    return sections


Change = Callable[[dict[str, Any]], None]
CASES: list[tuple[str, Change, str]] = [
    (
        "profile ref names another profile",
        lambda e: e["pack"]["presentation_profile_ref"].update(profile_id="profile_other"),
        "PROFILE_MISMATCH",
    ),
    (
        "profile ref names another version",
        lambda e: e["pack"]["presentation_profile_ref"].update(profile_version="2.0.0"),
        "PROFILE_MISMATCH",
    ),
    (
        "profile belongs to another pack",
        lambda e: e["profile"].update(schema_pack_id="pack_other"),
        "PROFILE_MISMATCH",
    ),
    (
        "profile lists a field the pack lacks",
        lambda e: _sections(e)[1]["fields"].append(
            {"field_key": "cooling_off_period", "short_title": "犹豫期"}
        ),
        "PROFILE_INVALID",
    ),
    (
        "profile retitles a field",
        lambda e: _sections(e)[1]["fields"][0].update(short_title="观察期"),
        "PROFILE_INVALID",
    ),
    (
        "profile lists a field twice",
        lambda e: _sections(e)[0]["fields"].append(
            {"field_key": "waiting_period", "short_title": "等待期"}
        ),
        "PROFILE_INVALID",
    ),
    (
        "profile repeats a section key",
        lambda e: _sections(e)[1].update(section_key="overview"),
        "PROFILE_INVALID",
    ),
    (
        "profile has an empty section",
        lambda e: _sections(e)[0].update(fields=[]),
        "PROFILE_INVALID",
    ),
]


@pytest.mark.parametrize(("case", "change", "reason"), CASES, ids=[c[0] for c in CASES])
def test_an_inconsistent_profile_is_refused(
    tmp_path: Path, case: str, change: Change, reason: str
) -> None:
    broken = entry()
    change(broken)
    with pytest.raises(BundleError) as error:
        product_page(write(tmp_path, broken), "pack_demo", entity_id="1828", name=NAME)
    assert error.value.reason == reason, case


def test_a_pack_missing_from_the_catalog_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError) as error:
        product_page(write(tmp_path, entry()), "pack_missing", entity_id="1828", name=NAME)
    assert error.value.reason == "PACK_UNKNOWN"


def test_a_classification_shared_with_another_pack_is_refused(tmp_path: Path) -> None:
    """Readers match an entity to its profile by label, so a label must name one pack."""
    catalog = write(tmp_path, entry(), entry("pack_twin"))
    with pytest.raises(BundleError) as error:
        product_page(catalog, "pack_demo", entity_id="1828", name=NAME)
    assert error.value.reason == "PROFILE_INVALID"


@pytest.mark.parametrize("content", ["not json", '{"entries": "none"}', '{"entries": [{}]}'])
def test_an_unreadable_catalog_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(content, encoding="utf-8")
    for catalog in (path, tmp_path / "missing.json"):
        with pytest.raises(BundleError) as error:
            product_page(catalog, "pack_demo", entity_id="1828", name=NAME)
        assert error.value.reason == "CATALOG_UNREADABLE"
