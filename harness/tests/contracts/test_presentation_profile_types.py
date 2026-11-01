"""SK-3 acceptance: a presentation profile may serve entity types and declare method knowledge
(Spec docs/design/slices/SK-3-销售方法阅读与问答.md §1, §2.1).

Protected file: written by Claude. A profile gives classification labels, entity types or both;
`knowledge_class` ("method" only) needs entity types; the method reading copy (`reading_note`,
`notices`) only comes with a knowledge class. Profiles without the new keys read as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import PresentationProfile
from insurance_harness.contracts.export import export


def profile(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "profile_id": "p",
        "profile_version": "1",
        "profile_sha256": "a" * 64,
        "schema_pack_id": "pack",
        "classification_labels": ["critical"],
        "sections": [
            {
                "section_key": "s",
                "display_name": "合同",
                "fields": [{"field_key": "cooling_off_period", "short_title": "犹豫期"}],
            }
        ],
    }
    data.update(changes)
    return {key: value for key, value in data.items() if value is not None}


def test_a_label_profile_reads_as_before() -> None:
    parsed = PresentationProfile.model_validate(profile())
    assert parsed.entity_types is None and parsed.knowledge_class is None
    assert parsed.reading_note is None and parsed.notices == {}
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    assert dumped["classification_labels"] == ["critical"]


def test_a_method_profile_serves_its_types_without_labels() -> None:
    parsed = PresentationProfile.model_validate(
        profile(
            classification_labels=None,
            entity_types=["sales_method"],
            knowledge_class="method",
            reading_note="销售方法（培训材料，非产品事实）。",
            notices={"product_info": "其中的产品信息以条款为准。"},
        )
    )
    assert parsed.classification_labels == []
    assert parsed.entity_types == ["sales_method"]
    assert parsed.knowledge_class == "method"
    assert parsed.notices == {"product_info": "其中的产品信息以条款为准。"}


@pytest.mark.parametrize(
    "changes",
    [
        {"classification_labels": []},  # neither labels nor types
        {"classification_labels": None},
        {"knowledge_class": "method"},  # a class needs entity types
        {"entity_types": ["sales_method"], "knowledge_class": "advice"},  # only "method"
        {"entity_types": []},
        {"entity_types": [" "]},
        {"reading_note": "说明"},  # reading copy only with a class
        {"notices": {"product_info": "提示"}},
        {"entity_types": ["m"], "knowledge_class": "method", "reading_note": " "},
        {"entity_types": ["m"], "knowledge_class": "method", "notices": {"product_info": " "}},
    ],
)
def test_malformed_type_profiles_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PresentationProfile.model_validate(profile(**changes))


def test_the_exported_schema_declares_the_type_keys(tmp_path: Path) -> None:
    export(tmp_path)
    schema = json.loads((tmp_path / "presentation_profile.schema.json").read_text(encoding="utf-8"))
    keys = {"entity_types", "knowledge_class", "reading_note", "notices"}
    assert keys <= set(schema["properties"])
    assert "classification_labels" not in schema["required"]
