"""PV-4b acceptance: question types are navigation data (Spec PV-4b-读取侧.md §4.1).

Protected file: written by Claude. The platform decides whether a question is a sales or a
service question only from the published navigation's `question_intents`, shaped like
`question_terms` (groups of 1-3 terms of 2+ characters, every term of one group must occur).
Only the two intents the platform knows are allowed; navigations without the key still read.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.contracts import NavigationProfile


def navigation(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "navigation_id": "enterprise",
        "navigation_version": "v1",
        "domains": [
            {
                "domain_key": "product",
                "display_name": "产品库",
                "entity_types": ["insurance_product"],
                "groups": [],
            }
        ],
    }
    data.update(changes)
    return data


def test_intents_are_optional_and_round_trip() -> None:
    assert NavigationProfile.model_validate(navigation()).question_intents is None
    intents = {"sales": [["推荐"], ["哪款", "适合"]], "service": [["理赔"], ["保全"]]}
    profile = NavigationProfile.model_validate(navigation(question_intents=intents))
    assert profile.model_dump(mode="json", exclude_none=True)["question_intents"] == intents


@pytest.mark.parametrize(
    "intents",
    [
        {"advice": [["推荐"]]},  # only sales and service are known intents
        {"sales": [[]]},  # an empty group
        {"sales": [["推荐", "哪款", "适合", "对比"]]},  # more than 3 terms
        {"sales": [["荐"]]},  # a term of one character
        {"sales": [["推荐", "推荐"]]},  # a repeated term
        {"sales": [[" "]]},  # a blank term
    ],
)
def test_malformed_intents_are_rejected(intents: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NavigationProfile.model_validate(navigation(question_intents=intents))


def test_the_shipped_navigation_publishes_both_intents() -> None:
    profile = load_navigation()
    assert profile.navigation_version == "2026-11-01.1"
    assert profile.question_intents is not None
    assert set(profile.question_intents) == {"sales", "service"}
    assert all(profile.question_intents[intent] for intent in ("sales", "service"))
    # A term in both intents would make every question that uses it ambiguous.
    sales = {term for group in profile.question_intents["sales"] for term in group}
    service = {term for group in profile.question_intents["service"] for term in group}
    assert not sales & service
