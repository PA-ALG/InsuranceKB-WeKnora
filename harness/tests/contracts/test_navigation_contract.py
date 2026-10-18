"""S3e-1 acceptance: the navigation contract and the profile's display data (Spec §2.1, §2.2).

Protected file: written by Claude. Navigation is versioned data a reader follows: domains by entity
type, groups by classification label. Keys are unique where a reader looks them up and every name a
reader shows is non-blank. Profiles gain the pack's display name and each field's definition and
schema category, all optional so older releases still read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import NavigationProfile, PresentationProfile, ProfileField
from insurance_harness.contracts.export import export


def navigation(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "navigation_id": "enterprise",
        "navigation_version": "v1",
        "domains": [
            {
                "domain_key": "product",
                "display_name": "产品库",
                "entity_types": ["insurance_product"],
                "groups": [
                    {"group_key": "pack_a", "display_name": "甲险", "classification_labels": ["a"]},
                    {"group_key": "pack_b", "display_name": "乙险", "classification_labels": ["b"]},
                ],
            },
            {
                "domain_key": "service_benefit",
                "display_name": "服务权益",
                "entity_types": ["service_benefit"],
                "groups": [
                    {"group_key": "pack_a", "display_name": "家医", "classification_labels": ["x"]}
                ],
            },
        ],
    }
    data.update(changes)
    return data


def test_a_valid_navigation_parses_and_one_group_key_may_recur_across_domains() -> None:
    parsed = NavigationProfile.model_validate(navigation())
    assert [d.domain_key for d in parsed.domains] == ["product", "service_benefit"]
    assert [g.group_key for g in parsed.domains[0].groups] == ["pack_a", "pack_b"]


def broken(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    data = navigation()
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return data


@pytest.mark.parametrize(
    "data",
    [
        broken(("domains", 1, "domain_key"), "product"),
        broken(("domains", 0, "groups", 1, "group_key"), "pack_a"),
        broken(("domains", 0, "display_name"), " "),
        broken(("domains", 0, "groups", 0, "display_name"), ""),
        broken(("domains", 0, "entity_types"), []),
        broken(("navigation_version",), " "),
        navigation(extra="x"),
    ],
    ids=[
        "domain twice",
        "group twice in a domain",
        "blank domain name",
        "blank group name",
        "no entity types",
        "blank version",
        "extra key",
    ],
)
def test_an_invalid_navigation_is_refused(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NavigationProfile.model_validate(data)


def test_profiles_carry_optional_display_data() -> None:
    plain = ProfileField(field_key="cooling_off_period", short_title="犹豫期")
    assert plain.description is None and plain.schema_category is None
    rich = ProfileField(
        field_key="cooling_off_period",
        short_title="犹豫期",
        description="投保人收到合同后可解除合同的期间。",
        schema_category="05 合同与交费规则",
    )
    profile = PresentationProfile.model_validate(
        {
            "profile_id": "p",
            "profile_version": "1",
            "profile_sha256": "a" * 64,
            "schema_pack_id": "pack",
            "display_name": "重疾险",
            "classification_labels": ["critical"],
            "sections": [
                {"section_key": "s", "display_name": "合同", "fields": [rich.model_dump()]}
            ],
        }
    )
    assert profile.display_name == "重疾险"
    assert profile.sections[0].fields[0].schema_category == "05 合同与交费规则"


def test_the_exported_schemas_include_the_navigation_and_profile_display_data(
    tmp_path: Path,
) -> None:
    names = {path.name for path in export(tmp_path)}
    assert "navigation_profile.schema.json" in names
    profile = json.loads(
        (tmp_path / "presentation_profile.schema.json").read_text(encoding="utf-8")
    )
    assert "display_name" in profile["properties"]
    field = profile["$defs"]["ProfileField"]["properties"]
    assert {"description", "schema_category"} <= set(field)
